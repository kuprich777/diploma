from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
import httpx
from database import get_db
from models import EnergyRecord
from schemas import EnergyStatus, Outage, EnergyRisk, ScenarioStepResult
from utils.logging import setup_logging
from config import Settings
from datetime import datetime

logger = setup_logging()
settings = Settings()

def clip01(v: float) -> float:
    return max(0.0, min(1.0, float(v)))

def compute_energy_risk(record: EnergyRecord) -> float:
    """Compute normalized sector risk x_energy in [0,1] from the latest sector record."""
    if record is None:
        return 0.0

    if getattr(record, "is_operational", True) is False:
        dur = getattr(record, "duration", 0) or 0
        dur_term = clip01(dur / float(settings.MAX_OUTAGE_DURATION))
        return clip01(settings.OUTAGE_BASE_RISK + settings.OUTAGE_DURATION_WEIGHT * dur_term)

    prod = float(getattr(record, "production", 0.0) or 0.0)
    cons = float(getattr(record, "consumption", 0.0) or 0.0)
    if prod <= 0:
        return 0.95

    util = cons / prod
    util_term = (util - float(settings.UTILIZATION_LOW)) / max(1e-9, float(settings.UTILIZATION_HIGH - settings.UTILIZATION_LOW))
    return clip01(util_term)

def get_latest_record(db: Session, scenario_id: str | None, run_id: int | None) -> EnergyRecord | None:
    """Return latest record for (scenario_id, run_id). If context is missing, use global (manual) state."""
    q = db.query(EnergyRecord)
    if scenario_id is not None and run_id is not None:
        q = q.filter(EnergyRecord.scenario_id == scenario_id, EnergyRecord.run_id == run_id)
    return q.order_by(EnergyRecord.id.desc()).first()

# Создаём роутер для эндпойнтов микросервиса
router = APIRouter(prefix="/api/v1/energy", tags=["energy"])


# ----------------------------
# Experiment key helpers
# (mirrors water_service / transport_service pattern)
# ----------------------------

def experiment_key(
    scenario_id: str = Query(..., description="Experiment key: scenario identifier"),
    run_id: int = Query(..., ge=1, description="Experiment key: run identifier"),
) -> tuple[str, int]:
    return scenario_id, run_id


def mutation_trace(
    step_index: int = Query(..., ge=1, description="Scenario step index"),
    action: str = Query(..., description="Scenario action name"),
) -> tuple[int, str]:
    return step_index, action


# ----------------------------
# Helpers for cross-service status checks
# ----------------------------

async def fetch_water_operational(scenario_id: str, run_id: int) -> bool:
    """Return True if water service is operational for the given experiment key."""
    url = settings.WATER_SERVICE_URL.rstrip("/") + "/api/v1/water/status"
    try:
        async with httpx.AsyncClient(timeout=settings.DEPENDENCY_CHECK_TIMEOUT) as client:
            resp = await client.get(url, params={"scenario_id": scenario_id, "run_id": run_id})
        resp.raise_for_status()
        return bool(resp.json().get("operational", True))
    except Exception as e:
        logger.warning("⚠️ fetch_water_operational failed: %s", e)
        return False


async def fetch_transport_operational(scenario_id: str, run_id: int) -> bool:
    """Return True if transport service is operational for the given experiment key."""
    url = settings.TRANSPORT_SERVICE_URL.rstrip("/") + "/api/v1/transport/status"
    try:
        async with httpx.AsyncClient(timeout=settings.DEPENDENCY_CHECK_TIMEOUT) as client:
            resp = await client.get(url, params={"scenario_id": scenario_id, "run_id": run_id})
        resp.raise_for_status()
        return bool(resp.json().get("operational", True))
    except Exception as e:
        logger.warning("⚠️ fetch_transport_operational failed: %s", e)
        return False

@router.post("/init", tags=["energy"])
async def init_energy_state(
    scenario_id: str | None = Query(default=None),
    run_id: int | None = Query(default=None),
    force: bool = Query(default=False, description="If true, reset state for the given (scenario_id, run_id) before init."),
    db: Session = Depends(get_db),
):
    """Инициализирует базовую запись состояния энергосистемы.

    При force=true выполняется сброс состояния для заданного (scenario_id, run_id),
    чтобы базовое состояние эксперимента было воспроизводимым.
    """

    # If force reset is requested, require a concrete context key
    if force:
        if scenario_id is None or run_id is None:
            raise HTTPException(
                status_code=400,
                detail="force=true requires both scenario_id and run_id",
            )
        # Remove all previous records for this (scenario_id, run_id)
        (
            db.query(EnergyRecord)
            .filter(EnergyRecord.scenario_id == scenario_id, EnergyRecord.run_id == run_id)
            .delete(synchronize_session=False)
        )
        db.commit()

    record = get_latest_record(db, scenario_id, run_id)
    if record and not force:
        return {"message": "Already initialized"}

    # Baseline state for experiments must be "normal": operational
    new_record = EnergyRecord(
        production=settings.DEFAULT_PRODUCTION,
        consumption=settings.DEFAULT_CONSUMPTION,
        is_operational=True,
        scenario_id=scenario_id,
        run_id=run_id,
        step_index=0,
        action="init",
    )
    db.add(new_record)
    db.commit()
    return {
        "message": "Initialized",
        "production": new_record.production,
        "consumption": new_record.consumption,
        "is_operational": new_record.is_operational,
        "scenario_id": scenario_id,
        "run_id": run_id,
        "force": force,
    }

# --- Основные эндпойнты ---
@router.get("/status", response_model=EnergyStatus)
async def get_energy_status(
    scenario_id: str | None = Query(default=None),
    run_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Возвращает текущее состояние энергетического сектора."""
    record = get_latest_record(db, scenario_id, run_id)
    if not record:
        raise HTTPException(status_code=404, detail="No records found for given scenario/run")

    logger.debug(f"📊 Current energy status: {record.production}/{record.consumption}")
    return EnergyStatus(
        production=record.production,
        consumption=record.consumption,
        is_operational=record.is_operational,
        degradation=compute_energy_risk(record),
    )

@router.get("/risk/current", response_model=EnergyRisk)
async def get_energy_risk(
    scenario_id: str | None = Query(default=None),
    run_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    record = get_latest_record(db, scenario_id, run_id)
    if not record:
        raise HTTPException(status_code=404, detail="No records found for given scenario/run")
    x = compute_energy_risk(record)
    return EnergyRisk(risk=x, calculated_at=datetime.utcnow().isoformat())

@router.post("/adjust_production", response_model=dict)
async def adjust_production(
    amount: float,
    scenario_id: str | None = Query(default=None),
    run_id: int | None = Query(default=None),
    step_index: int | None = Query(default=None),
    action: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Регулирует производство энергии (изменяет мощность)."""
    record = get_latest_record(db, scenario_id, run_id)
    if not record:
        raise HTTPException(status_code=404, detail="No records found for given scenario/run")

    new_production = max(0, record.production + amount)
    action = action or "adjust_production"
    new_record = EnergyRecord(
        production=new_production,
        consumption=record.consumption,
        is_operational=new_production > 0,
        scenario_id=scenario_id,
        run_id=run_id,
        step_index=step_index,
        action=action,
    )
    risk_before = compute_energy_risk(record)
    risk_after = compute_energy_risk(new_record)
    db.add(new_record)
    db.commit()
    logger.info(f"🔧 Adjusted production by {amount} → {new_production} MW")
    return {
        "production": new_production,
        **ScenarioStepResult(
            sector="energy",
            scenario_id=scenario_id or "manual",
            run_id=run_id or 0,
            step_index=step_index or 0,
            action=action,
            risk_before=risk_before,
            risk_after=risk_after,
            delta=risk_after - risk_before,
        ).model_dump()
    }

@router.post("/adjust_consumption", response_model=dict)
async def adjust_consumption(
    amount: float,
    scenario_id: str | None = Query(default=None),
    run_id: int | None = Query(default=None),
    step_index: int | None = Query(default=None),
    action: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Регулирует потребление энергии (спрос)."""
    record = get_latest_record(db, scenario_id, run_id)
    if not record:
        raise HTTPException(status_code=404, detail="No records found for given scenario/run")

    new_consumption = max(0, record.consumption + amount)
    action = action or "adjust_consumption"
    new_record = EnergyRecord(
        production=record.production,
        consumption=new_consumption,
        is_operational=record.is_operational,
        scenario_id=scenario_id,
        run_id=run_id,
        step_index=step_index,
        action=action,
    )
    risk_before = compute_energy_risk(record)
    risk_after = compute_energy_risk(new_record)
    db.add(new_record)
    db.commit()
    logger.info(f"💡 Adjusted consumption by {amount} → {new_consumption} MW")
    return {
        "consumption": new_consumption,
        **ScenarioStepResult(
            sector="energy",
            scenario_id=scenario_id or "manual",
            run_id=run_id or 0,
            step_index=step_index or 0,
            action=action,
            risk_before=risk_before,
            risk_after=risk_after,
            delta=risk_after - risk_before,
        ).model_dump()
    }

@router.post("/simulate_outage", response_model=dict)
async def simulate_outage(
    outage: Outage,
    scenario_id: str | None = Query(default=None),
    run_id: int | None = Query(default=None),
    step_index: int | None = Query(default=None),
    action: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Симулирует сбой в энергосекторе."""
    record = get_latest_record(db, scenario_id, run_id)
    if not record:
        raise HTTPException(status_code=404, detail="No records found for given scenario/run")

    action = action or "outage"
    duration_factor = clip01(float(outage.duration) / float(settings.MAX_OUTAGE_DURATION))
    degraded_production = max(0.0, float(record.production) * (1.0 - 0.85 * duration_factor))

    new_record = EnergyRecord(
        production=degraded_production,
        consumption=record.consumption,
        is_operational=duration_factor < 0.98,
        reason=outage.reason,
        duration=outage.duration,
        scenario_id=scenario_id,
        run_id=run_id,
        step_index=step_index,
        action=action,
    )
    risk_before = compute_energy_risk(record)
    risk_after = compute_energy_risk(new_record)
    db.add(new_record)
    db.commit()
    logger.warning(f"⚠️ Outage simulated: {outage.reason}, duration {outage.duration} min")
    return {
        "message": f"Outage simulated: {outage.reason}, duration: {outage.duration} minutes",
        "degradation": risk_after,
        "operational": new_record.is_operational,
        "duration": outage.duration,
        **ScenarioStepResult(
            sector="energy",
            scenario_id=scenario_id or "manual",
            run_id=run_id or 0,
            step_index=step_index or 0,
            action=action,
            risk_before=risk_before,
            risk_after=risk_after,
            delta=risk_after - risk_before,
        ).model_dump()
    }

@router.post("/resolve_outage", response_model=dict)
async def resolve_outage(
    scenario_id: str | None = Query(default=None),
    run_id: int | None = Query(default=None),
    step_index: int | None = Query(default=None),
    action: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Восстанавливает работу системы после сбоя."""
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
    risk_before = compute_energy_risk(record)
    risk_after = compute_energy_risk(new_record)
    db.add(new_record)
    db.commit()
    logger.info("✅ Outage resolved, system is operational again.")
    return {
        "message": "Outage resolved, system is operational",
        **ScenarioStepResult(
            sector="energy",
            scenario_id=scenario_id or "manual",
            run_id=run_id or 0,
            step_index=step_index or 0,
            action=action,
            risk_before=risk_before,
            risk_after=risk_after,
            delta=risk_after - risk_before,
        ).model_dump()
    }


@router.post("/increase_load", response_model=dict)
async def increase_load(
    amount: float = Query(..., description="Load increase as fraction of DEFAULT_PRODUCTION (reduces production)"),
    key: tuple[str, int] = Depends(experiment_key),
    trace: tuple[int, str] = Depends(mutation_trace),
    db: Session = Depends(get_db),
):
    """Simulate partial energy degradation by reducing production by amount * DEFAULT_PRODUCTION."""
    scenario_id, run_id = key
    step_index, action = trace

    record = get_latest_record(db, scenario_id, run_id)
    if not record:
        raise HTTPException(status_code=404, detail="No energy records found for given experiment key")

    reduction = amount * settings.DEFAULT_PRODUCTION
    new_production = max(1.0, float(record.production) - reduction)
    new_record = EnergyRecord(
        production=new_production,
        consumption=record.consumption,
        is_operational=record.is_operational,
        scenario_id=scenario_id,
        run_id=run_id,
        step_index=step_index,
        action=action,
    )
    risk_before = compute_energy_risk(record)
    risk_after = compute_energy_risk(new_record)
    db.add(new_record)
    db.commit()
    logger.info(
        "⚡ [%s:%s step=%s action=%s] increase_load amount=%.3f → production %.1f → %.1f  risk %.4f → %.4f",
        scenario_id, run_id, step_index, action, amount, record.production, new_production, risk_before, risk_after,
    )
    return {
        "message": "Energy production reduced (load increase)",
        "scenario_id": scenario_id,
        "run_id": run_id,
        "step_index": step_index,
        "action": action,
        "production": new_production,
        "risk_before": risk_before,
        "risk_after": risk_after,
        "delta": risk_after - risk_before,
    }


@router.post("/check_water_dependency")
async def check_water_dependency(
    source_duration: int = Query(default=0, ge=0, description="Source outage duration (min)"),
    source_degradation: float = Query(default=0.0, ge=0.0, le=1.0, description="Source degradation level"),
    key: tuple[str, int] = Depends(experiment_key),
    trace: tuple[int, str] = Depends(mutation_trace),
    db: Session = Depends(get_db),
):
    """Apply water-sector impact on energy (A[energy][water]=0.2).

    Cooling water shortages reduce energy production capacity.
    dependency_weight=0.2 matches matrix A[0][1].
    """
    scenario_id, run_id = key
    step_index, action = trace

    record = get_latest_record(db, scenario_id, run_id)
    if not record:
        raise HTTPException(status_code=404, detail="No energy records found for given experiment key")

    is_water_ok = await fetch_water_operational(scenario_id, run_id)

    if not is_water_ok:
        source_level = max(float(source_degradation), clip01(float(source_duration) / 30.0))
        dependency_weight = 0.2  # A[energy][water]
        impact = clip01(source_level * dependency_weight)

        degraded_production = max(0.0, float(record.production) * (1.0 - impact))
        new_record = EnergyRecord(
            production=degraded_production,
            consumption=record.consumption,
            is_operational=record.is_operational,
            reason=f"Water dependency impact={impact:.2f}",
            scenario_id=scenario_id,
            run_id=run_id,
            step_index=step_index,
            action=action,
        )
        risk_before = compute_energy_risk(record)
        risk_after = compute_energy_risk(new_record)
        db.add(new_record)
        db.commit()
        logger.warning(
            "🚨 [%s:%s step=%s action=%s] energy impacted by water outage: impact=%.2f",
            scenario_id, run_id, step_index, action, impact,
        )
        return {
            "message": "Energy sector impacted by water outage",
            "scenario_id": scenario_id,
            "run_id": run_id,
            "step_index": step_index,
            "action": action,
            "operational": new_record.is_operational,
            "reason": new_record.reason,
            "degradation": risk_after,
        }

    logger.info(
        "✅ [%s:%s step=%s action=%s] water ok; no impact on energy",
        scenario_id, run_id, step_index, action,
    )
    return {
        "message": "Water service is operational, no impact on energy",
        "scenario_id": scenario_id,
        "run_id": run_id,
        "step_index": step_index,
        "action": action,
        "operational": record.is_operational,
        "reason": record.reason,
        "degradation": compute_energy_risk(record),
    }


@router.post("/check_transport_dependency")
async def check_transport_dependency(
    source_duration: int = Query(default=0, ge=0, description="Source outage duration (min)"),
    source_degradation: float = Query(default=0.0, ge=0.0, le=1.0, description="Source degradation level"),
    key: tuple[str, int] = Depends(experiment_key),
    trace: tuple[int, str] = Depends(mutation_trace),
    db: Session = Depends(get_db),
):
    """Apply transport-sector impact on energy (A[energy][transport]=0.3).

    Fuel delivery disruptions reduce energy production capacity.
    dependency_weight=0.3 matches matrix A[0][2].
    """
    scenario_id, run_id = key
    step_index, action = trace

    record = get_latest_record(db, scenario_id, run_id)
    if not record:
        raise HTTPException(status_code=404, detail="No energy records found for given experiment key")

    is_transport_ok = await fetch_transport_operational(scenario_id, run_id)

    if not is_transport_ok:
        source_level = max(float(source_degradation), clip01(float(source_duration) / 30.0))
        dependency_weight = 0.3  # A[energy][transport]
        impact = clip01(source_level * dependency_weight)

        degraded_production = max(0.0, float(record.production) * (1.0 - impact))
        new_record = EnergyRecord(
            production=degraded_production,
            consumption=record.consumption,
            is_operational=record.is_operational,
            reason=f"Transport dependency impact={impact:.2f}",
            scenario_id=scenario_id,
            run_id=run_id,
            step_index=step_index,
            action=action,
        )
        risk_before = compute_energy_risk(record)
        risk_after = compute_energy_risk(new_record)
        db.add(new_record)
        db.commit()
        logger.warning(
            "🚨 [%s:%s step=%s action=%s] energy impacted by transport disruption: impact=%.2f",
            scenario_id, run_id, step_index, action, impact,
        )
        return {
            "message": "Energy sector impacted by transport disruption",
            "scenario_id": scenario_id,
            "run_id": run_id,
            "step_index": step_index,
            "action": action,
            "operational": new_record.is_operational,
            "reason": new_record.reason,
            "degradation": risk_after,
        }

    logger.info(
        "✅ [%s:%s step=%s action=%s] transport ok; no impact on energy",
        scenario_id, run_id, step_index, action,
    )
    return {
        "message": "Transport service is operational, no impact on energy",
        "scenario_id": scenario_id,
        "run_id": run_id,
        "step_index": step_index,
        "action": action,
        "operational": record.is_operational,
        "reason": record.reason,
        "degradation": compute_energy_risk(record),
    }
