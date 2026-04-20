"""
Apply the canonical A*-transformation of Haimes 2005 Part I, eq. (11):

    A*_ij = A_ij * x_j / x_i    for i != j
    A*_ii = 0

Turns raw Leontief direct-requirements coefficients into the inter-industry
inoperability matrix used in the canonical IIM,
q = (I - A*)^{-1} * c*.

Inputs:
  - data/calibration/A_wiod_sensitivity.json   (raw A, sectors, off-diag max=0.5)
  - data/calibration/wiod_sector_outputs.json  (x_j averaged over WIOD 2014)

Outputs:
  - data/calibration/A_star_iim_canonical.json
"""
import json
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
A_PATH = REPO_ROOT / "data" / "calibration" / "A_wiod_sensitivity.json"
X_PATH = REPO_ROOT / "data" / "calibration" / "wiod_sector_outputs.json"
OUT_PATH = REPO_ROOT / "data" / "calibration" / "A_star_iim_canonical.json"


def main() -> None:
    wiod = json.loads(A_PATH.read_text())
    A_raw = np.array(wiod["matrix"], dtype=float)
    sectors = wiod["sectors"]

    x_data = json.loads(X_PATH.read_text())
    x = np.array([x_data["outputs_million_usd"][s] for s in sectors], dtype=float)

    n = len(sectors)
    A_star = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            if i != j:
                A_star[i, j] = A_raw[i, j] * (x[j] / x[i])

    rho_raw = float(np.max(np.abs(np.linalg.eigvals(A_raw))))
    rho_star = float(np.max(np.abs(np.linalg.eigvals(A_star))))
    print(f"rho(A_raw) = {rho_raw:.4f}")
    print(f"rho(A*)    = {rho_star:.4f}")

    normalized = False
    if rho_star > 0.95:
        A_star = A_star * (0.95 / rho_star)
        rho_star = float(np.max(np.abs(np.linalg.eigvals(A_star))))
        normalized = True
        print(f"Soft-normalised to rho(A*) = {rho_star:.4f}")

    print("\nA* matrix:")
    print(f"  {'':<10s}" + "".join(f"{s:>12s}" for s in sectors))
    for i in range(n):
        row = "".join(f"{A_star[i, j]:12.4f}" for j in range(n))
        print(f"  {sectors[i]:<10s}{row}")

    # Sanity check — Europe 2006 (energy shock c*=0.30)
    c_star = np.array([0.30, 0.0, 0.0])
    q_star = np.linalg.solve(np.eye(n) - A_star, c_star)
    q_raw = np.linalg.solve(np.eye(n) - A_raw, c_star)
    print("\nSanity check Europe 2006 (c* = [0.30, 0, 0]):")
    print(f"  on A_raw:  q_energy={q_raw[0]:.4f}  q_water={q_raw[1]:.4f}  "
          f"q_transport={q_raw[2]:.4f}")
    print(f"  on A*:     q_energy={q_star[0]:.4f}  q_water={q_star[1]:.4f}  "
          f"q_transport={q_star[2]:.4f}")
    print(f"  ground truth:                    q_water=0.10   q_transport=0.50")

    output = {
        "schema_version": 1,
        "role": "IIM canonical matrix per Haimes 2005 Part I eq. (11)",
        "sectors": sectors,
        "matrix": A_star.tolist(),
        "spectral_radius": rho_star,
        "rho_raw": rho_raw,
        "construction": "A*_ij = A_ij * (x_j / x_i), A*_ii = 0",
        "source_A": "data/calibration/A_wiod_sensitivity.json",
        "source_x": "data/calibration/wiod_sector_outputs.json",
        "x_values_million_usd": {s: float(x[i]) for i, s in enumerate(sectors)},
        "normalized_to_0_95": normalized,
        "sanity_europe_2006": {
            "c_star": c_star.tolist(),
            "q_on_A_raw": q_raw.tolist(),
            "q_on_A_star": q_star.tolist(),
            "ground_truth_intensities": {"water": 0.10, "transport": 0.50},
        },
        "citation": (
            "Haimes, Y. Y., Horowitz, B. M., Lambert, J. H., Santos, J. R., Crowther, K., "
            "Lian, C. (2005). Inoperability Input-Output Model for Interdependent Infrastructure "
            "Sectors. I: Theory and Methodology. Journal of Infrastructure Systems, 11(2), 67-79."
        ),
    }
    OUT_PATH.write_text(json.dumps(output, indent=2))
    print(f"\nSaved: {OUT_PATH}")


if __name__ == "__main__":
    main()
