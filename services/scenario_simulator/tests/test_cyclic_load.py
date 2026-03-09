"""Tests for Phase 2: cyclic load scenario support.

Covers:
  - S4_cyclic_transport_load catalog entry structure
  - _build_mc_steps with initiator_action="cyclic_load"
  - Correct alternating ±amplitude step sequence
  - Floor clamping for negative amplitudes in _build_mc_steps
  - cyclic_periods parameter respected
  - Backward compatibility: existing scenarios untouched
  - MonteCarloRequest accepts the new fields
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
SIM_DIR = ROOT / "services" / "scenario_simulator"
if str(SIM_DIR) not in sys.path:
    sys.path.insert(0, str(SIM_DIR))

import pytest
from schemas import MonteCarloRequest, ScenarioStep
from routers.simulator import SCENARIO_CATALOG, _build_mc_steps


# ── helpers ───────────────────────────────────────────────────────────────────

def _mc_req(**overrides) -> MonteCarloRequest:
    base = dict(
        scenario_id="S4_cyclic_transport_load",
        sector="transport",
        runs=100,
        duration_min=10,
        duration_max=30,
        mode="real",
    )
    base.update(overrides)
    return MonteCarloRequest(**base)


# ── Catalog: S4 entry ─────────────────────────────────────────────────────────

class TestCatalogS4:
    def test_s4_key_exists(self):
        assert "S4_cyclic_transport_load" in SCENARIO_CATALOG

    def test_s4_has_four_steps(self):
        steps = SCENARIO_CATALOG["S4_cyclic_transport_load"]["steps"]
        assert len(steps) == 4

    def test_s4_all_steps_are_load_increase(self):
        steps = SCENARIO_CATALOG["S4_cyclic_transport_load"]["steps"]
        for s in steps:
            assert s["action"] == "load_increase"

    def test_s4_all_steps_target_transport(self):
        steps = SCENARIO_CATALOG["S4_cyclic_transport_load"]["steps"]
        for s in steps:
            assert s["sector"] == "transport"

    def test_s4_amplitudes_alternate_sign(self):
        steps = SCENARIO_CATALOG["S4_cyclic_transport_load"]["steps"]
        amounts = [s["params"]["amount"] for s in steps]
        # expected: +, -, +, -
        assert amounts[0] > 0
        assert amounts[1] < 0
        assert amounts[2] > 0
        assert amounts[3] < 0

    def test_s4_step_indices_are_sequential(self):
        steps = SCENARIO_CATALOG["S4_cyclic_transport_load"]["steps"]
        indices = [s["step_index"] for s in steps]
        assert indices == [1, 2, 3, 4]

    def test_s4_description_mentions_cyclic(self):
        desc = SCENARIO_CATALOG["S4_cyclic_transport_load"]["description"].lower()
        assert "цикл" in desc or "cycl" in desc or "load" in desc


# ── _build_mc_steps: cyclic_load ──────────────────────────────────────────────

class TestBuildMcStepsCyclic:
    def test_default_periods_produces_four_steps(self):
        """default cyclic_periods=2 → 2 * 2 = 4 half-steps."""
        req = _mc_req(initiator_action="cyclic_load", load_amount=0.25)
        steps = _build_mc_steps(req, duration=20)
        assert len(steps) == 4

    def test_one_period_produces_two_steps(self):
        req = _mc_req(initiator_action="cyclic_load", load_amount=0.25, cyclic_periods=1)
        steps = _build_mc_steps(req, duration=20)
        assert len(steps) == 2

    def test_three_periods_produces_six_steps(self):
        req = _mc_req(initiator_action="cyclic_load", load_amount=0.25, cyclic_periods=3)
        steps = _build_mc_steps(req, duration=20)
        assert len(steps) == 6

    def test_steps_alternate_positive_negative(self):
        req = _mc_req(initiator_action="cyclic_load", load_amount=0.3)
        steps = _build_mc_steps(req, duration=20)
        amounts = [s.params["amount"] for s in steps]
        for i, a in enumerate(amounts):
            if i % 2 == 0:
                assert a >= 0, f"step {i} should be positive, got {a}"
            else:
                assert a <= 0, f"step {i} should be negative, got {a}"

    def test_all_steps_use_load_increase_action(self):
        req = _mc_req(initiator_action="cyclic_load", load_amount=0.2)
        steps = _build_mc_steps(req, duration=20)
        for s in steps:
            assert s.action == "load_increase"

    def test_all_steps_target_requested_sector(self):
        req = _mc_req(initiator_action="cyclic_load", sector="transport")
        steps = _build_mc_steps(req, duration=20)
        for s in steps:
            assert s.sector == "transport"

    def test_step_indices_are_sequential_from_one(self):
        req = _mc_req(initiator_action="cyclic_load", cyclic_periods=2)
        steps = _build_mc_steps(req, duration=20)
        assert [s.step_index for s in steps] == [1, 2, 3, 4]

    def test_amplitude_magnitude_matches_load_amount(self):
        req = _mc_req(initiator_action="cyclic_load", load_amount=0.4, cyclic_periods=1)
        steps = _build_mc_steps(req, duration=20)
        # dependency_multiplier defaults to 1.0, so amplitude should equal load_amount
        assert steps[0].params["amount"] == pytest.approx(0.4)
        assert steps[1].params["amount"] == pytest.approx(-0.4)

    def test_dependency_multiplier_scales_amplitude(self):
        """Non-unit multiplier should scale amplitude proportionally."""
        req = _mc_req(initiator_action="cyclic_load", load_amount=0.4, cyclic_periods=1)
        steps = _build_mc_steps(req, duration=20, dependency_multiplier=0.5)
        assert steps[0].params["amount"] == pytest.approx(0.2)
        assert steps[1].params["amount"] == pytest.approx(-0.2)

    def test_zero_amplitude_is_valid(self):
        """load_amount=0 is valid (ge=0.0 in schema); produces zero-amplitude steps."""
        req = _mc_req(initiator_action="cyclic_load", load_amount=0.0, cyclic_periods=1)
        steps = _build_mc_steps(req, duration=20)
        assert all(s.params["amount"] == pytest.approx(0.0) for s in steps)

    def test_negative_dependency_multiplier_floors_amplitude_to_zero(self):
        """Negative multiplier → noisy_amplitude = max(0.0, ...) = 0.0."""
        req = _mc_req(initiator_action="cyclic_load", load_amount=0.3, cyclic_periods=1)
        steps = _build_mc_steps(req, duration=20, dependency_multiplier=-1.0)
        assert all(s.params["amount"] == pytest.approx(0.0) for s in steps)


# ── Schema: new MonteCarloRequest fields ──────────────────────────────────────

class TestMonteCarloRequestSchema:
    def test_cyclic_load_is_valid_initiator_action(self):
        req = _mc_req(initiator_action="cyclic_load")
        assert req.initiator_action == "cyclic_load"

    def test_outage_still_valid(self):
        req = _mc_req(initiator_action="outage")
        assert req.initiator_action == "outage"

    def test_load_increase_still_valid(self):
        req = _mc_req(initiator_action="load_increase")
        assert req.initiator_action == "load_increase"

    def test_cyclic_periods_default_is_two(self):
        req = _mc_req(initiator_action="cyclic_load")
        assert req.cyclic_periods == 2

    def test_cyclic_periods_set_to_custom_value(self):
        req = _mc_req(initiator_action="cyclic_load", cyclic_periods=3)
        assert req.cyclic_periods == 3

    def test_cyclic_periods_rejects_zero(self):
        with pytest.raises(Exception):
            _mc_req(initiator_action="cyclic_load", cyclic_periods=0)

    def test_cyclic_periods_rejects_above_ten(self):
        with pytest.raises(Exception):
            _mc_req(initiator_action="cyclic_load", cyclic_periods=11)

    def test_invalid_initiator_action_rejected(self):
        with pytest.raises(Exception):
            _mc_req(initiator_action="unknown_action")


# ── Backward compatibility: existing scenarios unchanged ──────────────────────

class TestBackwardCompatibility:
    def test_s1_catalog_unchanged(self):
        assert "S1_energy_outage" in SCENARIO_CATALOG
        steps = SCENARIO_CATALOG["S1_energy_outage"]["steps"]
        assert len(steps) == 3
        assert steps[0]["action"] == "outage"
        assert steps[0]["sector"] == "energy"

    def test_s2_catalog_unchanged(self):
        assert "S2_water_outage" in SCENARIO_CATALOG
        steps = SCENARIO_CATALOG["S2_water_outage"]["steps"]
        assert steps[0]["sector"] == "water"
        assert steps[0]["action"] == "outage"

    def test_s3_catalog_unchanged(self):
        assert "S3_transport_load" in SCENARIO_CATALOG
        steps = SCENARIO_CATALOG["S3_transport_load"]["steps"]
        assert len(steps) == 1
        assert steps[0]["action"] == "load_increase"

    def test_build_mc_steps_outage_unchanged(self):
        req = _mc_req(scenario_id="S1_energy_outage", sector="energy", initiator_action="outage")
        steps = _build_mc_steps(req, duration=30)
        assert len(steps) == 3
        assert steps[0].action == "outage"
        assert steps[0].sector == "energy"

    def test_build_mc_steps_load_increase_unchanged(self):
        req = _mc_req(scenario_id="S3_transport_load", sector="transport",
                      initiator_action="load_increase", load_amount=0.25)
        steps = _build_mc_steps(req, duration=20)
        assert len(steps) == 1
        assert steps[0].action == "load_increase"
        assert steps[0].params["amount"] == pytest.approx(0.25)
