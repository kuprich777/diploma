"""K_Leontief — статический линейный оператор. METHODOLOGY §3.1, §12.1.

x_∞ = (I - A)^{-1} (x_0 + u)

Условие сходимости: ρ(A) < 1.
"""
from __future__ import annotations

import numpy as np

from services.risk_engine.contract import OperatorInput, OperatorResult


def compute_K_leontief(inp: OperatorInput) -> OperatorResult:
    """K_Leontief per §3.1 / §12.1.

    Детерминированный, N_runs = 1. Использует только u на шоке t=0.
    Для пошагового u — суммирует по горизонту T (интерпретация: total impulse).
    """
    n = inp.n
    A = inp.A
    if not np.allclose(np.diag(A), 0.0):
        raise ValueError("diag(A) must be zero (§7.1)")
    rho = np.max(np.abs(np.linalg.eigvals(A)))
    if rho >= 1.0:
        raise ValueError(f"ρ(A) must be < 1 (§7.3), got {rho:.4f}")

    # Total impulse: сумма всех u_t на горизонте T
    if inp.u.ndim == 1:
        u_total = inp.u
    else:
        u_total = inp.u[: inp.T].sum(axis=0)

    I_n = np.eye(n)
    x_inf = np.linalg.solve(I_n - A, inp.x0 + u_total)
    x_final = np.clip(x_inf, 0.0, 1.0)

    i0 = inp.initiator_index()
    delta_x = x_final - inp.x0
    cascade = any(
        delta_x[i] >= inp.delta for i in range(n) if i != i0
    )
    return OperatorResult(
        x_final=x_final,
        I=int(cascade),
        trajectory=None,
        s_final=None,
        metadata={
            "operator_name": "K_Leontief",
            "rho_A": float(rho),
            "initiator": int(i0),
        },
    )
