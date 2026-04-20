"""
cascade_operators.py
====================
Альтернативные каскадные операторы для сравнения с текущим SDE-интегратором.

Реализовано три оператора:

1. ClassicalOperator (baseline, x + A·x)
   x(t+1) = clip_{[0,1]}( x(t) + A · x(t) )
   Совпадает с оператором в services/risk_engine/* при σ=0, ρ=0, dt=1.

2. IIMOperator (Inoperability Input-Output Model, Haimes & Santos 2005)
   q(t+1) = clip_{[0,1]}( A* · q(t) + c*(t) )
   где q — вектор inoperability (q=0 — нормально, q=1 — полный отказ),
   A* — матрица взаимозависимостей (та же, что в нашем A),
   c*(t) — экзогенный шок.
   Ссылка: Haimes Y.Y., Santos J.R. (2005). A risk-based methodology for
           assessing and managing the vulnerability of critical infrastructures
           to terrorism. Systems Engineering, 8(4), 273-291.

3. NevaOperator (non-linear operator, Barucca et al. 2020)
   h_i(t+1) = max(h_i(0) - Σ_j A[i][j] · stress_j(h_j(t)), 0)
   где h ∈ [0,1] — "health" (h = 1-x), stress(h) — нелинейная функция потерь.
   β-параметр контролирует нелинейность:
     stress(h) = 1 - h^β            (для h ∈ [0,1]; β ≥ 1)
   β=1 → линейный DebtRank (Battiston et al. 2012)
   β>1 → концентрация потерь вблизи дефолта (NEVA характерно)
   Ссылка: Barucca P., Bardoscia M., Caccioli F. et al. (2020).
           Network valuation in financial systems. Math. Finance 30(4), 1181-1204.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np


# ---------------------------------------------------------------------------
# Shared base
# ---------------------------------------------------------------------------

@dataclass
class OperatorResult:
    """Результат многошаговой итерации оператора."""
    trajectory: np.ndarray     # shape (T+1, N)
    final_state: np.ndarray    # shape (N,)
    converged: bool
    n_steps_to_convergence: int
    fixed_point: Optional[np.ndarray] = None


def _iterate(
    step_func: Callable[[np.ndarray, int], np.ndarray],
    x0: np.ndarray,
    n_steps: int,
    tol: float = 1e-6,
) -> OperatorResult:
    """Generic fixed-point iteration loop."""
    x = x0.copy()
    trajectory = [x.copy()]
    converged = False
    n_conv = n_steps
    for t in range(n_steps):
        x_next = step_func(x, t)
        trajectory.append(x_next.copy())
        if np.max(np.abs(x_next - x)) < tol:
            converged = True
            n_conv = t + 1
            break
        x = x_next
    return OperatorResult(
        trajectory=np.array(trajectory),
        final_state=trajectory[-1].copy(),
        converged=converged,
        n_steps_to_convergence=n_conv,
    )


# ---------------------------------------------------------------------------
# 1. Classical operator: x + A·x
# ---------------------------------------------------------------------------

class ClassicalOperator:
    """Baseline iterative operator x(t+1) = clip(x(t) + A·x(t))."""

    def __init__(self, A: np.ndarray) -> None:
        self.A = np.asarray(A, dtype=float)
        assert self.A.ndim == 2 and self.A.shape[0] == self.A.shape[1]

    def step(self, x: np.ndarray) -> np.ndarray:
        x_next = x + self.A @ x
        return np.clip(x_next, 0.0, 1.0)

    def run(self, x0: np.ndarray, n_steps: int = 50, tol: float = 1e-6) -> OperatorResult:
        return _iterate(lambda x, _t: self.step(x), x0, n_steps, tol)


# ---------------------------------------------------------------------------
# 2. IIM (Haimes-Santos 2005)
# ---------------------------------------------------------------------------

class IIMOperator:
    """
    q(t+1) = clip(A* · q(t) + c*(t))

    c_star_func возвращает экзогенный perturbation vector на шаг t
    (например, постоянный shock в момент t=0 и ноль далее).
    """

    def __init__(self, A_star: np.ndarray, c_star_func: Callable[[int], np.ndarray]) -> None:
        self.A_star = np.asarray(A_star, dtype=float)
        self.c_star_func = c_star_func
        assert self.A_star.ndim == 2 and self.A_star.shape[0] == self.A_star.shape[1]

    def step(self, q: np.ndarray, t: int) -> np.ndarray:
        q_next = self.A_star @ q + self.c_star_func(t)
        return np.clip(q_next, 0.0, 1.0)

    def run(self, q0: np.ndarray, n_steps: int = 50, tol: float = 1e-6) -> OperatorResult:
        result = _iterate(self.step, q0, n_steps, tol)
        # closed-form fixed point (no clipping)
        rho = float(np.max(np.abs(np.linalg.eigvals(self.A_star))))
        if rho < 1.0:
            c_const = self.c_star_func(0)
            try:
                fp = np.linalg.solve(np.eye(len(c_const)) - self.A_star, c_const)
                result.fixed_point = fp
            except np.linalg.LinAlgError:
                pass
        return result


# ---------------------------------------------------------------------------
# 3. NEVA non-linear operator (infrastructure-adapted)
# ---------------------------------------------------------------------------

class NevaOperator:
    """
    Non-linear valuation operator (Barucca et al. 2020 generalisation of DebtRank).

    Working variable: health h = 1 - x ∈ [0, 1].
    Propagation in terms of disruption x:

        x_i(t+1) = clip( x_i(0) + Σ_j A[i][j] · stress_j(h_j(t)), 0, 1 )
        stress_j(h) = 1 - h^β              (β ≥ 1; β=1 → linear DebtRank)

    При β=1 совпадает с линейным DebtRank (Battiston 2012).
    При β>1 — non-linear NEVA (концентрация потерь у дефолта).
    """

    def __init__(self, A: np.ndarray, beta: float = 2.0) -> None:
        self.A = np.asarray(A, dtype=float)
        self.beta = float(beta)
        assert self.A.ndim == 2 and self.A.shape[0] == self.A.shape[1]
        assert self.beta >= 1.0, "β must be ≥ 1 (1 = linear DebtRank)"

    def stress(self, h: np.ndarray) -> np.ndarray:
        """stress_j(h) = 1 - h^β; h ∈ [0,1]."""
        h_clipped = np.clip(h, 0.0, 1.0)
        return 1.0 - np.power(h_clipped, self.beta)

    def step(self, x: np.ndarray, x0: np.ndarray) -> np.ndarray:
        h = 1.0 - x
        s = self.stress(h)
        x_next = x0 + self.A @ s
        return np.clip(x_next, 0.0, 1.0)

    def run(self, x0: np.ndarray, n_steps: int = 50, tol: float = 1e-6) -> OperatorResult:
        x0_arr = np.asarray(x0, dtype=float)
        return _iterate(lambda x, _t: self.step(x, x0_arr), x0_arr.copy(), n_steps, tol)


# ---------------------------------------------------------------------------
# Cascade indicator helpers (compatible with H₁)
# ---------------------------------------------------------------------------

def classical_indicator(trajectory: np.ndarray, C: np.ndarray, initiator: int) -> int:
    """I_cl = 1 iff any non-initiator node crosses its capacity C."""
    N = trajectory.shape[1]
    for j in range(N):
        if j == initiator:
            continue
        if np.any(trajectory[:, j] >= C[j]):
            return 1
    return 0


def quantitative_indicator(trajectory: np.ndarray, delta: float, initiator: int) -> int:
    """I_q = 1 iff any non-initiator node increases by more than δ from t=0."""
    N = trajectory.shape[1]
    x0 = trajectory[0]
    for j in range(N):
        if j == initiator:
            continue
        if np.any(trajectory[:, j] - x0[j] >= delta):
            return 1
    return 0
