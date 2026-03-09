from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
SIM_DIR = ROOT / "services" / "scenario_simulator"
if str(SIM_DIR) not in sys.path:
    sys.path.insert(0, str(SIM_DIR))

from schemas import MonteCarloRequest
from routers.simulator import _build_mc_steps


def test_build_mc_steps_energy_matches_catalog_shape() -> None:
    req = MonteCarloRequest(
        scenario_id="S1_energy_outage",
        sector="energy",
        runs=100,
        duration_min=30,
        duration_max=30,
        mode="real",
    )

    steps = _build_mc_steps(req, duration=30)

    assert len(steps) == 3
    assert steps[0].sector == "energy"
    assert steps[0].action == "outage"
    assert steps[0].params["duration"] == 30
    assert steps[1].sector == "water"
    assert steps[1].action == "dependency_check"
    assert steps[1].params["source_sector"] == "energy"
    assert steps[1].params["source_duration"] == 30
    assert steps[2].sector == "transport"
    assert steps[2].action == "dependency_check"
    assert steps[2].params["source_sector"] == "energy"
    assert steps[2].params["source_duration"] == 30
