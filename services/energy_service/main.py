from fastapi import FastAPI, HTTPException, Depends
from sqlalchemy.orm import Session
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel
from typing import Optional

from database import get_db, engine, ensure_schema
from models import Base, EnergyRecord
from utils.logging import setup_logging

# --- Инициализация приложения ---
logger = setup_logging()
app = FastAPI(title="energy_service", version="1.0.0", description="Energy sector microservice")

# Метрики Prometheus — доступны на /metrics
Instrumentator().instrument(app).expose(app, include_in_schema=False)

# --- События приложения ---
@app.on_event("startup")
def startup_event():
    """Создание схемы и таблиц при запуске"""
    ensure_schema()
    Base.metadata.create_all(bind=engine)
    logger.info("✅ energy_service started and schema ensured.")


# --- Pydantic-схемы (DTO) ---
class EnergyStatus(BaseModel):
    production: float
    consumption: float
    is_operational: bool


class Outage(BaseModel):
    reason: str
    duration: int  # в минутах


# --- Health & readiness ---
@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok", "service": "energy_service"}


@app.get("/ready", tags=["system"])
async def ready():
    return {"status": "ready"}


@app.get("/", include_in_schema=False)
async def root():
    return {"message": "Energy Service is operational"}


# --- Бизнес-эндпойнты ---
@app.get("/status", response_model=EnergyStatus, tags=["energy"])
async def get_energy_status(db: Session = Depends(get_db)):
    """Возвращает текущее состояние энергетического сектора"""
    record = db.query(EnergyRecord).order_by(EnergyRecord.id.desc()).first()
    if not record:
        raise HTTPException(status_code=404, detail="No records found")
    return EnergyStatus(
        production=record.production,
        consumption=record.consumption,
        is_operational=record.is_operational
    )


@app.post("/adjust_production", tags=["energy"])
async def adjust_production(amount: float, db: Session = Depends(get_db)):
    """Регулирует производство энергии"""
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


@app.post("/adjust_consumption", tags=["energy"])
async def adjust_consumption(amount: float, db: Session = Depends(get_db)):
    """Регулирует потребление энергии"""
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


@app.post("/simulate_outage", tags=["energy"])
async def simulate_outage(outage: Outage, db: Session = Depends(get_db)):
    """Симулирует сбой в энергосекторе"""
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


@app.post("/resolve_outage", tags=["energy"])
async def resolve_outage(db: Session = Depends(get_db)):
    """Восстанавливает нормальную работу после сбоя"""
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
