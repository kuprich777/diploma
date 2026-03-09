from __future__ import annotations

import asyncio
from typing import Any

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

# ---------------------------------------------------------------------------
# Async messaging state
# ---------------------------------------------------------------------------
_mq: Any = None  # RabbitMQConnection | None

# In-memory cache of last known energy state, keyed by (scenario_id, run_id)
# Updated by the "energy.state_changed" consumer.
_energy_cache: dict[tuple[str, str], dict] = {}


def set_mq(conn: Any) -> None:
    """Injected by main.py startup after the broker connects."""
    global _mq
    _mq = conn


def _is_mq_connected() -> bool:
    return _mq is not None and _mq.is_connected


async def handle_energy_event(envelope: dict) -> None:
    """Consumer handler: update local energy cache from energy.state_changed event."""
    scenario_id = str(envelope.get("scenario_id", ""))
    run_id = str(envelope.get("run_id", ""))
    payload = envelope.get("payload", {})
    _energy_cache[(scenario_id, run_id)] = payload
    logger.info(
        "🔄 [transport] energy cache updated (%s, %s): operational=%s risk=%.3f",
        scenario_id,
        run_id,
        payload.get("operational"),
        float(payload.get("risk_level", 0.0)),
    )


def _publish(routing_key: str, payload: dict, scenario_id: str, run_id: str) -> None:
    """Schedule a fire-and-forget publish if messaging is available."""
    if not _is_mq_connected():
        return
    try:
        from messaging import publish_event_safe
        asyncio.create_task(
            publish_event_safe(
                _mq.channel,
                settings.RABBITMQ_EXCHANGE,
                routing_key,
                payload,
                scenario_id=scenario_id,
                run_id=run_id,
                sector="transport",
            )
        )
    except Exception as exc:
        logger.warning("📤 Publish scheduling failed (non-critical): %s", exc)


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

async def _fetch_energy_operational_http(scenario_id: str, run_id: int) -> bool:
    """Synchronous HTTP fallback: fetch energy operational flag directly."""
    energy_status_url = settings.ENERGY_SERVICE_URL.rstrip("/") + "/status"
    try:
        async with httpx.AsyncClient(timeout=settings.ENERGY_CHECK_TIMEOUT) as client:
            resp = await client.get(
                energy_status_url,
                params={"scenario_id": scenario_id, "run_id": run_id},
            )
        resp.raise_for_status()
        data = resp.json()
        is_op = bool(data.get("is_operational", False))
        logger.debug("🔌 [transport HTTP] energy operational (%s, %s): %s", scenario_id, run_id, is_op)
        return is_op
    except httpx.RequestError as exc:
        logger.error("❌ [transport] HTTP energy fetch failed: %s", exc)
        return False
    except httpx.HTTPStatusError as exc:
        logger.warning("⚠️ [transport] Energy service HTTP %s", exc.response.status_code)
        return False


async def get_energy_operational(scenario_id: str, run_id: int) -> bool:
    """Return energy operational status.

    Fast-path (async mode): read from local cache populated by energy.state_changed events.
    Fallback (sync mode or broker down): direct HTTP call.
    """
    if _is_mq_connected():
        cached = _energy_cache.get((scenario_id, str(run_id)))
        if cached is not None:
            return bool(cached.get("operational", True))
        logger.debug(
            "📭 [transport] energy cache miss for (%s, %s); assuming operational", scenario_id, run_id
        )
        return True
    return await _fetch_energy_operational_http(scenario_id, run_id)


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

    is_energy_ok = await get_energy_operational(scenario_id, run_id)

    if not is_energy_ok:
        source_level = max(float(source_degradation), clip01(float(source_duration) / 30.0))
        dependency_weight = 0.70
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

        degradation = compute_transport_degradation(new_record)
        logger.warning(
            f"🚨 [{scenario_id}:{run_id} step={step_index} action={action}] impacted by energy outage: impact={impact:.2f}"
        )
        _publish(
            "transport.state_changed",
            {
                "load": new_load,
                "operational": operational,
                "energy_impact": impact,
            },
            scenario_id=scenario_id,
            run_id=str(run_id),
        )
        return {
            "message": "Transport system impacted by energy outage",
            "scenario_id": scenario_id,
            "run_id": run_id,
            "step_index": step_index,
            "action": action,
            "operational": operational,
            "reason": new_record.reason,
            "degradation": degradation,
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