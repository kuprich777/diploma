"""
Этап 3 — Сравнение трёх каскадных операторов на синтетическом шоке.

Даёт таблицу: Classical vs IIM vs NEVA(β=1) vs NEVA(β=2) на A_empirical_bayesian_v1.
Выход: results/stage3_operator_comparison.json + printed table
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from services.risk_engine.cascade_operators import (
    ClassicalOperator,
    IIMOperator,
    NevaOperator,
    classical_indicator,
    quantitative_indicator,
)

ROOT = Path(__file__).resolve().parent.parent
A_JSON = ROOT / "data/calibration/A_empirical_bayesian_v1.json"
OUT_JSON = ROOT / "results/stage3_operator_comparison.json"

SECTORS = ("energy", "water", "transport")
C_DEFAULT = np.array([0.75, 0.75, 0.75])
DELTA = 0.10
N_STEPS = 50


def load_matrix() -> np.ndarray:
    with A_JSON.open() as f:
        d = json.load(f)
    return np.array(d["matrix_posterior_mean_spectral_capped"])


def run_scenarios(A: np.ndarray) -> dict:
    scenarios = {
        "S_energy_mild": np.array([0.30, 0.10, 0.10]),
        "S_energy_severe": np.array([0.70, 0.10, 0.10]),
        "S_transport_mild": np.array([0.10, 0.10, 0.30]),
        "S_transport_severe": np.array([0.10, 0.10, 0.70]),
        "S_water_mild": np.array([0.10, 0.30, 0.10]),
    }
    operators = {
        "classical": lambda x0: ClassicalOperator(A).run(x0, N_STEPS),
        "iim": lambda x0: IIMOperator(A, lambda t: x0 if t == 0 else np.zeros(3)).run(
            np.zeros(3), N_STEPS
        ),
        "neva_beta1": lambda x0: NevaOperator(A, beta=1.0).run(x0, N_STEPS),
        "neva_beta2": lambda x0: NevaOperator(A, beta=2.0).run(x0, N_STEPS),
    }

    results = {}
    for s_name, x0 in scenarios.items():
        initiator = int(np.argmax(x0))
        per_op = {}
        for op_name, op_fn in operators.items():
            r = op_fn(x0)
            per_op[op_name] = {
                "final_state": r.final_state.tolist(),
                "max_delta_off_initiator": float(
                    np.max(
                        [
                            r.trajectory[:, j].max() - r.trajectory[0, j]
                            for j in range(3) if j != initiator
                        ]
                    )
                ),
                "I_cl": classical_indicator(r.trajectory, C_DEFAULT, initiator),
                "I_q": quantitative_indicator(r.trajectory, DELTA, initiator),
                "converged": bool(r.converged),
                "n_steps_to_convergence": int(r.n_steps_to_convergence),
            }
        results[s_name] = {
            "initiator": SECTORS[initiator],
            "x0": x0.tolist(),
            "operators": per_op,
        }
    return results


def format_table(results: dict) -> str:
    lines = []
    header = f"{'Scenario':<25s} {'Op':<12s} {'I_cl':>5s} {'I_q':>5s} {'maxΔ':>7s} {'water':>7s} {'transport':>9s} {'energy':>7s} {'conv@':>5s}"
    lines.append(header)
    lines.append("-" * len(header))
    for s_name, sdata in results.items():
        for op_name, o in sdata["operators"].items():
            fs = o["final_state"]
            lines.append(
                f"{s_name:<25s} {op_name:<12s} {o['I_cl']:>5d} {o['I_q']:>5d} "
                f"{o['max_delta_off_initiator']:>7.3f} "
                f"{fs[1]:>7.3f} {fs[2]:>9.3f} {fs[0]:>7.3f} "
                f"{o['n_steps_to_convergence']:>5d}"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    A = load_matrix()
    print(f"A_empirical_bayesian_v1 (capped, ρ=0.95):")
    for i, s in enumerate(SECTORS):
        print(f"  {s:10s} {A[i].round(4).tolist()}")
    print(f"\nSpectral radius: {float(np.max(np.abs(np.linalg.eigvals(A)))):.4f}")
    print(f"\n=== Running scenarios ===\n")

    results = run_scenarios(A)
    table = format_table(results)
    print(table)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "matrix": A.tolist(),
        "capacity_C": C_DEFAULT.tolist(),
        "delta": DELTA,
        "n_steps": N_STEPS,
        "sectors": list(SECTORS),
        "scenarios": results,
    }
    with OUT_JSON.open("w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {OUT_JSON.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
