from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
import httpx

from database import get_db
from models import TransportStatus as TransportStatusModel
from schemas import TransportStatus, LoadUpdate
from utils.logging import setup_logging
from config import settings

logger = setup_logging()

router = APIRouter(prefix="/api/v1/transport", tags=["transport"])


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
    # In docker-compose, ENERGY_SERVICE_URL is configured as the full status endpoint.
    energy_status_url = settings.ENERGY_SERVICE_URL.rstrip("/")

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
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
        logger.error(f"❌ Error connecting to Energy Service: {e}")
        return False
    except httpx.HTTPStatusError as e:
        logger.warning(f"⚠️ Energy Service returned HTTP {e.response.status_code}")
        return False


def latest_status(db: Session, scenario_id: str, run_id: int) -> TransportStatusModel | None:
    return (
        db.query(TransportStatusModel)
        .filter(
            TransportStatusModel.scenario_id == scenario_id,
            TransportStatusModel.run_id == run_id,
        )
        .order_by(TransportStatusModel.id.desc())
        .first()
    )


def to_dto(record: TransportStatusModel) -> TransportStatus:
    return TransportStatus(
        load=record.load,
        operational=record.operational,
        energy_dependent=record.energy_dependent,
        reason=record.reason,
    )


# ----------------------------
# API
# ----------------------------

@router.post("/init")
async def init_transport_state(
    key: tuple[str, int] = Depends(experiment_key),
    force: bool = Query(
        default=False,
        description="If true, reset state for (scenario_id, run_id) even if already initialized",
    ),
    db: Session = Depends(get_db),
):
    """Initialize/reset transport state for a specific experiment key."""
    scenario_id, run_id = key

    # If already initialized and not forcing reset, keep baseline stable
    existing = latest_status(db, scenario_id, run_id)
    if existing and not force:
        return {
            "message": "Already initialized",
            "scenario_id": scenario_id,
            "run_id": run_id,
        }

    # If force=True, reset records for this experiment key (isolation for Monte-Carlo)
    if force:
        db.query(TransportStatusModel).filter(
            TransportStatusModel.scenario_id == scenario_id,
            TransportStatusModel.run_id == run_id,
        ).delete()

    new_record = TransportStatusModel(
        scenario_id=scenario_id,
        run_id=run_id,
        load=settings.DEFAULT_LOAD,
        operational=True,
        energy_dependent=True,
        reason=None,
    )
    db.add(new_record)
    db.commit()
    db.refresh(new_record)

    logger.info(
        f"🚚 Transport init ({scenario_id}, {run_id}): load={new_record.load}, operational={new_record.operational}"
    )

    return {
        "message": "Transport state initialized",
        "scenario_id": scenario_id,
        "run_id": run_id,
        "load": new_record.load,
        "operational": new_record.operational,
    }


@router.get("/status", response_model=TransportStatus)
async def get_transport_status(
    key: tuple[str, int] = Depends(experiment_key),
    db: Session = Depends(get_db),
):
    """Return current transport state for the given experiment key."""
    scenario_id, run_id = key

    record = latest_status(db, scenario_id, run_id)
    if not record:
        raise HTTPException(status_code=404, detail="No transport status found for given experiment key")

    return to_dto(record)


@router.post("/update_load")
async def update_load(
    update: LoadUpdate,
    key: tuple[str, int] = Depends(experiment_key),
    trace: tuple[int, str] = Depends(mutation_trace),
    db: Session = Depends(get_db),
):
    """Set transport load (does not change operational flags by itself)."""
    scenario_id, run_id = key
    step_index, action = trace

    record = latest_status(db, scenario_id, run_id)
    if not record:
        raise HTTPException(status_code=404, detail="No transport status found for given experiment key")

    new_record = TransportStatusModel(
        scenario_id=scenario_id,
        run_id=run_id,
        load=update.load,
        operational=record.operational,
        energy_dependent=record.energy_dependent,
        reason=record.reason,
    )
    db.add(new_record)
    db.commit()
    db.refresh(new_record)

    logger.info(
        f"🚦 [{scenario_id}:{run_id} step={step_index} action={action}] load updated -> {new_record.load}"
    )
    return {
        "message": "Transport load updated",
        "scenario_id": scenario_id,
        "run_id": run_id,
        "step_index": step_index,
        "action": action,
        "load": new_record.load,
    }


@router.post("/increase_load")
async def increase_load(
    amount: float = Query(..., description="Increase amount"),
    key: tuple[str, int] = Depends(experiment_key),
    trace: tuple[int, str] = Depends(mutation_trace),
    db: Session = Depends(get_db),
):
    """Increase transport load by amount."""
    scenario_id, run_id = key
    step_index, action = trace

    record = latest_status(db, scenario_id, run_id)
    if not record:
        raise HTTPException(status_code=404, detail="No transport status found for given experiment key")

    new_load = max(0.0, record.load + amount)

    new_record = TransportStatusModel(
        scenario_id=scenario_id,
        run_id=run_id,
        load=new_load,
        operational=record.operational,
        energy_dependent=record.energy_dependent,
        reason=record.reason,
    )

    db.add(new_record)
    db.commit()
    db.refresh(new_record)

    logger.info(
        f"📈 [{scenario_id}:{run_id} step={step_index} action={action}] load +{amount} -> {new_load}"
    )
    return {
        "message": "Transport load increased",
        "scenario_id": scenario_id,
        "run_id": run_id,
        "step_index": step_index,
        "action": action,
        "previous_load": record.load,
        "new_load": new_load,
    }


@router.post("/check_energy_dependency")
async def check_energy_dependency(
    key: tuple[str, int] = Depends(experiment_key),
    trace: tuple[int, str] = Depends(mutation_trace),
    db: Session = Depends(get_db),
):
    """Check energy dependency; if energy down, mark transport as non-operational for this experiment key."""
    scenario_id, run_id = key
    step_index, action = trace

    record = latest_status(db, scenario_id, run_id)
    if not record:
        raise HTTPException(status_code=404, detail="No transport status found for given experiment key")

    is_energy_ok = await fetch_energy_operational(scenario_id, run_id)

    if not is_energy_ok:
        new_record = TransportStatusModel(
            scenario_id=scenario_id,
            run_id=run_id,
            load=record.load,
            operational=False,
            energy_dependent=True,
            reason="Energy service outage",
        )
        db.add(new_record)
        db.commit()
        db.refresh(new_record)

        logger.warning(
            f"🚨 [{scenario_id}:{run_id} step={step_index} action={action}] impacted by energy outage"
        )
        return {
            "message": "Transport system impacted by energy outage",
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
        "message": "Energy service is operational, no impact on transport",
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
    """Resolve transport outage for this experiment key."""
    scenario_id, run_id = key
    step_index, action = trace

    record = latest_status(db, scenario_id, run_id)
    if not record:
        raise HTTPException(status_code=404, detail="No transport status found for given experiment key")

    new_record = TransportStatusModel(
        scenario_id=scenario_id,
        run_id=run_id,
        load=record.load,
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
        "message": "Transport outage resolved, transport sector is operational",
        "scenario_id": scenario_id,
        "run_id": run_id,
        "step_index": step_index,
        "action": action,
        "operational": new_record.operational,
    }