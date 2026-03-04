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


def test_interaction_queue_creates_cross_sector_events(monkeypatch: pytest.MonkeyPatch) -> None:
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
