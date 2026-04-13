"""
run_bayesian_calibration.py
===========================
End-to-end Bayesian calibration of the dependency matrix A.

Steps
-----
1. Load per-country Leontief matrices from A_calibrated_wiod.json
2. Build BayesianCalibrator (prior = WIOD 3-country average + inter-country variance)
3. Update posterior from proxy CSV data (Texas 2021, India 2012)
4. Print calibration summary table
5. Save posterior to A_bayesian_posterior.json
6. Sample N=1000 matrices, plot marginal distributions

Usage
-----
    python matrix_doc/run_bayesian_calibration.py

Outputs
-------
    matrix_doc/A_bayesian_posterior.json
    matrix_doc/bayesian_distributions.png
"""

import json
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ---------------------------------------------------------------------------
REPO_ROOT    = Path(__file__).resolve().parent.parent
WIOD_JSON    = REPO_ROOT / "matrix_doc" / "A_calibrated_wiod.json"
POSTERIOR_OUT = REPO_ROOT / "matrix_doc" / "A_bayesian_posterior.json"
DIST_PNG_OUT  = REPO_ROOT / "matrix_doc" / "bayesian_distributions.png"

PROXY_CSVS = [
    str(REPO_ROOT / "real_data_validation" / "data" / "texas_2021_proxy.csv"),
    str(REPO_ROOT / "real_data_validation" / "data" / "india_2012_proxy.csv"),
]

# Add matrix_doc to path for bayesian_calibrator import
sys.path.insert(0, str(REPO_ROOT / "matrix_doc"))
from bayesian_calibrator import BayesianCalibrator, SECTORS, N_SECTORS

SECTOR_PAIRS = [(i, j) for i in range(N_SECTORS) for j in range(N_SECTORS) if i != j]
EDGE_LABELS  = [f"{SECTORS[i][:3].upper()}<-{SECTORS[j][:3].upper()}" for i, j in SECTOR_PAIRS]

# MIPT colours
C_BLUE   = "#003366"
C_ORANGE = "#FF6600"
C_GREEN  = "#1a7340"
FONT     = "DejaVu Sans"

plt.rcParams.update({
    "font.family": FONT,
    "font.size": 11,
    "axes.titlesize": 11,
})


# ---------------------------------------------------------------------------
def load_country_matrices() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Load RUS, DEU, USA Leontief coefficient matrices from the WIOD JSON.
    Returns three (3×3) numpy arrays with NaN for missing values.
    """
    if not WIOD_JSON.exists():
        print(f"[error] {WIOD_JSON} not found.")
        print("  Run: python matrix_doc/calibrate_wiod.py")
        sys.exit(1)

    data = json.loads(WIOD_JSON.read_text(encoding="utf-8"))
    countries = {}
    for country in ["RUS", "DEU", "USA"]:
        raw = data["per_country"][country]["a_raw"]
        arr = np.array(
            [[v if v is not None else np.nan for v in row] for row in raw],
            dtype=float,
        )
        # Scale to max_offdiag = 0.5 (same as A_wiod_v3 scale factor)
        scale = float(data.get("A_wiod_v3_scale_factor", 1.0))
        arr_scaled = arr * scale
        np.fill_diagonal(arr_scaled, 0.0)
        countries[country] = arr_scaled

    return countries["RUS"], countries["DEU"], countries["USA"]


def print_summary_table(calibrator: BayesianCalibrator) -> None:
    """Print prior → posterior comparison table."""
    shrink = calibrator.shrinkage()
    header = f"{'Edge':22s}  {'Prior mu':>10}  {'Prior σ':>8}  {'Post mu':>10}  {'Post σ':>8}  {'Shrink%':>8}"
    print("\n" + "=" * 75)
    print("  Bayesian Calibration Results")
    print("  Prior = WIOD 3-country average | Likelihood = Texas+India proxy")
    print("=" * 75)
    print(f"  {header}")
    print("  " + "-" * 73)

    for (i, j), label in zip(SECTOR_PAIRS, EDGE_LABELS):
        mu0  = calibrator.mu_prior[i, j]
        s0   = calibrator.sigma_prior[i, j]
        mup  = calibrator.mu_post[i, j]
        sp   = calibrator.sigma_post[i, j]
        sh   = shrink[i, j]
        direction = "<" if mup < mu0 else ">"
        print(f"  {label:22s}  {mu0:10.4f}  {s0:8.4f}  {mup:10.4f}  {sp:8.4f}  "
              f"{sh:7.1f}% {direction}")

    print("=" * 75)
    print(f"  sigma_epsilon = {calibrator.sigma_epsilon}  |  "
          f"n_data_points = {calibrator._n_data_points}  |  "
          f"sources = {calibrator._data_sources}")
    print("=" * 75 + "\n")


def plot_distributions(
    calibrator: BayesianCalibrator,
    n_samples: int = 1000,
    out_path: Path = DIST_PNG_OUT,
) -> None:
    """
    Draw N=1000 samples from posterior, plot marginal histograms
    for all 6 off-diagonal elements (2 rows × 3 cols).
    """
    rng = np.random.default_rng(42)
    samples = calibrator.sample_matrices(n=n_samples, seed=42)  # (1000, 3, 3)

    fig, axes = plt.subplots(2, 3, figsize=(13, 7))
    axes = axes.flatten()

    for ax_idx, ((i, j), label) in enumerate(zip(SECTOR_PAIRS, EDGE_LABELS)):
        ax = axes[ax_idx]
        vals = samples[:, i, j]

        mu_pr = calibrator.mu_prior[i, j]
        sig_pr = calibrator.sigma_prior[i, j]
        mu_po = calibrator.mu_post[i, j]
        sig_po = calibrator.sigma_post[i, j]

        # Histogram of samples
        ax.hist(vals, bins=40, density=True, color=C_BLUE, alpha=0.6,
                label=f"Posterior samples (n={n_samples})")

        # Overlay theoretical posterior Gaussian
        x = np.linspace(max(0, mu_po - 4*sig_po), min(1, mu_po + 4*sig_po), 200)
        if sig_po > 0:
            from scipy.stats import norm
            y_post = norm.pdf(x, mu_po, sig_po)
            ax.plot(x, y_post, color=C_BLUE, lw=2.0, label=f"N({mu_po:.3f}, {sig_po:.3f})")

        # Prior Gaussian
        x_pr = np.linspace(max(0, mu_pr - 4*sig_pr), min(1, mu_pr + 4*sig_pr), 200)
        if sig_pr > 0:
            y_prior = norm.pdf(x_pr, mu_pr, sig_pr)
            ax.plot(x_pr, y_prior, color=C_ORANGE, lw=1.5, ls="--",
                    label=f"Prior N({mu_pr:.3f}, {sig_pr:.3f})")

        # Vertical lines: prior and posterior means
        ax.axvline(mu_pr, color=C_ORANGE, lw=1.2, ls=":", alpha=0.8)
        ax.axvline(mu_po, color=C_BLUE,   lw=1.5, alpha=0.9)

        ax.set_title(label, fontweight="bold")
        ax.set_xlabel("a_ij")
        ax.set_ylabel("Density")
        ax.legend(fontsize=8, loc="upper right")
        ax.grid(axis="y", alpha=0.3)
        ax.set_xlim(left=0)

    fig.suptitle(
        f"Posterior distributions of dependency matrix A\n"
        f"(Prior: WIOD 3-country | Likelihood: Texas+India | n_samples={n_samples})",
        fontsize=12, y=1.01,
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"[save] {out_path}")


def print_posterior_matrix(calibrator: BayesianCalibrator) -> None:
    """Print posterior mean matrix in risk_engine config.py format."""
    mu = calibrator.mu_post
    sig = calibrator.sigma_post
    print("\n  Posterior mean matrix (A_bayesian) — for config.py:")
    print("  A_bayesian = [")
    for i, row in enumerate(mu):
        vals = ", ".join(f"{v:.6f}" for v in row)
        print(f"      [{vals}],  # {SECTORS[i]} ← energy, water, transport")
    print("  ]")
    print("\n  Posterior std matrix:")
    print("  sigma_A = [")
    for i, row in enumerate(sig):
        vals = ", ".join(f"{v:.6f}" for v in row)
        print(f"      [{vals}],")
    print("  ]")

    # Spectral radius of posterior mean
    eig = np.linalg.eigvals(mu)
    rho = float(np.max(np.abs(eig)))
    print(f"\n  Spectral radius ρ(A_post_mean) = {rho:.4f}  "
          f"({'stable' if rho < 1 else 'UNSTABLE — will be rescaled on sampling'})")


# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 65)
    print("Bayesian Calibration of Dependency Matrix A")
    print("=" * 65)

    # Step 1: Load country matrices
    print("\n[1] Loading per-country WIOD matrices...")
    A_rus, A_deu, A_usa = load_country_matrices()
    for name, mat in [("RUS", A_rus), ("DEU", A_deu), ("USA", A_usa)]:
        print(f"  {name}: max_offdiag = {np.nanmax(np.where(np.eye(3)==0, mat, 0)):.4f}")

    # Step 2: Build calibrator (prior from WIOD)
    print("\n[2] Building prior from 3-country WIOD statistics...")
    calibrator = BayesianCalibrator.from_country_matrices(A_rus, A_deu, A_usa)
    print("  Prior means (A_wiod_v3 approx):")
    for i, row in enumerate(calibrator.mu_prior):
        print(f"    {SECTORS[i]:12s}: {[round(v,4) for v in row]}")
    print("  Prior stds:")
    for i, row in enumerate(calibrator.sigma_prior):
        print(f"    {SECTORS[i]:12s}: {[round(v,4) for v in row]}")

    # Step 3: Update from proxy data
    print("\n[3] Updating posterior from proxy data...")
    calibrator.update_from_proxy_data(PROXY_CSVS, verbose=True)

    # Step 4: Print summary
    print_summary_table(calibrator)
    print_posterior_matrix(calibrator)

    # Step 5: Save posterior
    print(f"\n[5] Saving posterior to {POSTERIOR_OUT} ...")
    calibrator.save_posterior(str(POSTERIOR_OUT))
    print(f"    File size: {POSTERIOR_OUT.stat().st_size // 1024 + 1} KB")

    # Step 6: Plot distributions
    print("\n[6] Plotting posterior distributions (N=1000 samples)...")
    plot_distributions(calibrator, n_samples=1000, out_path=DIST_PNG_OUT)

    print("\n[done]")


if __name__ == "__main__":
    main()
