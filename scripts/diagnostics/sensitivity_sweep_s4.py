"""Sensitivity sweep на S_4 (water partial degradation).

Декартово произведение 45 = 5×3×3 конфигураций:
    rho_target_floor ∈ {None, 0.30, 0.50, 0.70, 0.95}
    epsilon_cl        ∈ {0.001, 0.01, 0.05}   (0.05 pre-registered)
    delta             ∈ {0.05, 0.10, 0.20}    (0.10 pre-registered)

rho_target_floor=None → A_WIOD_v4 без дополнительного масштабирования
                       (ρ(A)=0.022 — текущая калибровка).
rho_target_floor=φ   → если ρ(A) < φ, A ← A·(φ/ρ(A)); иначе без изменений.

Сценарий S_4: water partial degradation, u=[0, 0.30, 0], x0=[0.30, 0.30, 0.30],
T=24, Δt=1ч, θ_node=0.75, σ — из sigma_calibrated_v2.json (arithmetic Δx).

Для каждой конфигурации:
  - Детерминированные K_Leontief, K_cl, K_DR — один прогон
  - Стохастические K_q_deg, K_q_abs — N_runs=1000, seeds 0..999
  - Сохраняем K (доля каскадов), D (weighted final degradation),
    10 попарных |ΔK|, is_marginal (K∈(0,1) хотя бы для одного оператора).

ВЫХОДЫ:
    results/sensitivity/sweep_s4_raw.json     — 45 конфигов со всеми метриками
    results/sensitivity/sweep_s4_summary.csv  — табличная сводка
    results/sensitivity/sweep_s4_report.md    — аналитика, топы, heatmap reference
    results/sensitivity/sweep_s4_heatmap.png  — rho_floor × eps_cl, max|ΔK|
"""
from __future__ import annotations

import csv
import itertools
import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from services.risk_engine.contract import OperatorInput
from services.risk_engine.operators import (
    compute_K_cl,
    compute_K_DR,
    compute_K_leontief,
    compute_K_q_abs,
    compute_K_q_deg,
)

# --- Load artefacts ---
A_PATH = REPO_ROOT / "data" / "calibration" / "A_WIOD_v4.json"
C_PATH = REPO_ROOT / "data" / "calibration" / "capacity_thresholds.json"
SIGMA_PATH = REPO_ROOT / "data" / "calibration" / "sigma_calibrated_v2.json"
W_PATH = REPO_ROOT / "data" / "calibration" / "sector_weights_v1.json"

OUT_DIR = REPO_ROOT / "results" / "sensitivity"
OUT_DIR.mkdir(parents=True, exist_ok=True)
RAW_OUT = OUT_DIR / "sweep_s4_raw.json"
CSV_OUT = OUT_DIR / "sweep_s4_summary.csv"
REPORT_OUT = OUT_DIR / "sweep_s4_report.md"
HEATMAP_OUT = OUT_DIR / "sweep_s4_heatmap.png"

# --- Scenario S_4 constants ---
X0 = np.array([0.30, 0.30, 0.30])
U = np.array([0.0, 0.30, 0.0])         # water initiator, partial degradation
T_STEPS = 24
DT = 1.0
THETA_NODE = 0.75
N_RUNS = 1000
SECTORS = ("energy", "water", "transport")

# --- Sweep grid ---
RHO_FLOORS: list[float | None] = [None, 0.30, 0.50, 0.70, 0.95]
EPS_CLS: list[float] = [0.001, 0.01, 0.05]
DELTAS: list[float] = [0.05, 0.10, 0.20]

OPS = ["K_leontief", "K_cl", "K_DR", "K_q_deg", "K_q_abs"]


def load_artefacts() -> dict:
    A = np.array(json.loads(A_PATH.read_text())["A_WIOD_v4"])
    cap = json.loads(C_PATH.read_text())
    C = np.array([cap["sectors"][s]["C"] for s in SECTORS])
    sig = json.loads(SIGMA_PATH.read_text())["sectors"]
    sigma = np.array([
        sig["energy"].get("sigma_x_per_sqrt_hour", sig["energy"].get("sigma_dim")),
        sig["water"].get("sigma_x_per_sqrt_hour", sig["water"].get("sigma_dim")),
        sig["transport"].get("sigma_x_per_sqrt_hour", sig["transport"].get("sigma_dim")),
    ])
    w = np.array(json.loads(W_PATH.read_text())["weights"])
    return {"A": A, "C": C, "sigma": sigma, "w": w}


def apply_rho_floor(A: np.ndarray, floor: float | None) -> tuple[np.ndarray, float, float, bool]:
    """Возвращает (A_eff, rho_orig, rho_eff, scaled)."""
    rho_orig = float(np.max(np.abs(np.linalg.eigvals(A))))
    if floor is None or rho_orig >= floor:
        return A.copy(), rho_orig, rho_orig, False
    A_scaled = A * (floor / rho_orig)
    rho_eff = float(np.max(np.abs(np.linalg.eigvals(A_scaled))))
    return A_scaled, rho_orig, rho_eff, True


def make_input(
    A: np.ndarray, C: np.ndarray, sigma: np.ndarray,
    epsilon_cl: float, delta: float, seed: int | None = None,
) -> OperatorInput:
    return OperatorInput(
        x0=X0.copy(),
        u=U.copy(),
        A=A.copy(),
        C=C.copy(),
        T=T_STEPS,
        delta=delta,
        theta_node=THETA_NODE,
        epsilon_cl=epsilon_cl,
        sigma=sigma.copy(),
        alpha=0.0,
        dt=DT,
        seed=seed,
    )


def run_config(
    A_eff: np.ndarray, C: np.ndarray, sigma: np.ndarray, w: np.ndarray,
    eps_cl: float, delta: float,
) -> dict:
    """Запускает 5 операторов на одной конфигурации."""
    out: dict[str, dict] = {}

    # Deterministic (N=1)
    for name, fn in (
        ("K_leontief", compute_K_leontief),
        ("K_cl", compute_K_cl),
        ("K_DR", compute_K_DR),
    ):
        res = fn(make_input(A_eff, C, sigma, eps_cl, delta))
        D = float((res.x_final * w).sum())
        out[name] = {
            "K": int(res.I),
            "D": round(D, 6),
            "x_final": [round(float(v), 6) for v in res.x_final],
        }

    # Stochastic (N=1000)
    for name, fn in (("K_q_deg", compute_K_q_deg), ("K_q_abs", compute_K_q_abs)):
        I_vals = np.zeros(N_RUNS, dtype=int)
        D_vals = np.zeros(N_RUNS)
        for r in range(N_RUNS):
            res = fn(make_input(A_eff, C, sigma, eps_cl, delta, seed=r))
            I_vals[r] = int(res.I)
            D_vals[r] = float((res.x_final * w).sum())
        out[name] = {
            "K": float(I_vals.mean()),
            "D": float(D_vals.mean()),
            "D_std": float(D_vals.std(ddof=1)) if N_RUNS > 1 else 0.0,
        }
    return out


def pairwise_deltas(ops_res: dict) -> dict:
    """10 попарных |K_a - K_b| (из 5 операторов)."""
    pairs = list(itertools.combinations(OPS, 2))
    out = {}
    for a, b in pairs:
        key = f"{a}_vs_{b}"
        out[key] = round(abs(ops_res[a]["K"] - ops_res[b]["K"]), 6)
    return out


def main() -> None:
    art = load_artefacts()
    A, C, sigma, w = art["A"], art["C"], art["sigma"], art["w"]
    rho0 = float(np.max(np.abs(np.linalg.eigvals(A))))
    print(f"[load] A shape={A.shape}, ρ(A)={rho0:.4f}, max|a_ij|={np.max(np.abs(A)):.4f}")
    print(f"[load] C = {C.tolist()}")
    print(f"[load] σ = {sigma.tolist()}  (arithmetic Δx in x-space)")
    print(f"[load] w = {w.tolist()}")
    n_configs = len(RHO_FLOORS) * len(EPS_CLS) * len(DELTAS)
    print(f"\n[sweep] 45 configs = {len(RHO_FLOORS)}×{len(EPS_CLS)}×{len(DELTAS)}")

    results: list[dict] = []
    for i, (rho_floor, eps_cl, delta) in enumerate(itertools.product(RHO_FLOORS, EPS_CLS, DELTAS)):
        A_eff, rho_orig, rho_eff, scaled = apply_rho_floor(A, rho_floor)
        max_a = float(np.max(np.abs(A_eff)))
        rho_label = "None" if rho_floor is None else f"{rho_floor:.2f}"
        print(
            f"  [{i+1:>2d}/{n_configs}] rho_floor={rho_label:>5s}  "
            f"eps_cl={eps_cl:.3f}  delta={delta:.2f}  "
            f"ρ_eff={rho_eff:.4f}  max|a|={max_a:.4f}",
            flush=True,
        )
        ops_res = run_config(A_eff, C, sigma, w, eps_cl, delta)
        pw = pairwise_deltas(ops_res)
        Ks = [ops_res[o]["K"] for o in OPS]
        max_pair_dK = max(pw.values())
        # marginal = хотя бы один оператор имеет K ∈ (0.05, 0.95)
        is_marginal = any(0.05 < k < 0.95 for k in Ks)
        # working region: все K ∈ (0,1) строго AND max pairwise |ΔK| >= 0.1
        all_interior = all(0.0 < k < 1.0 for k in Ks)
        working = bool(all_interior and max_pair_dK >= 0.1)
        entry = {
            "config": {
                "rho_floor": rho_floor,
                "epsilon_cl": eps_cl,
                "delta": delta,
            },
            "A_info": {
                "rho_original": round(rho_orig, 6),
                "rho_effective": round(rho_eff, 6),
                "scaled": scaled,
                "max_abs_a": round(max_a, 6),
            },
            "operators": ops_res,
            "pairwise_dK": pw,
            "max_pairwise_dK": round(max_pair_dK, 6),
            "is_marginal": is_marginal,
            "is_working_region": working,
        }
        results.append(entry)
        # Краткий print результата строки
        K_str = "  ".join(f"{o.split('K_')[1]}:{ops_res[o]['K']:.3f}" for o in OPS)
        print(f"       Ks: {K_str}  max|ΔK|={max_pair_dK:.3f}  marg={is_marginal}  work={working}")

    # --- Save raw ---
    payload = {
        "scenario": {
            "name": "S_4_water_partial_degradation",
            "x0": X0.tolist(),
            "u": U.tolist(),
            "T": T_STEPS,
            "dt": DT,
            "theta_node": THETA_NODE,
            "N_runs_stochastic": N_RUNS,
        },
        "sigma_used": sigma.tolist(),
        "C_used": C.tolist(),
        "w_used": w.tolist(),
        "grid": {
            "rho_target_floor": ["None" if v is None else v for v in RHO_FLOORS],
            "epsilon_cl": EPS_CLS,
            "delta": DELTAS,
        },
        "n_configs": len(results),
        "results": results,
    }
    RAW_OUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"\n[save] {RAW_OUT}")

    # --- Save CSV ---
    with CSV_OUT.open("w", newline="") as f:
        cols = (
            ["rho_floor", "epsilon_cl", "delta", "rho_eff", "max_abs_a"]
            + [f"K_{o.split('K_')[1]}" for o in OPS]
            + [f"D_{o.split('K_')[1]}" for o in OPS]
            + ["max_pair_dK", "is_marginal", "is_working"]
        )
        wr = csv.writer(f)
        wr.writerow(cols)
        for e in results:
            row = [
                "None" if e["config"]["rho_floor"] is None else e["config"]["rho_floor"],
                e["config"]["epsilon_cl"],
                e["config"]["delta"],
                e["A_info"]["rho_effective"],
                e["A_info"]["max_abs_a"],
            ]
            row += [e["operators"][o]["K"] for o in OPS]
            row += [e["operators"][o]["D"] for o in OPS]
            row += [e["max_pairwise_dK"], e["is_marginal"], e["is_working_region"]]
            wr.writerow(row)
    print(f"[save] {CSV_OUT}")

    # --- Analysis ---
    print("\n" + "=" * 70)
    print("АНАЛИЗ")
    print("=" * 70)

    # Top-10 by max pairwise |ΔK|
    sorted_by_dK = sorted(results, key=lambda e: -e["max_pairwise_dK"])
    print("\nТоп-10 конфигураций по max попарному |ΔK|:")
    print(f"{'rank':>4}  {'rho_fl':>7}  {'eps_cl':>7}  {'delta':>6}  "
          f"{'max_|ΔK|':>8}  worst_pair")
    for rank, e in enumerate(sorted_by_dK[:10], 1):
        best_pair = max(e["pairwise_dK"].items(), key=lambda kv: kv[1])
        rho_s = "None" if e["config"]["rho_floor"] is None else f"{e['config']['rho_floor']:.2f}"
        print(
            f"{rank:>4}  {rho_s:>7}  {e['config']['epsilon_cl']:>7.3f}  "
            f"{e['config']['delta']:>6.2f}  {e['max_pairwise_dK']:>8.3f}  "
            f"{best_pair[0]} ({best_pair[1]:.3f})"
        )

    working_configs = [e for e in results if e["is_working_region"]]
    marginal_configs = [e for e in results if e["is_marginal"]]
    print(f"\nРабочих конфигураций (all K∈(0,1), max|ΔK|≥0.1): {len(working_configs)}/{len(results)}")
    print(f"Маргинальных (есть K∈(0.05, 0.95)): {len(marginal_configs)}/{len(results)}")

    # --- Heatmap: rho_floor × eps_cl, max over delta ---
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        rho_labels = ["None" if v is None else f"{v:.2f}" for v in RHO_FLOORS]
        eps_labels = [f"{e:.3f}" for e in EPS_CLS]
        grid = np.zeros((len(RHO_FLOORS), len(EPS_CLS)))
        for i_rho, rho in enumerate(RHO_FLOORS):
            for j_eps, eps in enumerate(EPS_CLS):
                dKs = [
                    e["max_pairwise_dK"] for e in results
                    if e["config"]["rho_floor"] == rho and e["config"]["epsilon_cl"] == eps
                ]
                grid[i_rho, j_eps] = max(dKs) if dKs else 0.0

        fig, ax = plt.subplots(figsize=(7, 5))
        im = ax.imshow(grid, cmap="viridis", aspect="auto", vmin=0, vmax=1)
        ax.set_xticks(range(len(eps_labels)))
        ax.set_xticklabels(eps_labels)
        ax.set_yticks(range(len(rho_labels)))
        ax.set_yticklabels(rho_labels)
        ax.set_xlabel("epsilon_cl")
        ax.set_ylabel("rho_target_floor")
        ax.set_title("S_4 sweep: max pairwise |ΔK| over delta")
        for i in range(grid.shape[0]):
            for j in range(grid.shape[1]):
                ax.text(j, i, f"{grid[i, j]:.2f}", ha="center", va="center",
                        color="white" if grid[i, j] < 0.5 else "black", fontsize=9)
        fig.colorbar(im, ax=ax, label="max |K_a - K_b|")
        fig.tight_layout()
        fig.savefig(HEATMAP_OUT, dpi=120)
        plt.close(fig)
        print(f"[save] {HEATMAP_OUT}")
    except Exception as e:
        print(f"[warn] heatmap failed: {e}")

    # --- Report markdown ---
    lines = []
    lines.append("# Sensitivity sweep S_4 — отчёт\n")
    lines.append("**Сценарий:** S_4 water partial degradation, u=[0, 0.30, 0], "
                 f"x0={X0.tolist()}, T={T_STEPS}, Δt={DT}, θ_node={THETA_NODE}.\n")
    lines.append(f"**σ (arithmetic Δx, x-space):** energy={sigma[0]:.4f}, "
                 f"water={sigma[1]:.4f}, transport={sigma[2]:.4f}.\n")
    lines.append(f"**N_runs (стохастика):** {N_RUNS}. Фиксированный seed list 0..{N_RUNS-1}.\n")
    lines.append(f"**Базовая матрица A:** A_WIOD_v4 DEU, ρ(A)={rho0:.4f}, "
                 f"max|a_ij|={np.max(np.abs(A)):.4f}.\n\n")

    lines.append("## 1. Методология sweep\n")
    lines.append("Декартово произведение 45 = 5 × 3 × 3:\n")
    lines.append("- `rho_target_floor` ∈ {None, 0.30, 0.50, 0.70, 0.95} — "
                 "None=без доп. масштабирования; "
                 "число φ = если ρ(A) < φ, то A ← A·(φ/ρ(A)) (ceiling-or-floor).\n")
    lines.append("- `epsilon_cl` ∈ {0.001, 0.01, 0.05} (0.05 pre-registered §0.4).\n")
    lines.append("- `delta` ∈ {0.05, 0.10, 0.20} (0.10 pre-registered §0.4).\n\n")
    lines.append("На каждой конфигурации запускаются 5 операторов "
                 "(K_Leontief, K_cl, K_DR, K_q_deg, K_q_abs). "
                 "Вычисляются 10 попарных |K_a − K_b|, margin (K ∈ (0.05, 0.95) для ≥1 оператора), "
                 "working region (все K ∈ (0,1) AND max|ΔK| ≥ 0.1).\n\n")

    lines.append("## 2. Сводная статистика\n")
    lines.append(f"- Всего конфигов: **{len(results)}**\n")
    lines.append(f"- Working region (все K∈(0,1) ∧ max|ΔK|≥0.1): "
                 f"**{len(working_configs)}/{len(results)}**\n")
    lines.append(f"- Маргинальные (есть K∈(0.05, 0.95)): "
                 f"**{len(marginal_configs)}/{len(results)}**\n\n")

    lines.append("## 3. Топ-10 конфигураций по max попарному |ΔK|\n")
    lines.append("| rank | rho_floor | eps_cl | delta | max\\|ΔK\\| | best pair | rho_eff | max\\|a\\| |\n")
    lines.append("|---:|:---:|:---:|:---:|---:|:---|---:|---:|\n")
    for rank, e in enumerate(sorted_by_dK[:10], 1):
        best_pair = max(e["pairwise_dK"].items(), key=lambda kv: kv[1])
        rho_s = "None" if e["config"]["rho_floor"] is None else f"{e['config']['rho_floor']:.2f}"
        lines.append(
            f"| {rank} | {rho_s} | {e['config']['epsilon_cl']:.3f} | "
            f"{e['config']['delta']:.2f} | {e['max_pairwise_dK']:.3f} | "
            f"{best_pair[0]} ({best_pair[1]:.3f}) | "
            f"{e['A_info']['rho_effective']:.3f} | "
            f"{e['A_info']['max_abs_a']:.3f} |\n"
        )
    lines.append("\n")

    if working_configs:
        lines.append("## 4. Working region\n")
        lines.append(f"Конфигураций с all K ∈ (0,1) ∧ max|ΔK| ≥ 0.1: **{len(working_configs)}**\n\n")
        lines.append("| rho_floor | eps_cl | delta | K_Leo | K_cl | K_DR | K_q_deg | K_q_abs | max\\|ΔK\\| |\n")
        lines.append("|:---:|:---:|:---:|---:|---:|---:|---:|---:|---:|\n")
        for e in sorted(working_configs, key=lambda x: -x["max_pairwise_dK"]):
            rho_s = "None" if e["config"]["rho_floor"] is None else f"{e['config']['rho_floor']:.2f}"
            Ks = {o: e["operators"][o]["K"] for o in OPS}
            lines.append(
                f"| {rho_s} | {e['config']['epsilon_cl']:.3f} | "
                f"{e['config']['delta']:.2f} | "
                f"{Ks['K_leontief']} | {Ks['K_cl']} | {Ks['K_DR']} | "
                f"{Ks['K_q_deg']:.3f} | {Ks['K_q_abs']:.3f} | "
                f"{e['max_pairwise_dK']:.3f} |\n"
            )
        lines.append("\n")
    else:
        lines.append("## 4. Working region\n")
        lines.append("🔴 **Пусто.** Ни одна из 45 конфигураций не даёт одновременно "
                     "(а) все K ∈ (0,1) и (б) max попарное |ΔK| ≥ 0.1. "
                     "Методология в текущей калибровке не имеет режима, где 5 операторов "
                     "одновременно различимы.\n\n")

    lines.append("## 5. Heatmap (rho_floor × epsilon_cl)\n")
    lines.append("Цвет ячейки = max попарное |ΔK|, максимум по всем значениям δ для данной пары.\n\n")
    lines.append(f"![heatmap]({HEATMAP_OUT.name})\n\n")

    lines.append("## 6. Интерпретация\n")
    lines.append("_автоматическая сводка; итоговое суждение за автором_:\n\n")
    best = sorted_by_dK[0]
    best_rho = "None" if best["config"]["rho_floor"] is None else f"{best['config']['rho_floor']:.2f}"
    lines.append(f"- Максимум max|ΔK| по всей сетке: **{best['max_pairwise_dK']:.3f}** "
                 f"при rho_floor={best_rho}, eps_cl={best['config']['epsilon_cl']:.3f}, "
                 f"δ={best['config']['delta']:.2f}.\n")
    if best["max_pairwise_dK"] < 0.1:
        lines.append("- Ни одна конфигурация не даёт max|ΔK| ≥ 0.1 — операторы неразличимы "
                     "на уровне бинарной метрики K во всём sweep-диапазоне.\n")
    elif best["max_pairwise_dK"] < 0.25:
        lines.append("- Максимум |ΔK| ∈ [0.1, 0.25): слабая различимость, ConfirmationRate "
                     "(порог 0.25) не достижим ни в одной конфигурации.\n")
    else:
        lines.append(f"- Достижимая максимальная различимость |ΔK|={best['max_pairwise_dK']:.3f} "
                     f"≥ 0.25 — ConfirmationRate-potential присутствует.\n")
    lines.append("- См. `sweep_s4_raw.json` для полных K/D/x_final по каждому оператору "
                 "и `sweep_s4_summary.csv` для выгрузки в Excel.\n\n")
    lines.append("## 7. Решения автора — оставлены открытыми\n")
    lines.append("Sweep НЕ применяет найденных параметров к основной калибровке. "
                 "Pre-registered параметры (θ_node=0.75, ε_cl=0.05, δ=0.10) сохранены. "
                 "Решение о следующем шаге — за автором.\n")

    REPORT_OUT.write_text("".join(lines), encoding="utf-8")
    print(f"[save] {REPORT_OUT}")


if __name__ == "__main__":
    main()
