"""
Этап 4-ter, ШАГ 2.4 — sanity check после применения пары (ρ_A=0.50, ρ_rec=0.30).

Три контрольные точки:
  S_energy_sev010    (low, amp=0.10)  → ожидается K_NLDR ∈ (0.0, 0.3)
  S_transport_sev025 (marginal, amp=0.25) → ожидается K_NLDR ∈ (0.1, 0.9)
  S_energy_sev100    (high, amp=1.00) → ожидается K_NLDR ≈ 1.0

N_runs = 500 (точнее, чем sweep; быстрее, чем полный MC).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from services.risk_engine.mc_harness import MCConfig, Scenario, run_mc

ROOT = Path(__file__).resolve().parents[2]
A_JSON = ROOT / "data/calibration/A_empirical_bayesian_v1.json"
SIGMA_JSON = ROOT / "data/calibration/sigma_empirical_v1.json"

N_RUNS = 500


def main() -> None:
    A = np.array(json.loads(A_JSON.read_text())["matrix_posterior_mean_spectral_capped"])
    sv = json.loads(SIGMA_JSON.read_text())["sigma_vector_per_hour"]
    sigma = np.array([sv["energy"], sv["water"], sv["transport"]])

    cfg = MCConfig(
        A=A, sigma=sigma,
        rho=np.array([0.30, 0.30, 0.30]),
        C=np.array([0.75, 0.75, 0.75]),
        delta=0.10, dt=0.1, T_steps=30,
        alpha=3.0, neva_beta=2.0,
        operator_noise_scale=1.0,
    )

    rho_A = float(np.max(np.abs(np.linalg.eigvals(A))))
    print(f"A ρ = {rho_A:.4f}, ρ_rec = 0.30, λ = {rho_A-0.30:+.2f}, T=30")
    print()

    checks = [
        ("low (amp=0.10)",    Scenario("S_energy_sev010",    0, 0.10, np.array([0.3]*3)), (0.0, 0.3)),
        ("marginal (0.25)",   Scenario("S_transport_sev025", 2, 0.25, np.array([0.3]*3)), (0.1, 0.9)),
        ("high (amp=1.00)",   Scenario("S_energy_sev100",    0, 1.00, np.array([0.3]*3)), (0.8, 1.01)),
    ]

    print(f"{'scenario':<22s} {'SDE K_cl':>10s} {'IIM K_cl':>10s} {'NEVA K_cl':>10s} "
          f"{'expected':<15s} {'pass':>5s}")
    print("-" * 80)
    all_pass = True
    for label, sc, (lo, hi) in checks:
        r = run_mc(sc, cfg, N_RUNS)
        kcl_sde = r["per_operator"]["sde"]["K_cl"]
        kcl_iim = r["per_operator"]["iim"]["K_cl"]
        kcl_neva = r["per_operator"]["neva"]["K_cl"]
        ok = lo <= kcl_sde <= hi
        all_pass = all_pass and ok
        print(f"{label:<22s} {kcl_sde:>10.3f} {kcl_iim:>10.3f} {kcl_neva:>10.3f} "
              f"[{lo:.2f},{hi:.2f}]    {'YES' if ok else 'NO':>5s}")

    print()
    print("OVERALL:", "PASS" if all_pass else "FAIL")


if __name__ == "__main__":
    main()
