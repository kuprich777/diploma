# services/risk_engine/routers/risk.py

import asyncio
from typing import Union, Literal, Optional

from pydantic import BaseModel

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models import RiskSnapshot
from schemas import (
    AggregatedRisk,
    RiskHistory,
    RiskRecalcRequest,
    RiskSnapshotOut,
)
from utils.logging import setup_logging


RiskMethod = Literal["classical", "quantitative"]

# -------------------------------------------------------------------
# Sector weights for the integral (aggregated) risk.
# Source of truth on startup: settings (env/config). Can be updated at runtime
# via POST /update_weights if ENABLE_DYNAMIC_WEIGHTS is enabled.
# -------------------------------------------------------------------
WEIGHTS: dict[str, float] = {
    "energy": float(getattr(settings, "ENERGY_WEIGHT", 0.7)),
    "water": float(getattr(settings, "WATER_WEIGHT", 0.2)),
    "transport": float(getattr(settings, "TRANSPORT_WEIGHT", 0.1)),
}

# -------------------------------------------------------------------
# Dependency matrix A (versioned, runtime-configurable)
# Order of sectors: [energy, water, transport]
# A[i][j] — влияние сектора j на сектор i
# Источник правды по умолчанию: settings.DEPENDENCY_MATRIX (+ версия)
# В runtime можно обновить через POST /dependency_matrix (если разрешено конфигурацией).
# -------------------------------------------------------------------
SECTORS_ORDER = ["energy", "water", "transport"]

CURRENT_DEPENDENCY_MATRIX: list[list[float]] = getattr(settings, "DEPENDENCY_MATRIX", [
    [0.0, 0.0, 0.0],
    [0.0, 0.0, 0.0],
    [0.0, 0.0, 0.0],
])
CURRENT_DEPENDENCY_MATRIX_VERSION: str = getattr(settings, "DEPENDENCY_MATRIX_VERSION", "v0")

logger = setup_logging()

router = APIRouter(prefix="/api/v1/risk", tags=["risk"])


def _validate_matrix_3x3(matrix: list[list[float]]) -> None:
    if len(matrix) != 3 or any(len(row) != 3 for row in matrix):
        raise HTTPException(status_code=400, detail="dependency matrix must be 3x3")
    for row in matrix:
        for v in row:
            if not isinstance(v, (int, float)):
                raise HTTPException(status_code=400, detail="dependency matrix values must be numeric")
            if v < 0.0 or v > 1.0:
                raise HTTPException(status_code=400, detail="dependency matrix values must be in [0,1]")


def _matrix_as_dict(matrix: list[list[float]]) -> dict[str, dict[str, float]]:
    """Convenience representation for meta/debug: src -> {dest: weight}.

    Note: in A[i][j], j is source, i is destination.
    """
    out: dict[str, dict[str, float]] = {s: {} for s in SECTORS_ORDER}
    for i, dest in enumerate(SECTORS_ORDER):
        for j, src in enumerate(SECTORS_ORDER):
            w = float(matrix[i][j])
            if w != 0.0 and src != dest:
                out[src][dest] = w
    return out


def apply_dependencies_quantitative(energy_risk: float, water_risk: float, transport_risk: float) -> dict[str, float]:
    """Количественный оператор: x' = clip(x + A x).

    Здесь x = (energy, water, transport) в шкале [0,1].
    A[i][j] — вклад риска j в риск i.
    """
    x = [float(energy_risk), float(water_risk), float(transport_risk)]
    A = CURRENT_DEPENDENCY_MATRIX

    # y = x + A x
    y = [0.0, 0.0, 0.0]
    for i in range(3):
        ax = 0.0
        for j in range(3):
            ax += float(A[i][j]) * x[j]
        y[i] = x[i] + ax

    # clip to [0,1]
    for i in range(3):
        if y[i] < 0.0:
            y[i] = 0.0
        elif y[i] > 1.0:
            y[i] = 1.0

    return {
        "energy": y[0],
        "water": y[1],
        "transport": y[2],
    }


def apply_dependencies_classical(
    energy_risk: float,
    water_risk: float,
    transport_risk: float,
    threshold: float = 0.5,
) -> dict[str, float]:
    """Классический rule-based подход.

    1) Бинаризация рисков: y_i = I(x_i >= threshold).
    2) Распространение деградаций по A с порогом связности:
       y_i(t+1) = y_i(t) OR exists j: (y_j(t)=1 AND A[i][j] >= threshold)

    Возвращает бинарные риски, приведённые к {0,1}.
    """
    y = [
        1.0 if float(energy_risk) >= threshold else 0.0,
        1.0 if float(water_risk) >= threshold else 0.0,
        1.0 if float(transport_risk) >= threshold else 0.0,
    ]

    A = CURRENT_DEPENDENCY_MATRIX

    # One-step propagation (достаточно для сценарного детектора каскада)
    y_next = y.copy()
    for i in range(3):
        if y_next[i] >= 1.0:
            continue
        for j in range(3):
            if y[j] >= 1.0 and float(A[i][j]) >= threshold:
                y_next[i] = 1.0
                break

    return {
        "energy": y_next[0],
        "water": y_next[1],
        "transport": y_next[2],
    }


# ---------- Вспомогательные функции ----------


def _risk_candidates(status_url: str) -> list[str]:
    """Build candidate risk endpoints for a service from its status URL."""
    base = status_url.rstrip("/")
    candidates = []
    if base.endswith("/status"):
        candidates.append(base[: -len("/status")] + "/risk/current")
    if "/api/v1/" in base:
        prefix = base.split("/api/v1/")[0]
        tail = base.split("/api/v1/")[1]
        sector = tail.split("/")[0] if tail else ""
        if sector:
            candidates.append(f"{prefix}/api/v1/{sector}/risk/current")
    return list(dict.fromkeys(candidates))


async def fetch_sector_risk(url: str, name: str, scenario_id: Optional[str] = None, run_id: Optional[int] = None) -> float:
    """Fetch normalized sector risk x_i in [0,1].

    Priority: explicit sector risk endpoint (/risk/current). Fallback: operational flag -> {0,1}.
    """
    params = {}
    if scenario_id is not None:
        params["scenario_id"] = scenario_id
    if run_id is not None:
        params["run_id"] = run_id

    try:
        async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT) as client:
            for risk_url in _risk_candidates(url):
                try:
                    resp = await client.get(risk_url, params=params)
                    resp.raise_for_status()
                    data = resp.json()
                    if "risk" in data:
                        risk = float(data["risk"])
                        logger.debug("🔍 Sector %s: direct risk=%.3f", name, risk)
                        return max(0.0, min(1.0, risk))
                except (httpx.RequestError, httpx.HTTPStatusError, ValueError, TypeError):
                    continue

            # Fallback to status endpoint behavior (prefer continuous degradation over binary flag)
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

            degradation = data.get("degradation")
            if degradation is None:
                degradation = data.get("risk_proxy")
            if degradation is None and "supply" in data and "demand" in data:
                demand = float(data.get("demand", 0.0) or 0.0)
                supply = float(data.get("supply", 0.0) or 0.0)
                degradation = max(0.0, demand - supply) / max(demand, 1.0)
            if degradation is None and "load" in data:
                degradation = float(data.get("load", 0.0) or 0.0)

            if degradation is not None:
                risk = max(0.0, min(1.0, float(degradation)))
                logger.debug("🔍 Sector %s: fallback degradation risk=%.3f", name, risk)
                return risk

            is_op = data.get("is_operational")
            if is_op is None:
                is_op = data.get("operational")
            risk = 0.0 if bool(is_op) else 1.0
            logger.debug("🔍 Sector %s: fallback binary risk=%.3f", name, risk)
            return risk

    except httpx.RequestError as e:
        logger.error(f"❌ HTTP error while fetching {name} risk/status: {e}")
        return 1.0
    except httpx.HTTPStatusError as e:
        logger.warning(
            f"⚠️ {name} service returned HTTP {e.response.status_code} to risk_engine"
        )
        return 1.0
    except Exception as e:
        logger.error(f"❌ Unexpected error while fetching {name} risk/status: {e}")
        return 1.0


async def calculate_risks(
    save: bool,
    db: Session | None,
    method: RiskMethod = "quantitative",
    scenario_id: Optional[str] = None,
    run_id: Optional[int] = None,
) -> Union[AggregatedRisk, RiskSnapshotOut]:
    """
    Основная функция расчёта рисков:
      - опрашивает energy / water / transport,
      - переводит состояние в риск (0 или 1),
      - агрегирует риск по весам,
      - опционально сохраняет снапшот в БД.
    """

    # Normalize method defensively (in case of future callers passing raw strings)
    method_norm = str(method).strip().lower()
    if method_norm not in {"classical", "quantitative"}:
        raise HTTPException(status_code=400, detail=f"Unknown method: {method}")

    # Параллельно опрашиваем три сектора
    energy_risk, water_risk, transport_risk = await asyncio.gather(
        fetch_sector_risk(settings.ENERGY_SERVICE_URL, "energy", scenario_id=scenario_id, run_id=run_id),
        fetch_sector_risk(settings.WATER_SERVICE_URL, "water", scenario_id=scenario_id, run_id=run_id),
        fetch_sector_risk(settings.TRANSPORT_SERVICE_URL, "transport", scenario_id=scenario_id, run_id=run_id),
    )

    energy_ok = energy_risk < 0.5
    water_ok = water_risk < 0.5
    transport_ok = transport_risk < 0.5

    # Применяем матрицу межотраслевых зависимостей
    if method_norm == "classical":
        sector_risk = apply_dependencies_classical(energy_risk, water_risk, transport_risk)
    else:
        sector_risk = apply_dependencies_quantitative(energy_risk, water_risk, transport_risk)
    adj_energy_risk = sector_risk["energy"]
    adj_water_risk = sector_risk["water"]
    adj_transport_risk = sector_risk["transport"]

    # Интегральный риск как взвешенная сумма уже скорректированных рисков
    w_e = WEIGHTS["energy"]
    w_w = WEIGHTS["water"]
    w_t = WEIGHTS["transport"]
    w_sum = w_e + w_w + w_t if (w_e + w_w + w_t) > 0 else 1.0

    total_risk = (adj_energy_risk * w_e + adj_water_risk * w_w + adj_transport_risk * w_t) / w_sum

    # Интегральный риск тоже ограничиваем диапазоном [0, 1],
    # чтобы он не выходил за рамки шкалы и валидировался Pydantic-схемой.
    if total_risk < 0.0:
        total_risk = 0.0
    elif total_risk > 1.0:
        total_risk = 1.0

    logger.info(
        "📊 Calculated risks | energy=%.2f, water=%.2f, transport=%.2f, total=%.2f",
        adj_energy_risk,
        adj_water_risk,
        adj_transport_risk,
        total_risk,
    )

    if not save:
        # Возвращаем просто текущий агрегированный риск, ничего не записывая
        return AggregatedRisk(
            energy_risk=adj_energy_risk,
            water_risk=adj_water_risk,
            transport_risk=adj_transport_risk,
            total_risk=total_risk,
        )

    if db is None:
        raise HTTPException(
            status_code=500,
            detail="DB session is required to save risk snapshot.",
        )

    # Сохраняем снапшот в БД
    snapshot = RiskSnapshot(
        energy_risk=adj_energy_risk,
        water_risk=adj_water_risk,
        transport_risk=adj_transport_risk,
        total_risk=total_risk,
        meta={
            "weights": {
                "energy": w_e,
                "water": w_w,
                "transport": w_t,
            },
            "operational_flags": {
                "energy": energy_ok,
                "water": water_ok,
                "transport": transport_ok,
            },
            "raw_sector_risk": {
                "energy": energy_risk,
                "water": water_risk,
                "transport": transport_risk,
            },
            "dependency_matrix_version": CURRENT_DEPENDENCY_MATRIX_VERSION,
            "dependency_matrix": CURRENT_DEPENDENCY_MATRIX,
            "dependency_matrix_dict": _matrix_as_dict(CURRENT_DEPENDENCY_MATRIX),
            "method": method_norm,
            "scenario_id": scenario_id,
            "run_id": run_id,
        },
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)

    logger.info("💾 Risk snapshot saved with id=%s", snapshot.id)
    return RiskSnapshotOut.model_validate(snapshot)


# ---------- Эндпойнты ----------

class WeightUpdate(BaseModel):
    energy: float | None = None
    water: float | None = None
    transport: float | None = None


@router.get("/current", response_model=AggregatedRisk)
async def get_current_risk(
    method: RiskMethod = "quantitative",
    scenario_id: Optional[str] = None,
    run_id: Optional[int] = None,
):
    """
    Возвращает текущую оценку интегрального риска без сохранения в БД.
    Используется для онлайн-оценки состояния инфраструктуры.
    """
    result = await calculate_risks(save=False, db=None, method=method, scenario_id=scenario_id, run_id=run_id)
    # Здесь result всегда AggregatedRisk
    return result  # type: ignore[return-value]


@router.post("/recalculate", response_model=Union[AggregatedRisk, RiskSnapshotOut])
async def recalculate_risk(
    body: RiskRecalcRequest,
    db: Session = Depends(get_db),
):
    """
    Пересчитывает риск по текущему состоянию доменных сервисов.
    По умолчанию сохраняет снапшот в БД (save=True).
      - Если save=False → просто возвращает AggregatedRisk.
      - Если save=True  → сохраняет и возвращает сохранённый RiskSnapshotOut.
    """
    result = await calculate_risks(save=body.save, db=db, method=body.method, scenario_id=body.scenario_id, run_id=body.run_id)
    return result

@router.post("/update_weights")
async def update_weights(payload: WeightUpdate):
    """
    Обновляет веса отраслей в интегральном риске.
    Работает до перезапуска контейнера (in-memory).
    Стартовые значения берутся из config.py / .env.
    """
    if not settings.ENABLE_DYNAMIC_WEIGHTS:
        raise HTTPException(status_code=403, detail="Dynamic weights update is disabled by configuration")

    if payload.energy is not None:
        WEIGHTS["energy"] = payload.energy
    if payload.water is not None:
        WEIGHTS["water"] = payload.water
    if payload.transport is not None:
        WEIGHTS["transport"] = payload.transport

    total = WEIGHTS["energy"] + WEIGHTS["water"] + WEIGHTS["transport"]
    if total <= 0:
        raise HTTPException(status_code=400, detail="Sum of weights must be > 0")

    return {"weights": WEIGHTS, "sum": total}


class DependencyMatrixUpdate(BaseModel):
    matrix: list[list[float]]
    version: str | None = None


@router.get("/dependency_matrix")
async def get_dependency_matrix():
    """Возвращает текущую матрицу A и её версию (для воспроизводимости экспериментов)."""
    return {
        "sectors_order": SECTORS_ORDER,
        "version": CURRENT_DEPENDENCY_MATRIX_VERSION,
        "matrix": CURRENT_DEPENDENCY_MATRIX,
    }


@router.post("/dependency_matrix")
async def update_dependency_matrix(payload: DependencyMatrixUpdate):
    """Обновляет матрицу A (in-memory) и версию.

    Используется для контролируемых экспериментов и анализа чувствительности.
    """
    if not getattr(settings, "ENABLE_DYNAMIC_MATRIX", False):
        raise HTTPException(status_code=403, detail="Dynamic dependency matrix update is disabled by configuration")

    _validate_matrix_3x3(payload.matrix)

    global CURRENT_DEPENDENCY_MATRIX, CURRENT_DEPENDENCY_MATRIX_VERSION
    CURRENT_DEPENDENCY_MATRIX = payload.matrix

    # Если версия не передана, авто-инкрементируем vX.Y -> v(X+1).Y (простая политика)
    if payload.version:
        CURRENT_DEPENDENCY_MATRIX_VERSION = payload.version
    else:
        # best-effort auto bump
        ver = CURRENT_DEPENDENCY_MATRIX_VERSION
        try:
            if ver.startswith("v"):
                num = ver[1:]
                major = int(num.split(".")[0])
                rest = ".".join(num.split(".")[1:])
                if rest:
                    CURRENT_DEPENDENCY_MATRIX_VERSION = f"v{major + 1}.{rest}"
                else:
                    CURRENT_DEPENDENCY_MATRIX_VERSION = f"v{major + 1}"
            else:
                CURRENT_DEPENDENCY_MATRIX_VERSION = ver + "+1"
        except Exception:
            CURRENT_DEPENDENCY_MATRIX_VERSION = ver + "+1"

    return {
        "status": "updated",
        "sectors_order": SECTORS_ORDER,
        "version": CURRENT_DEPENDENCY_MATRIX_VERSION,
        "matrix": CURRENT_DEPENDENCY_MATRIX,
    }


@router.get("/history", response_model=RiskHistory)
async def get_risk_history(
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """
    Возвращает историю сохранённых оценок риска (последние N записей).
    """
    if limit <= 0:
        raise HTTPException(status_code=400, detail="limit must be positive")

    items = (
        db.query(RiskSnapshot)
        .order_by(RiskSnapshot.calculated_at.desc())
        .limit(limit)
        .all()
    )

    # Преобразуем ORM-модели в DTO
    dto_items = [RiskSnapshotOut.model_validate(obj) for obj in items]

    return RiskHistory(items=dto_items, count=len(dto_items))
