from pathlib import Path
import sys

import asyncio
import pytest

ROOT = Path(__file__).resolve().parents[3]
SIM_DIR = ROOT / "services" / "scenario_simulator"
if str(SIM_DIR) not in sys.path:
    sys.path.insert(0, str(SIM_DIR))

from routers import simulator


def test_dependency_matrix_from_meta_parses_valid_matrix() -> None:
    order, matrix = simulator._dependency_matrix_from_meta(
        {
            "sectors_order": ["energy", "water", "transport"],
            "matrix": [[0.0, 0.1, 0.2], [0.3, 0.0, 0.4], [0.2, 0.5, 0.0]],
        }
    )
    assert order == ["energy", "water", "transport"]
    assert matrix[1][0] == 0.3


# ---------------------------------------------------------------------------
# Issue 1: All-neighbors fanout (not top-1)
# ---------------------------------------------------------------------------

def test_interaction_queue_creates_cross_sector_events(monkeypatch: pytest.MonkeyPatch) -> None:
    """Existing test: at least one neighbor is reached from energy (unchanged contract)."""
    async def fake_apply_step(step, scenario_id, run_id):
        return {
            "sector": step.sector,
            "action": step.action,
            "scenario_id": scenario_id,
            "run_id": run_id,
            "step_index": step.step_index,
        }

    monkeypatch.setattr(simulator, "_apply_step", fake_apply_step)

    logs = asyncio.run(simulator._run_interaction_queue(
        scenario_id="S1_energy_outage",
        run_id=77,
        seed=42,
        parent_step_index=1,
        source_sector="energy",
        source_action="outage",
        source_payload={"duration": 30},
        matrix_order=["energy", "water", "transport"],
        matrix=[
            [0.0, 0.0, 0.0],
            [0.8, 0.0, 0.0],
            [0.8, 0.0, 0.0],
        ],
    ))

    assert logs, "Expected queue propagation logs"
    affected = {item["sector"] for item in logs}
    assert "water" in affected or "transport" in affected
    assert all("queue_event" in item for item in logs)


def test_interaction_queue_all_neighbors_fanout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Issue #1: With nonzero edges to BOTH water and transport, both must be reachable.

    Before the fix (top-1 slice [:1]), only the highest-weight edge could ever fire.
    After the fix (all-neighbors), across enough seeds both water AND transport must
    appear together in at least one run.
    Stochastic jitter means a single run may miss one edge (~5% chance); iterating
    50 seeds makes the probability of never seeing both < 0.001.
    """
    async def fake_apply_step(step, scenario_id, run_id):
        return {
            "sector": step.sector,
            "action": step.action,
            "scenario_id": scenario_id,
            "run_id": run_id,
            "step_index": step.step_index,
        }

    monkeypatch.setattr(simulator, "_apply_step", fake_apply_step)

    both_triggered = False
    for seed in range(50):
        logs = asyncio.run(simulator._run_interaction_queue(
            scenario_id="fanout_test",
            run_id=1,
            seed=seed,
            parent_step_index=1,
            source_sector="energy",
            source_action="outage",
            source_payload={"duration": 30},
            matrix_order=["energy", "water", "transport"],
            matrix=[
                [0.0, 0.0, 0.0],
                [0.95, 0.0, 0.0],   # water depends on energy
                [0.95, 0.0, 0.0],   # transport depends on energy
            ],
        ))
        affected = {item["sector"] for item in logs}
        if "water" in affected and "transport" in affected:
            both_triggered = True
            break

    assert both_triggered, (
        "In 50 seeds, water AND transport were never both triggered from energy — "
        "all-neighbors fanout appears broken (top-1 may still be active)"
    )


def test_interaction_queue_weight_attenuation_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that lower-weight edges have a lower trigger probability (weight metadata)."""
    async def fake_apply_step(step, scenario_id, run_id):
        return {"sector": step.sector, "action": step.action,
                "scenario_id": scenario_id, "run_id": run_id,
                "step_index": step.step_index}

    monkeypatch.setattr(simulator, "_apply_step", fake_apply_step)

    logs = asyncio.run(simulator._run_interaction_queue(
        scenario_id="weight_test",
        run_id=2,
        seed=7,
        parent_step_index=1,
        source_sector="energy",
        source_action="outage",
        source_payload={"duration": 30},
        matrix_order=["energy", "water", "transport"],
        matrix=[
            [0.0, 0.0, 0.0],
            [0.9, 0.0, 0.0],
            [0.4, 0.0, 0.0],
        ],
    ))

    # If any event was logged, its matrix_weight must match the original edge weight
    for item in logs:
        qe = item["queue_event"]
        src = qe["source_sector"]
        dest = qe["target_sector"]
        if src == "energy" and dest == "water":
            assert abs(qe["matrix_weight"] - 0.9) < 0.001
        if src == "energy" and dest == "transport":
            assert abs(qe["matrix_weight"] - 0.4) < 0.001


# ---------------------------------------------------------------------------
# Issue 2: Multi-hop propagation depth > 1
# ---------------------------------------------------------------------------

def test_interaction_queue_depth_2_propagation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Issue #2: With max_depth=2, a second-hop event must be reachable.

    Path: energy(depth=0) → water(depth=1) → transport(depth=2).
    Stochastic jitter can drop individual hops; iterating seeds verifies the
    structural capability, not a specific deterministic outcome.
    """
    async def fake_apply_step(step, scenario_id, run_id):
        return {"sector": step.sector, "action": step.action,
                "scenario_id": scenario_id, "run_id": run_id,
                "step_index": step.step_index}

    monkeypatch.setattr(simulator, "_apply_step", fake_apply_step)

    # The cyclic matrix enables the full chain:
    #   energy(depth=0) → water(depth=1 event) → transport(depth=2 event) → energy(no child)
    # transport has an outgoing edge to energy [A[0][2]=0.9], so when transport
    # is processed at depth=2 it triggers a depth=2 queue_event for energy.
    depth2_reached = False
    for seed in range(50):
        logs = asyncio.run(simulator._run_interaction_queue(
            scenario_id="depth2_test",
            run_id=3,
            seed=seed,
            parent_step_index=1,
            source_sector="energy",
            source_action="outage",
            source_payload={"duration": 30},
            matrix_order=["energy", "water", "transport"],
            matrix=[
                [0.0, 0.0, 0.9],   # energy depends on transport (enables depth=2 event)
                [0.9, 0.0, 0.0],   # water depends on energy
                [0.0, 0.9, 0.0],   # transport depends on water
            ],
            max_depth=2,
        ))
        depths = [item["queue_event"]["propagation_depth"] for item in logs]
        if any(d >= 2 for d in depths):
            depth2_reached = True
            break

    assert depth2_reached, "In 50 seeds, depth=2 was never reached — depth>1 propagation broken"


def test_interaction_queue_depth_3_propagation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Issue #2: With max_depth=3, a third-hop event must be reachable.

    Chain: energy(0) → water(1) → transport(2) → energy(3).
    """
    async def fake_apply_step(step, scenario_id, run_id):
        return {"sector": step.sector, "action": step.action,
                "scenario_id": scenario_id, "run_id": run_id,
                "step_index": step.step_index}

    monkeypatch.setattr(simulator, "_apply_step", fake_apply_step)

    depth3_reached = False
    for seed in range(100):
        logs = asyncio.run(simulator._run_interaction_queue(
            scenario_id="depth3_test",
            run_id=4,
            seed=seed,
            parent_step_index=1,
            source_sector="energy",
            source_action="outage",
            source_payload={"duration": 30},
            matrix_order=["energy", "water", "transport"],
            matrix=[
                [0.0, 0.0, 0.9],   # energy depends on transport (third hop back)
                [0.9, 0.0, 0.0],   # water depends on energy
                [0.0, 0.9, 0.0],   # transport depends on water
            ],
            max_depth=3,
        ))
        depths = [item["queue_event"]["propagation_depth"] for item in logs]
        if any(d >= 3 for d in depths):
            depth3_reached = True
            break

    assert depth3_reached, "In 100 seeds, depth=3 was never reached — 3-hop propagation broken"


def test_interaction_queue_depth_capped_at_max(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that propagation depth never exceeds max_depth."""
    async def fake_apply_step(step, scenario_id, run_id):
        return {"sector": step.sector, "action": step.action,
                "scenario_id": scenario_id, "run_id": run_id,
                "step_index": step.step_index}

    monkeypatch.setattr(simulator, "_apply_step", fake_apply_step)

    for max_d in (1, 2, 3):
        logs = asyncio.run(simulator._run_interaction_queue(
            scenario_id="cap_test",
            run_id=5,
            seed=0,
            parent_step_index=1,
            source_sector="energy",
            source_action="outage",
            source_payload={"duration": 30},
            matrix_order=["energy", "water", "transport"],
            matrix=[
                [0.0, 0.0, 0.9],
                [0.9, 0.0, 0.0],
                [0.0, 0.9, 0.0],
            ],
            max_depth=max_d,
        ))
        for item in logs:
            d = item["queue_event"]["propagation_depth"]
            assert d <= max_d, f"Event at depth={d} exceeds max_depth={max_d}"
