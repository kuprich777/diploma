# services/risk_engine/routers/risk.py

import asyncio
from typing import Union
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

# Простая матрица межотраслевых зависимостей
# Ключи: источник риска → словарь (зависимый сектор → коэффициент влияния)
DEPENDENCY_MATRIX = {
    "energy": {"water": 0.6, "transport": 0.4},
    "water": {"transport": 0.3},
}


def apply_dependencies(energy_risk: float, water_risk: float, transport_risk: float) -> dict[str, float]:
    """\
    Применяет простую модель кросс-отраслевых эффектов:
    риск одного сектора частично переносится на другие по матрице DEPENDENCY_MATRIX.

    Возвращает скорректированные секторальные риски.
    """
    sector_risk = {
        "energy": float(energy_risk),
        "water": float(water_risk),
        "transport": float(transport_risk),
    }

    # Проходим по матрице и добавляем влияние источников на зависимые сектора
    for src, deps in DEPENDENCY_MATRIX.items():
        src_val = sector_risk.get(src, 0.0)
        for dest, weight in deps.items():
            if dest not in sector_risk:
                continue
            sector_risk[dest] += src_val * weight

    # Нормируем секторальные риски в диапазон [0, 1],
    # чтобы они соответствовали шкале моделей и ограничениям Pydantic.
    for key in sector_risk:
        if sector_risk[key] < 0.0:
            sector_risk[key] = 0.0
        elif sector_risk[key] > 1.0:
            sector_risk[key] = 1.0

    return sector_risk

# Текущие веса отраслей для агрегирования риска (могут обновляться через API)
WEIGHTS = {
    "energy": settings.ENERGY_WEIGHT,
    "water": settings.WATER_WEIGHT,
    "transport": settings.TRANSPORT_WEIGHT,
}

logger = setup_logging()

router = APIRouter(prefix="/api/v1/risk", tags=["risk"])


# ---------- Вспомогательные функции ----------


async def fetch_sector_operational(url: str, name: str) -> bool:
    """
    Запрашивает статус сектора по его URL.
    Ожидаем, что сервис вернёт JSON с полем is_operational или operational.
    Если запрос не удался — считаем сектор неработоспособным (максимальный риск).
    """
    try:
        async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT) as client:
            resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

        # energy_service возвращает is_operational,
        # water/transport — operational
        is_op = data.get("is_operational")
        if is_op is None:
            is_op = data.get("operational")

        is_op = bool(is_op)
        logger.debug(f"🔍 Sector {name}: operational={is_op}")
        return is_op
    except httpx.RequestError as e:
        logger.error(f"❌ HTTP error while fetching {name} status: {e}")
        return False
    except httpx.HTTPStatusError as e:
        logger.warning(
            f"⚠️ {name} service returned HTTP {e.response.status_code} to risk_engine"
        )
        return False
    except Exception as e:
        logger.error(f"❌ Unexpected error while fetching {name} status: {e}")
        return False


async def calculate_risks(save: bool, db: Session | None) -> Union[AggregatedRisk, RiskSnapshotOut]:
    """
    Основная функция расчёта рисков:
      - опрашивает energy / water / transport,
      - переводит состояние в риск (0 или 1),
      - агрегирует риск по весам,
      - опционально сохраняет снапшот в БД.
    """

    # Параллельно опрашиваем три сектора
    energy_ok, water_ok, transport_ok = await asyncio.gather(
        fetch_sector_operational(settings.ENERGY_SERVICE_URL, "energy"),
        fetch_sector_operational(settings.WATER_SERVICE_URL, "water"),
        fetch_sector_operational(settings.TRANSPORT_SERVICE_URL, "transport"),
    )

    energy_risk = 0.0 if energy_ok else 1.0
    water_risk = 0.0 if water_ok else 1.0
    transport_risk = 0.0 if transport_ok else 1.0

    # Применяем матрицу межотраслевых зависимостей
    sector_risk = apply_dependencies(energy_risk, water_risk, transport_risk)
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
            "dependency_matrix": DEPENDENCY_MATRIX,
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
async def get_current_risk():
    """
    Возвращает текущую оценку интегрального риска без сохранения в БД.
    Используется для онлайн-оценки состояния инфраструктуры.
    """
    result = await calculate_risks(save=False, db=None)
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
    result = await calculate_risks(save=body.save, db=db)
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
