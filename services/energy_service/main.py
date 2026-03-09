from fastapi import FastAPI, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel
from typing import Optional
from routers import energy as energy_router

from database import get_db, engine, ensure_schema
from models import Base, EnergyRecord
from utils.logging import setup_logging
from config import settings

from datetime import datetime



# --- Инициализация приложения ---
logger = setup_logging()
app = FastAPI(title="energy_service", version="1.0.0", description="Energy sector microservice")

# --- Model-to-risk mapping (x_energy in [0,1]) ---
# Risk is treated as a normalized degradation level of the sector state.
# This service exposes x_energy(t) derived from its operational variables.

# Tuning parameters (can be moved to env/config later)
MAX_DURATION_MIN = 24 * 60  # cap for outage duration normalization

def clip01(v: float) -> float:
    return max(0.0, min(1.0, float(v)))

def compute_energy_risk(record: EnergyRecord) -> float:
    """Compute normalized sector risk x_energy in [0,1] from the latest sector record.
    Model assumption (for experiments): risk increases with non-operational state,
    high utilization (consumption/production), and long outage duration.
    """
    if record is None:
        return 0.0

    # 1) Hard failure dominates
    if getattr(record, "is_operational", True) is False:
        dur = getattr(record, "duration", 0) or 0
        dur_term = clip01(dur / MAX_DURATION_MIN)
        # Base outage risk with duration amplification
        return clip01(0.75 + 0.25 * dur_term)

    # 2) Soft degradation via utilization
    prod = float(getattr(record, "production", 0.0) or 0.0)
    cons = float(getattr(record, "consumption", 0.0) or 0.0)
    if prod <= 0:
        # no production but operational flag true => treat as near-critical
        return 0.95

    util = cons / prod  # >1 means deficit
    # map utilization to risk smoothly: util<=0.6 ~ low risk, util>=1.0 ~ high risk
    util_term = (util - 0.6) / 0.4
    return clip01(util_term)

def get_latest_record(db: Session, scenario_id: str | None, run_id: int | None) -> EnergyRecord | None:
    """Return the latest EnergyRecord for a given (scenario_id, run_id).
    If scenario_id or run_id is None, fall back to the global (manual) state.
    """
    q = db.query(EnergyRecord)
    if scenario_id is not None and run_id is not None:
        q = q.filter(EnergyRecord.scenario_id == scenario_id,
                     EnergyRecord.run_id == run_id)
    return q.order_by(EnergyRecord.id.desc()).first()

# Метрики Prometheus — доступны на /metrics
Instrumentator().instrument(app).expose(app, include_in_schema=False)

# --- События приложения ---
@app.on_event("startup")
async def startup_event():
    """Создание схемы и таблиц при запуске, инициализация async messaging."""
    ensure_schema()
    Base.metadata.create_all(bind=engine)
    logger.info("✅ energy_service started and schema ensured.")

    if settings.ASYNC_MESSAGING_ENABLED:
        try:
            from messaging import RabbitMQConnection
            from routers.energy import set_mq
            mq = RabbitMQConnection(settings.RABBITMQ_URL)
            await mq.connect()
            set_mq(mq)
            app.state.mq = mq
            logger.info("🐇 energy_service: async messaging connected")
        except Exception as exc:
            logger.warning(
                "⚠️  RabbitMQ unavailable — energy_service running in sync-only mode: %s", exc
            )
            app.state.mq = None


@app.on_event("shutdown")
async def shutdown_event():
    mq = getattr(app.state, "mq", None)
    if mq:
        await mq.close()


# --- Pydantic-схемы (DTO) ---
class EnergyStatus(BaseModel):
    production: float
    consumption: float
    is_operational: bool


class Outage(BaseModel):
    reason: str
    duration: int  # в минутах


# --- Risk Response Model ---
class EnergyRisk(BaseModel):
    sector: str
    x: float  # normalized risk in [0,1]
    production: float
    consumption: float
    is_operational: bool
    calculated_at: str


# --- Health & readiness ---
@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok", "service": "energy_service"}


@app.get("/ready", tags=["system"])
async def ready():
    return {"status": "ready"}

# Подключаем energy роутер
app.include_router(energy_router.router)

@app.get("/", include_in_schema=False)
async def root():
    return {"message": "Energy Service is operational"}


# --- Бизнес-эндпойнты ---
@app.get("/status", response_model=EnergyStatus, tags=["energy"])
async def get_energy_status(
    scenario_id: str | None = Query(default=None),
    run_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Возвращает текущее состояние энергетического сектора"""
    record = get_latest_record(db, scenario_id, run_id)
    if not record:
        raise HTTPException(status_code=404, detail="No records found for given scenario/run")
    return EnergyStatus(
        production=record.production,
        consumption=record.consumption,
        is_operational=record.is_operational
    )


# --- Risk endpoint ---
@app.get("/risk/current", response_model=EnergyRisk, tags=["risk"])
async def get_energy_risk(
    scenario_id: str | None = Query(default=None),
    run_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Returns normalized sector risk x_energy(t) in [0,1].
    This endpoint is used by the experiment's risk engine / analytics layer.
    """
    record = get_latest_record(db, scenario_id, run_id)
    if not record:
        raise HTTPException(status_code=404, detail="No records found for given scenario/run")

    x = compute_energy_risk(record)
    return EnergyRisk(
        sector="energy",
        x=x,
        production=record.production,
        consumption=record.consumption,
        is_operational=record.is_operational,
        calculated_at=datetime.utcnow().isoformat(),
    )


@app.post("/adjust_production", tags=["energy"])
async def adjust_production(
    amount: float,
    scenario_id: str | None = Query(default=None),
    run_id: int | None = Query(default=None),
    step_index: int | None = Query(default=None),
    action: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Регулирует производство энергии"""
    record = get_latest_record(db, scenario_id, run_id)
    if not record:
        raise HTTPException(status_code=404, detail="No records found for given scenario/run")

    action = action or "adjust_production"
    new_production = max(0, record.production + amount)
    new_record = EnergyRecord(
        production=new_production,
        consumption=record.consumption,
        is_operational=new_production > 0,
        scenario_id=scenario_id,
        run_id=run_id,
        step_index=step_index,
        action=action,
    )
    db.add(new_record)
    db.commit()
    logger.info(f"🔧 Adjusted production by {amount} → {new_production} MW")
    # risk before/after (for scenario step logging)
    risk_before = compute_energy_risk(record)
    risk_after = compute_energy_risk(new_record)
    return {
        "production": new_production,
        "risk_before": risk_before,
        "risk_after": risk_after,
        "delta": risk_after - risk_before,
    }


@app.post("/adjust_consumption", tags=["energy"])
async def adjust_consumption(
    amount: float,
    scenario_id: str | None = Query(default=None),
    run_id: int | None = Query(default=None),
    step_index: int | None = Query(default=None),
    action: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Регулирует потребление энергии"""
    record = get_latest_record(db, scenario_id, run_id)
    if not record:
        raise HTTPException(status_code=404, detail="No records found for given scenario/run")

    action = action or "adjust_consumption"
    new_consumption = max(0, record.consumption + amount)
    new_record = EnergyRecord(
        production=record.production,
        consumption=new_consumption,
        is_operational=record.is_operational,
        scenario_id=scenario_id,
        run_id=run_id,
        step_index=step_index,
        action=action,
    )
    db.add(new_record)
    db.commit()
    logger.info(f"💡 Adjusted consumption by {amount} → {new_consumption} MW")
    risk_before = compute_energy_risk(record)
    risk_after = compute_energy_risk(new_record)
    return {
        "consumption": new_consumption,
        "risk_before": risk_before,
        "risk_after": risk_after,
        "delta": risk_after - risk_before,
    }


@app.post("/simulate_outage", tags=["energy"])
async def simulate_outage(
    outage: Outage,
    scenario_id: str | None = Query(default=None),
    run_id: int | None = Query(default=None),
    step_index: int | None = Query(default=None),
    action: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Симулирует сбой в энергосекторе"""
    record = get_latest_record(db, scenario_id, run_id)
    if not record:
        raise HTTPException(status_code=404, detail="No records found for given scenario/run")

    action = action or "outage"
    new_record = EnergyRecord(
        production=record.production,
        consumption=record.consumption,
        is_operational=False,
        reason=outage.reason,
        duration=outage.duration,
        scenario_id=scenario_id,
        run_id=run_id,
        step_index=step_index,
        action=action,
    )
    db.add(new_record)
    db.commit()
    logger.warning(f"⚠️ Outage simulated: {outage.reason}, duration {outage.duration} min")
    risk_before = compute_energy_risk(record)
    risk_after = compute_energy_risk(new_record)
    return {
        "message": f"Outage simulated: {outage.reason}, duration: {outage.duration} minutes",
        "risk_before": risk_before,
        "risk_after": risk_after,
        "delta": risk_after - risk_before,
    }


@app.post("/resolve_outage", tags=["energy"])
async def resolve_outage(
    scenario_id: str | None = Query(default=None),
    run_id: int | None = Query(default=None),
    step_index: int | None = Query(default=None),
    action: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Восстанавливает нормальную работу после сбоя"""
    record = get_latest_record(db, scenario_id, run_id)
    if not record:
        raise HTTPException(status_code=404, detail="No records found for given scenario/run")

    action = action or "resolve_outage"
    new_record = EnergyRecord(
        production=record.production,
        consumption=record.consumption,
        is_operational=True,
        scenario_id=scenario_id,
        run_id=run_id,
        step_index=step_index,
        action=action,
    )
    db.add(new_record)
    db.commit()
    logger.info("✅ Outage resolved, system is operational again.")
    risk_before = compute_energy_risk(record)
    risk_after = compute_energy_risk(new_record)
    return {
        "message": "Outage resolved, system is operational",
        "risk_before": risk_before,
        "risk_after": risk_after,
        "delta": risk_after - risk_before,
    }
