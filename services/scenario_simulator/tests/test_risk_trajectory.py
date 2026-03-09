"""Tests for Phase 1: per-step risk trajectory fields.

Covers:
  - ScenarioRunResult accepts and exposes risk_trajectory_q / risk_trajectory_cl
  - MonteCarloRun accepts and exposes the same fields
  - Trajectory values are dicts with the three sector keys
  - None is a valid default (backward-compatible)
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
SIM_DIR = ROOT / "services" / "scenario_simulator"
if str(SIM_DIR) not in sys.path:
    sys.path.insert(0, str(SIM_DIR))

import pytest
from schemas import ScenarioRunResult, MonteCarloRun


# ── helpers ──────────────────────────────────────────────────────────────────

def _minimal_run_result(**overrides) -> ScenarioRunResult:
    base = dict(
        scenario_id="S1_energy_outage",
        run_id=1,
        initiator="energy",
        steps=[],
    )
    base.update(overrides)
    return ScenarioRunResult(**base)


def _minimal_mc_run(**overrides) -> MonteCarloRun:
    base = dict(
        scenario_id="S1_energy_outage",
        run_id=1,
        run=1,
        before=0.2,
        after=0.35,
        delta=0.15,
        duration=30,
    )
    base.update(overrides)
    return MonteCarloRun(**base)


# ── ScenarioRunResult trajectory fields ──────────────────────────────────────

class TestScenarioRunResultTrajectory:
    def test_trajectory_fields_default_to_none(self):
        res = _minimal_run_result()
        assert res.risk_trajectory_q is None
        assert res.risk_trajectory_cl is None

    def test_trajectory_q_accepted_as_list_of_dicts(self):
        traj = [
            {"energy": 0.1, "water": 0.2, "transport": 0.3},
            {"energy": 0.2, "water": 0.25, "transport": 0.35},
        ]
        res = _minimal_run_result(risk_trajectory_q=traj)
        assert res.risk_trajectory_q == traj

    def test_trajectory_cl_accepted_as_list_of_dicts(self):
        traj = [{"energy": 0.0, "water": 1.0, "transport": 0.0}]
        res = _minimal_run_result(risk_trajectory_cl=traj)
        assert res.risk_trajectory_cl == traj

    def test_both_trajectories_set_independently(self):
        traj_q = [{"energy": 0.4, "water": 0.5, "transport": 0.6}]
        traj_cl = [{"energy": 0.0, "water": 1.0, "transport": 0.0}]
        res = _minimal_run_result(risk_trajectory_q=traj_q, risk_trajectory_cl=traj_cl)
        assert res.risk_trajectory_q == traj_q
        assert res.risk_trajectory_cl == traj_cl

    def test_trajectory_length_reflects_step_count(self):
        """A 3-step scenario should produce a trajectory of length 3 (one entry per step)."""
        traj = [
            {"energy": 0.1, "water": 0.1, "transport": 0.1},
            {"energy": 0.3, "water": 0.2, "transport": 0.15},
            {"energy": 0.5, "water": 0.3, "transport": 0.2},
        ]
        res = _minimal_run_result(risk_trajectory_q=traj)
        assert len(res.risk_trajectory_q) == 3

    def test_trajectory_values_within_unit_interval(self):
        traj = [{"energy": 0.0, "water": 0.5, "transport": 1.0}]
        res = _minimal_run_result(risk_trajectory_q=traj)
        for vec in res.risk_trajectory_q:
            for v in vec.values():
                assert 0.0 <= v <= 1.0

    def test_empty_trajectory_is_valid(self):
        res = _minimal_run_result(risk_trajectory_q=[], risk_trajectory_cl=[])
        assert res.risk_trajectory_q == []
        assert res.risk_trajectory_cl == []

    def test_existing_fields_unaffected(self):
        """Adding trajectory fields must not break existing before/after/delta."""
        res = _minimal_run_result(
            before=0.2, after=0.4, delta=0.2,
            risk_trajectory_q=[{"energy": 0.3, "water": 0.3, "transport": 0.3}],
        )
        assert res.before == pytest.approx(0.2)
        assert res.after == pytest.approx(0.4)
        assert res.delta == pytest.approx(0.2)


# ── MonteCarloRun trajectory fields ──────────────────────────────────────────

class TestMonteCarloRunTrajectory:
    def test_trajectory_fields_default_to_none(self):
        run = _minimal_mc_run()
        assert run.risk_trajectory_q is None
        assert run.risk_trajectory_cl is None

    def test_trajectory_q_propagated_from_scenario_result(self):
        traj = [{"energy": 0.2, "water": 0.2, "transport": 0.2}]
        run = _minimal_mc_run(risk_trajectory_q=traj)
        assert run.risk_trajectory_q == traj

    def test_trajectory_cl_propagated_from_scenario_result(self):
        traj = [{"energy": 0.0, "water": 0.0, "transport": 0.0}]
        run = _minimal_mc_run(risk_trajectory_cl=traj)
        assert run.risk_trajectory_cl == traj

    def test_existing_mc_run_fields_still_present(self):
        run = _minimal_mc_run(
            I_cl=0, I_q=1,
            before_vec_q={"energy": 0.1, "water": 0.1, "transport": 0.1},
            risk_trajectory_q=[{"energy": 0.2, "water": 0.2, "transport": 0.2}],
        )
        assert run.I_cl == 0
        assert run.I_q == 1
        assert run.before_vec_q == {"energy": 0.1, "water": 0.1, "transport": 0.1}
        assert run.risk_trajectory_q is not None


# ── simulator helpers used for trajectory collection ─────────────────────────

class TestSectorRiskVector:
    """_sector_risk_vector must produce the canonical {energy, water, transport} dict."""

    def test_extracts_all_three_sectors(self):
        from routers.simulator import _sector_risk_vector
        payload = {
            "energy_risk": 0.1,
            "water_risk": 0.2,
            "transport_risk": 0.3,
            "total_risk": 0.21,
        }
        vec = _sector_risk_vector(payload)
        assert vec == {"energy": 0.1, "water": 0.2, "transport": 0.3}

    def test_missing_keys_default_to_zero(self):
        from routers.simulator import _sector_risk_vector
        vec = _sector_risk_vector({})
        assert vec == {"energy": 0.0, "water": 0.0, "transport": 0.0}

    def test_values_are_floats(self):
        from routers.simulator import _sector_risk_vector
        vec = _sector_risk_vector({"energy_risk": 1, "water_risk": 0, "transport_risk": 1})
        assert all(isinstance(v, float) for v in vec.values())
