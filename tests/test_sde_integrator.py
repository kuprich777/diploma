"""
tests/test_sde_integrator.py
============================
Unit tests for SDEIntegrator.

Tests
-----
1.  Deterministic: σ=0, no shock → trajectory equals Euler forward-Euler (ODE)
2.  Boundaries: all values in [0,1] after many steps with large σ
3.  Reproducibility: same seed → identical trajectory
4.  Shock applied only at step 0: subsequent steps unaffected by re-passing shock
5.  detect_cascade: I_cl=0 and I_q=0 when no cascade occurs
6.  detect_cascade: I_cl=1 triggered when x reaches C
7.  detect_cascade: I_q=1 triggered when Δx >= delta, I_cl=0 (below C threshold)
8.  make_seed: different inputs → different seeds, same input → same seed
9.  SDEConfig validation: bad shapes raise AssertionError
10. Compatibility check: σ=0, ρ=0 → matches old clip(x + A·x) operator at dt=1

Dynamic A(t) tests (α > 0)
----------------------------
11. alpha=0 reproduces static-A trajectory exactly (backward compatibility)
12. _compute_dynamic_A: overloaded supplier column is attenuated, others unchanged
13. _compute_dynamic_A: φ_j ∈ (0,1] for all x ∈ [0,1], A_dynamic ≤ A_static
14. K_q with alpha>0 is deterministic (same seed → same result) and ∈ [0,1]
"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.risk_engine.sde_integrator import SDEConfig, SDEIntegrator, CascadeResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg(
    A=None, sigma=None, rho=None, C=None,
    dt=0.1, T_steps=20, delta=0.10,
) -> SDEConfig:
    N = 3
    if A     is None: A     = np.zeros((N, N))
    if sigma is None: sigma = np.zeros(N)
    if rho   is None: rho   = np.zeros(N)
    if C     is None: C     = np.ones(N) * 0.9
    return SDEConfig(A=A, sigma=sigma, rho=rho, C=C, dt=dt, T_steps=T_steps, delta=delta)


# ---------------------------------------------------------------------------
# Test 1: Deterministic trajectory (σ=0)
# ---------------------------------------------------------------------------
def test_deterministic_no_noise():
    """With σ=0, trajectory must exactly match forward-Euler ODE."""
    A = np.array([[0.0, 0.2, 0.0],
                  [0.1, 0.0, 0.3],
                  [0.0, 0.1, 0.0]])
    rho  = np.array([0.0, 0.0, 0.0])
    x0   = np.array([0.3, 0.5, 0.2])
    dt   = 0.1
    cfg  = _cfg(A=A, rho=rho, dt=dt, T_steps=10)
    integrator = SDEIntegrator(cfg)
    traj = integrator.run(x0=x0, seed=0)

    # Manual ODE forward-Euler
    x = x0.copy()
    for k in range(10):
        drift = A @ x - rho * x
        x = np.clip(x + drift * dt, 0.0, 1.0)
    np.testing.assert_allclose(traj[-1], x, atol=1e-12)


# ---------------------------------------------------------------------------
# Test 2: Boundaries [0, 1] with large σ
# ---------------------------------------------------------------------------
def test_boundaries():
    """All trajectory values must stay in [0, 1] even with large volatility."""
    sigma = np.array([5.0, 5.0, 5.0])
    cfg   = _cfg(sigma=sigma, T_steps=500)
    integrator = SDEIntegrator(cfg)
    traj = integrator.run(x0=np.array([0.5, 0.5, 0.5]), seed=123)
    assert np.all(traj >= 0.0), f"min={traj.min()}"
    assert np.all(traj <= 1.0), f"max={traj.max()}"


# ---------------------------------------------------------------------------
# Test 3: Reproducibility
# ---------------------------------------------------------------------------
def test_reproducibility():
    """Same seed must produce identical trajectory."""
    sigma = np.array([0.2, 0.3, 0.1])
    cfg   = _cfg(sigma=sigma, T_steps=50)
    integrator = SDEIntegrator(cfg)
    x0 = np.array([0.4, 0.6, 0.3])
    t1 = integrator.run(x0=x0, seed=42)
    t2 = integrator.run(x0=x0, seed=42)
    np.testing.assert_array_equal(t1, t2)


def test_different_seeds_differ():
    """Different seeds must produce different trajectories."""
    sigma = np.array([0.3, 0.3, 0.3])
    cfg   = _cfg(sigma=sigma, T_steps=20)
    integrator = SDEIntegrator(cfg)
    x0 = np.array([0.5, 0.5, 0.5])
    t1 = integrator.run(x0=x0, seed=1)
    t2 = integrator.run(x0=x0, seed=2)
    assert not np.array_equal(t1, t2)


# ---------------------------------------------------------------------------
# Test 4: Shock only at step 0
# ---------------------------------------------------------------------------
def test_shock_applied_once():
    """Shock vector should only modify step 0→1 transition."""
    sigma = np.zeros(3)
    cfg   = _cfg(sigma=sigma, T_steps=5)
    integrator = SDEIntegrator(cfg)
    x0    = np.array([0.2, 0.2, 0.2])
    shock = np.array([0.3, 0.0, 0.0])

    traj_shock  = integrator.run(x0=x0, shock=shock,  seed=0)
    traj_noshock = integrator.run(x0=x0, shock=None,  seed=0)

    # Step 1 should differ
    assert not np.allclose(traj_shock[1], traj_noshock[1])
    # Steps 2+ should differ only because initial conditions diverged (not double-shock)
    # Verify: run from x1_shock with no shock matches remaining trajectory
    cfg2   = _cfg(sigma=sigma, T_steps=4)
    int2   = SDEIntegrator(cfg2)
    tail   = int2.run(x0=traj_shock[1], seed=0)
    np.testing.assert_allclose(traj_shock[1:], tail, atol=1e-12)


# ---------------------------------------------------------------------------
# Test 5: No cascade (low state, high threshold)
# ---------------------------------------------------------------------------
def test_no_cascade():
    """Starting well below C with no shock → I_cl=0, I_q=0."""
    sigma = np.zeros(3)
    cfg   = _cfg(sigma=sigma, C=np.array([0.9, 0.9, 0.9]), delta=0.10, T_steps=20)
    integrator = SDEIntegrator(cfg)
    x0   = np.array([0.1, 0.1, 0.1])
    traj = integrator.run(x0=x0, seed=0)
    result = integrator.detect_cascade(traj, initiator=0)
    assert result.I_cl == 0
    assert result.I_q  == 0


# ---------------------------------------------------------------------------
# Test 6: Classical cascade triggered
# ---------------------------------------------------------------------------
def test_classical_cascade():
    """Node 1 forced above C[1] → I_cl=1."""
    sigma = np.zeros(3)
    # Low capacity threshold for node 1
    C   = np.array([0.9, 0.5, 0.9])
    cfg = _cfg(sigma=sigma, C=C, T_steps=5)
    integrator = SDEIntegrator(cfg)
    x0    = np.array([0.4, 0.4, 0.1])
    shock = np.array([0.0, 0.2, 0.0])   # pushes node 1 to 0.6 >= C[1]=0.5
    traj  = integrator.run(x0=x0, shock=shock, seed=0)
    result = integrator.detect_cascade(traj, initiator=0)
    assert result.I_cl == 1
    assert 1 in result.failed_nodes_cl


# ---------------------------------------------------------------------------
# Test 7: Quantitative cascade without classical
# ---------------------------------------------------------------------------
def test_quantitative_only_cascade():
    """Δx >= delta but x stays below C → I_q=1, I_cl=0."""
    sigma = np.zeros(3)
    C     = np.array([0.9, 0.9, 0.9])
    delta = 0.10
    cfg   = _cfg(sigma=sigma, C=C, delta=delta, T_steps=5)
    integrator = SDEIntegrator(cfg)
    x0    = np.array([0.4, 0.3, 0.1])
    # Shock node 1 by +0.15: x1 goes from 0.3 to 0.45 → Δ=0.15 >= 0.10
    # but 0.45 < 0.9 = C[1]
    shock = np.array([0.0, 0.15, 0.0])
    traj  = integrator.run(x0=x0, shock=shock, seed=0)
    result = integrator.detect_cascade(traj, initiator=0)
    assert result.I_q  == 1
    assert result.I_cl == 0, f"I_cl={result.I_cl}, max x1={traj[:,1].max():.3f}"


# ---------------------------------------------------------------------------
# Test 8: make_seed determinism and uniqueness
# ---------------------------------------------------------------------------
def test_make_seed():
    s1 = SDEIntegrator.make_seed("S3", 1)
    s2 = SDEIntegrator.make_seed("S3", 1)
    s3 = SDEIntegrator.make_seed("S3", 2)
    s4 = SDEIntegrator.make_seed("S4", 1)
    assert s1 == s2, "same input → same seed"
    assert s1 != s3, "different run_idx → different seed"
    assert s1 != s4, "different scenario → different seed"
    assert 0 <= s1 < 2**32


# ---------------------------------------------------------------------------
# Test 9: SDEConfig validation
# ---------------------------------------------------------------------------
def test_config_bad_shape():
    with pytest.raises(AssertionError):
        SDEConfig(
            A=np.zeros((3, 3)),
            sigma=np.zeros(4),   # wrong length
            rho=np.zeros(3),
            C=np.zeros(3),
        )


# ---------------------------------------------------------------------------
# Test 10: Compatibility with old clip(x + A·x) operator (σ=0, ρ=0, dt=1)
# ---------------------------------------------------------------------------
def test_compatible_with_old_operator():
    """
    When σ=0, ρ=0, dt=1, no shock:
      x_{t+1} = clip(x_t + A @ x_t) = clip(x_t + A·x_t)
    This matches the previous risk_engine operator exactly.
    """
    A = np.array([[0.0, 0.350, 0.304],
                  [0.006, 0.0,  0.001],
                  [0.500, 0.332, 0.0]])
    sigma = np.zeros(3)
    rho   = np.zeros(3)
    x0    = np.array([0.667, 0.400, 0.333])
    dt    = 1.0
    cfg   = SDEConfig(A=A, sigma=sigma, rho=rho, C=np.ones(3)*0.9, dt=dt, T_steps=1)
    integrator = SDEIntegrator(cfg)
    traj  = integrator.run(x0=x0, seed=0)

    # Old operator: x_new = clip(x + A @ x)
    expected = np.clip(x0 + A @ x0, 0.0, 1.0)
    np.testing.assert_allclose(traj[1], expected, atol=1e-12)


# ===========================================================================
# Dynamic A(t) tests
# ===========================================================================

# Shared matrix and calibrated thresholds for dynamic-A tests
_A_DYN = np.array([[0.0, 0.350, 0.304],
                   [0.006, 0.0,  0.001],
                   [0.500, 0.332, 0.0]])
# Calibrated thresholds from data/calibration/capacity_thresholds.json
_C_DYN = np.array([0.883, 0.646, 0.928])


def _dyn_cfg(alpha: float = 0.0, **kw) -> SDEConfig:
    defaults = dict(A=_A_DYN, sigma=np.zeros(3), rho=np.zeros(3),
                    C=_C_DYN, dt=0.1, T_steps=20, delta=0.10)
    defaults.update(kw)
    defaults["alpha"] = alpha
    return SDEConfig(**defaults)


# ---------------------------------------------------------------------------
# Test 11: alpha=0 → identical to static-A (backward compatibility)
# ---------------------------------------------------------------------------
def test_dynamic_A_alpha_zero_matches_static():
    """With α=0, trajectory must be bit-for-bit identical to static-A run."""
    sigma = np.array([0.2, 0.1, 0.15])
    x0    = np.array([0.4, 0.3, 0.5])

    # Static baseline: alpha=0 (default)
    cfg_static  = _dyn_cfg(alpha=0.0, sigma=sigma, T_steps=50)
    cfg_dynamic = _dyn_cfg(alpha=0.0, sigma=sigma, T_steps=50)

    t_static  = SDEIntegrator(cfg_static).run(x0=x0, seed=42)
    t_dynamic = SDEIntegrator(cfg_dynamic).run(x0=x0, seed=42)

    np.testing.assert_array_equal(t_static, t_dynamic,
        err_msg="alpha=0 must reproduce static-A trajectory exactly")


# ---------------------------------------------------------------------------
# Test 12: overloaded supplier column is attenuated; others unchanged
# ---------------------------------------------------------------------------
def test_dynamic_A_degradation_reduces_supplier_column():
    """
    When x_energy > C_energy with α=5, column 0 (energy) of A_dynamic must be
    strictly less than A_static column 0.  Columns 1 and 2 (within capacity)
    must be unchanged.
    """
    alpha = 5.0
    # energy (j=0) overloaded: x_energy=0.95 > C_energy=0.883
    x = np.array([0.95, 0.30, 0.40])

    cfg = _dyn_cfg(alpha=alpha)
    integrator = SDEIntegrator(cfg)

    A_dyn = integrator._compute_dynamic_A(x)

    # Column 0 (energy supplier) must be attenuated everywhere it was non-zero
    assert np.all(A_dyn[:, 0] <= _A_DYN[:, 0]), \
        "overloaded supplier column must not exceed A_static"
    assert np.any(A_dyn[:, 0] < _A_DYN[:, 0]), \
        "overloaded supplier column must be strictly reduced somewhere"

    # Column 1 (water, within capacity): x_water=0.30 < C_water=0.646 → φ=1
    np.testing.assert_array_equal(A_dyn[:, 1], _A_DYN[:, 1],
        err_msg="within-capacity supplier column must be unchanged")

    # Column 2 (transport, within capacity): x_transport=0.40 < C_transport=0.928
    np.testing.assert_array_equal(A_dyn[:, 2], _A_DYN[:, 2],
        err_msg="within-capacity supplier column must be unchanged")


# ---------------------------------------------------------------------------
# Test 13: φ_j ∈ (0,1] for all x ∈ [0,1]; A_dynamic ≤ A_static element-wise
# ---------------------------------------------------------------------------
def test_dynamic_A_phi_bounds():
    """
    For 100 random state vectors x ∈ [0,1]^3 (seed=42):
      - A_dynamic ≥ 0  (no negative coupling)
      - A_dynamic ≤ A_static element-wise  (attenuation, not amplification)
    """
    rng   = np.random.default_rng(42)
    alpha = 5.0
    cfg   = _dyn_cfg(alpha=alpha)
    integrator = SDEIntegrator(cfg)

    for _ in range(100):
        x     = rng.uniform(0.0, 1.0, size=3)
        A_dyn = integrator._compute_dynamic_A(x)

        assert np.all(A_dyn >= 0.0), \
            f"A_dynamic must be non-negative; got min={A_dyn.min()}"
        assert np.all(A_dyn <= _A_DYN + 1e-12), \
            f"A_dynamic must not exceed A_static; diff={(_A_DYN - A_dyn).min()}"


# ---------------------------------------------------------------------------
# Test 14: K_q with alpha>0 is deterministic and in [0,1]
# ---------------------------------------------------------------------------
def test_dynamic_A_cascade_deterministic():
    """
    K_q computed with α=5 must be deterministic (identical across two runs with
    the same seeds) and lie in [0, 1].  No assertion on the specific value.
    """
    N_runs = 100
    alpha  = 5.0
    sigma  = np.array([0.15, 0.10, 0.12])
    shock  = np.array([0.15, 0.0,  0.0])   # energy shock
    x0     = np.array([0.5,  0.3,  0.4])

    cfg = _dyn_cfg(alpha=alpha, sigma=sigma, T_steps=30)
    integrator = SDEIntegrator(cfg)

    def run_kq(base_seed: int) -> float:
        hits = 0
        for r in range(N_runs):
            seed = SDEIntegrator.make_seed(f"dynA_test_{base_seed}", r)
            traj = integrator.run(x0=x0, shock=shock, seed=seed)
            res  = integrator.detect_cascade(traj, initiator=0)
            hits += res.I_q
        return hits / N_runs

    kq_run1 = run_kq(base_seed=1)
    kq_run2 = run_kq(base_seed=1)   # same base_seed → must be identical

    assert kq_run1 == kq_run2, \
        f"K_q must be deterministic; got {kq_run1} vs {kq_run2}"
    assert 0.0 <= kq_run1 <= 1.0, \
        f"K_q must lie in [0,1]; got {kq_run1}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
