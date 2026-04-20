"""
Этап 4-quater — Beta-Binomial posterior с informative prior из WIOD v3.

Motivation
----------
v1 использовал Beta(1,1) uniform prior. При n=4 исторических событий 4/6
off-diagonal ячеек имели n=0 → posterior ≡ prior = 0.5. После spectral cap
ρ=0.50 матрица схлопывалась в узкий диапазон [0.21, 0.29] без реальной
асимметрии. IIM (steady-state) не достигал C=0.70 при любом amp.

v2 — informative prior:
  μ_ij = WIOD v3 (Leontief direct requirements, RUS+DEU+USA, 2014)
  α_0 = κ · μ_ij,   β_0 = κ · (1 − μ_ij),      где κ = effective prior sample size
  Posterior: α = α_0 + Σx,  β = β_0 + n − Σx

При n=0 posterior = prior = μ (реальная WIOD-асимметрия).
При n>0 данные сдвигают posterior — сила смещения ∝ 1/κ.

κ=2 ≈ «2 псевдо-наблюдения» (равно баллу v1 Beta(1,1) по силе).
κ=4 — умеренный prior (предпочтителен при редких событиях).
κ=1 — слабый prior.

Вход:
  data/empirical_cascades/historical_dataset/cascade_events.yaml
  results/A_wiod_v3_snapshot.json
Выход:
  data/calibration/A_empirical_bayesian_v2.json
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from scipy.stats import beta as beta_dist

ROOT = Path(__file__).resolve().parents[2]
EVENTS_YAML = ROOT / "data/empirical_cascades/historical_dataset/cascade_events.yaml"
WIOD_JSON = ROOT / "results/A_wiod_v3_snapshot.json"
OUTPUT_JSON = ROOT / "data/calibration/A_empirical_bayesian_v2.json"

SECTORS = ("energy", "water", "transport")

# effective prior sample size (пересматривается через sweep; дефолт 2).
PRIOR_KAPPA = 2.0

# ρ_target=0.50, см. v1.
SPECTRAL_CAP = 0.50


def load_events() -> list[dict]:
    with EVENTS_YAML.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)["events"]


def load_wiod() -> np.ndarray:
    with WIOD_JSON.open("r", encoding="utf-8") as f:
        d = json.load(f)
    A = np.array(d["matrix"])
    assert list(d["sectors_order"]) == list(SECTORS), (
        f"WIOD sectors {d['sectors_order']} != {SECTORS}"
    )
    return A


def extract_observations(events: list[dict]) -> dict[str, dict[str, list[float]]]:
    obs = {i: {j: [] for j in SECTORS} for i in SECTORS}
    for ev in events:
        initiator = ev["initiator"]["sector"]
        for affected, cell in ev["affected"].items():
            val = cell.get("intensity")
            if isinstance(val, (int, float)) and affected != initiator:
                obs[affected][initiator].append(float(val))
    return obs


def posterior_cell(
    observations: list[float], prior_mean: float, kappa: float
) -> dict[str, float]:
    """Beta posterior with informative prior parameterised as (μ, κ).

    α_0 = max(κ·μ, ε),  β_0 = max(κ·(1−μ), ε)  — guard против κ·0 при μ=0 или 1.
    """
    eps = 1e-6
    alpha_0 = max(kappa * prior_mean, eps)
    beta_0 = max(kappa * (1.0 - prior_mean), eps)
    n = len(observations)
    s = float(sum(observations))
    alpha = alpha_0 + s
    beta = beta_0 + n - s
    mean = alpha / (alpha + beta)
    var = (alpha * beta) / ((alpha + beta) ** 2 * (alpha + beta + 1))
    return {
        "n_observations": n,
        "sum_intensities": s,
        "prior_mean_mu": prior_mean,
        "prior_alpha_0": alpha_0,
        "prior_beta_0": beta_0,
        "posterior_alpha": alpha,
        "posterior_beta": beta,
        "posterior_mean": mean,
        "posterior_std": float(np.sqrt(var)),
        "ci_95_lo": float(beta_dist.ppf(0.025, alpha, beta)),
        "ci_95_hi": float(beta_dist.ppf(0.975, alpha, beta)),
    }


def build_posterior_matrix(
    obs: dict, mu_prior: np.ndarray, kappa: float
) -> tuple[np.ndarray, dict]:
    matrix = np.zeros((3, 3))
    details: dict[str, dict[str, dict]] = {i: {} for i in SECTORS}
    for i_idx, i in enumerate(SECTORS):
        for j_idx, j in enumerate(SECTORS):
            if i == j:
                details[i][j] = {"diagonal": True, "value": 0.0}
                continue
            cell = posterior_cell(obs[i][j], mu_prior[i_idx, j_idx], kappa)
            matrix[i_idx, j_idx] = cell["posterior_mean"]
            details[i][j] = cell
    return matrix, details


def apply_spectral_cap(matrix: np.ndarray, cap: float) -> tuple[np.ndarray, dict]:
    rho = float(np.max(np.abs(np.linalg.eigvals(matrix))))
    meta = {"spectral_radius_before": rho, "cap": cap}
    if rho > cap:
        matrix = matrix * (cap / rho)
        meta["rescale_factor"] = cap / rho
        meta["spectral_radius_after"] = cap
        meta["applied"] = True
    else:
        meta["rescale_factor"] = 1.0
        meta["spectral_radius_after"] = rho
        meta["applied"] = False
    return matrix, meta


def main() -> None:
    events = load_events()
    mu_prior = load_wiod()
    obs = extract_observations(events)

    mat_raw, details = build_posterior_matrix(obs, mu_prior, PRIOR_KAPPA)
    mat_capped, spec = apply_spectral_cap(mat_raw.copy(), SPECTRAL_CAP)

    out = {
        "schema_version": "2.0",
        "sectors": list(SECTORS),
        "prior": {
            "type": "Beta(κ·μ, κ·(1−μ)) per cell, informative",
            "kappa": PRIOR_KAPPA,
            "mu_source": "A_wiod_v3 (Leontief direct requirements, RUS+DEU+USA 2014)",
            "mu_matrix": mu_prior.tolist(),
            "justification": (
                "v1 Beta(1,1) prior dominated posterior because 4/6 off-diagonal cells "
                "had n=0. Using WIOD v3 as prior mean grounds the empty cells in "
                "structural I-O data while preserving Bayesian updating for cells "
                "with n≥1 (water←energy, transport←energy from historical cascades)."
            ),
        },
        "likelihood": "Observed intensity x_k ∈ [0,1] as fractional success over n trials.",
        "n_events_used": len(events),
        "events_used": [e["id"] for e in events],
        "spectral_normalisation": spec,
        "matrix_posterior_mean_raw": mat_raw.tolist(),
        "matrix_posterior_mean_spectral_capped": mat_capped.tolist(),
        "cell_details": details,
        "notes": [
            f"Informative prior κ={PRIOR_KAPPA}: cells with n=0 recover WIOD mean μ_ij.",
            "Cells with n>0 blend WIOD prior and empirical observations.",
            f"Spectral cap ρ={SPECTRAL_CAP}: preserves convergent-regime stability (Bardoscia 2017).",
        ],
    }

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_JSON.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    print(f"Wrote {OUTPUT_JSON.relative_to(ROOT)}\n")

    print("WIOD prior μ:")
    print(f"  {'':10s}  " + " ".join(f"{j:>8s}" for j in SECTORS))
    for i_idx, i in enumerate(SECTORS):
        row = " ".join(f"{mu_prior[i_idx, j_idx]:8.4f}" for j_idx in range(3))
        print(f"  {i:10s}  {row}")

    print(f"\nPosterior RAW (κ={PRIOR_KAPPA}, ρ={float(np.max(np.abs(np.linalg.eigvals(mat_raw)))):.4f}):")
    print(f"  {'':10s}  " + " ".join(f"{j:>8s}" for j in SECTORS))
    for i_idx, i in enumerate(SECTORS):
        row = " ".join(f"{mat_raw[i_idx, j_idx]:8.4f}" for j_idx in range(3))
        print(f"  {i:10s}  {row}")

    print(f"\nPosterior CAPPED (ρ={SPECTRAL_CAP}):")
    print(f"  {'':10s}  " + " ".join(f"{j:>8s}" for j in SECTORS))
    for i_idx, i in enumerate(SECTORS):
        row = " ".join(f"{mat_capped[i_idx, j_idx]:8.4f}" for j_idx in range(3))
        print(f"  {i:10s}  {row}")

    print("\nPer-cell details:")
    for i in SECTORS:
        for j in SECTORS:
            if i == j:
                continue
            d = details[i][j]
            print(
                f"  A[{i:10s}][{j:10s}] μ={d['prior_mean_mu']:.3f} "
                f"n={d['n_observations']} sum={d['sum_intensities']:.2f} "
                f"post_mean={d['posterior_mean']:.4f} "
                f"CI95=[{d['ci_95_lo']:.3f}, {d['ci_95_hi']:.3f}]"
            )


if __name__ == "__main__":
    main()
