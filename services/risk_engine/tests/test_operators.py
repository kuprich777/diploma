"""Unit tests for RiskOperator implementations and RiskAggregator.

All tests are pure-Python — no database, no HTTP, no FastAPI app.
Run with: pytest services/risk_engine/tests/test_operators.py -v
"""

from __future__ import annotations

import sys
import os

# Make the risk_engine package importable without installing it
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from aggregator import RiskAggregator
from operators import ClassicalOperator, QuantitativeOperator


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

ZERO_MATRIX = [
    [0.0, 0.0, 0.0],
    [0.0, 0.0, 0.0],
    [0.0, 0.0, 0.0],
]

# A[i][j]: sector j influences sector i
SAMPLE_MATRIX = [
    [0.0, 0.2, 0.3],  # energy ← water(0.2), transport(0.3)
    [0.4, 0.0, 0.2],  # water  ← energy(0.4), transport(0.2)
    [0.5, 0.3, 0.0],  # transport ← energy(0.5), water(0.3)
]

# Simple propagation matrix: only j=1 influences i=0
PROP_MATRIX = [
    [0.0, 0.6, 0.0],
    [0.0, 0.0, 0.0],
    [0.0, 0.0, 0.0],
]

ZERO_U = [0.0, 0.0, 0.0]


# ---------------------------------------------------------------------------
# QuantitativeOperator
# ---------------------------------------------------------------------------


class TestQuantitativeOperator:
    """Tests for the continuous-dynamics risk operator."""

    def setup_method(self):
        self.op = QuantitativeOperator()

    # --- compute ---

    def test_identity_zero_matrix_zero_u(self):
        """With A=0 and u=0, output equals input (identity)."""
        x = [0.3, 0.5, 0.1]
        result = self.op.compute(x, ZERO_U, ZERO_MATRIX)
        assert result == pytest.approx(x, abs=1e-9)

    def test_known_values_sample_matrix(self):
        """Manual computation: x=[0.5,0.5,0.5], u=0, A=SAMPLE_MATRIX."""
        x = [0.5, 0.5, 0.5]
        # A·x: row 0 → 0*0.5+0.2*0.5+0.3*0.5=0.25; y0=0.5+0.25=0.75
        #       row 1 → 0.4*0.5+0*0.5+0.2*0.5=0.30; y1=0.5+0.30=0.80
        #       row 2 → 0.5*0.5+0.3*0.5+0*0.5=0.40; y2=0.5+0.40=0.90
        expected = [0.75, 0.80, 0.90]
        result = self.op.compute(x, ZERO_U, SAMPLE_MATRIX)
        assert result == pytest.approx(expected, abs=1e-9)

    def test_clipping_upper_bound(self):
        """Large positive disturbance must be clipped to 1.0."""
        x = [0.9, 0.9, 0.9]
        u = [0.5, 0.5, 0.5]
        result = self.op.compute(x, u, SAMPLE_MATRIX)
        assert all(v <= 1.0 for v in result)
        # With x=[0.9], A·x already pushes well over 1.0 even without u
        assert result == pytest.approx([1.0, 1.0, 1.0], abs=1e-9)

    def test_clipping_lower_bound(self):
        """Large negative disturbance must be clipped to 0.0."""
        x = [0.1, 0.0, 0.0]
        u = [-1.0, -1.0, -1.0]
        result = self.op.compute(x, u, ZERO_MATRIX)
        assert all(v >= 0.0 for v in result)
        assert result == pytest.approx([0.0, 0.0, 0.0], abs=1e-9)

    def test_disturbance_applied_correctly(self):
        """u_t shifts the result by the expected amount when A=0."""
        x = [0.2, 0.3, 0.4]
        u = [0.1, 0.2, 0.1]
        result = self.op.compute(x, u, ZERO_MATRIX)
        assert result == pytest.approx([0.3, 0.5, 0.5], abs=1e-9)

    def test_matrix_only_increments(self):
        """A·x adds to x, so output is always >= input when A values are non-negative."""
        x = [0.2, 0.3, 0.1]
        result = self.op.compute(x, ZERO_U, SAMPLE_MATRIX)
        for original, new in zip(x, result):
            assert new >= original - 1e-9

    # --- detect_cascade ---

    def test_cascade_detected_when_rise_exceeds_delta(self):
        """Cascade flag raised when a non-initiating sector rises by >= δ."""
        trajectory = [
            [0.5, 0.1, 0.1],   # t=0: initial state, sector 0 is initiator
            [0.9, 0.4, 0.1],   # t=1: sector 1 rose by 0.3 >= δ=0.3
        ]
        assert self.op.detect_cascade(trajectory, i0=0, threshold=0.3) is True

    def test_cascade_not_detected_when_rise_below_delta(self):
        """No cascade when non-initiating sector rise is below δ."""
        trajectory = [
            [0.5, 0.1, 0.1],
            [0.9, 0.25, 0.1],  # sector 1 rose by 0.15 < δ=0.3
        ]
        assert self.op.detect_cascade(trajectory, i0=0, threshold=0.3) is False

    def test_cascade_only_initiating_sector_rises(self):
        """Only the initiating sector rising must NOT trigger a cascade."""
        trajectory = [
            [0.0, 0.1, 0.1],
            [0.8, 0.1, 0.1],   # only i0=0 changes
        ]
        assert self.op.detect_cascade(trajectory, i0=0, threshold=0.1) is False

    def test_cascade_single_step_trajectory_returns_false(self):
        """A trajectory of length 1 cannot contain a cascade."""
        assert self.op.detect_cascade([[0.5, 0.5, 0.5]], i0=0, threshold=0.1) is False

    def test_cascade_empty_trajectory_returns_false(self):
        """An empty trajectory must return False without raising."""
        assert self.op.detect_cascade([], i0=0, threshold=0.1) is False

    def test_cascade_detected_at_later_step(self):
        """Cascade detection looks across ALL time steps, not just the last."""
        trajectory = [
            [0.5, 0.0, 0.0],
            [0.8, 0.0, 0.0],   # no cascade yet
            [0.8, 0.0, 0.4],   # sector 2 rose by 0.4 >= δ=0.3
        ]
        assert self.op.detect_cascade(trajectory, i0=0, threshold=0.3) is True

    def test_cascade_exact_delta_boundary(self):
        """Rise exactly equal to δ should count as a cascade (>= not >)."""
        trajectory = [
            [0.5, 0.0, 0.0],
            [0.9, 0.3, 0.0],   # sector 1 rose exactly δ=0.3
        ]
        assert self.op.detect_cascade(trajectory, i0=0, threshold=0.3) is True


# ---------------------------------------------------------------------------
# ClassicalOperator
# ---------------------------------------------------------------------------


class TestClassicalOperator:
    """Tests for the binary (rule-based) risk operator."""

    def setup_method(self):
        self.op = ClassicalOperator(theta=0.5)

    # --- constructor ---

    def test_invalid_theta_zero_raises(self):
        """theta=0 is invalid (must be > 0)."""
        with pytest.raises(ValueError, match="theta"):
            ClassicalOperator(theta=0.0)

    def test_invalid_theta_negative_raises(self):
        with pytest.raises(ValueError, match="theta"):
            ClassicalOperator(theta=-0.1)

    def test_invalid_theta_above_one_raises(self):
        with pytest.raises(ValueError, match="theta"):
            ClassicalOperator(theta=1.1)

    def test_theta_one_is_valid(self):
        """theta=1.0 is the boundary but still valid."""
        op = ClassicalOperator(theta=1.0)
        assert op.theta == 1.0

    # --- compute: binarisation ---

    def test_all_below_threshold_returns_zeros(self):
        """All sectors below θ=0.5 → all zeros, even with propagation matrix."""
        x = [0.4, 0.3, 0.2]
        result = self.op.compute(x, ZERO_U, SAMPLE_MATRIX)
        assert result == [0.0, 0.0, 0.0]

    def test_sector_at_threshold_activates(self):
        """Sector at exactly θ=0.5 should be binarised to 1.0."""
        x = [0.5, 0.0, 0.0]
        result = self.op.compute(x, ZERO_U, ZERO_MATRIX)
        assert result[0] == 1.0
        assert result[1] == 0.0
        assert result[2] == 0.0

    def test_sector_below_threshold_stays_zero(self):
        x = [0.49, 0.0, 0.0]
        result = self.op.compute(x, ZERO_U, ZERO_MATRIX)
        assert result == [0.0, 0.0, 0.0]

    def test_output_values_are_binary(self):
        """All output values must be exactly 0.0 or 1.0."""
        x = [0.7, 0.3, 0.6]
        result = self.op.compute(x, ZERO_U, SAMPLE_MATRIX)
        for v in result:
            assert v in (0.0, 1.0)

    # --- compute: propagation ---

    def test_propagation_through_active_edge(self):
        """Active sector j=1 propagates to sector i=0 via A[0][1]=0.6 >= θ=0.5."""
        x = [0.0, 0.8, 0.0]  # sector 1 active, sector 0 below threshold
        result = self.op.compute(x, ZERO_U, PROP_MATRIX)
        assert result[1] == 1.0  # initiator stays active
        assert result[0] == 1.0  # propagated to sector 0
        assert result[2] == 0.0  # unaffected

    def test_no_propagation_when_edge_below_threshold(self):
        """Edge weight below θ blocks propagation."""
        weak_matrix = [
            [0.0, 0.4, 0.0],  # A[0][1]=0.4 < θ=0.5 — too weak to propagate
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
        ]
        x = [0.0, 0.8, 0.0]
        result = self.op.compute(x, ZERO_U, weak_matrix)
        assert result[0] == 0.0  # no propagation
        assert result[1] == 1.0

    def test_disturbance_pushes_sector_above_threshold(self):
        """u_t can push a sector from below to above θ before binarisation."""
        x = [0.3, 0.0, 0.0]  # below θ
        u = [0.25, 0.0, 0.0]  # 0.3 + 0.25 = 0.55 >= 0.5 → activates
        result = self.op.compute(x, u, ZERO_MATRIX)
        assert result[0] == 1.0

    def test_disturbance_clipped_before_binarisation(self):
        """Large u must not produce values outside {0, 1}."""
        x = [0.9, 0.0, 0.0]
        u = [2.0, 0.0, 0.0]  # clips to 1.0
        result = self.op.compute(x, u, ZERO_MATRIX)
        assert result[0] == 1.0

    def test_custom_theta_higher(self):
        """With θ=0.8, a sector at 0.7 should NOT activate."""
        op = ClassicalOperator(theta=0.8)
        x = [0.7, 0.0, 0.0]
        result = op.compute(x, ZERO_U, ZERO_MATRIX)
        assert result[0] == 0.0

    def test_custom_theta_activates_at_boundary(self):
        """With θ=0.8, a sector at exactly 0.8 should activate."""
        op = ClassicalOperator(theta=0.8)
        x = [0.8, 0.0, 0.0]
        result = op.compute(x, ZERO_U, ZERO_MATRIX)
        assert result[0] == 1.0

    # --- detect_cascade ---

    def test_cascade_detected_non_initiating_activates(self):
        """Cascade flagged when a non-initiating sector reaches θ after t=0."""
        trajectory = [
            [1.0, 0.0, 0.0],   # t=0: only initiator i0=0 active
            [1.0, 1.0, 0.0],   # t=1: sector 1 activated → cascade
        ]
        assert self.op.detect_cascade(trajectory, i0=0, threshold=0.5) is True

    def test_no_cascade_only_initiator_changes(self):
        trajectory = [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],   # only i0=0 changed
        ]
        assert self.op.detect_cascade(trajectory, i0=0, threshold=0.5) is False

    def test_cascade_single_step_returns_false(self):
        assert self.op.detect_cascade([[1.0, 0.0, 0.0]], i0=0, threshold=0.5) is False

    def test_cascade_empty_trajectory_returns_false(self):
        assert self.op.detect_cascade([], i0=0, threshold=0.5) is False

    def test_cascade_detected_at_later_step(self):
        """Cascade may appear at any step, not just t=1."""
        trajectory = [
            [1.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],   # still no cascade
            [1.0, 0.0, 1.0],   # sector 2 activated → cascade
        ]
        assert self.op.detect_cascade(trajectory, i0=0, threshold=0.5) is True

    def test_all_sectors_i0_excluded(self):
        """Even if the trajectory has only the initiating sector active,
        cascade must NOT be flagged."""
        trajectory = [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
        ]
        # i0=0 is the initiator; sectors 1 and 2 never activate
        assert self.op.detect_cascade(trajectory, i0=0, threshold=0.5) is False


# ---------------------------------------------------------------------------
# RiskAggregator
# ---------------------------------------------------------------------------


class TestRiskAggregator:
    """Tests for the weighted-mean integral risk aggregator."""

    # --- constructor validation ---

    def test_empty_weights_raises(self):
        with pytest.raises(ValueError, match="empty"):
            RiskAggregator({})

    def test_negative_weight_raises(self):
        with pytest.raises(ValueError, match="energy"):
            RiskAggregator({"energy": -0.1, "water": 0.3, "transport": 0.3})

    def test_zero_total_raises(self):
        with pytest.raises(ValueError, match="sum"):
            RiskAggregator({"energy": 0.0, "water": 0.0, "transport": 0.0})

    def test_weights_property_returns_copy(self):
        """Mutating the returned dict must not affect the aggregator."""
        agg = RiskAggregator({"energy": 0.4, "water": 0.3, "transport": 0.3})
        w = agg.weights
        w["energy"] = 99.0
        assert agg.weights["energy"] == pytest.approx(0.4)

    # --- aggregate (dict-based) ---

    def test_equal_weights_is_arithmetic_mean(self):
        agg = RiskAggregator({"energy": 1.0, "water": 1.0, "transport": 1.0})
        x = {"energy": 0.3, "water": 0.6, "transport": 0.9}
        assert agg.aggregate(x) == pytest.approx((0.3 + 0.6 + 0.9) / 3, abs=1e-9)

    def test_unequal_weights_normalised_correctly(self):
        """Weights {0.4, 0.3, 0.3} must be normalised to sum 1.0."""
        agg = RiskAggregator({"energy": 0.4, "water": 0.3, "transport": 0.3})
        x = {"energy": 1.0, "water": 0.0, "transport": 0.0}
        # expected = 0.4 * 1.0 / 1.0 = 0.4
        assert agg.aggregate(x) == pytest.approx(0.4, abs=1e-9)

    def test_non_normalised_weights_produce_same_result(self):
        """Un-normalised weights {4, 3, 3} must give the same result as {0.4, 0.3, 0.3}."""
        agg_norm = RiskAggregator({"energy": 0.4, "water": 0.3, "transport": 0.3})
        agg_unnorm = RiskAggregator({"energy": 4.0, "water": 3.0, "transport": 3.0})
        x = {"energy": 0.8, "water": 0.5, "transport": 0.2}
        assert agg_norm.aggregate(x) == pytest.approx(agg_unnorm.aggregate(x), abs=1e-9)

    def test_all_zero_risk_returns_zero(self):
        agg = RiskAggregator({"energy": 0.4, "water": 0.3, "transport": 0.3})
        x = {"energy": 0.0, "water": 0.0, "transport": 0.0}
        assert agg.aggregate(x) == pytest.approx(0.0, abs=1e-9)

    def test_all_max_risk_returns_one(self):
        agg = RiskAggregator({"energy": 0.4, "water": 0.3, "transport": 0.3})
        x = {"energy": 1.0, "water": 1.0, "transport": 1.0}
        assert agg.aggregate(x) == pytest.approx(1.0, abs=1e-9)

    def test_result_clipped_above_one(self):
        """If caller supplies x_t > 1.0, result is still clipped to 1.0."""
        agg = RiskAggregator({"energy": 1.0})
        assert agg.aggregate({"energy": 2.0}) == pytest.approx(1.0, abs=1e-9)

    def test_result_clipped_below_zero(self):
        """If caller supplies x_t < 0.0, result is still clipped to 0.0."""
        agg = RiskAggregator({"energy": 1.0})
        assert agg.aggregate({"energy": -0.5}) == pytest.approx(0.0, abs=1e-9)

    def test_missing_sector_raises_keyerror(self):
        agg = RiskAggregator({"energy": 0.4, "water": 0.3, "transport": 0.3})
        with pytest.raises(KeyError):
            agg.aggregate({"energy": 0.5, "water": 0.5})  # transport missing

    def test_extra_keys_in_x_are_ignored(self):
        """Extra sectors in x_t that are not in weights should be silently ignored."""
        agg = RiskAggregator({"energy": 0.4, "water": 0.3, "transport": 0.3})
        x = {"energy": 0.5, "water": 0.5, "transport": 0.5, "unknown_sector": 0.9}
        # Should not raise; unknown_sector is outside weights
        result = agg.aggregate(x)
        assert 0.0 <= result <= 1.0

    # --- aggregate_vector ---

    def test_aggregate_vector_matches_aggregate_dict(self):
        agg = RiskAggregator({"energy": 0.4, "water": 0.3, "transport": 0.3})
        sectors = ["energy", "water", "transport"]
        x = [0.8, 0.5, 0.2]
        via_dict = agg.aggregate(dict(zip(sectors, x)))
        via_vector = agg.aggregate_vector(sectors, x)
        assert via_vector == pytest.approx(via_dict, abs=1e-9)

    def test_aggregate_vector_known_value(self):
        """0.4*0.8 + 0.3*0.5 + 0.3*0.2 = 0.32+0.15+0.06 = 0.53"""
        agg = RiskAggregator({"energy": 0.4, "water": 0.3, "transport": 0.3})
        result = agg.aggregate_vector(
            ["energy", "water", "transport"],
            [0.8, 0.5, 0.2],
        )
        assert result == pytest.approx(0.53, abs=1e-9)

    # --- total_weight property ---

    def test_total_weight_property(self):
        agg = RiskAggregator({"energy": 0.4, "water": 0.3, "transport": 0.3})
        assert agg.total_weight == pytest.approx(1.0, abs=1e-9)

    def test_total_weight_unnormalised(self):
        agg = RiskAggregator({"energy": 2.0, "water": 1.0})
        assert agg.total_weight == pytest.approx(3.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Integration: operator + aggregator pipeline
# ---------------------------------------------------------------------------


class TestOperatorAggregatorPipeline:
    """End-to-end tests combining operator.compute() with aggregator.aggregate()."""

    def test_quantitative_pipeline_zero_disturbance(self):
        """With zero disturbance and no dependencies, R_t equals the raw weighted mean."""
        op = QuantitativeOperator()
        agg = RiskAggregator({"energy": 0.4, "water": 0.3, "transport": 0.3})
        x = [0.6, 0.4, 0.2]
        adjusted = op.compute(x, ZERO_U, ZERO_MATRIX)
        R = agg.aggregate_vector(["energy", "water", "transport"], adjusted)
        expected = 0.4 * 0.6 + 0.3 * 0.4 + 0.3 * 0.2
        assert R == pytest.approx(expected, abs=1e-9)

    def test_classical_pipeline_all_inactive(self):
        """All sectors below θ → all zeros → R_t = 0."""
        op = ClassicalOperator(theta=0.5)
        agg = RiskAggregator({"energy": 0.4, "water": 0.3, "transport": 0.3})
        x = [0.1, 0.2, 0.3]
        adjusted = op.compute(x, ZERO_U, ZERO_MATRIX)
        R = agg.aggregate_vector(["energy", "water", "transport"], adjusted)
        assert R == pytest.approx(0.0, abs=1e-9)

    def test_classical_pipeline_all_active(self):
        """All sectors above θ → all ones → R_t = 1."""
        op = ClassicalOperator(theta=0.5)
        agg = RiskAggregator({"energy": 0.4, "water": 0.3, "transport": 0.3})
        x = [0.9, 0.8, 0.7]
        adjusted = op.compute(x, ZERO_U, ZERO_MATRIX)
        R = agg.aggregate_vector(["energy", "water", "transport"], adjusted)
        assert R == pytest.approx(1.0, abs=1e-9)

    def test_quantitative_cascade_detected_after_shock(self):
        """Apply a shock via u_t, run two steps, detect cascade."""
        op = QuantitativeOperator()
        A = SAMPLE_MATRIX
        x0 = [0.1, 0.0, 0.0]
        u1 = [0.5, 0.0, 0.0]  # shock to sector 0 only

        x1 = op.compute(x0, u1, A)
        x2 = op.compute(x1, ZERO_U, A)

        trajectory = [x0, x1, x2]
        # Sector 0 received the shock (i0=0); other sectors should have risen
        cascade = op.detect_cascade(trajectory, i0=0, threshold=0.05)
        assert cascade is True
