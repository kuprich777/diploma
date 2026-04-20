"""
Этап 4-ter, ШАГ 1 — параметрический sweep (ρ_A, ρ_rec).

Цель: найти физически осмысленную пару (ρ_A, ρ_rec), при которой SDE-модель
разрешает амплитуду шока на маржинальном сценарии (K_NLDR ∈ (0.1, 0.9)) и
не уходит в сатурацию clip=1.0.

Marginal scenario: S_transport_sev025 (severity=0.25, initiator=transport,
x0=[0.3, 0.3, 0.3], C=[0.75]*3, δ=0.10, dt=0.1, T_steps=30).

Grid:
  ρ_A   ∈ {0.30, 0.40, 0.50, 0.60, 0.70}
  ρ_rec ∈ {0.05, 0.10, 0.20, 0.30, 0.50}
N_runs per cell = 200.

Выход:
  results/diagnostics/rho_sweep.csv
  results/diagnostics/rho_sweep.md
"""
from __future__ import annotations

import csv
import json
import time
from pathlib import Path

import numpy as np

from services.risk_engine.sde_integrator import SDEConfig, SDEIntegrator
from services.risk_engine.mc_harness import make_seed, indicators

ROOT = Path(__file__).resolve().parents[2]
A_JSON = ROOT / "data/calibration/A_empirical_bayesian_v1.json"
SIGMA_JSON = ROOT / "data/calibration/sigma_empirical_v1.json"
OUT_CSV = ROOT / "results/diagnostics/rho_sweep.csv"
OUT_MD = ROOT / "results/diagnostics/rho_sweep.md"

RHO_A_GRID = [0.30, 0.40, 0.50, 0.60, 0.70]
RHO_REC_GRID = [0.05, 0.10, 0.20, 0.30, 0.50]

SECTORS = ("energy", "water", "transport")
N_RUNS = 200
T_STEPS = 30
DT = 0.1
DELTA = 0.10
ALPHA = 3.0
X0_BASE = np.array([0.3, 0.3, 0.3])
C_DEFAULT = np.array([0.75, 0.75, 0.75])

SCENARIO_ID = "S_transport_sev025"
INITIATOR = 2  # transport
SEVERITY = 0.25


def load_raw_matrix() -> np.ndarray:
    """Load raw posterior-mean matrix (pre-cap)."""
    with A_JSON.open() as f:
        d = json.load(f)
    return np.array(d["matrix_posterior_mean_raw"])


def renormalize(A_raw: np.ndarray, target_rho: float) -> np.ndarray:
    """Rescale A so that spectral radius = target_rho."""
    rho = float(np.max(np.abs(np.linalg.eigvals(A_raw))))
    if rho == 0.0:
        return A_raw.copy()
    return A_raw * (target_rho / rho)


def load_sigma() -> np.ndarray:
    with SIGMA_JSON.open() as f:
        d = json.load(f)
    sv = d["sigma_vector_per_hour"]
    return np.array([sv["energy"], sv["water"], sv["transport"]])


def run_cell(A: np.ndarray, sigma: np.ndarray, rho_rec: float) -> dict:
    """Run MC on marginal scenario, return summary."""
    rho_vec = np.array([rho_rec] * 3)
    cfg = SDEConfig(
        A=A, sigma=sigma, rho=rho_vec, C=C_DEFAULT,
        delta=DELTA, dt=DT, T_steps=T_STEPS, alpha=ALPHA,
    )
    integ = SDEIntegrator(cfg)
    shock = np.zeros(3)
    shock[INITIATOR] = SEVERITY

    icl_arr, iq_arr, md_arr, maxx_arr = [], [], [], []
    for k in range(N_RUNS):
        traj = integ.run(x0=X0_BASE, shock=shock,
                         seed=make_seed(SCENARIO_ID, k, "sde_sweep"))
        I_cl, I_q, md = indicators(traj, C_DEFAULT, DELTA, INITIATOR)
        icl_arr.append(I_cl)
        iq_arr.append(I_q)
        md_arr.append(md)
        # max of non-initiator sectors reached in this run
        non_init = [j for j in range(3) if j != INITIATOR]
        maxx_arr.append(float(np.max(traj[:, non_init])))
    return {
        "K_NLDR": float(np.mean(icl_arr)),   # SDE classical indicator = "NLDR K_cl"
        "K_q": float(np.mean(iq_arr)),
        "mean_delta": float(np.mean(md_arr)),
        "mean_max_x": float(np.mean(maxx_arr)),
        "p95_max_x": float(np.quantile(maxx_arr, 0.95)),
    }


def main() -> None:
    A_raw = load_raw_matrix()
    sigma = load_sigma()
    print(f"A_raw ρ = {float(np.max(np.abs(np.linalg.eigvals(A_raw)))):.4f}")
    print(f"sigma = {sigma.round(4).tolist()}")
    print(f"\nGrid: ρ_A {RHO_A_GRID} × ρ_rec {RHO_REC_GRID}  "
          f"× N={N_RUNS} × T={T_STEPS}\n")

    t0 = time.time()
    rows = []
    for rho_A in RHO_A_GRID:
        A = renormalize(A_raw, rho_A)
        for rho_rec in RHO_REC_GRID:
            res = run_cell(A, sigma, rho_rec)
            lam = rho_A - rho_rec
            discriminating = 0.1 < res["K_NLDR"] < 0.9 and res["mean_max_x"] < 1.0
            row = {
                "rho_A": rho_A,
                "rho_rec": rho_rec,
                "lambda_growth": round(lam, 4),
                "K_NLDR": round(res["K_NLDR"], 3),
                "K_q": round(res["K_q"], 3),
                "mean_delta": round(res["mean_delta"], 3),
                "mean_max_x": round(res["mean_max_x"], 3),
                "p95_max_x": round(res["p95_max_x"], 3),
                "discriminating": int(discriminating),
            }
            rows.append(row)
            flag = "  ★" if discriminating else ""
            print(f"  ρ_A={rho_A:.2f} ρ_rec={rho_rec:.2f} "
                  f"λ={lam:+.2f} K_NLDR={res['K_NLDR']:.3f} "
                  f"K_q={res['K_q']:.3f} max_x={res['mean_max_x']:.3f}{flag}")
    elapsed = time.time() - t0
    print(f"\nSweep done in {elapsed:.1f}s, {len(rows)} cells.")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {OUT_CSV.relative_to(ROOT)}")

    # discriminating pairs
    disc = [r for r in rows if r["discriminating"] == 1]
    print(f"\nDiscriminating pairs (K∈(0.1,0.9), max_x<1.0): {len(disc)}")
    for r in disc:
        print(f"  ρ_A={r['rho_A']:.2f} ρ_rec={r['rho_rec']:.2f} "
              f"λ={r['lambda_growth']:+.2f} K_NLDR={r['K_NLDR']:.3f} "
              f"max_x={r['mean_max_x']:.3f}")

    write_markdown(rows, disc, elapsed)


def write_markdown(rows, disc, elapsed):
    with OUT_MD.open("w", encoding="utf-8") as f:
        f.write(f"# ρ_A × ρ_rec sweep (Этап 4-ter ШАГ 1)\n\n")
        f.write(f"**Сценарий:** {SCENARIO_ID} (initiator=transport, severity={SEVERITY}, "
                f"x0=[0.3,0.3,0.3], C=[0.75]*3, T={T_STEPS}, N={N_RUNS})\n\n")
        f.write(f"**Время прогона:** {elapsed:.1f}s для {len(rows)} ячеек\n\n")
        f.write("## Полная таблица\n\n")
        f.write("| ρ_A | ρ_rec | λ_growth | K_NLDR | K_q | mean_Δ | mean_max_x | p95_max_x | discrim? |\n")
        f.write("|---|---|---|---|---|---|---|---|---|\n")
        for r in rows:
            f.write(f"| {r['rho_A']:.2f} | {r['rho_rec']:.2f} | {r['lambda_growth']:+.2f} | "
                    f"{r['K_NLDR']:.3f} | {r['K_q']:.3f} | {r['mean_delta']:.3f} | "
                    f"{r['mean_max_x']:.3f} | {r['p95_max_x']:.3f} | "
                    f"{'★' if r['discriminating'] else ''} |\n")
        f.write(f"\n## Discriminating pairs (K∈(0.1,0.9) AND mean_max_x<1.0)\n\n")
        if not disc:
            f.write("_Нет пар, удовлетворяющих критерию — структурная проблема не решается_\n"
                    "_перекалибровкой (ρ_A, ρ_rec) на данном сценарии._\n")
        else:
            f.write("| ρ_A | ρ_rec | λ | K_NLDR | max_x |\n|---|---|---|---|---|\n")
            for r in disc:
                f.write(f"| {r['rho_A']:.2f} | {r['rho_rec']:.2f} | "
                        f"{r['lambda_growth']:+.2f} | {r['K_NLDR']:.3f} | "
                        f"{r['mean_max_x']:.3f} |\n")


if __name__ == "__main__":
    main()
