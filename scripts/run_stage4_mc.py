"""
Этап 4 — Полный Monte Carlo на 15 сценариях × 3 операторах.

Сценарный каталог (15):
  3 initiator × 5 severity-levels = 15 scenarios
  initiator:  energy / water / transport (по нашему 3-секторному каталогу)
  severity:   [0.10, 0.25, 0.50, 0.75, 1.00]  (intensity scale из cascade_events.yaml)

Baseline state x0 = [0.3, 0.3, 0.3]  (generic operational baseline).
A = full-data Bayesian posterior (spectral capped ρ=0.95).
σ = empirical per-hour vector из sigma_empirical_v1.json.
ρ_recovery = 0.02/step (mild mean-reversion для SDE).
C = [0.75, 0.75, 0.75] (из выбранного θ=0.75 в предыдущих экспериментах).
δ = 0.10.
dt = 0.1, T_steps = 50 (≈5 часов модельного времени).
α = 3.0 (dynamic matrix).
β_NEVA = 2.0.
N_runs = 1000.

LOO-robustness: дополнительный прогон на 4 LOO-матрицах для primary сценария
  (energy, severity=0.75 — аналог Техас 2021) — 4 extra MC cells × 3 ops.

Выход: results/stage4_mc_15x3.json + results/stage4_loo_robustness.json
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from services.risk_engine.mc_harness import MCConfig, Scenario, bootstrap_ci, run_mc

ROOT = Path(__file__).resolve().parent.parent
A_JSON = ROOT / "data/calibration/A_empirical_bayesian_v1.json"
LOO_JSON = ROOT / "data/calibration/A_loo_v1.json"
SIGMA_JSON = ROOT / "data/calibration/sigma_empirical_v1.json"
OUT_MAIN = ROOT / "results/stage4_mc_15x3.json"
OUT_LOO = ROOT / "results/stage4_loo_robustness.json"

SECTORS = ("energy", "water", "transport")
SEVERITIES = [0.10, 0.25, 0.50, 0.75, 1.00]
N_RUNS = 1000
X0_BASE = np.array([0.3, 0.3, 0.3])
C_DEFAULT = np.array([0.75, 0.75, 0.75])
# Этап 4-ter: ρ_rec = 0.30 (было 0.02) — characteristic recovery time 3.3h.
# Выбрано вместе с ρ_A=0.50 после параметрического sweep 5×5,
# см. results/diagnostics/rho_sweep.md и docs/methodology/calibration_rationale.md.
RHO_RECOVERY = np.array([0.30, 0.30, 0.30])
ALPHA = 3.0
BETA_NEVA = 2.0
DT = 0.1
# T_steps = 30 (было 50) — калибровка под early-warning horizon.
# Инвестиционный due diligence интересуется первыми часами развития
# каскада (risk signal detection), а не асимптотическим equilibrium.
# Соответствует физическому времени первичной фазы реальных каскадов
# до активации emergency response. UCTE 2007 Final Report: первые
# 60 минут определили географический масштаб Europe 2006.
T_STEPS = 30
DELTA = 0.10


def load_matrix(path: Path, key: str = "matrix_posterior_mean_spectral_capped") -> np.ndarray:
    with path.open() as f:
        d = json.load(f)
    return np.array(d[key])


def load_sigma() -> np.ndarray:
    with SIGMA_JSON.open() as f:
        d = json.load(f)
    sv = d["sigma_vector_per_hour"]
    return np.array([sv["energy"], sv["water"], sv["transport"]])


def build_catalog() -> list[Scenario]:
    scenarios = []
    for i_idx, sec in enumerate(SECTORS):
        for sev in SEVERITIES:
            scenarios.append(Scenario(
                id=f"S_{sec}_sev{int(sev*100):03d}",
                initiator=i_idx,
                severity=sev,
                x0=X0_BASE.copy(),
                description=f"Initiator={sec}, severity={sev}, x0=[.3,.3,.3]",
            ))
    return scenarios


def run_main_experiment() -> dict:
    A = load_matrix(A_JSON)
    sigma = load_sigma()
    cfg = MCConfig(
        A=A, sigma=sigma, rho=RHO_RECOVERY, C=C_DEFAULT,
        delta=DELTA, dt=DT, T_steps=T_STEPS, alpha=ALPHA,
        neva_beta=BETA_NEVA, operator_noise_scale=1.0,
    )
    scenarios = build_catalog()
    print(f"\n=== Stage 4 main: {len(scenarios)} scenarios × 3 ops × {N_RUNS} runs ===")
    print(f"A: ρ={float(np.max(np.abs(np.linalg.eigvals(A)))):.4f}")
    print(f"σ={sigma.round(4).tolist()}  ρ_rec={RHO_RECOVERY.tolist()}  α={ALPHA}  β_NEVA={BETA_NEVA}")

    t0 = time.time()
    results = []
    for idx, sc in enumerate(scenarios):
        r = run_mc(sc, cfg, N_RUNS)
        # add bootstrap CI for K_cl and K_q per operator
        for op in ("sde", "iim", "neva"):
            for key in ("I_cl", "I_q"):
                lo, hi = bootstrap_ci(r["raw"][op][key])
                r["per_operator"][op][f"{key}_ci95"] = [lo, hi]
        # strip raw to save space
        r.pop("raw")
        results.append(r)
        elapsed = time.time() - t0
        print(f"[{idx+1:2d}/{len(scenarios)}] {sc.id:30s} "
              f"SDE K_cl={r['per_operator']['sde']['K_cl']:.3f} K_q={r['per_operator']['sde']['K_q']:.3f} | "
              f"IIM K_cl={r['per_operator']['iim']['K_cl']:.3f} K_q={r['per_operator']['iim']['K_q']:.3f} | "
              f"NEVA K_cl={r['per_operator']['neva']['K_cl']:.3f} K_q={r['per_operator']['neva']['K_q']:.3f} "
              f"[{elapsed:.1f}s]")

    return {
        "config": {
            "A_source": str(A_JSON.relative_to(ROOT)),
            "A_matrix": A.tolist(),
            "sigma": sigma.tolist(),
            "rho_recovery": RHO_RECOVERY.tolist(),
            "C": C_DEFAULT.tolist(),
            "delta": DELTA, "dt": DT, "T_steps": T_STEPS,
            "alpha": ALPHA, "neva_beta": BETA_NEVA,
            "n_runs_per_scenario": N_RUNS,
            "x0_base": X0_BASE.tolist(),
            "sectors": list(SECTORS),
            "severities": SEVERITIES,
        },
        "scenarios": results,
    }


def run_loo_experiment() -> dict:
    """
    LOO-robustness: один primary сценарий (energy, sev=0.75) × 4 LOO-матрицы + full.
    Проверяет, насколько чувствителен MC-результат к выбору исключённого события.
    """
    sigma = load_sigma()
    with LOO_JSON.open() as f:
        loo = json.load(f)

    primary = Scenario(
        id="S_energy_sev075_LOO",
        initiator=0,
        severity=0.75,
        x0=X0_BASE.copy(),
        description="Primary LOO probe: energy shock 0.75, x0=.3",
    )

    print(f"\n=== Stage 4 LOO: primary S_energy_sev075 × {len(loo['loo']) + 1} matrices × 3 ops × {N_RUNS} runs ===")

    out = {}
    cases = {"full": loo["full_data"]}
    cases.update(loo["loo"])

    for label, case in cases.items():
        A = np.array(case["matrix_capped"])
        cfg = MCConfig(
            A=A, sigma=sigma, rho=RHO_RECOVERY, C=C_DEFAULT,
            delta=DELTA, dt=DT, T_steps=T_STEPS, alpha=ALPHA,
            neva_beta=BETA_NEVA, operator_noise_scale=1.0,
        )
        r = run_mc(primary, cfg, N_RUNS)
        for op in ("sde", "iim", "neva"):
            for key in ("I_cl", "I_q"):
                lo, hi = bootstrap_ci(r["raw"][op][key])
                r["per_operator"][op][f"{key}_ci95"] = [lo, hi]
        r.pop("raw")
        out[label] = {
            "matrix": A.tolist(),
            "rho": float(np.max(np.abs(np.linalg.eigvals(A)))),
            "per_operator": r["per_operator"],
        }
        print(f"  held_out={label:<15s} "
              f"SDE K_cl={r['per_operator']['sde']['K_cl']:.3f} K_q={r['per_operator']['sde']['K_q']:.3f} | "
              f"IIM K_cl={r['per_operator']['iim']['K_cl']:.3f} K_q={r['per_operator']['iim']['K_q']:.3f} | "
              f"NEVA K_cl={r['per_operator']['neva']['K_cl']:.3f} K_q={r['per_operator']['neva']['K_q']:.3f}")

    return {
        "primary_scenario": {
            "id": primary.id,
            "initiator": int(primary.initiator),
            "severity": primary.severity,
            "x0": primary.x0.tolist(),
        },
        "n_runs": N_RUNS,
        "cases": out,
    }


def main() -> None:
    main_res = run_main_experiment()
    OUT_MAIN.parent.mkdir(parents=True, exist_ok=True)
    with OUT_MAIN.open("w") as f:
        json.dump(main_res, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {OUT_MAIN.relative_to(ROOT)}")

    loo_res = run_loo_experiment()
    with OUT_LOO.open("w") as f:
        json.dump(loo_res, f, indent=2, ensure_ascii=False)
    print(f"Wrote {OUT_LOO.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
