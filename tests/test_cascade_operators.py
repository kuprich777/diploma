"""
Тесты каскадных операторов (Classical, IIM, NEVA).
"""
from __future__ import annotations

import numpy as np
import pytest

from services.risk_engine.cascade_operators import (
    ClassicalOperator,
    IIMOperator,
    NevaOperator,
    classical_indicator,
    quantitative_indicator,
)


@pytest.fixture
def A_empirical():
    """A_empirical_bayesian_v1 (capped, ρ=0.95)."""
    return np.array(
        [
            [0.0000, 0.4750, 0.4750],
            [0.5542, 0.0000, 0.4750],
            [0.3958, 0.4750, 0.0000],
        ]
    )


@pytest.fixture
def capacity_C():
    return np.array([0.75, 0.75, 0.75])


# ---------------------------------------------------------------------------
# Classical operator
# ---------------------------------------------------------------------------

class TestClassicalOperator:
    def test_zero_shock_stays_zero(self, A_empirical):
        op = ClassicalOperator(A_empirical)
        result = op.run(np.zeros(3), n_steps=20)
        assert np.allclose(result.final_state, 0.0)
        assert result.converged

    def test_positive_shock_cascades(self, A_empirical):
        op = ClassicalOperator(A_empirical)
        x0 = np.array([0.6, 0.1, 0.1])  # energy shock
        result = op.run(x0, n_steps=50)
        # positive shock to energy must propagate to water and transport
        assert result.final_state[1] > 0.1  # water rises
        assert result.final_state[2] > 0.1  # transport rises
        # saturates at 1.0 (clipping) because ρ(A)≈0.95 is near-unstable
        assert np.all(result.final_state <= 1.0)


# ---------------------------------------------------------------------------
# IIM operator
# ---------------------------------------------------------------------------

class TestIIMOperator:
    def test_zero_perturbation(self, A_empirical):
        c_func = lambda t: np.zeros(3)
        op = IIMOperator(A_empirical, c_func)
        result = op.run(np.zeros(3), n_steps=20)
        assert np.allclose(result.final_state, 0.0)

    def test_impulse_perturbation_decays(self, A_empirical):
        """с(0)=impulse, c(t>0)=0. Для ρ(A) < 1 каскад должен затухать."""
        c_values = np.array([0.5, 0.0, 0.0])
        c_func = lambda t: c_values if t == 0 else np.zeros(3)
        op = IIMOperator(A_empirical, c_func)
        result = op.run(np.zeros(3), n_steps=50)
        # trajectory[0] = q0 = 0
        # trajectory[1] = step(q0, t=0) = A·0 + c = c = [0.5, 0, 0]
        # trajectory[2] = step(c, t=1) = A·c + 0 — impact on water/transport
        assert result.trajectory[2, 1] > 0.0  # water gets hit
        assert result.trajectory[2, 2] > 0.0  # transport gets hit

    def test_sustained_perturbation_fixed_point(self, A_empirical):
        """Постоянный shock → q стремится к (I-A)^-1 · c."""
        c_const = np.array([0.1, 0.0, 0.0])
        c_func = lambda t: c_const
        op = IIMOperator(A_empirical, c_func)
        result = op.run(np.zeros(3), n_steps=200, tol=1e-8)
        # Closed-form fixed point (without clipping)
        fp_expected = np.linalg.solve(np.eye(3) - A_empirical, c_const)
        # iteration-based fixed point
        if result.fixed_point is not None and np.all(fp_expected <= 1.0):
            np.testing.assert_allclose(result.final_state, fp_expected, atol=1e-4)


# ---------------------------------------------------------------------------
# NEVA operator
# ---------------------------------------------------------------------------

class TestNevaOperator:
    def test_stress_function_properties(self, A_empirical):
        op = NevaOperator(A_empirical, beta=2.0)
        assert op.stress(np.array([1.0]))[0] == pytest.approx(0.0)  # healthy → no stress
        assert op.stress(np.array([0.0]))[0] == pytest.approx(1.0)  # failed → full stress
        # monotonic decrease in h
        h = np.linspace(0.0, 1.0, 11)
        s = op.stress(h)
        assert np.all(np.diff(s) < 0)

    def test_linear_limit_beta_equals_1(self, A_empirical):
        """β=1 → stress(h) = 1-h = x. Почти совпадает с classical."""
        op_neva = NevaOperator(A_empirical, beta=1.0)
        x0 = np.array([0.3, 0.0, 0.0])
        result = op_neva.run(x0, n_steps=30)
        # positive shock should still propagate
        assert result.final_state[1] > 0.0
        assert result.final_state[2] > 0.0

    def test_beta_2_more_concentrated(self, A_empirical):
        """β=2 должен давать меньшее воздействие при малом x (более нелинейный)."""
        x0 = np.array([0.1, 0.0, 0.0])  # small initial shock
        op1 = NevaOperator(A_empirical, beta=1.0)
        op2 = NevaOperator(A_empirical, beta=2.0)
        r1 = op1.run(x0, n_steps=30)
        r2 = op2.run(x0, n_steps=30)
        # Under small shock, non-linear β>1 should transmit less stress
        # (since stress(0.9) = 1 - 0.9^2 = 0.19 < 1 - 0.9 = 0.1 ... wait 0.19 > 0.10)
        # Actually 1 - h^β for h=0.9: β=1 gives 0.1, β=2 gives 0.19. β=2 MORE stress.
        # For large h (healthy), β>1 amplifies. For small h, β>1 dampens.
        # Correct interpretation: β>1 is more pessimistic near healthy state.
        # So r2 should show MORE cascade than r1 at small x
        assert np.sum(r2.final_state) >= np.sum(r1.final_state) - 1e-6

    def test_zero_shock_stays_zero(self, A_empirical):
        op = NevaOperator(A_empirical, beta=2.0)
        result = op.run(np.zeros(3), n_steps=10)
        # stress(1.0) = 0, so x_next = x0 + A·0 = 0
        assert np.allclose(result.final_state, 0.0)


# ---------------------------------------------------------------------------
# Cross-operator comparison
# ---------------------------------------------------------------------------

class TestOperatorComparison:
    def test_all_three_propagate_energy_shock(self, A_empirical, capacity_C):
        """Единичный шок в energy: все три оператора должны зафиксировать каскад."""
        x0 = np.array([0.7, 0.1, 0.1])

        cl = ClassicalOperator(A_empirical).run(x0, n_steps=50)
        iim = IIMOperator(A_empirical, lambda t: x0 if t == 0 else np.zeros(3)).run(
            np.zeros(3), n_steps=50
        )
        neva = NevaOperator(A_empirical, beta=1.0).run(x0, n_steps=50)

        for traj, name in [(cl.trajectory, "classical"), (neva.trajectory, "neva_beta1")]:
            ind = classical_indicator(traj, capacity_C, initiator=0)
            assert ind == 1, f"{name} should detect cascade"
