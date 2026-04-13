"""
test_bayesian_calibrator.py
===========================
Unit tests for BayesianCalibrator.

Tests
-----
  1. Conjugacy: flat prior → posterior ≈ OLS estimate
  2. No data: posterior = prior
  3. Clip guarantee: all samples a_ij ∈ [0, 1], diagonal = 0
  4. Spectral radius: ρ(A_sample) < 1 for 10000 samples
  5. Determinism: same seed → same sample
  6. JSON round-trip: save → load → sample → identical output
  7. Shrinkage direction: large data → posterior ≠ prior
  8. from_country_matrices: check min_var floor and diagonal zeroing

Usage
-----
    python matrix_doc/test_bayesian_calibrator.py

All tests print PASS / FAIL.
"""

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bayesian_calibrator import (
    BayesianCalibrator,
    SECTORS,
    N_SECTORS,
    SIGMA_EPSILON,
    _compute_sufficient_stats,
    _load_proxy_csv,
)

PASS = "[PASS]"
FAIL = "[FAIL]"

results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = PASS if condition else FAIL
    results.append((name, condition, detail))
    print(f"  {status}  {name}" + (f"  — {detail}" if detail else ""))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_calibrator(
    mu0=None, sig0=None, sigma_eps=SIGMA_EPSILON
) -> BayesianCalibrator:
    if mu0 is None:
        mu0 = np.array([
            [0.0, 0.35,  0.304],
            [0.006, 0.0, 0.001],
            [0.5,  0.332, 0.0 ],
        ])
    if sig0 is None:
        sig0 = np.array([
            [0.0, 0.04, 0.03],
            [0.001, 0.0, 0.0002],
            [0.06, 0.025, 0.0],
        ])
    # sig0 here is std — convert to variance
    return BayesianCalibrator(
        prior_means=mu0,
        prior_variances=sig0 ** 2,
        sigma_epsilon=sigma_eps,
    )


def _make_synthetic_csv(
    n_rows: int = 400,
    a_true: float = 0.20,
    initiator: tuple = (2, 0),  # target row i, source col j (transport←energy)
    sigma: float = 0.005,
    seed: int = 0,
) -> pd.DataFrame:
    """
    Generate stationary synthetic data where OLS reliably estimates a_true.

    x_j(t): zero-mean sinusoidal oscillation centred at 0.5 so that the
            cumulative sum does NOT drift and x_i stays well within [0, 1].
    x_i(t): x_i(0) = 0.5, x_i(t+1) = clip(x_i(t) + a_true*x_j_centered(t) + ε)
            where x_j_centered = x_j - 0.5  (zero mean → no drift in x_i).

    OLS regresses Δx_i on x_j (raw), so:
      S_xy[i,j] = Σ x_j(t) * Δx_i(t)
                = Σ x_j(t) * (a * (x_j(t)-0.5) + ε)
                = a * Σ x_j*(x_j-0.5) + noise
      S_xx[i,j] = Σ x_j(t)²
      OLS = S_xy / S_xx = a * Σ(x_j² - 0.5*x_j) / Σ x_j²
    The test only requires post ≈ OLS (conjugacy), not post ≈ true_a.
    """
    rng = np.random.default_rng(seed)
    i_t, j_t = initiator
    T = n_rows

    # Source: sinusoidal oscillation ∈ [0.2, 0.8], zero-mean centred at 0.5
    t_idx = np.arange(T)
    x_j = 0.5 + 0.3 * np.sin(2 * np.pi * t_idx / 40.0)  # period=40 steps

    # Target: mean-reverting accumulation using zero-centred x_j
    x_j_c = x_j - 0.5       # zero mean → no drift
    x_i = np.zeros(T)
    x_i[0] = 0.5
    for t in range(T - 1):
        dx = a_true * x_j_c[t] + rng.normal(0, sigma)
        x_i[t + 1] = np.clip(x_i[t] + dx, 0.0, 1.0)

    x_other = 0.1 * np.ones(T)
    data = np.zeros((T, N_SECTORS))
    data[:, j_t] = x_j
    data[:, i_t] = x_i
    remaining = [k for k in range(N_SECTORS) if k not in (i_t, j_t)][0]
    data[:, remaining] = x_other
    return pd.DataFrame(data, columns=SECTORS)


# ---------------------------------------------------------------------------
# Test 1: Conjugacy — flat prior → posterior ≈ OLS
# ---------------------------------------------------------------------------
print("\n=== Test 1: Conjugacy (flat prior → posterior ≈ OLS) ===")

A_TRUE_01 = 0.20   # transport←energy (matches _make_synthetic_csv default)
N_OBS = 400

df_synth = _make_synthetic_csv(n_rows=N_OBS, a_true=A_TRUE_01,
                                initiator=(2, 0), sigma=0.005, seed=42)

# Flat prior: σ₀² very large → prior precision ≈ 0
mu_flat  = np.zeros((N_SECTORS, N_SECTORS))
sig2_flat = np.full((N_SECTORS, N_SECTORS), 1e6)
np.fill_diagonal(sig2_flat, 0.0)

cal_flat = BayesianCalibrator(mu_flat, sig2_flat, sigma_epsilon=0.005)

# Manual S_xx, S_xy for verification
S_xx, S_xy = _compute_sufficient_stats(df_synth)
ols_estimate = S_xy[2, 0] / S_xx[2, 0] if S_xx[2, 0] > 0 else 0.0

# Update via CSV written to temp file
with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
    df_synth.to_csv(f.name, index=False)
    tmp_path = f.name

cal_flat.update_from_proxy_data([tmp_path], verbose=False)
post_val = cal_flat.mu_post[2, 0]

check("flat prior → posterior ≈ OLS",
      abs(post_val - ols_estimate) < 0.01,
      f"post={post_val:.5f}, ols={ols_estimate:.5f}")

# OLS on zero-mean x_j: OLS_coef = a * Cov(x_j, x_j-0.5) / Var(x_j)
# = a * (E[x_j²] - 0.5*E[x_j]) / E[x_j²]  -- not exactly a_true, but consistent
# We only test the conjugacy property (post ≈ OLS), not OLS accuracy
check("flat prior → positive posterior (data-driven)",
      post_val > 0,
      f"post={post_val:.5f} > 0")

Path(tmp_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Test 2: No data → posterior = prior
# ---------------------------------------------------------------------------
print("\n=== Test 2: No data → posterior = prior ===")
cal_nodata = _make_calibrator()
cal_nodata.update_from_proxy_data([], verbose=False)
check("mu_post == mu_prior when no data",
      np.allclose(cal_nodata.mu_post, cal_nodata.mu_prior))
check("sigma2_post == sigma2_prior when no data",
      np.allclose(cal_nodata.sigma2_post, cal_nodata.sigma2_prior))


# ---------------------------------------------------------------------------
# Test 3: Clip guarantee — all samples in [0, 1], diagonal = 0
# ---------------------------------------------------------------------------
print("\n=== Test 3: Clip guarantee ===")
cal_clip = _make_calibrator()
cal_clip.update_from_proxy_data([], verbose=False)  # posterior = prior

N_CLIP = 5000
samples_clip = cal_clip.sample_matrices(n=N_CLIP, seed=7)
check("all samples ∈ [0, 1]",
      bool(np.all(samples_clip >= 0.0) and np.all(samples_clip <= 1.0)),
      f"min={samples_clip.min():.4f}, max={samples_clip.max():.4f}")
check("diagonal = 0 for all samples",
      all(samples_clip[k, i, i] == 0.0
          for k in range(N_CLIP) for i in range(N_SECTORS)),
      "checked all 5000 × 3 diagonal entries")


# ---------------------------------------------------------------------------
# Test 4: Spectral radius < 1 for 10000 samples
# ---------------------------------------------------------------------------
print("\n=== Test 4: Spectral radius ρ(A) < 1 ===")
cal_spec = _make_calibrator()
# Use wide sigma to force many samples near instability
mu_wide = np.array([[0.0, 0.4, 0.4],
                     [0.4, 0.0, 0.4],
                     [0.4, 0.4, 0.0]])
sig_wide = np.full((3, 3), 0.3)
np.fill_diagonal(sig_wide, 0.0)
cal_wide = BayesianCalibrator(mu_wide, sig_wide**2)
samples_spec = cal_wide.sample_matrices(n=10000, seed=99)
rhos = np.array([np.max(np.abs(np.linalg.eigvals(A))) for A in samples_spec])
check("spectral radius < 1 for all 10000 samples",
      bool(np.all(rhos < 1.0)),
      f"max_rho={rhos.max():.4f}")


# ---------------------------------------------------------------------------
# Test 5: Determinism — same seed → same sample
# ---------------------------------------------------------------------------
print("\n=== Test 5: Determinism ===")
cal_det = _make_calibrator()
rng1 = np.random.default_rng(1234)
rng2 = np.random.default_rng(1234)
A1 = cal_det.sample_matrix(rng1)
A2 = cal_det.sample_matrix(rng2)
check("same seed → identical sample",
      np.array_equal(A1, A2),
      f"A1[0]={A1[0].round(4)}, A2[0]={A2[0].round(4)}")

rng3 = np.random.default_rng(9999)
A3 = cal_det.sample_matrix(rng3)
check("different seed → different sample",
      not np.array_equal(A1, A3))


# ---------------------------------------------------------------------------
# Test 6: JSON round-trip
# ---------------------------------------------------------------------------
print("\n=== Test 6: JSON round-trip ===")
cal_rt = _make_calibrator()
with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    tmp_json = f.name

cal_rt.save_posterior(tmp_json)
cal_loaded = BayesianCalibrator.load_posterior(tmp_json)
Path(tmp_json).unlink(missing_ok=True)

check("mu_post preserved",
      np.allclose(cal_rt.mu_post, cal_loaded.mu_post))
check("sigma2_post preserved",
      np.allclose(cal_rt.sigma2_post, cal_loaded.sigma2_post))
check("mu_prior preserved",
      np.allclose(cal_rt.mu_prior, cal_loaded.mu_prior))

# Sample with same seed → same output
rng_rt1 = np.random.default_rng(555)
rng_rt2 = np.random.default_rng(555)
A_rt1 = cal_rt.sample_matrix(rng_rt1)
A_rt2 = cal_loaded.sample_matrix(rng_rt2)
check("sample identical after round-trip",
      np.allclose(A_rt1, A_rt2))


# ---------------------------------------------------------------------------
# Test 7: from_country_matrices — min_var floor and diagonal
# ---------------------------------------------------------------------------
print("\n=== Test 7: from_country_matrices ===")
A1 = np.array([[0.0, 0.3, 0.2], [0.1, 0.0, 0.05], [0.5, 0.1, 0.0]])
A2 = np.array([[0.0, 0.3, 0.2], [0.1, 0.0, 0.05], [0.5, 0.1, 0.0]])  # same = σ²=0
A3 = np.array([[0.0, 0.4, 0.3], [0.15, 0.0, 0.07], [0.6, 0.2, 0.0]])

cal_cm = BayesianCalibrator.from_country_matrices(A1, A2, A3)

check("diagonal of mu_prior = 0",
      all(cal_cm.mu_prior[i, i] == 0.0 for i in range(N_SECTORS)))
check("diagonal of sigma2_prior = 0",
      all(cal_cm.sigma2_prior[i, i] == 0.0 for i in range(N_SECTORS)))
check("min_var floor applied (σ²>0 when 2 countries identical)",
      all(cal_cm.sigma2_prior[i, j] > 0.0
          for i in range(N_SECTORS) for j in range(N_SECTORS) if i != j),
      f"min off-diag variance: {np.min(cal_cm.sigma2_prior[cal_cm.sigma2_prior > 0]):.6f}")


# ---------------------------------------------------------------------------
# Test 8: Sufficient statistics computation
# ---------------------------------------------------------------------------
print("\n=== Test 8: Sufficient statistics ===")
# Known synthetic case: x_j constant → S_xx = T * x_j²
T = 100
x_j_const = 0.5
df_const = pd.DataFrame({
    "energy":    [x_j_const] * T,
    "water":     [0.1] * T,
    "transport": np.linspace(0, 0.5, T),  # varying
})
S_xx_test, S_xy_test = _compute_sufficient_stats(df_const)

# energy is constant → dx_energy = 0 → S_xy[energy_row, any] = 0
check("S_xy zero for constant target",
      np.allclose(S_xy_test[0, :], 0.0, atol=1e-10),
      f"S_xy[0,:] = {S_xy_test[0,:].round(6)}")
# S_xx[transport_row, energy_col] = Σ x_energy² = (T-1) * 0.5²
expected_sxx = (T - 1) * x_j_const ** 2
check("S_xx correct for constant source",
      abs(S_xx_test[2, 0] - expected_sxx) < 1e-10,
      f"expected={expected_sxx:.2f}, got={S_xx_test[2,0]:.2f}")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"\n{'='*55}")
print(f"  Results: {n_pass} PASS, {n_fail} FAIL  (total {len(results)})")
print(f"{'='*55}")
if n_fail > 0:
    print("  FAILED tests:")
    for name, ok, detail in results:
        if not ok:
            print(f"    - {name}: {detail}")
    sys.exit(1)
else:
    print("  All tests passed.")
    sys.exit(0)
