from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import httpx

from database import get_db
from models import WaterStatus as WaterStatusModel
from schemas import WaterStatus, SupplyUpdate, DemandUpdate
from utils.logging import setup_logging
from config import settings

logger = setup_logging()

router = APIRouter(prefix="/api/v1/water", tags=["water"])


# ---------- Вспомогательные функции ----------

async def fetch_energy_operational() -> bool:
    """
    Запрашивает статус энергосервиса.
    Ожидает endpoint /api/v1/energy/status от energy_service.
    """
    energy_status_url = settings.ENERGY_SERVICE_URL.rstrip("/") + "/api/v1/energy/status"
    try:
        async with httpx.AsyncClient(timeout=settings.ENERGY_CHECK_TIMEOUT) as client:
            resp = await client.get(energy_status_url)
        resp.raise_for_status()
        data = resp.json()
        is_op = bool(data.get("is_operational", False))
        logger.debug(f"🔌 Energy service operational (from water): {is_op}")
        return is_op
    except httpx.RequestError as e:
        logger.error(f"❌ Error connecting to Energy Service from water_service: {e}")
        return False
    except httpx.HTTPStatusError as e:
        logger.warning(
            f"⚠️ Energy Service returned HTTP {e.response.status_code} to water_service"
        )
        return False


# ---------- Эндпойнты ----------

@router.post("/init")
async def init_water_state(db: Session = Depends(get_db)):
    """
    Инициализирует базовую запись состояния водного сектора.
    Использует дефолтные значения из config.py.
    """
    record = (
        db.query(WaterStatusModel)
        .order_by(WaterStatusModel.id.desc())
        .first()
    )
    if record:
        return {"message": "Water state already initialized"}

    new_record = WaterStatusModel(
        supply=settings.DEFAULT_SUPPLY,
        demand=settings.DEFAULT_DEMAND,
        operational=settings.DEFAULT_OPERATIONAL,
        energy_dependent=True,
        reason=None,
    )
    db.add(new_record)
    db.commit()
    db.refresh(new_record)

    logger.info(
        f"💧 Water initialized: supply={new_record.supply}, "
        f"demand={new_record.demand}, operational={new_record.operational}"
    )

    return {
        "message": "Water state initialized",
        "supply": new_record.supply,
        "demand": new_record.demand,
        "operational": new_record.operational,
    }


@router.get("/status", response_model=WaterStatus)
async def get_water_status(db: Session = Depends(get_db)):
    """
    Возвращает текущее состояние водного сектора.
    """
    record = (
        db.query(WaterStatusModel)
        .order_by(WaterStatusModel.id.desc())
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="No water status found")

    return WaterStatus(
        supply=record.supply,
        demand=record.demand,
        operational=record.operational,
        energy_dependent=record.energy_dependent,
        reason=record.reason,
    )


@router.post("/adjust_supply")
async def adjust_supply(update: SupplyUpdate, db: Session = Depends(get_db)):
    """
    Обновляет объём производства воды (скважины, насосные станции).
    """
    record = (
        db.query(WaterStatusModel)
        .order_by(WaterStatusModel.id.desc())
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="No water status found")

    new_record = WaterStatusModel(
        supply=update.supply,
        demand=record.demand,
        operational=record.operational,
        energy_dependent=record.energy_dependent,
        reason=record.reason,
    )
    db.add(new_record)
    db.commit()
    db.refresh(new_record)

    logger.info(f"🚰 Water supply updated: {new_record.supply}")
    return {"message": "Water supply updated", "supply": new_record.supply}


@router.post("/adjust_demand")
async def adjust_demand(update: DemandUpdate, db: Session = Depends(get_db)):
    """
    Обновляет объём потребления воды (население, промышленность).
    """
    record = (
        db.query(WaterStatusModel)
        .order_by(WaterStatusModel.id.desc())
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="No water status found")

    new_record = WaterStatusModel(
        supply=record.supply,
        demand=update.demand,
        operational=record.operational,
        energy_dependent=record.energy_dependent,
        reason=record.reason,
    )
    db.add(new_record)
    db.commit()
    db.refresh(new_record)

    logger.info(f"🚿 Water demand updated: {new_record.demand}")
    return {"message": "Water demand updated", "demand": new_record.demand}


@router.post("/check_energy_dependency")
async def check_energy_dependency(db: Session = Depends(get_db)):
    """
    Проверяет зависимость водного сектора от энергосервиса.
    Если Energy Service не работает — помечает water как неоперационный.
    """
    record = (
        db.query(WaterStatusModel)
        .order_by(WaterStatusModel.id.desc())
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="No water status found")

    is_energy_ok = await fetch_energy_operational()

    if not is_energy_ok:
        new_record = WaterStatusModel(
            supply=record.supply,
            demand=record.demand,
            operational=False,
            energy_dependent=True,
            reason="Energy service outage",
        )
        db.add(new_record)
        db.commit()
        db.refresh(new_record)

        logger.warning("🚨 Water sector impacted by energy outage")
        return {
            "message": "Water sector impacted by energy outage",
            "operational": False,
            "reason": new_record.reason,
        }

    logger.info("✅ Energy service operational, water not impacted")
    return {
        "message": "Energy service is operational, no impact on water sector",
        "operational": record.operational,
        "reason": record.reason,
    }
