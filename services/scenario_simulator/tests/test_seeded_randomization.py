from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[3]
SIM_DIR = ROOT / "services" / "scenario_simulator"
if str(SIM_DIR) not in sys.path:
    sys.path.insert(0, str(SIM_DIR))

from routers.simulator import _derive_seed, _randomize_steps_for_run
from schemas import ScenarioStep


def test_derive_seed_is_stable_for_same_pair() -> None:
    a = _derive_seed("S1_energy_outage", 101)
    b = _derive_seed("S1_energy_outage", 101)
    c = _derive_seed("S1_energy_outage", 102)
    assert a == b
    assert a != c


def test_randomize_steps_for_run_is_reproducible_with_same_seed() -> None:
    steps = [
        ScenarioStep(step_index=1, sector="energy", action="outage", params={"duration": 30}),
        ScenarioStep(step_index=2, sector="water", action="dependency_check", params={"source_sector": "energy", "source_duration": 30}),
    ]

    first, first_params = _randomize_steps_for_run(
        steps=steps,
        rng=random.Random(123),
        stochastic_scale=0.2,
    )
    second, second_params = _randomize_steps_for_run(
        steps=steps,
        rng=random.Random(123),
        stochastic_scale=0.2,
    )

    assert [s.params for s in first] == [s.params for s in second]
    assert first_params == second_params
