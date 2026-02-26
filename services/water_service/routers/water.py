from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
import httpx

from database import get_db
from models import WaterStatus as WaterStatusModel
from schemas import WaterStatus, SupplyUpdate, DemandUpdate
from utils.logging import setup_logging
from config import settings

logger = setup_logging()

router = APIRouter(prefix="/api/v1/water", tags=["water"])


# ----------------------------
# Experiment key helpers
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
# Internal helpers
# ----------------------------

async def fetch_energy_operational(scenario_id: str, run_id: int) -> bool:
    """Fetch energy status for the SAME experiment key."""
    energy_status_url = settings.ENERGY_SERVICE_URL.rstrip("/") + "/api/v1/energy/status"

    try:
        async with httpx.AsyncClient(timeout=settings.ENERGY_CHECK_TIMEOUT) as client:
            resp = await client.get(
                energy_status_url,
                params={"scenario_id": scenario_id, "run_id": run_id},
            )
        resp.raise_for_status()
        data = resp.json()
        is_op = bool(data.get("is_operational", False))
        logger.debug(f"🔌 Energy operational for ({scenario_id}, {run_id}): {is_op}")
        return is_op
    except httpx.RequestError as e:
        logger.error(f"❌ Error connecting to Energy Service from water_service: {e}")
        return False
    except httpx.HTTPStatusError as e:
        logger.warning(
            f"⚠️ Energy Service returned HTTP {e.response.status_code} to water_service"
        )
        return False


def latest_status(db: Session, scenario_id: str, run_id: int) -> WaterStatusModel | None:
    return (
        db.query(WaterStatusModel)
        .filter(
            WaterStatusModel.scenario_id == scenario_id,
            WaterStatusModel.run_id == run_id,
        )
        .order_by(WaterStatusModel.id.desc())
        .first()
    )


def to_dto(record: WaterStatusModel) -> WaterStatus:
    return WaterStatus(
        supply=record.supply,
        demand=record.demand,
        operational=record.operational,
        energy_dependent=record.energy_dependent,
        reason=record.reason,
    )


# ----------------------------
# API
# ----------------------------

@router.post("/init")
async def init_water_state(
    key: tuple[str, int] = Depends(experiment_key),
    force: bool = Query(default=False, description="If true, reset state for (scenario_id, run_id)"),
    db: Session = Depends(get_db),
):
    """Initialize/reset water state for a specific experiment key."""
    scenario_id, run_id = key

    existing = latest_status(db, scenario_id, run_id)
    if existing and not force:
        return {
            "message": "Already initialized",
            "scenario_id": scenario_id,
            "run_id": run_id,
        }

    if force:
        db.query(WaterStatusModel).filter(
            WaterStatusModel.scenario_id == scenario_id,
            WaterStatusModel.run_id == run_id,
        ).delete()

    new_record = WaterStatusModel(
        scenario_id=scenario_id,
        run_id=run_id,
        supply=settings.DEFAULT_SUPPLY,
        demand=settings.DEFAULT_DEMAND,
        operational=True,
        energy_dependent=True,
        reason=None,
    )
    db.add(new_record)
    db.commit()
    db.refresh(new_record)

    logger.info(
        f"💧 Water init ({scenario_id}, {run_id}): supply={new_record.supply}, demand={new_record.demand}, operational={new_record.operational}"
    )

    return {
        "message": "Water state initialized",
        "scenario_id": scenario_id,
        "run_id": run_id,
        "supply": new_record.supply,
        "demand": new_record.demand,
        "operational": new_record.operational,
    }


@router.get("/status", response_model=WaterStatus)
async def get_water_status(
    key: tuple[str, int] = Depends(experiment_key),
    db: Session = Depends(get_db),
):
    """Return current water state for the given experiment key."""
    scenario_id, run_id = key

    record = latest_status(db, scenario_id, run_id)
    if not record:
        raise HTTPException(status_code=404, detail="No water status found for given experiment key")

    return to_dto(record)


@router.post("/adjust_supply")
async def adjust_supply(
    update: SupplyUpdate,
    key: tuple[str, int] = Depends(experiment_key),
    trace: tuple[int, str] = Depends(mutation_trace),
    db: Session = Depends(get_db),
):
    scenario_id, run_id = key
    step_index, action = trace

    record = latest_status(db, scenario_id, run_id)
    if not record:
        raise HTTPException(status_code=404, detail="No water status found for given experiment key")

    new_record = WaterStatusModel(
        scenario_id=scenario_id,
        run_id=run_id,
        supply=update.supply,
        demand=record.demand,
        operational=record.operational,
        energy_dependent=record.energy_dependent,
        reason=record.reason,
    )
    db.add(new_record)
    db.commit()
    db.refresh(new_record)

    logger.info(
        f"🚰 [{scenario_id}:{run_id} step={step_index} action={action}] supply -> {new_record.supply}"
    )
    return {
        "message": "Water supply updated",
        "scenario_id": scenario_id,
        "run_id": run_id,
        "step_index": step_index,
        "action": action,
        "supply": new_record.supply,
    }


@router.post("/adjust_demand")
async def adjust_demand(
    update: DemandUpdate,
    key: tuple[str, int] = Depends(experiment_key),
    trace: tuple[int, str] = Depends(mutation_trace),
    db: Session = Depends(get_db),
):
    scenario_id, run_id = key
    step_index, action = trace

    record = latest_status(db, scenario_id, run_id)
    if not record:
        raise HTTPException(status_code=404, detail="No water status found for given experiment key")

    new_record = WaterStatusModel(
        scenario_id=scenario_id,
        run_id=run_id,
        supply=record.supply,
        demand=update.demand,
        operational=record.operational,
        energy_dependent=record.energy_dependent,
        reason=record.reason,
    )
    db.add(new_record)
    db.commit()
    db.refresh(new_record)

    logger.info(
        f"🚿 [{scenario_id}:{run_id} step={step_index} action={action}] demand -> {new_record.demand}"
    )
    return {
        "message": "Water demand updated",
        "scenario_id": scenario_id,
        "run_id": run_id,
        "step_index": step_index,
        "action": action,
        "demand": new_record.demand,
    }


@router.post("/check_energy_dependency")
async def check_energy_dependency(
    key: tuple[str, int] = Depends(experiment_key),
    trace: tuple[int, str] = Depends(mutation_trace),
    db: Session = Depends(get_db),
):
    scenario_id, run_id = key
    step_index, action = trace

    record = latest_status(db, scenario_id, run_id)
    if not record:
        raise HTTPException(status_code=404, detail="No water status found for given experiment key")

    is_energy_ok = await fetch_energy_operational(scenario_id, run_id)

    if not is_energy_ok:
        new_record = WaterStatusModel(
            scenario_id=scenario_id,
            run_id=run_id,
            supply=record.supply,
            demand=record.demand,
            operational=False,
            energy_dependent=True,
            reason="Energy service outage",
        )
        db.add(new_record)
        db.commit()
        db.refresh(new_record)

        logger.warning(
            f"🚨 [{scenario_id}:{run_id} step={step_index} action={action}] water impacted by energy outage"
        )
        return {
            "message": "Water sector impacted by energy outage",
            "scenario_id": scenario_id,
            "run_id": run_id,
            "step_index": step_index,
            "action": action,
            "operational": False,
            "reason": new_record.reason,
        }

    logger.info(
        f"✅ [{scenario_id}:{run_id} step={step_index} action={action}] energy ok; no impact"
    )
    return {
        "message": "Energy service is operational, no impact on water sector",
        "scenario_id": scenario_id,
        "run_id": run_id,
        "step_index": step_index,
        "action": action,
        "operational": record.operational,
        "reason": record.reason,
    }


@router.post("/resolve_outage")
async def resolve_outage(
    key: tuple[str, int] = Depends(experiment_key),
    trace: tuple[int, str] = Depends(mutation_trace),
    db: Session = Depends(get_db),
):
    scenario_id, run_id = key
    step_index, action = trace

    record = latest_status(db, scenario_id, run_id)
    if not record:
        raise HTTPException(status_code=404, detail="No water status found for given experiment key")

    new_record = WaterStatusModel(
        scenario_id=scenario_id,
        run_id=run_id,
        supply=record.supply,
        demand=record.demand,
        operational=True,
        energy_dependent=record.energy_dependent,
        reason=None,
    )
    db.add(new_record)
    db.commit()
    db.refresh(new_record)

    logger.info(
        f"✅ [{scenario_id}:{run_id} step={step_index} action={action}] outage resolved"
    )
    return {
        "message": "Water outage resolved, sector is operational",
        "scenario_id": scenario_id,
        "run_id": run_id,
        "step_index": step_index,
        "action": action,
        "operational": new_record.operational,
    }
