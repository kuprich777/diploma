"""Dry-run Серии 1 на S_4 (water partial degradation), N_runs=1000, 4 оператора.

Цель: получить фактические значения K_cl, K_DR, K_Leontief, K_q на текущей
калибровке (A_WIOD_v4 DEU, C_j из §8.1, σ_j v2 single-representative).

Сценарий S_4 (предварительное толкование Каталога §9.1): частичная деградация
водоснабжения — initiator = water, u_water = +0.30 на t=0 (partial degradation,
ниже порога C_water=0.646).

Это ДИАГНОСТИКА, не полная Серия 1. Используется для проверки
«различимы ли операторы на текущей калибровке» перед принятием решений.
"""
from __future__ import annotations

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
A_path = REPO_ROOT / "data" / "calibration" / "A_WIOD_v4.json"
C_path = REPO_ROOT / "data" / "calibration" / "capacity_thresholds.json"
SIGMA_path = REPO_ROOT / "data" / "calibration" / "sigma_calibrated_v2.json"
W_path = REPO_ROOT / "data" / "calibration" / "sector_weights_v1.json"

A = np.array(json.loads(A_path.read_text())["A_WIOD_v4"])
cap = json.loads(C_path.read_text())
C = np.array([cap["sectors"][s]["C"] for s in ("energy", "water", "transport")])
sigma_j = json.loads(SIGMA_path.read_text())["sectors"]
sigma = np.array([
    sigma_j["energy"]["sigma_dim"],
    sigma_j["water"]["sigma_dim"],
    sigma_j["transport"]["sigma_dim"],
])
w = np.array(json.loads(W_path.read_text())["weights"])

print(f"A_WIOD_v4 = {A.tolist()}")
print(f"ρ(A) = {np.max(np.abs(np.linalg.eigvals(A))):.4f}")
print(f"C = {C.tolist()}")
print(f"σ = {sigma.tolist()}")
print(f"w = {w.tolist()}")

# --- S_4: water partial degradation ---
# Initial x: choose normal-mode baseline where x < C (no pre-existing overload).
# Per §2.1, x ∈ [0,1] is degradation score; baseline — «healthy»-ish.
# Convention для 3 секторов (пред./Ctx): x_0 = [0.30, 0.30, 0.30] (no sector overloaded yet).
x0 = np.array([0.30, 0.30, 0.30])
# S_4: water initiator, partial degradation.
# «Partial» — величина, не выводящая напрямую за C_water=0.646 (иначе это не S_4, а S-полный отказ).
# u_water = +0.30 → x_water_post = 0.60 < C_water → тест «слабого шока».
u = np.array([0.0, 0.30, 0.0])
T = 24  # 24 шага по Δt=1ч
dt = 1.0
theta_node = 0.75
epsilon_cl = 0.05
delta = 0.10
N = 1000

print(f"\n--- Scenario S_4: water partial degradation ---")
print(f"x_0 = {x0.tolist()}, u = {u.tolist()} (initiator=water)")
print(f"x_0+u = {(x0+u).tolist()}")
print(f"T = {T}, Δt = {dt}h, θ_node = {theta_node}, ε_cl = {epsilon_cl}, δ = {delta}")
print(f"N_runs = {N}")


def make_input(seed: int | None = None) -> OperatorInput:
    return OperatorInput(
        x0=x0.copy(),
        u=u.copy(),
        A=A.copy(),
        C=C.copy(),
        T=T,
        delta=delta,
        theta_node=theta_node,
        epsilon_cl=epsilon_cl,
        sigma=sigma.copy(),
        alpha=0.0,
        dt=dt,
        seed=seed,
    )


# --- Deterministic operators (Leontief, cl, DR) — single run each ---
print("\n--- Deterministic operators (N=1) ---")
res_leo = compute_K_leontief(make_input())
print(f"K_Leontief: I={res_leo.I}  x_final={np.round(res_leo.x_final, 4).tolist()}")

res_cl = compute_K_cl(make_input())
print(f"K_cl:       I={res_cl.I}  x_final={np.round(res_cl.x_final, 4).tolist()}  (ε_cl zeroes weak edges)")

res_dr = compute_K_DR(make_input())
print(f"K_DR:       I={res_dr.I}  x_final={np.round(res_dr.x_final, 4).tolist()}  s_final={res_dr.s_final.tolist()}")

# --- Stochastic operators (K_q_deg, K_q_abs) — N_runs ---
print("\n--- Stochastic operators (N=1000) ---")

for op_name, op_fn in (("K_q_deg", compute_K_q_deg), ("K_q_abs", compute_K_q_abs)):
    I_vals = np.zeros(N, dtype=int)
    x_finals = np.zeros((N, 3))
    max_deltas = np.zeros((N, 3))
    for r in range(N):
        inp = make_input(seed=r)
        res = op_fn(inp)
        I_vals[r] = res.I
        x_finals[r] = res.x_final
        md = np.array(res.metadata.get("max_delta", [0, 0, 0]))
        max_deltas[r] = md

    K = float(I_vals.mean())
    D = float((x_finals * w).sum(axis=1).mean())
    mean_dx = max_deltas.mean(axis=0)
    print(
        f"{op_name}: K={K:.4f}  D={D:.4f}  mean_max_δ_per_sector={np.round(mean_dx,4).tolist()}"
    )

# D for deterministic (for completeness)
D_leo = float((res_leo.x_final * w).sum())
D_cl = float((res_cl.x_final * w).sum())
D_dr = float((res_dr.x_final * w).sum())
print(f"\nDeterministic D:  K_Leontief={D_leo:.4f}  K_cl={D_cl:.4f}  K_DR={D_dr:.4f}")
