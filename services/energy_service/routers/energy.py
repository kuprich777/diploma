from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import EnergyRecord
from schemas import EnergyStatus, Outage
from utils.logging import setup_logging
from config import settings

logger = setup_logging()

# Создаём роутер для эндпойнтов микросервиса
router = APIRouter(prefix="/api/v1/energy", tags=["energy"])

@router.post("/init", tags=["energy"])
async def init_energy_state(db: Session = Depends(get_db)):
    """Инициализирует базовую запись состояния энергосистемы."""
    record = db.query(EnergyRecord).order_by(EnergyRecord.id.desc()).first()
    if record:
        return {"message": "Already initialized"}

    new_record = EnergyRecord(
        production=settings.DEFAULT_PRODUCTION,
        consumption=settings.DEFAULT_CONSUMPTION,
        is_operational=True,
    )
    db.add(new_record)
    db.commit()
    return {
        "message": "Initialized",
        "production": new_record.production,
        "consumption": new_record.consumption,
    }

# --- Основные эндпойнты ---
@router.get("/status", response_model=EnergyStatus)
async def get_energy_status(db: Session = Depends(get_db)):
    """Возвращает текущее состояние энергетического сектора."""
    record = db.query(EnergyRecord).order_by(EnergyRecord.id.desc()).first()
    if not record:
        raise HTTPException(status_code=404, detail="No records found")

    logger.debug(f"📊 Current energy status: {record.production}/{record.consumption}")
    return EnergyStatus(
        production=record.production,
        consumption=record.consumption,
        is_operational=record.is_operational
    )


@router.post("/adjust_production")
async def adjust_production(amount: float, db: Session = Depends(get_db)):
    """Регулирует производство энергии (изменяет мощность)."""
    record = db.query(EnergyRecord).order_by(EnergyRecord.id.desc()).first()
    if not record:
        raise HTTPException(status_code=404, detail="No records found")

    new_production = max(0, record.production + amount)
    new_record = EnergyRecord(
        production=new_production,
        consumption=record.consumption,
        is_operational=new_production > 0
    )
    db.add(new_record)
    db.commit()
    logger.info(f"🔧 Adjusted production by {amount} → {new_production} MW")
    return {"production": new_production}


@router.post("/adjust_consumption")
async def adjust_consumption(amount: float, db: Session = Depends(get_db)):
    """Регулирует потребление энергии (спрос)."""
    record = db.query(EnergyRecord).order_by(EnergyRecord.id.desc()).first()
    if not record:
        raise HTTPException(status_code=404, detail="No records found")

    new_consumption = max(0, record.consumption + amount)
    new_record = EnergyRecord(
        production=record.production,
        consumption=new_consumption,
        is_operational=record.is_operational
    )
    db.add(new_record)
    db.commit()
    logger.info(f"💡 Adjusted consumption by {amount} → {new_consumption} MW")
    return {"consumption": new_consumption}


@router.post("/simulate_outage")
async def simulate_outage(outage: Outage, db: Session = Depends(get_db)):
    """Симулирует сбой в энергосекторе."""
    record = db.query(EnergyRecord).order_by(EnergyRecord.id.desc()).first()
    if not record:
        raise HTTPException(status_code=404, detail="No records found")

    new_record = EnergyRecord(
        production=record.production,
        consumption=record.consumption,
        is_operational=False,
        reason=outage.reason,
        duration=outage.duration
    )
    db.add(new_record)
    db.commit()
    logger.warning(f"⚠️ Outage simulated: {outage.reason}, duration {outage.duration} min")
    return {"message": f"Outage simulated: {outage.reason}, duration: {outage.duration} minutes"}


@router.post("/resolve_outage")
async def resolve_outage(db: Session = Depends(get_db)):
    """Восстанавливает работу системы после сбоя."""
    record = db.query(EnergyRecord).order_by(EnergyRecord.id.desc()).first()
    if not record:
        raise HTTPException(status_code=404, detail="No records found")

    new_record = EnergyRecord(
        production=record.production,
        consumption=record.consumption,
        is_operational=True
    )
    db.add(new_record)
    db.commit()
    logger.info("✅ Outage resolved, system is operational again.")
    return {"message": "Outage resolved, system is operational"}
