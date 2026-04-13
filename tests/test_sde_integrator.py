"""
tests/test_sde_integrator.py
============================
Unit tests for SDEIntegrator.

Tests
-----
1. Deterministic: σ=0, no shock → trajectory equals Euler forward-Euler (ODE)
2. Boundaries: all values in [0,1] after many steps with large σ
3. Reproducibility: same seed → identical trajectory
4. Shock applied only at step 0: subsequent steps unaffected by re-passing shock
5. detect_cascade: I_cl=0 and I_q=0 when no cascade occurs
6. detect_cascade: I_cl=1 triggered when x reaches C
7. detect_cascade: I_q=1 triggered when Δx >= delta, I_cl=0 (below C threshold)
8. make_seed: different inputs → different seeds, same input → same seed
9. SDEConfig validation: bad shapes raise AssertionError
10. Compatibility check: σ=0, ρ=0 → matches old clip(x + A·x) operator at dt=1
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
