from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
SIM_DIR = ROOT / "services" / "scenario_simulator"
if str(SIM_DIR) not in sys.path:
    sys.path.insert(0, str(SIM_DIR))

from routers.simulator import outage_impact_from_duration


def test_duration_semantics_monotonic_and_nonnegative_delta() -> None:
    duration_a = 10
    duration_b = 40

    after_a = outage_impact_from_duration(duration_a, max_duration=60)
    after_b = outage_impact_from_duration(duration_b, max_duration=60)

    assert after_a <= after_b

    baseline = 0.0
    assert after_a - baseline >= 0.0
    assert after_b - baseline >= 0.0
