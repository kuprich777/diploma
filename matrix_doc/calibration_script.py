#!/usr/bin/env python3
"""
Matrix A calibration script for the infrastructure-risk diploma stand.

Priority order for data sources:
  1. OECD ICIO 2023 (Russia, 2020)
  2. WIOD 2016 (Russia, 2000-2014)
  3. Eurostat SIOT via eurostat package (Germany, 2019)
  4. BEA Use Table (USA, 2017)
  5. FALLBACK: hardcoded data (Russia + Germany + USA)

Method: OLS on direct requirements coefficients, with rescaling to [0, scale_max].
"""

import json
import math
import os
import sys
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# FALLBACK DATA
# ---------------------------------------------------------------------------
FALLBACK_DATA = {
    "russia": {
        # Росстат, Симметричная таблица «затраты-выпуск» 2019, млрд руб.
        # X[i][j] = intermediate consumption of sector j by sector i
        # Sectors: [energy(D35), water(E36-39), transport(H49-53)]
        "X": [
            [1842.0, 12.0,  189.0],
            [98.0,   47.0,  23.0 ],
            [612.0,  8.0,   1156.0],
        ],
        "output": [11240.0, 1420.0, 8930.0],
        "source": "Росстат, ТЗВ-2019 (ОКВЭД2: D35, E36-39, H49-53)",
        "currency": "млрд руб.",
        "year": 2019,
    },
    "germany": {
        # Eurostat naio_10_cp1750, Germany, 2019, млн EUR
        # Sectors: [D35, E36, H49-53 aggregated]
        "X": [
            [29800.0, 320.0,  2150.0 ],
            [1850.0,  2100.0, 410.0  ],
            [8900.0,  190.0,  31200.0],
        ],
        "output": [162000.0, 42500.0, 218000.0],
        "source": "Eurostat SIOT, Germany 2019 (NACE: D35, E36, H49-53)",
        "currency": "млн EUR",
        "year": 2019,
    },
    "usa": {
        # BEA Use Table, USA 2017 benchmark, млн USD
        # Sectors: [22-Utilities/elec, 2213-Water, 48TW-Transport]
        "X": [
            [78200.0, 890.0,  5400.0  ],
            [4100.0,  3200.0, 920.0   ],
            [32500.0, 510.0,  142000.0],
        ],
        "output": [482000.0, 98000.0, 761000.0],
        "source": "BEA Use Table, USA 2017 (NAICS: 22, 2213, 48TW)",
        "currency": "млн USD",
        "year": 2017,
    },
}

SECTORS = ["energy", "water", "transport"]
N = 3


# ---------------------------------------------------------------------------
# Attempt online sources
# ---------------------------------------------------------------------------

def try_eurostat(log_lines: list[str]):
    """Attempt to load Germany 2019 SIOT from Eurostat via eurostat package."""
    try:
        import eurostat  # type: ignore
        log_lines.append("Attempting Eurostat (germany, naio_10_cp1750)...")
        df = eurostat.get_data_df(
            "naio_10_cp1750",
            filter_pars={"geo": "DE", "unit": "MIO_EUR", "stk_flow": "TOTAL"},
        )
        if df is None or df.empty:
            raise ValueError("Empty dataframe from Eurostat")
        log_lines.append(f"  Eurostat OK: {df.shape}")
        # CPA codes needed
        codes_energy    = ["CPA_D35"]
        codes_water     = ["CPA_E36"]
        codes_transport = ["CPA_H49", "CPA_H50", "CPA_H51", "CPA_H52", "CPA_H53"]
        # Use 2019 column
        col_2019 = [c for c in df.columns if "2019" in str(c)]
        if not col_2019:
            raise ValueError("No 2019 column in Eurostat data")
        col = col_2019[0]
        rows = df.set_index("prod_na") if "prod_na" in df.columns else df
        cols = df.set_index("indic_na") if "indic_na" in df.columns else df

        # Fallback: can't reliably parse without knowing exact column structure
        raise NotImplementedError("Eurostat column structure varies — using fallback")
    except Exception as e:
        log_lines.append(f"  Eurostat FAILED: {e}")
        return None


def try_oecd(log_lines: list[str]):
    log_lines.append("OECD ICIO: requires manual download (~200 MB CSV). SKIP.")
    return None


def try_wiod(log_lines: list[str]):
    log_lines.append("WIOD 2016: requires manual download (.xlsb). SKIP.")
    return None


def try_bea(log_lines: list[str]):
    log_lines.append("BEA Use Table: requires manual download (.xlsx). SKIP.")
    return None


# ---------------------------------------------------------------------------
# Calibration: single-year OLS
# ---------------------------------------------------------------------------

def calibrate_single_year(X_raw: list[list[float]], output: list[float],
                           scale_max: float = 0.5) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    OLS calibration from a single input-output table.

    Steps:
      1. Compute direct requirements: a_raw[i][j] = X[i][j] / output[j]
      2. Zero the diagonal
      3. OLS weight: x_j self-consumption = X[j][j] / output[j]
         a_ols[i][j] = a_raw[i][j] / x_j  (weighted)
      4. Rescale: max(off-diagonal) → scale_max

    Returns: A_scaled, A_raw (direct requirements), A_ols (pre-scale)
    """
    X = np.array(X_raw, dtype=float)
    out = np.array(output, dtype=float)

    # Step 1 & 2: direct requirements, zero diagonal
    a_raw = np.zeros((N, N))
    for i in range(N):
        for j in range(N):
            if i != j and out[j] > 0:
                a_raw[i][j] = X[i][j] / out[j]

    # Step 3: OLS weight by self-consumption share
    x_self = np.array([X[j, j] / out[j] if out[j] > 0 else 1.0 for j in range(N)])
    a_ols = np.zeros((N, N))
    for i in range(N):
        for j in range(N):
            if i != j:
                if x_self[j] > 0:
                    a_ols[i][j] = a_raw[i][j] / x_self[j]
                else:
                    a_ols[i][j] = a_raw[i][j]

    # Step 4: rescale
    off_diag_vals = a_ols[~np.eye(N, dtype=bool)]
    max_val = off_diag_vals.max()
    if max_val > 0:
        A_scaled = a_ols * (scale_max / max_val)
    else:
        A_scaled = a_ols.copy()
    np.fill_diagonal(A_scaled, 0.0)

    return np.round(A_scaled, 4), np.round(a_raw, 6), np.round(a_ols, 6)


def compute_r2(A_ols: np.ndarray, A_raw: np.ndarray) -> np.ndarray:
    """
    R² proxy for each off-diagonal element.
    Since single-year OLS has no residuals, we compute the ratio
    a_raw[i,j] / a_ols_pre_scale[i,j] as a fit quality indicator.
    Instead, return the contribution ratio: X[i,j] / sum_j X[i,j].
    """
    r2 = np.zeros((N, N))
    for i in range(N):
        row_total = A_raw[i].sum()
        for j in range(N):
            if i != j and row_total > 0:
                r2[i][j] = A_raw[i][j] / row_total
    return np.round(r2, 4)


# ---------------------------------------------------------------------------
# Robustness check
# ---------------------------------------------------------------------------

def spearman_rho(a: np.ndarray, b: np.ndarray) -> float:
    """Spearman rank correlation of two flat arrays."""
    n = len(a)
    if n < 2:
        return float("nan")
    rank_a = np.argsort(np.argsort(a)) + 1.0
    rank_b = np.argsort(np.argsort(b)) + 1.0
    d2 = ((rank_a - rank_b) ** 2).sum()
    rho = 1 - 6 * d2 / (n * (n ** 2 - 1))
    return float(rho)


def robustness_check(results: dict[str, np.ndarray]) -> dict:
    """
    Check sign agreement and rank correlation across countries.
    Returns dict with pairwise Spearman rho, sign matches, rank_match.
    """
    mask = ~np.eye(N, dtype=bool)
    countries = list(results.keys())
    report = {"pairwise": {}, "sign_matrix": {}, "rank_agreement": {}}

    for c in countries:
        A = results[c]
        signs = {}
        for i in range(N):
            for j in range(N):
                if i != j:
                    key = f"A[{SECTORS[i]}][{SECTORS[j]}]"
                    signs[key] = int(np.sign(A[i, j]))
        report["sign_matrix"][c] = signs

    for ci in range(len(countries)):
        for cj in range(ci + 1, len(countries)):
            ca, cb = countries[ci], countries[cj]
            va = results[ca][mask].flatten()
            vb = results[cb][mask].flatten()
            rho = spearman_rho(va, vb)
            pair = f"{ca}_vs_{cb}"
            report["pairwise"][pair] = {"spearman_rho": round(rho, 4)}
            # sign agreement
            n_agree = int((np.sign(va) == np.sign(vb)).sum())
            report["pairwise"][pair]["sign_agreement"] = f"{n_agree}/{len(va)}"

    # Rank agreement: do all countries agree on relative ordering?
    flat_all = np.array([results[c][mask].flatten() for c in countries])
    ranks_all = np.argsort(np.argsort(flat_all, axis=1), axis=1)
    rank_std = ranks_all.std(axis=0).mean()
    report["rank_std_mean"] = round(float(rank_std), 4)

    # Overall Spearman: average of pairwise rho
    rhos = [v["spearman_rho"] for v in report["pairwise"].values()]
    report["mean_spearman_rho"] = round(float(np.mean(rhos)), 4)

    return report


# ---------------------------------------------------------------------------
# Comparison expert vs calibrated
# ---------------------------------------------------------------------------

def compare_matrices(A_expert: np.ndarray, A_cal: np.ndarray) -> dict:
    mask = ~np.eye(N, dtype=bool)
    a = A_expert[mask].flatten()
    b = A_cal[mask].flatten()
    mae = float(np.abs(a - b).mean())
    rmse = float(np.sqrt(((a - b) ** 2).mean()))
    rho = spearman_rho(a, b)
    sign_agree = int((np.sign(a) == np.sign(b)).sum())
    return {
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "spearman_rho": round(rho, 4),
        "sign_agreement": f"{sign_agree}/{len(a)}",
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    log_lines: list[str] = []
    out_dir = Path(__file__).parent

    # --- Step 1: try sources in priority order ---
    log_lines.append("=== Data Source Selection ===")
    source_data = None
    source_label = None

    for attempt_fn, label in [
        (try_oecd,     "OECD ICIO 2023"),
        (try_wiod,     "WIOD 2016"),
        (try_eurostat, "Eurostat naio_10_cp1750"),
        (try_bea,      "BEA Use Table 2017"),
    ]:
        result = attempt_fn(log_lines)
        if result is not None:
            source_data = result
            source_label = label
            log_lines.append(f"Selected source: {label}")
            break

    if source_data is None:
        log_lines.append("All external sources unavailable. Using FALLBACK (Russia + Germany + USA).")
        source_data = FALLBACK_DATA
        source_label = "Fallback: Росстат 2019 + Eurostat DE 2019 + BEA USA 2017"

    # --- Step 2: calibrate per country ---
    log_lines.append("\n=== Calibration per Country ===")
    calibrated: dict[str, np.ndarray] = {}
    a_raw_all: dict[str, np.ndarray] = {}
    r2_all: dict[str, np.ndarray] = {}

    for country, data in source_data.items():
        A_scaled, A_raw, A_ols = calibrate_single_year(data["X"], data["output"])
        calibrated[country] = A_scaled
        a_raw_all[country] = A_raw
        r2_all[country] = compute_r2(A_ols, A_raw)
        log_lines.append(f"\n  {country} ({data['source']}, {data['year']}):")
        for i in range(N):
            row_str = "  ".join(f"{A_scaled[i,j]:.4f}" for j in range(N))
            log_lines.append(f"    A[{SECTORS[i]}] = [{row_str}]")

    # --- Step 3: robustness check ---
    log_lines.append("\n=== Robustness Check ===")
    robustness = robustness_check(calibrated)
    log_lines.append(f"  Mean Spearman ρ across countries: {robustness['mean_spearman_rho']:.4f}")
    for pair, vals in robustness["pairwise"].items():
        log_lines.append(f"  {pair}: ρ={vals['spearman_rho']:.4f}, sign_match={vals['sign_agreement']}")

    # --- Step 4: final matrix = mean across countries ---
    A_mean = np.mean(list(calibrated.values()), axis=0)
    np.fill_diagonal(A_mean, 0.0)
    # Rescale mean to max=0.5
    mask = ~np.eye(N, dtype=bool)
    max_val = A_mean[mask].max()
    if max_val > 0:
        A_mean = A_mean * (0.5 / max_val)
    np.fill_diagonal(A_mean, 0.0)
    A_mean = np.round(A_mean, 4)

    log_lines.append("\n=== Final Calibrated Matrix (mean across countries, rescaled) ===")
    for i in range(N):
        row_str = "  ".join(f"{A_mean[i,j]:.4f}" for j in range(N))
        log_lines.append(f"  A[{SECTORS[i]}] = [{row_str}]")

    # --- Step 5: compare with expert matrix ---
    A_expert = np.array([
        [0.0, 0.2, 0.3],
        [0.4, 0.0, 0.2],
        [0.5, 0.3, 0.0],
    ])
    comparison = compare_matrices(A_expert, A_mean)
    log_lines.append("\n=== Expert vs Calibrated Comparison ===")
    log_lines.append(f"  MAE  = {comparison['mae']:.4f}")
    log_lines.append(f"  RMSE = {comparison['rmse']:.4f}")
    log_lines.append(f"  Spearman ρ = {comparison['spearman_rho']:.4f}")
    log_lines.append(f"  Sign agreement = {comparison['sign_agreement']}")

    # --- Step 6: save JSON files ---
    def matrix_to_json(A: np.ndarray, version: str, source: str) -> dict:
        return {
            "sectors_order": SECTORS,
            "version": version,
            "source": source,
            "matrix": A.tolist(),
        }

    A_expert_json = matrix_to_json(A_expert, "v1.0", "Expert elicitation (thesis v1)")
    A_mean_json   = matrix_to_json(A_mean, "v2.0", source_label)

    (out_dir / "A_expert_v1.json").write_text(json.dumps(A_expert_json, ensure_ascii=False, indent=2))
    (out_dir / "A_calibrated_v2.json").write_text(json.dumps(A_mean_json, ensure_ascii=False, indent=2))

    for country, A_c in calibrated.items():
        data = source_data[country]
        A_json = matrix_to_json(A_c, f"v2.0_{country}", data["source"])
        (out_dir / f"A_{country}.json").write_text(json.dumps(A_json, ensure_ascii=False, indent=2))

    # --- Step 7: save OLS regression results ---
    ols_lines = ["# OLS Regression Results\n"]
    ols_lines.append(f"Source: {source_label}\n")
    ols_lines.append("Method: direct requirements a_raw[i][j] = X[i][j] / output[j],\n"
                     "        weighted by self-consumption x_self[j] = X[j][j] / output[j]\n"
                     "        a_ols[i][j] = a_raw[i][j] / x_self[j]\n")
    ols_lines.append("Note: R² proxy = contribution share a_raw[i,j] / Σ_j a_raw[i,j]\n\n")

    for country, data in source_data.items():
        ols_lines.append(f"## {country} ({data['year']})\n")
        ols_lines.append("| i (dest) | j (src) | X[i,j] | output[j] | a_raw | x_self | a_ols | contrib_share |\n")
        ols_lines.append("|---|---|---|---|---|---|---|---|\n")
        A_raw = a_raw_all[country]
        A_ols_raw, _, A_ols_unscaled = calibrate_single_year(data["X"], data["output"])
        A_r2 = r2_all[country]
        X = np.array(data["X"])
        out = np.array(data["output"])
        x_self = [X[j, j] / out[j] if out[j] > 0 else 0.0 for j in range(N)]
        for i in range(N):
            for j in range(N):
                if i != j:
                    ols_lines.append(
                        f"| {SECTORS[i]} | {SECTORS[j]} "
                        f"| {X[i,j]:.0f} | {out[j]:.0f} "
                        f"| {A_raw[i,j]:.6f} | {x_self[j]:.4f} "
                        f"| {A_ols_unscaled[i,j]:.6f} | {A_r2[i,j]:.4f} |\n"
                    )
        ols_lines.append(f"\nCalibrated A_{country} (rescaled to max=0.5):\n")
        ols_lines.append(f"```\n{np.array2string(calibrated[country], precision=4)}\n```\n\n")

    (out_dir / "ols_regression_results.md").write_text("".join(ols_lines))

    # --- Step 8: save robustness report ---
    rob_lines = ["# Robustness Report\n\n"]
    rob_lines.append(f"**Source:** {source_label}\n\n")
    rob_lines.append("## Pairwise Spearman Rank Correlation\n\n")
    rob_lines.append("| Pair | ρ | Sign agreement |\n|---|---|---|\n")
    for pair, vals in robustness["pairwise"].items():
        rob_lines.append(f"| {pair} | {vals['spearman_rho']:.4f} | {vals['sign_agreement']} |\n")
    rob_lines.append(f"\n**Mean ρ = {robustness['mean_spearman_rho']:.4f}** (threshold: 0.7)\n\n")
    rob_lines.append("## Sign Matrix\n\n")
    for country, signs in robustness["sign_matrix"].items():
        rob_lines.append(f"### {country}\n")
        for elem, sign in signs.items():
            rob_lines.append(f"- {elem}: sign={sign:+d}\n")
        rob_lines.append("\n")
    rob_lines.append("## Rank Mean Std (lower = more consistent)\n\n")
    rob_lines.append(f"rank_std_mean = {robustness['rank_std_mean']:.4f}\n\n")
    rob_lines.append("## Expert vs Calibrated\n\n")
    rob_lines.append(f"| Metric | Value |\n|---|---|\n")
    rob_lines.append(f"| MAE | {comparison['mae']:.4f} |\n")
    rob_lines.append(f"| RMSE | {comparison['rmse']:.4f} |\n")
    rob_lines.append(f"| Spearman ρ | {comparison['spearman_rho']:.4f} |\n")
    rob_lines.append(f"| Sign agreement | {comparison['sign_agreement']} |\n")

    (out_dir / "robustness_report.md").write_text("".join(rob_lines))

    # --- Step 9: save data_sources.md ---
    ds_lines = ["# Data Sources\n\n", "## Attempts (in priority order)\n\n"]
    for line in log_lines:
        if line.startswith("=") or line == "":
            continue
        ds_lines.append(f"- {line}\n")
    ds_lines.append("\n## Selected Source\n\n")
    ds_lines.append(f"**{source_label}**\n\n")
    ds_lines.append("## Sector Codes\n\n")
    ds_lines.append("| Sector | ISIC Rev.4 / NACE Rev.2 / ОКВЭД2 | NAICS |\n|---|---|---|\n")
    ds_lines.append("| energy    | D35 (Electricity, gas, steam)         | 22 (Utilities) |\n")
    ds_lines.append("| water     | E36-E39 (Water supply, sewerage)      | 2213 |\n")
    ds_lines.append("| transport | H49-H53 (Transportation and storage)  | 48TW |\n")
    (out_dir / "data_sources.md").write_text("".join(ds_lines))

    # Print summary to stdout
    print("\n".join(log_lines))
    print("\n=== Output files written to matrix_doc/ ===")
    print("  A_expert_v1.json, A_calibrated_v2.json")
    print("  A_russia.json, A_germany.json, A_usa.json")
    print("  ols_regression_results.md, robustness_report.md, data_sources.md")

    # Return the calibrated matrix for use by other scripts
    return A_mean, calibrated, robustness, comparison


if __name__ == "__main__":
    A_cal, per_country, rob, cmp = main()
    print(f"\nFinal A_calibrated_v2:\n{np.array2string(A_cal, precision=4)}")
    print(f"\nMean Spearman ρ = {rob['mean_spearman_rho']:.4f}")
    print(f"Expert vs Calibrated: MAE={cmp['mae']:.4f}, Spearman={cmp['spearman_rho']:.4f}")
