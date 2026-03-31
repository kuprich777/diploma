from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
import httpx

from database import get_db
from models import TransportStatus as TransportStatusModel
from schemas import TransportStatus, LoadUpdate, TransportRisk
from utils.logging import setup_logging
from config import settings

logger = setup_logging()

router = APIRouter(prefix="/api/v1/transport", tags=["transport"])


def clip01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def compute_transport_degradation(record: TransportStatusModel) -> float:
    if record is None:
        return 0.0

    load_term = 1.0 - pow(2.718281828, -3.0 * max(0.0, float(record.load)))

    # Avoid hard binary risk jumps from the operational flag.
    # Even when operational=False, keep a soft degradation floor.
    if not bool(record.operational):
        return clip01(max(0.85, load_term))

    return clip01(load_term)


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
    energy_status_url = settings.ENERGY_SERVICE_URL.rstrip("/") + "/status"

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
        return True  # no data = not yet degraded
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return True  # no record = not degraded
        logger.warning(f"⚠️ Energy Service returned HTTP {e.response.status_code}")
        return True


async def fetch_water_operational(scenario_id: str, run_id: int) -> bool:
    """Fetch water status for the SAME experiment key."""
    url = settings.WATER_SERVICE_URL.rstrip("/") + "/status"
    try:
        async with httpx.AsyncClient(timeout=settings.ENERGY_CHECK_TIMEOUT) as client:
            resp = await client.get(url, params={"scenario_id": scenario_id, "run_id": run_id})
        resp.raise_for_status()
        return bool(resp.json().get("operational", True))
    except Exception as e:
        logger.warning("⚠️ fetch_water_operational (transport_service) failed: %s", e)
        return True  # no data = not yet degraded


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
        degradation=compute_transport_degradation(record),
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




@router.get("/risk/current", response_model=TransportRisk)
async def get_transport_risk(
    key: tuple[str, int] = Depends(experiment_key),
    db: Session = Depends(get_db),
):
    scenario_id, run_id = key
    record = latest_status(db, scenario_id, run_id)
    if not record:
        raise HTTPException(status_code=404, detail="No transport status found for given experiment key")

    degradation = compute_transport_degradation(record)
    return TransportRisk(risk=degradation, degradation=degradation)
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
    source_duration: int = Query(default=0, ge=0, description="Длительность outage источника (мин)"),
    source_degradation: float = Query(default=0.0, ge=0.0, le=1.0, description="Уровень деградации источника"),
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
        source_level = max(float(source_degradation), clip01(float(source_duration) / 30.0))
        # Domain-layer physical weight (0.70): reflects how much energy loss increases
        # transport load (signal disruption, traffic management failures). Intentionally
        # higher than matrix A[transport][energy]=0.5, which is the abstract risk-propagation
        # weight used by risk_engine. The two weights serve different modeling layers:
        # this weight governs physical load increase; A[2][0]=0.5 governs risk vector
        # propagation. See docs/ARCHITECTURE.md section 9 for a full reconciliation.
        dependency_weight = 0.50
        impact = clip01(source_level * dependency_weight)

        new_load = clip01(float(record.load) + impact * 0.8)
        operational = True
        reason = f"Energy dependency soft impact={impact:.2f}"

        new_record = TransportStatusModel(
            scenario_id=scenario_id,
            run_id=run_id,
            load=new_load,
            operational=operational,
            energy_dependent=True,
            reason=reason,
        )
        db.add(new_record)
        db.commit()
        db.refresh(new_record)

        logger.warning(
            f"🚨 [{scenario_id}:{run_id} step={step_index} action={action}] impacted by energy outage: impact={impact:.2f}"
        )
        return {
            "message": "Transport system impacted by energy outage",
            "scenario_id": scenario_id,
            "run_id": run_id,
            "step_index": step_index,
            "action": action,
            "operational": operational,
            "reason": new_record.reason,
            "degradation": compute_transport_degradation(new_record),
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
        "degradation": compute_transport_degradation(record),
    }


@router.post("/check_water_dependency")
async def check_water_dependency(
    source_duration: int = Query(default=0, ge=0, description="Source outage duration (min)"),
    source_degradation: float = Query(default=0.0, ge=0.0, le=1.0, description="Source degradation level"),
    key: tuple[str, int] = Depends(experiment_key),
    trace: tuple[int, str] = Depends(mutation_trace),
    db: Session = Depends(get_db),
):
    """Apply water-sector impact on transport (A[transport][water]=0.3).

    Water shortages affect transport operations (vehicle cleaning, cooling systems).
    dependency_weight=0.3 matches matrix A[2][1].
    """
    scenario_id, run_id = key
    step_index, action = trace

    record = latest_status(db, scenario_id, run_id)
    if not record:
        raise HTTPException(status_code=404, detail="No transport status found for given experiment key")

    is_water_ok = await fetch_water_operational(scenario_id, run_id)

    if not is_water_ok:
        source_level = max(float(source_degradation), clip01(float(source_duration) / 30.0))
        dependency_weight = 0.3  # A[transport][water]
        impact = clip01(source_level * dependency_weight)

        new_load = clip01(float(record.load) + impact * 0.8)
        operational = True  # soft impact, stays operational
        reason = f"Water dependency soft impact={impact:.2f}"

        new_record = TransportStatusModel(
            scenario_id=scenario_id,
            run_id=run_id,
            load=new_load,
            operational=operational,
            energy_dependent=record.energy_dependent,
            reason=reason,
        )
        db.add(new_record)
        db.commit()
        db.refresh(new_record)
        logger.warning(
            f"🚨 [{scenario_id}:{run_id} step={step_index} action={action}] transport impacted by water outage: impact={impact:.2f}"
        )
        return {
            "message": "Transport system impacted by water outage",
            "scenario_id": scenario_id,
            "run_id": run_id,
            "step_index": step_index,
            "action": action,
            "operational": operational,
            "reason": reason,
            "degradation": compute_transport_degradation(new_record),
        }

    logger.info(
        f"✅ [{scenario_id}:{run_id} step={step_index} action={action}] water ok; no impact on transport"
    )
    return {
        "message": "Water service is operational, no impact on transport",
        "scenario_id": scenario_id,
        "run_id": run_id,
        "step_index": step_index,
        "action": action,
        "operational": record.operational,
        "reason": record.reason,
        "degradation": compute_transport_degradation(record),
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