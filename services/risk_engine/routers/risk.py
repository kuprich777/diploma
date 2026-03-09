# services/risk_engine/routers/risk.py

import asyncio
from typing import Any, Union, Literal, Optional

from pydantic import BaseModel

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from aggregator import RiskAggregator
from config import settings
from database import get_db
from models import RiskSnapshot
from operators import ClassicalOperator, QuantitativeOperator, RiskOperator
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

# Weights version — bumped when POST /update_weights is called
CURRENT_WEIGHTS_VERSION: str = "v1.0"

logger = setup_logging()

router = APIRouter(prefix="/api/v1/risk", tags=["risk"])

# ---------------------------------------------------------------------------
# Async messaging state
# ---------------------------------------------------------------------------
_mq: Any = None  # RabbitMQConnection | None


def set_mq(conn: Any) -> None:
    """Injected by main.py startup after the broker connects."""
    global _mq
    _mq = conn


def _is_mq_connected() -> bool:
    return _mq is not None and _mq.is_connected


# ---------------------------------------------------------------------------
# Event-driven sector state cache
# key: (scenario_id, run_id, sector)  — all strings
# value: {"risk": float, "operational": bool, "updated_at": int}
# ---------------------------------------------------------------------------
_sector_cache: dict[tuple[str, str, str], dict] = {}
_prev_total_risk: dict[tuple[str, str], float] = {}


async def handle_sector_event(envelope: dict) -> None:
    """Consumer handler for energy/water/transport.state_changed events.

    Updates the in-memory sector cache, then immediately recomputes the
    integral risk R_t and publishes a ``risk.updated`` event.
    """
    scenario_id = str(envelope.get("scenario_id", ""))
    run_id = str(envelope.get("run_id", ""))
    sector = str(envelope.get("sector", ""))
    payload = envelope.get("payload", {})

    if not sector:
        logger.warning("📭 risk_engine received sector event with no 'sector' field — skipping")
        return

    # Extract normalised risk from payload (try multiple field names)
    risk_val = float(
        payload.get("risk_level")
        or payload.get("degradation")
        or (0.0 if payload.get("operational", True) else 1.0)
    )
    risk_val = max(0.0, min(1.0, risk_val))

    _sector_cache[(scenario_id, run_id, sector)] = {
        "risk": risk_val,
        "operational": bool(payload.get("operational", True)),
        "updated_at": envelope.get("timestamp_step", 0),
    }
    logger.info(
        "📊 [risk_engine] sector cache updated: %s (%s, %s) risk=%.3f",
        sector, scenario_id, run_id, risk_val,
    )

    # Trigger async risk recomputation (fire-and-forget, must not block consumer)
    asyncio.create_task(_recompute_and_publish(scenario_id, run_id))


async def _recompute_and_publish(scenario_id: str, run_id: str) -> None:
    """Recompute integral risk from cached sector values and publish risk.updated."""
    cached_e = _sector_cache.get((scenario_id, run_id, "energy"))
    cached_w = _sector_cache.get((scenario_id, run_id, "water"))
    cached_t = _sector_cache.get((scenario_id, run_id, "transport"))

    if not all([cached_e, cached_w, cached_t]):
        return  # not enough cached sectors yet

    x_t = [cached_e["risk"], cached_w["risk"], cached_t["risk"]]
    u_t = [0.0, 0.0, 0.0]
    A = CURRENT_DEPENDENCY_MATRIX

    op = QuantitativeOperator()
    adjusted = op.compute(x_t, u_t, A)

    aggregator = RiskAggregator(WEIGHTS)
    total_risk = aggregator.aggregate_vector(SECTORS_ORDER, adjusted)

    prev = _prev_total_risk.get((scenario_id, run_id), total_risk)
    delta_R = total_risk - prev
    _prev_total_risk[(scenario_id, run_id)] = total_risk

    cascade_indicator = any(v >= 0.8 for i, v in enumerate(adjusted))

    if _is_mq_connected():
        try:
            from messaging import publish_event_safe
            await publish_event_safe(
                _mq.channel,
                settings.RABBITMQ_EXCHANGE,
                "risk.updated",
                {
                    "integral_risk": total_risk,
                    "x_vector": {
                        "energy": adjusted[0],
                        "water": adjusted[1],
                        "transport": adjusted[2],
                    },
                    "delta_R": delta_R,
                    "cascade_indicator": cascade_indicator,
                    "method": "quantitative",
                },
                scenario_id=scenario_id,
                run_id=run_id,
                sector="risk",
                version_A=CURRENT_DEPENDENCY_MATRIX_VERSION,
                version_w=CURRENT_WEIGHTS_VERSION,
            )
        except Exception as exc:
            logger.warning("📤 risk.updated publish failed: %s", exc)


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

    # ------------------------------------------------------------------
    # Fast-path: use event-driven sector cache if all three sectors
    # have been updated via async messaging (avoids HTTP polling).
    # Falls back to HTTP if any cache entry is missing.
    # ------------------------------------------------------------------
    sid = str(scenario_id or "")
    rid = str(run_id or "")
    cached_e = _sector_cache.get((sid, rid, "energy"))
    cached_w = _sector_cache.get((sid, rid, "water"))
    cached_t = _sector_cache.get((sid, rid, "transport"))

    if cached_e and cached_w and cached_t:
        energy_risk = cached_e["risk"]
        water_risk = cached_w["risk"]
        transport_risk = cached_t["risk"]
        logger.debug(
            "📦 [risk_engine] cache fast-path for (%s, %s): e=%.3f w=%.3f t=%.3f",
            sid, rid, energy_risk, water_risk, transport_risk,
        )
    else:
        # HTTP polling fallback (original behaviour)
        energy_risk, water_risk, transport_risk = await asyncio.gather(
            fetch_sector_risk(settings.ENERGY_SERVICE_URL, "energy", scenario_id=scenario_id, run_id=run_id),
            fetch_sector_risk(settings.WATER_SERVICE_URL, "water", scenario_id=scenario_id, run_id=run_id),
            fetch_sector_risk(settings.TRANSPORT_SERVICE_URL, "transport", scenario_id=scenario_id, run_id=run_id),
        )

    energy_ok = energy_risk < 0.5
    water_ok = water_risk < 0.5
    transport_ok = transport_risk < 0.5

    # ------------------------------------------------------------------
    # Применяем оператор распространения рисков через матрицу зависимостей.
    # u_t = [0, 0, 0]: в текущем цикле опроса внешние шоки не подаются —
    # они применяются через вызовы доменных сервисов (/simulate_outage и др.)
    # ------------------------------------------------------------------
    A = CURRENT_DEPENDENCY_MATRIX
    x_t = [energy_risk, water_risk, transport_risk]
    u_t = [0.0, 0.0, 0.0]

    op: RiskOperator
    if method_norm == "classical":
        op = ClassicalOperator(theta=settings.CLASSICAL_THRESHOLD)
    else:
        op = QuantitativeOperator()

    adjusted = op.compute(x_t, u_t, A)
    adj_energy_risk, adj_water_risk, adj_transport_risk = adjusted

    # ------------------------------------------------------------------
    # Интегральный риск R_t = Agg(x_t, w) — нормализованная взвешенная сумма.
    # ------------------------------------------------------------------
    aggregator = RiskAggregator(WEIGHTS)
    sector_dict = dict(zip(SECTORS_ORDER, adjusted))
    total_risk = aggregator.aggregate(sector_dict)

    # Сохраняем веса из агрегатора для записи в meta
    w_e = WEIGHTS["energy"]
    w_w = WEIGHTS["water"]
    w_t = WEIGHTS["transport"]

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

    global CURRENT_WEIGHTS_VERSION

    if payload.energy is not None:
        WEIGHTS["energy"] = payload.energy
    if payload.water is not None:
        WEIGHTS["water"] = payload.water
    if payload.transport is not None:
        WEIGHTS["transport"] = payload.transport

    total = WEIGHTS["energy"] + WEIGHTS["water"] + WEIGHTS["transport"]
    if total <= 0:
        raise HTTPException(status_code=400, detail="Sum of weights must be > 0")

    # Bump weights version for traceability in event envelopes
    try:
        num = int(CURRENT_WEIGHTS_VERSION.lstrip("v").split(".")[0])
        CURRENT_WEIGHTS_VERSION = f"v{num + 1}.0"
    except Exception:
        CURRENT_WEIGHTS_VERSION = CURRENT_WEIGHTS_VERSION + "+1"

    return {"weights": WEIGHTS, "sum": total, "version": CURRENT_WEIGHTS_VERSION}


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


# ---------------------------------------------------------------------------
# Admin: dead-letter queue inspection
# ---------------------------------------------------------------------------

@router.get("/admin/dead-letters", tags=["admin"])
async def get_dead_letters(
    count: int = Query(default=20, ge=1, le=100, description="Max messages to retrieve"),
) -> dict:
    """Inspect failed messages in the dead-letter queue (non-destructive peek).

    Uses the RabbitMQ Management HTTP API with ``ack_requeue_true`` so that
    messages are returned to the queue after inspection.  Returns an empty
    list if the queue does not yet exist or is empty.

    Requires the RabbitMQ management plugin (enabled by default on the
    ``rabbitmq:3-management`` Docker image).
    """
    from messaging import DLQ_NAME  # imported here to keep optional

    mgmt = settings.RABBITMQ_MANAGEMENT_URL.rstrip("/")
    url = f"{mgmt}/api/queues/%2F/{DLQ_NAME}/get"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                url,
                json={
                    "count": count,
                    "ackmode": "ack_requeue_true",
                    "encoding": "auto",
                },
                auth=("guest", "guest"),
            )

        if resp.status_code == 200:
            messages = resp.json()
            return {
                "queue": DLQ_NAME,
                "count": len(messages),
                "messages": messages,
            }

        if resp.status_code == 404:
            return {
                "queue": DLQ_NAME,
                "count": 0,
                "messages": [],
                "note": "Queue not found (no failed messages yet)",
            }

        raise HTTPException(
            status_code=resp.status_code,
            detail=f"RabbitMQ management API returned {resp.status_code}",
        )

    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot reach RabbitMQ management API at {mgmt}: {exc}",
        )
