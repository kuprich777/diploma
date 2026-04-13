"""
calibrate_A.py
==============
Calibrate the inter-sector dependency matrix A using Leontief direct
requirements coefficients from WIOD 2016 National Input-Output Tables.

Method (Leontief)
-----------------
    a[i][j] = X[i][j] / q[j]

where:
  X[i][j] = intermediate use of sector i output by sector j
             (row i, column j in the domestic intermediate use block)
  q[j]    = total gross output of sector j (GO row, column j)

WIOD NIOT format (Nov16, sheet "National IO-tables")
----------------------------------------------------
  col 0: Year
  col 1: Code (ISIC-like: A01, D35, E36, H49, ...)
  col 2: Description
  col 3: Origin (Domestic / Imports / TOT)
  col 4..N-2: buying sectors (same codes as row codes)
  col N-1: GO (Gross Output)

Sector codes actually used in WIOD Nov16
-----------------------------------------
  Energy    → D35
  Water     → E36, E37-E39
  Transport → H49, H50, H51, H52, H53

Countries: RUS, DEU, USA  (year 2014)
"""

import json
import sys
from pathlib import Path

import numpy as np

try:
    import pandas as pd
    from scipy.stats import spearmanr
except ImportError:
    print("pip install openpyxl pandas scipy")
    sys.exit(1)

# ---------------------------------------------------------------------------
REPO_ROOT   = Path(__file__).resolve().parent.parent
WIOD_DIR    = REPO_ROOT / "matrix_doc" / "sources" / "NIOTS"
CALIB_OUT   = REPO_ROOT / "data" / "calibration" / "A_leontief.json"
SECTORS_OUT = ["energy", "water", "transport"]
COUNTRIES   = ["RUS", "DEU", "USA"]
YEAR        = 2014
SPECTRAL_CAP = 0.95

# Actual WIOD Nov16 sector codes (verified from file inspection)
SECTOR_CODES: dict[str, list[str]] = {
    "energy":    ["D35"],
    "water":     ["E36", "E37-E39"],
    "transport": ["H49", "H50", "H51", "H52", "H53"],
}


def _insufficient(param, needed, found, reason, recommendation):
    print(f"""
🔴 ДАННЫЕ НЕДОСТАТОЧНЫ

Параметр:           {param}
Что нужно:          {needed}
Что есть:           {found}
Почему не подходит: {reason}
Рекомендация:       {recommendation}
""")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Parse one country NIOT
# ---------------------------------------------------------------------------

def extract_leontief(country: str) -> tuple[np.ndarray, dict]:
    """
    Returns (A_3x3, debug_info) for a given country.
    A[i][j] = Leontief direct requirements: how much i is used per unit of j.
    """
    path = WIOD_DIR / f"{country}_NIOT_nov16.xlsx"
    if not path.exists():
        _insufficient(
            param=f"A_leontief ({country})",
            needed=f"Файл {country}_NIOT_nov16.xlsx",
            found=f"Не найден: {path}",
            reason="Файл отсутствует",
            recommendation=f"Скачать с http://www.wiod.org/database/niots16"
        )

    print(f"  Loading {path.name} ...")
    df = pd.ExcelFile(path, engine="openpyxl").parse(
        "National IO-tables", header=None
    )

    # Row 0 = column headers
    col_headers = [str(v).strip() for v in df.iloc[0].tolist()]
    # Map code → column index
    code_to_col = {c: i for i, c in enumerate(col_headers)}

    # Data rows (skip header row 0)
    data = df.iloc[1:].copy()
    data.columns = range(len(data.columns))
    data = data.reset_index(drop=True)

    # Filter: year=2014
    data_2014 = data[data.iloc[:, 0] == YEAR].copy()

    # Gross output row: Origin == "TOT", Code == "GO"
    go_row = data_2014[(data_2014.iloc[:, 1] == "GO") & (data_2014.iloc[:, 3] == "TOT")]

    # Domestic intermediate use rows
    dom = data_2014[data_2014.iloc[:, 3] == "Domestic"].copy()
    # Row code index: column 1
    dom_code_to_row = {}
    for _, row in dom.iterrows():
        dom_code_to_row[str(row.iloc[1]).strip()] = row

    # ---- Build 3×3 matrix ----
    n = len(SECTORS_OUT)
    A = np.zeros((n, n))
    debug: dict = {}

    for j_sec, j_name in enumerate(SECTORS_OUT):
        j_codes = SECTOR_CODES[j_name]

        # Gross output of sector j = sum over j_codes in go_row
        q_j = 0.0
        for jc in j_codes:
            jcol = code_to_col.get(jc)
            if jcol is not None and not go_row.empty:
                v = go_row.iloc[0, jcol]
                try:
                    q_j += float(v)
                except (TypeError, ValueError):
                    pass

        if q_j <= 0:
            print(f"    [warn] q_{j_name} = {q_j} — sector missing/zero in this country; using NaN")
            # Set all a[i][j] = NaN for this j-sector so nanmean skips this country
            for i_sec in range(n):
                if i_sec != j_sec:
                    A[i_sec, j_sec] = np.nan
            continue

        for i_sec, i_name in enumerate(SECTORS_OUT):
            if i_sec == j_sec:
                A[i_sec, j_sec] = 0.0
                continue

            i_codes = SECTOR_CODES[i_name]

            # X[i][j] = sum of dom rows matching i_codes, columns matching j_codes
            x_ij = 0.0
            for ic in i_codes:
                row_data = dom_code_to_row.get(ic)
                if row_data is None:
                    continue
                for jc in j_codes:
                    jcol = code_to_col.get(jc)
                    if jcol is not None:
                        v = row_data.iloc[jcol]
                        try:
                            x_ij += float(v)
                        except (TypeError, ValueError):
                            pass

            a_ij = x_ij / q_j
            A[i_sec, j_sec] = a_ij
            debug[f"{i_name}←{j_name}"] = {
                "x_ij": round(x_ij, 3),
                "q_j": round(q_j, 3),
                "a_ij": round(a_ij, 6),
            }

    np.fill_diagonal(A, 0.0)
    return A, debug


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 60)
    print("Calibrate A (Leontief) from WIOD 2016 NIOT")
    print(f"Year: {YEAR} | Countries: {COUNTRIES}")
    print("=" * 60)

    if not WIOD_DIR.exists():
        _insufficient(
            param="A_leontief",
            needed=f"Каталог {WIOD_DIR} с *_NIOT_nov16.xlsx",
            found="Каталог не существует",
            reason="WIOD NIOT файлы не загружены",
            recommendation="Скачать с http://www.wiod.org/database/niots16"
        )

    country_matrices: dict[str, np.ndarray] = {}
    country_debug: dict[str, dict] = {}

    for country in COUNTRIES:
        print(f"\n[{country}]")
        try:
            A, debug = extract_leontief(country)
        except SystemExit:
            raise
        except Exception as e:
            import traceback
            print(f"  [ERROR] {e}")
            traceback.print_exc()
            continue

        country_matrices[country] = A
        country_debug[country]    = debug

        print(f"  A_{country} (Leontief, {YEAR}):")
        print(f"  {'':16s}", end="")
        for s in SECTORS_OUT:
            print(f"  {s:>12s}", end="")
        print()
        for i, row in enumerate(A):
            print(f"  {SECTORS_OUT[i]:16s}", end="")
            for v in row:
                print(f"  {v:12.6f}", end="")
            print()

        # Show underlying X and q
        print(f"\n  X[i][j] and q[j] details:")
        for key, val in debug.items():
            print(f"    {key}: X={val['x_ij']:.1f}  q_j={val['q_j']:.1f}  a={val['a_ij']:.6f}")

    if not country_matrices:
        print("\n[ERROR] No matrices loaded.")
        sys.exit(1)

    # Average over countries
    stack = np.stack(list(country_matrices.values()), axis=0)
    A_mean = np.nanmean(stack, axis=0)
    np.fill_diagonal(A_mean, 0.0)

    # Spectral radius
    rho = float(np.max(np.abs(np.linalg.eigvals(A_mean))))
    print(f"\nSpectral radius ρ(A_mean) = {rho:.4f}", end="")
    if rho >= 1.0:
        scale = SPECTRAL_CAP / rho
        A_mean_off = A_mean * scale
        np.fill_diagonal(A_mean_off, 0.0)
        A_mean = A_mean_off
        rho = float(np.max(np.abs(np.linalg.eigvals(A_mean))))
        print(f" → rescaled → {rho:.4f}")
    else:
        print(" (stable ✓)")

    # Print final matrix
    print(f"\nA_leontief (mean over {list(country_matrices.keys())}):")
    print(f"  {'':16s}", end="")
    for s in SECTORS_OUT:
        print(f"  {s:>12s}", end="")
    print()
    for i, row in enumerate(A_mean):
        print(f"  {SECTORS_OUT[i]:16s}", end="")
        for v in row:
            print(f"  {v:12.6f}", end="")
        print()

    # Spearman vs A_wiod_v3
    A_wiod_v3 = np.array([
        [0.000, 0.350, 0.304],
        [0.006, 0.000, 0.001],
        [0.500, 0.332, 0.000],
    ])
    mask = ~np.eye(3, dtype=bool)
    rho_sp, pval = spearmanr(A_mean[mask].flatten(), A_wiod_v3[mask].flatten())
    print(f"\nSpearman ρ(A_new, A_wiod_v3) = {rho_sp:.4f}  (p={pval:.4f})")
    if rho_sp < 0.70:
        print("  [warn] Low Spearman rank correlation — verify sector code mapping")
    else:
        print("  ✓ Rank order consistent with A_wiod_v3")

    # Save
    result = {
        "method": "leontief_direct_requirements",
        "formula": "a[i][j] = X[i][j] / q[j]",
        "source": "WIOD 2016 NIOT (Nov16 release)",
        "year": YEAR,
        "countries": list(country_matrices.keys()),
        "sectors": SECTORS_OUT,
        "sector_codes": SECTOR_CODES,
        "per_country": {
            c: {
                "matrix": country_matrices[c].tolist(),
                "details": country_debug[c],
            }
            for c in country_matrices
        },
        "A_mean": A_mean.tolist(),
        "spectral_radius_mean": round(rho, 6),
        "spearman_vs_wiod_v3": round(float(rho_sp), 4) if not np.isnan(rho_sp) else None,
    }

    CALIB_OUT.parent.mkdir(parents=True, exist_ok=True)
    CALIB_OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\n[save] {CALIB_OUT}")


if __name__ == "__main__":
    main()
