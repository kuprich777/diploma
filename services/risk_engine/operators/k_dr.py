"""K_DR — канонический DebtRank со state memory. METHODOLOGY §3.3, §12.2.

Формула обновления (§3.3):
    h_i(t+1) = h_i(t),                                                  if s_i(t) = F
             = min{1, h_i(t) + Σ_{j: s_j(t)=O} a_{ij} h_j(t)},          otherwise.

State machine — §2.3 (единственный источник истины, state_machine.update_state).

Инициализация (§3.3):
    h(0) = x_0 + u
    s(0) = update_state(h(0), s_prev=(N,...,N), C)

Правило forced O → F за один шаг — часть state machine (§2.3, правило 2).

Индикатор каскада:
    I^(DR) = 1{∃ i ≠ i_0 : h_i(T) - h_i(0) ≥ δ}

Замечание: "h(0)" в индикаторе — это x_0 (pre-shock baseline), чтобы шок не
засчитывался автоматически как «каскад». См. K_Leontief для аналогичной логики.
"""
from __future__ import annotations

import numpy as np

from services.risk_engine.contract import OperatorInput, OperatorResult
from services.risk_engine.state_machine import (
    STATE_F,
    STATE_O,
    init_state,
    update_state,
)


def compute_K_DR(inp: OperatorInput) -> OperatorResult:
    n = inp.n
    A = inp.A
    C = inp.C

    if inp.u.ndim == 1:
        u_total = inp.u
    else:
        u_total = inp.u[: inp.T].sum(axis=0)

    h = np.clip(inp.x0 + u_total, 0.0, 1.0)
    s = update_state(h, init_state(n), C)

    traj = [h.copy()]
    for _ in range(inp.T):
        h_new = h.copy()
        for i in range(n):
            if s[i] == STATE_F:
                h_new[i] = h[i]
                continue
            contribution_i = 0.0
            for j in range(n):
                if s[j] == STATE_O:
                    contribution_i += A[i, j] * h[j]
            h_new[i] = min(1.0, h[i] + contribution_i)
        h = h_new
        s = update_state(h, s, C)
        traj.append(h.copy())

    i0 = inp.initiator_index()
    delta_h = h - inp.x0
    cascade = any(delta_h[i] >= inp.delta for i in range(n) if i != i0)

    return OperatorResult(
        x_final=h,
        I=int(cascade),
        trajectory=np.array(traj, dtype=float),
        s_final=s,
        metadata={
            "operator_name": "K_DR",
            "initiator": int(i0),
        },
    )
