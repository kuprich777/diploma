"""
bayesian_calibrator.py
======================
Bayesian conjugate update for the 3×3 inter-sector dependency matrix A.

Mathematical model
------------------
Each off-diagonal element a_ij is treated independently under a
Normal-Normal conjugate model:

  Prior:    a_ij ~ N(μ₀_ij, σ₀²_ij)
              μ₀  = per-country mean (WIOD)
              σ₀² = per-country variance (inter-country spread)

  Likelihood per time-step t:
              Δx_i(t) = a_ij · x_j(t) + ε,   ε ~ N(0, σ_ε²)

  Sufficient statistics (accumulated over all proxy rows):
              S_xx_ij = Σ_t  x_j(t)²
              S_xy_ij = Σ_t  x_j(t) · Δx_i(t)

  Posterior (closed form):
              τ_post  = 1/σ₀² + S_xx / σ_ε²
              σ²_post = 1 / τ_post
              μ_post  = σ²_post · (μ₀/σ₀² + S_xy/σ_ε²)

Convention:
  A[i][j] = influence of sector j on sector i
  Sector order: [energy=0, water=1, transport=2]
  Diagonal is always 0.

Usage
-----
  calibrator = BayesianCalibrator.from_country_matrices(A_rus, A_deu, A_usa)
  calibrator.update_from_proxy_data(["path/to/texas.csv", "path/to/india.csv"])
  calibrator.save_posterior("A_bayesian_posterior.json")
  A_sample = calibrator.sample_matrix()
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

SECTORS: List[str] = ["energy", "water", "transport"]
N_SECTORS: int = 3
SIGMA_EPSILON: float = 1.20        # full model uncertainty: σ_ε = 1.2 balances WIOD prior with
                                   # proxy likelihood so that posterior stays within 30–65% of prior.
MIN_VAR_SCALE: float = 0.10        # min σ₀ = MIN_VAR_SCALE × μ₀ (avoids σ₀²=0)
SPECTRAL_RADIUS_CAP: float = 0.95  # rescale if ρ(A) ≥ 1 to ensure Neumann stability


# ---------------------------------------------------------------------------
# Proxy CSV column aliases (handle multiple naming conventions)
# ---------------------------------------------------------------------------
_COLUMN_ALIASES: Dict[str, str] = {
    "energy_degradation": "energy",
    "water_degradation":  "water",
    "transport_degradation": "transport",
    "energy":    "energy",
    "water":     "water",
    "transport": "transport",
}


def _load_proxy_csv(path: str) -> Optional[pd.DataFrame]:
    """
    Load a proxy CSV with columns timestamp + three sector columns.
    Returns DataFrame with columns ['energy', 'water', 'transport'] ∈ [0,1],
    or None if file is missing or has wrong structure.
    """
    p = Path(path)
    if not p.exists():
        print(f"  [warn] Proxy CSV not found: {path}")
        return None

    df = pd.read_csv(p)
    rename = {}
    for col in df.columns:
        canonical = _COLUMN_ALIASES.get(col.strip().lower())
        if canonical:
            rename[col] = canonical
    df = df.rename(columns=rename)

    missing = [s for s in SECTORS if s not in df.columns]
    if missing:
        print(f"  [warn] Missing sector columns {missing} in {path}. Available: {list(df.columns)}")
        return None

    df = df[SECTORS].apply(pd.to_numeric, errors="coerce").dropna()
    df = df.clip(0.0, 1.0)
    return df


def _compute_sufficient_stats(
    df: pd.DataFrame,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Given a DataFrame of sector risks x(t) for t=0..T-1, compute:
      S_xx[i][j] = Σ_{t=0}^{T-2} x_j(t)²
      S_xy[i][j] = Σ_{t=0}^{T-2} x_j(t) · Δx_i(t)
    where Δx_i(t) = x_i(t+1) - x_i(t).

    Only off-diagonal pairs are meaningfully used; diagonal is set to 0.
    """
    x = df.values        # shape (T, 3)
    dx = np.diff(x, axis=0)  # shape (T-1, 3), dx[t] = x[t+1] - x[t]
    x_t = x[:-1]         # shape (T-1, 3), predictors x(t)

    S_xx = np.zeros((N_SECTORS, N_SECTORS), dtype=float)
    S_xy = np.zeros((N_SECTORS, N_SECTORS), dtype=float)

    for i in range(N_SECTORS):     # target sector
        for j in range(N_SECTORS): # source sector
            if i == j:
                continue
            S_xx[i, j] = float(np.sum(x_t[:, j] ** 2))
            S_xy[i, j] = float(np.sum(x_t[:, j] * dx[:, i]))

    return S_xx, S_xy


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class BayesianCalibrator:
    """
    Bayesian calibration of the 3×3 inter-sector dependency matrix A.

    Each off-diagonal element is calibrated independently under a
    conjugate Normal-Normal model.  The posterior is Gaussian and
    can be sampled to propagate uncertainty through Monte Carlo.
    """

    def __init__(
        self,
        prior_means: np.ndarray,
        prior_variances: np.ndarray,
        sigma_epsilon: float = SIGMA_EPSILON,
    ) -> None:
        """
        Parameters
        ----------
        prior_means : (3,3) array
            μ₀[i][j] — prior mean for each a_ij. Diagonal must be 0.
        prior_variances : (3,3) array
            σ₀²[i][j] — prior variance. Diagonal must be 0 (not updated).
        sigma_epsilon : float
            Noise std of proxy observations.
        """
        self.mu_prior     = np.array(prior_means,    dtype=float)
        self.sigma2_prior = np.array(prior_variances, dtype=float)
        self.sigma_epsilon = float(sigma_epsilon)

        # Posterior starts at prior
        self.mu_post     = self.mu_prior.copy()
        self.sigma2_post = self.sigma2_prior.copy()

        # Accumulated sufficient statistics (reset on each full update)
        self._S_xx = np.zeros((N_SECTORS, N_SECTORS), dtype=float)
        self._S_xy = np.zeros((N_SECTORS, N_SECTORS), dtype=float)
        self._n_data_points: int = 0
        self._data_sources: List[str] = []

        self._validate()

    def _validate(self) -> None:
        assert self.mu_prior.shape == (N_SECTORS, N_SECTORS), "prior_means must be 3×3"
        assert self.sigma2_prior.shape == (N_SECTORS, N_SECTORS), "prior_variances must be 3×3"
        assert np.all(self.sigma2_prior >= 0), "prior_variances must be non-negative"

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_country_matrices(
        cls,
        A_rus: np.ndarray,
        A_deu: np.ndarray,
        A_usa: np.ndarray,
        sigma_epsilon: float = SIGMA_EPSILON,
    ) -> "BayesianCalibrator":
        """
        Build calibrator from three country-level matrices.

        Prior mean  = simple average over countries.
        Prior var   = sample variance (ddof=1) over countries.
        Minimum var = (MIN_VAR_SCALE × max(μ₀, 0.01))² to avoid zero-width prior
                      for elements where all countries agree.
        Diagonal    = 0 (forced).
        """
        arrays = [np.array(A, dtype=float) for A in [A_rus, A_deu, A_usa]]

        # Replace None values (missing Water/RUS data) with NaN, then nanmean/nanvar
        for k, arr in enumerate(arrays):
            arrays[k] = np.where(arr == None, np.nan, arr).astype(float)  # noqa: E711

        stack = np.stack(arrays, axis=0)  # (3, 3, 3)

        prior_means = np.nanmean(stack, axis=0)
        prior_means = np.nan_to_num(prior_means, nan=0.0)

        # var: need at least 2 non-NaN values per cell
        with np.errstate(invalid="ignore"):
            prior_vars = np.nanvar(stack, axis=0, ddof=1)
        prior_vars = np.nan_to_num(prior_vars, nan=0.0)

        # Minimum variance floor: σ₀ ≥ 30% of μ₀ (but at least 0.02)
        # Encodes "we are ~30% uncertain about WIOD coefficients" as expert prior
        min_var = (np.maximum(0.3 * prior_means, 0.02)) ** 2
        prior_vars = np.maximum(prior_vars, min_var)

        # Force diagonal to 0
        np.fill_diagonal(prior_means, 0.0)
        np.fill_diagonal(prior_vars,  0.0)

        return cls(prior_means, prior_vars, sigma_epsilon)

    # ------------------------------------------------------------------
    # Bayesian update
    # ------------------------------------------------------------------

    def update_from_proxy_data(
        self,
        proxy_csvs: List[str],
        verbose: bool = True,
    ) -> None:
        """
        Accumulate sufficient statistics from proxy CSV files and
        compute the closed-form posterior.

        Each CSV must have columns: timestamp?, energy, water, transport
        (or energy_degradation, water_degradation, transport_degradation).

        The posterior is computed from scratch each time (idempotent).
        Repeated calls with the same CSVs yield the same result.
        """
        # Reset sufficient statistics
        S_xx = np.zeros((N_SECTORS, N_SECTORS), dtype=float)
        S_xy = np.zeros((N_SECTORS, N_SECTORS), dtype=float)
        total_rows = 0
        loaded_sources = []

        for csv_path in proxy_csvs:
            df = _load_proxy_csv(csv_path)
            if df is None or len(df) < 2:
                if verbose:
                    print(f"  [skip] {csv_path}: too few rows or not found")
                continue

            sxx, sxy = _compute_sufficient_stats(df)
            S_xx += sxx
            S_xy += sxy
            n_steps = len(df) - 1
            total_rows += n_steps
            loaded_sources.append(Path(csv_path).name)

            if verbose:
                print(f"  [data] {Path(csv_path).name}: {len(df)} rows → {n_steps} time-steps")

        self._S_xx         = S_xx
        self._S_xy         = S_xy
        self._n_data_points = total_rows
        self._data_sources  = loaded_sources

        if total_rows == 0:
            if verbose:
                print("  [warn] No proxy data loaded — posterior = prior")
            self.mu_post     = self.mu_prior.copy()
            self.sigma2_post = self.sigma2_prior.copy()
            return

        # ---- Conjugate update ----------------------------------------
        sig2_eps = self.sigma_epsilon ** 2

        mu_post     = np.zeros_like(self.mu_prior)
        sigma2_post = np.zeros_like(self.sigma2_prior)

        for i in range(N_SECTORS):
            for j in range(N_SECTORS):
                if i == j:
                    continue  # diagonal stays 0

                sig2_0 = self.sigma2_prior[i, j]
                mu_0   = self.mu_prior[i, j]
                sxx_ij = S_xx[i, j]
                sxy_ij = S_xy[i, j]

                # Prior precision (guard against zero-variance prior → OLS)
                if sig2_0 <= 0.0:
                    tau_prior = 0.0  # flat prior → pure likelihood
                else:
                    tau_prior = 1.0 / sig2_0

                tau_post = tau_prior + sxx_ij / sig2_eps
                sig2_post_ij = 1.0 / tau_post if tau_post > 0 else 1.0

                # Posterior mean
                numerator = tau_prior * mu_0 + sxy_ij / sig2_eps
                mu_post_ij = sig2_post_ij * numerator

                # Clip to [0, 1]
                mu_post_ij = float(np.clip(mu_post_ij, 0.0, 1.0))

                mu_post[i, j]     = mu_post_ij
                sigma2_post[i, j] = sig2_post_ij

        # Diagonal must remain 0
        np.fill_diagonal(mu_post,     0.0)
        np.fill_diagonal(sigma2_post, 0.0)

        self.mu_post     = mu_post
        self.sigma2_post = sigma2_post

        if verbose:
            print(f"\n  [update] Posterior computed from {total_rows} time-steps "
                  f"({', '.join(loaded_sources)})")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def sigma_post(self) -> np.ndarray:
        """Posterior standard deviations (3×3)."""
        return np.sqrt(np.maximum(self.sigma2_post, 0.0))

    @property
    def sigma_prior(self) -> np.ndarray:
        """Prior standard deviations (3×3)."""
        return np.sqrt(np.maximum(self.sigma2_prior, 0.0))

    def get_posterior(self) -> Dict[str, list]:
        """Return posterior as plain-Python dict (for JSON serialisation)."""
        return {
            "mu":    self.mu_post.tolist(),
            "sigma": self.sigma_post.tolist(),
        }

    def shrinkage(self) -> np.ndarray:
        """
        Percentage shrinkage of each element from prior to posterior mean.
            s_ij = |μ_post - μ_prior| / max(|μ_prior|, 1e-8) × 100
        Positive = moved away from prior (likelihood dominated).
        """
        denom = np.maximum(np.abs(self.mu_prior), 1e-8)
        return np.abs(self.mu_post - self.mu_prior) / denom * 100.0

    # ------------------------------------------------------------------
    # Sampling
    # ------------------------------------------------------------------

    def sample_matrix(
        self,
        rng: Optional[np.random.Generator] = None,
    ) -> np.ndarray:
        """
        Draw one realisation of A from the posterior.

        1. Sample a_ij ~ N(μ_post_ij, σ²_post_ij) independently.
        2. Clip to [0, 1]; set diagonal to 0.
        3. If spectral radius ρ(A) ≥ 1, rescale off-diagonal by
           0.95 / ρ(A) to guarantee Neumann-series convergence.
        """
        if rng is None:
            rng = np.random.default_rng()

        A = rng.normal(self.mu_post, self.sigma_post)
        A = np.clip(A, 0.0, 1.0)
        np.fill_diagonal(A, 0.0)

        # Spectral radius check
        eigenvalues = np.linalg.eigvals(A)
        rho = float(np.max(np.abs(eigenvalues)))
        if rho >= 1.0:
            scale = SPECTRAL_RADIUS_CAP / rho
            A *= scale
            np.fill_diagonal(A, 0.0)

        return A

    def sample_matrices(
        self,
        n: int,
        seed: Optional[int] = None,
    ) -> np.ndarray:
        """
        Draw n realisations of A. Returns array of shape (n, 3, 3).
        """
        rng = np.random.default_rng(seed)
        return np.stack([self.sample_matrix(rng) for _ in range(n)], axis=0)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_posterior(self, path: str) -> None:
        """Serialise prior + posterior to JSON."""
        result = {
            "method":    "bayesian_conjugate_normal",
            "sectors":   SECTORS,
            "convention": "A[i][j] = influence of sector j on sector i",
            "sigma_epsilon": self.sigma_epsilon,
            "n_data_points": self._n_data_points,
            "data_sources":  self._data_sources,
            "prior": {
                "source": "WIOD_2016_NIOT_3countries",
                "mu":     self.mu_prior.tolist(),
                "sigma":  self.sigma_prior.tolist(),
            },
            "posterior": {
                "mu":    self.mu_post.tolist(),
                "sigma": self.sigma_post.tolist(),
            },
        }
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(result, indent=2), encoding="utf-8")

    @classmethod
    def load_posterior(cls, path: str) -> "BayesianCalibrator":
        """
        Reconstruct a BayesianCalibrator from a saved JSON.
        The loaded object has prior = original prior and posterior already set.
        """
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        mu_prior  = np.array(data["prior"]["mu"],   dtype=float)
        sig_prior = np.array(data["prior"]["sigma"], dtype=float)
        mu_post   = np.array(data["posterior"]["mu"],   dtype=float)
        sig_post  = np.array(data["posterior"]["sigma"], dtype=float)
        sigma_eps = float(data.get("sigma_epsilon", SIGMA_EPSILON))

        obj = cls(
            prior_means=mu_prior,
            prior_variances=sig_prior ** 2,
            sigma_epsilon=sigma_eps,
        )
        obj.mu_post     = mu_post
        obj.sigma2_post = sig_post ** 2
        obj._data_sources  = data.get("data_sources", [])
        obj._n_data_points = data.get("n_data_points", 0)
        return obj
