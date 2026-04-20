"""
Extract total outputs x_j (Gross Output) for sectors energy, water, transport
from WIOD 2016 NIOT Excel files (RUS, DEU, USA; year 2014 — same coverage as
A_wiod_sensitivity.json).

ISIC Rev.4 codes:
  Energy     = D35
  Water      = E36
  Transport  = H49 + H50 + H51 + H52 + H53  (aggregated, matches matrix A)

x_j is read from the GO row (Origin=TOT), columns D35 / E36 / H49..H53,
summing Transport codes.

RUS has water GO=0 in WIOD NIOT 2014 — excluded from water average, same
rule as A_wiod_sensitivity.json construction.
"""
import json
from pathlib import Path

import openpyxl


REPO_ROOT = Path(__file__).resolve().parents[2]
NIOTS_DIR = REPO_ROOT / "matrix_doc" / "sources" / "NIOTS"
OUT_PATH = REPO_ROOT / "data" / "calibration" / "wiod_sector_outputs.json"

COUNTRIES = ["RUS", "DEU", "USA"]
YEAR = 2014

SECTOR_CODES = {
    "energy": ["D35"],
    "water": ["E36"],
    "transport": ["H49", "H50", "H51", "H52", "H53"],
}


def load_go_row(country: str, year: int):
    path = NIOTS_DIR / f"{country}_NIOT_nov16.xlsx"
    if not path.exists():
        raise FileNotFoundError(path)
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    ws = wb["National IO-tables"]
    all_rows = list(ws.iter_rows(values_only=True))
    headers = list(all_rows[0])
    col_idx = {h: i for i, h in enumerate(headers) if h is not None}
    data_rows = all_rows[2:]

    for row in data_rows:
        if row[0] is None:
            continue
        try:
            yr = int(row[0])
        except (TypeError, ValueError):
            continue
        if yr != year:
            continue
        if row[1] == "GO" and row[3] == "TOT":
            return row, col_idx
    raise RuntimeError(f"GO/TOT row for year {year} not found in {path}")


def extract_outputs(country: str, year: int = YEAR) -> dict:
    go_row, col_idx = load_go_row(country, year)

    def get_cell(code: str) -> float:
        idx = col_idx.get(code)
        if idx is None:
            return 0.0
        v = go_row[idx]
        return float(v) if v is not None else 0.0

    outputs = {}
    for sector, codes in SECTOR_CODES.items():
        total = sum(get_cell(c) for c in codes)
        outputs[sector] = total
    return outputs


def main() -> None:
    print(f"WIOD NIOT {YEAR} — Gross Output x_j (units: million USD)")
    print("=" * 60)
    per_country = {}
    for country in COUNTRIES:
        out = extract_outputs(country, YEAR)
        per_country[country] = out
        print(f"  {country}:  energy={out['energy']:>12,.2f}  "
              f"water={out['water']:>10,.2f}  transport={out['transport']:>12,.2f}")

    # Average across countries, excluding zero values (RUS water handling).
    sectors = list(SECTOR_CODES.keys())
    averaged: dict[str, float] = {}
    contributions: dict[str, list[str]] = {}
    for s in sectors:
        vals = [(c, per_country[c][s]) for c in COUNTRIES if per_country[c][s] > 0]
        if not vals:
            raise RuntimeError(f"No non-zero GO for sector {s}")
        contributions[s] = [c for c, _ in vals]
        averaged[s] = sum(v for _, v in vals) / len(vals)

    print("\nAveraged x_j (excluding zero-GO countries):")
    for s in sectors:
        print(f"  {s:<10s}: {averaged[s]:>14,.2f}   "
              f"from {contributions[s]}")

    e, w, t = averaged["energy"], averaged["water"], averaged["transport"]
    print("\nRatios:")
    print(f"  x_energy / x_water     = {e / w:6.2f}")
    print(f"  x_energy / x_transport = {e / t:6.2f}")
    print(f"  x_transport / x_water  = {t / w:6.2f}")

    output = {
        "schema_version": 1,
        "source": "WIOD 2016 NIOT",
        "countries": COUNTRIES,
        "year": YEAR,
        "sectors_mapping": SECTOR_CODES,
        "outputs_million_usd": averaged,
        "per_country_million_usd": per_country,
        "contributions": contributions,
        "construction": (
            "Gross Output read from the GO/TOT row of 'National IO-tables' sheet, "
            "columns D35 (Energy), E36 (Water), H49..H53 summed (Transport). "
            "Per-sector average over countries with GO>0 — RUS water excluded "
            "(E36 GO=0 in WIOD 2014), matching A_wiod_sensitivity.json rule."
        ),
        "citation": (
            "Timmer, M. P., Dietzenbacher, E., Los, B., Stehrer, R., de Vries, G. J. "
            "(2015). An Illustrated User Guide to the World Input-Output Database."
        ),
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, indent=2))
    print(f"\nSaved: {OUT_PATH}")


if __name__ == "__main__":
    main()
