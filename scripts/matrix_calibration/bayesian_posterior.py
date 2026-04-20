"""
Этап 1.4 — Beta-Binomial сопряжённое обновление матрицы A.

Prior (Level 1): уровень ячеек неинформативный Beta(1, 1) per Pescaroli & Alexander 2016
                 (Level 1 даёт только row-marginals как sanity check, не cell-level).
Likelihood:     наблюдаемые интенсивности x_k ∈ [0,1] трактуются как дробные успехи
                над одним «испытанием»: Bin(n=1, p=A[i][j]) с фракционной реализацией x_k.
Posterior:      Beta(α_0 + Σx_k, β_0 + n - Σx_k).

Применяется спектральная нормализация: если ρ(A) > 0.95, масштабируется до ρ=0.95.

Вход:  data/empirical_cascades/matrix_calibration/level1_aggregated.yaml
       data/calibration/A_empirical_v1.json
Выход: data/calibration/A_empirical_bayesian_v1.json
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from scipy.stats import beta as beta_dist

ROOT = Path(__file__).resolve().parents[2]
LEVEL1_YAML = ROOT / "data/empirical_cascades/matrix_calibration/level1_aggregated.yaml"
RAW_JSON = ROOT / "data/calibration/A_empirical_v1.json"
OUTPUT_JSON = ROOT / "data/calibration/A_empirical_bayesian_v1.json"

SECTORS = ("energy", "water", "transport")
PRIOR_ALPHA = 1.0
PRIOR_BETA = 1.0
# Этап 4-ter: сбалансированная перекалибровка.
# Выбор пары (ρ_A=0.50, ρ_rec=0.30) произведён после параметрического sweep 5×5
# (results/diagnostics/rho_sweep.md).  λ_growth = ρ_A - ρ_rec = +0.20 — режим
# слабой supercriticality, где SDE разрешает амплитуды и не уходит в clip=1.0
# за T=30 шагов (3h real time).
# Физическое обоснование:
#   ρ_A = 0.50 — сохраняет умеренную cross-sector связь (off-diag ~0.20-0.29),
#     в convergent-режиме по Bardoscia et al. (2017), Nature Commun. 8: 14416
#     «Pathways towards instability in financial networks».
#   ρ_rec = 0.30 (per step, см. run_stage4_mc.py) — characteristic recovery time
#     1/ρ_rec = 3.33 time units ≈ 3.3 часа при dt=0.1, согласуется с:
#     India 2012 (MoP Annual Report: "essential loads restored within 2-3 hours"),
#     UCTE 2006  (Final Report p.5: "normal in less than 2 hours").
# Условие Банаха (ρ_A<1) выполняется с запасом 0.50.
SPECTRAL_CAP = 0.50


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_raw_observations() -> dict[str, dict[str, list[float]]]:
    """Reconstruct per-cell intensity lists from cascade_events.yaml (authoritative)."""
    events_yaml = ROOT / "data/empirical_cascades/historical_dataset/cascade_events.yaml"
    data = load_yaml(events_yaml)
    obs: dict[str, dict[str, list[float]]] = {i: {j: [] for j in SECTORS} for i in SECTORS}
    for ev in data["events"]:
        initiator = ev["initiator"]["sector"]
        for affected, cell in ev["affected"].items():
            val = cell.get("intensity")
            if isinstance(val, (int, float)) and affected != initiator:
                obs[affected][initiator].append(float(val))
    return obs


def posterior_cell(observations: list[float]) -> dict[str, float]:
    """Beta-Binomial conjugate posterior with Beta(1,1) prior."""
    n = len(observations)
    s = float(sum(observations))
    alpha = PRIOR_ALPHA + s
    beta = PRIOR_BETA + n - s
    mean = alpha / (alpha + beta)
    var = (alpha * beta) / ((alpha + beta) ** 2 * (alpha + beta + 1))
    ci_lo = float(beta_dist.ppf(0.025, alpha, beta))
    ci_hi = float(beta_dist.ppf(0.975, alpha, beta))
    return {
        "n_observations": n,
        "sum_intensities": s,
        "posterior_alpha": alpha,
        "posterior_beta": beta,
        "posterior_mean": mean,
        "posterior_std": float(np.sqrt(var)),
        "ci_95_lo": ci_lo,
        "ci_95_hi": ci_hi,
    }


def build_posterior_matrix(obs: dict[str, dict[str, list[float]]]) -> tuple[np.ndarray, dict]:
    matrix = np.zeros((3, 3))
    cell_details: dict[str, dict[str, dict]] = {i: {} for i in SECTORS}
    for i_idx, i in enumerate(SECTORS):
        for j_idx, j in enumerate(SECTORS):
            if i == j:
                cell_details[i][j] = {"diagonal": True, "value": 0.0}
                continue
            post = posterior_cell(obs[i][j])
            matrix[i_idx, j_idx] = post["posterior_mean"]
            cell_details[i][j] = post
    return matrix, cell_details


def apply_spectral_cap(matrix: np.ndarray, cap: float) -> tuple[np.ndarray, dict]:
    eigvals = np.linalg.eigvals(matrix)
    rho = float(np.max(np.abs(eigvals)))
    meta = {"spectral_radius_before": rho, "cap": cap}
    if rho > cap:
        factor = cap / rho
        matrix = matrix * factor
        meta["rescale_factor"] = factor
        meta["spectral_radius_after"] = cap
        meta["applied"] = True
    else:
        meta["rescale_factor"] = 1.0
        meta["spectral_radius_after"] = rho
        meta["applied"] = False
    return matrix, meta


def level1_row_marginal_check(matrix: np.ndarray, level1: dict) -> dict:
    """Column sums of matrix A (over affected i) vs Luiijf secondary-disruptions-per-initiation."""
    col_sums = matrix.sum(axis=0)
    luiijf_avg_secondaries = {
        "energy": level1["secondary_disruptions_per_initiation"]["energy_initiated"],
        "transport": level1["secondary_disruptions_per_initiation"]["transport_initiated"],
        "water": level1["secondary_disruptions_per_initiation"]["water_initiated"],
    }
    report = {}
    for j_idx, j in enumerate(SECTORS):
        luiijf_val = luiijf_avg_secondaries[j]
        report[j] = {
            "posterior_col_sum": float(col_sums[j_idx]),
            "luiijf_avg_secondaries": luiijf_val,
            "note": (
                "Col sum ≈ expected impact count if each cell is interpreted as P(disrupt). "
                "Luiijf averages are counts over up to 2 other sectors (max 2 in 3-sector model)."
            ),
        }
    return report


def main() -> None:
    level1 = load_yaml(LEVEL1_YAML)
    obs = load_raw_observations()

    matrix_post, details = build_posterior_matrix(obs)
    matrix_capped, spec_meta = apply_spectral_cap(matrix_post.copy(), SPECTRAL_CAP)
    row_check = level1_row_marginal_check(matrix_capped, level1)

    output = {
        "schema_version": "1.0",
        "sectors": list(SECTORS),
        "prior": {
            "type": "Beta(alpha, beta) per cell, conjugate Beta-Binomial",
            "alpha_0": PRIOR_ALPHA,
            "beta_0": PRIOR_BETA,
            "justification": (
                "Level 1 (Pescaroli & Alexander 2016 / Luiijf 2009) provides only initiator "
                "marginals and average fan-out, not cell-level conditional probabilities. "
                "Therefore cell-level prior is uninformative Beta(1,1)."
            ),
        },
        "likelihood": "Observed intensity x_k in [0,1] treated as fractional success; Beta(alpha_0+sum x, beta_0+n-sum x).",
        "spectral_normalisation": spec_meta,
        "matrix_posterior_mean_raw": matrix_post.tolist(),
        "matrix_posterior_mean_spectral_capped": matrix_capped.tolist(),
        "cell_details": details,
        "level1_row_marginal_check": row_check,
        "notes": [
            "Cells with n=0 have posterior = prior = 0.5 (Beta(1,1) mean).",
            "This is the honest representation of absence-of-evidence in our 4-event dataset.",
            "Coverage: 2/6 off-diagonal cells have informative (n>=1) data.",
        ],
    }

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_JSON.open("w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Wrote {OUTPUT_JSON.relative_to(ROOT)}\n")
    print(f"A_empirical_bayesian (posterior means, capped; rows=affected, cols=initiator):")
    print(f"  {'':10s}  " + " ".join(f"{j:>7s}" for j in SECTORS))
    for i_idx, i in enumerate(SECTORS):
        row = " ".join(f"{matrix_capped[i_idx, j_idx]:7.4f}" for j_idx in range(3))
        print(f"  {i:10s}  {row}")
    print(f"\nSpectral: ρ_before = {spec_meta['spectral_radius_before']:.4f}, cap applied: {spec_meta['applied']}")
    print(f"\nCell 95% credible intervals (off-diagonal):")
    for i in SECTORS:
        for j in SECTORS:
            if i == j:
                continue
            d = details[i][j]
            print(
                f"  A[{i}][{j}]  n={d['n_observations']}  "
                f"mean={d['posterior_mean']:.3f}  95%CI=[{d['ci_95_lo']:.3f}, {d['ci_95_hi']:.3f}]"
            )


if __name__ == "__main__":
    main()
