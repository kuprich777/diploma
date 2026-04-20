"""K_cl — итеративный бинарный оператор. METHODOLOGY §3.2.

Thresholding матрицы:  ã_ij = a_ij · 1[a_ij ≥ ε_cl],  ε_cl = 0.05.
Бинаризация:            y_i,t = 1[x_i,t ≥ θ_node].
Инициализация:          y(0) = 1[x_0 + u ≥ θ_node]  (post-shock).
Распространение:        y_i,t+1 = y_i,t ∨ (∃ j ≠ i : y_j,t = 1 ∧ ã_ij > 0).
Индикатор каскада:      I^(cl) = 1{∃ i ≠ i_0, t ≤ T : y_i,t = 1}.

Contingency rule для θ_node (§8.5) применяется внешним раннером до вызова
оператора — здесь θ_node считается окончательным.
"""
from __future__ import annotations

import numpy as np

from services.risk_engine.contract import OperatorInput, OperatorResult


def compute_K_cl(inp: OperatorInput) -> OperatorResult:
    n = inp.n
    theta = inp.theta_node
    eps = inp.epsilon_cl

    # Thresholded ã (§3.2). Диагональ уже 0 по §7.1.
    A_tilde = np.where(inp.A >= eps, inp.A, 0.0)

    # Сумма всех шоков на горизонте (интерпретация post-shock state).
    if inp.u.ndim == 1:
        u_total = inp.u
    else:
        u_total = inp.u[: inp.T].sum(axis=0)

    x_post_shock = np.clip(inp.x0 + u_total, 0.0, 1.0)
    y = (x_post_shock >= theta).astype(int)

    i0 = inp.initiator_index()
    cascade_detected = any(y[i] == 1 for i in range(n) if i != i0)

    trajectory_y = [y.copy()]
    for t in range(inp.T):
        y_new = y.copy()
        for i in range(n):
            if y[i] == 1:
                continue
            for j in range(n):
                if j == i:
                    continue
                if y[j] == 1 and A_tilde[i][j] > 0.0:
                    y_new[i] = 1
                    break
        y = y_new
        trajectory_y.append(y.copy())
        if not cascade_detected:
            cascade_detected = any(y[i] == 1 for i in range(n) if i != i0)

    x_final = y.astype(float)

    return OperatorResult(
        x_final=x_final,
        I=int(cascade_detected),
        trajectory=np.array(trajectory_y, dtype=float),
        s_final=None,
        metadata={
            "operator_name": "K_cl",
            "theta_node": float(theta),
            "epsilon_cl": float(eps),
            "initiator": int(i0),
        },
    )
