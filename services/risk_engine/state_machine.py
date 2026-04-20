"""State machine s_j(t) ∈ {N, O, F} — METHODOLOGY §2.3.

Это единственный источник истины для правил переходов состояния.
Любое расхождение между §2.3 и этим модулем — ошибка реализации, не §2.3.

Используется:
  * K_DR (§3.3)
  * K_q^abs (§3.4)

Порядок приоритета правил (см. §2.3 и §12.3):
  1. F absorbing: s_prev == F → F
  2. Forced O → F за один шаг: s_prev == O → F
  3. Численное насыщение: x >= 1.0 → F
  4. N → O: x >= C_j при s_prev == N → O
  5. Иначе: N
"""
from __future__ import annotations

import numpy as np

STATE_N = "N"
STATE_O = "O"
STATE_F = "F"
VALID_STATES = frozenset({STATE_N, STATE_O, STATE_F})


def update_state(
    x_current: np.ndarray,
    s_prev: np.ndarray,
    C: np.ndarray,
) -> np.ndarray:
    """Обновление s_j(t) по §2.3 / §12.3.

    Parameters
    ----------
    x_current : np.ndarray, shape (n,)
        Текущий вектор состояния x_j(t), после clip на [0, 1].
    s_prev : np.ndarray, shape (n,), dtype '<U1'
        Состояние на предыдущем шаге, значения ∈ {'N', 'O', 'F'}.
    C : np.ndarray, shape (n,)
        Пороги перегрузки C_j.

    Returns
    -------
    s_new : np.ndarray, shape (n,), dtype '<U1'
    """
    x_current = np.asarray(x_current, dtype=float)
    s_prev = np.asarray(s_prev, dtype="<U1")
    C = np.asarray(C, dtype=float)
    n = x_current.shape[0]
    if s_prev.shape[0] != n or C.shape[0] != n:
        raise ValueError(
            f"shape mismatch: x({x_current.shape}), s_prev({s_prev.shape}), C({C.shape})"
        )
    s_new = np.empty(n, dtype="<U1")
    for j in range(n):
        if s_prev[j] == STATE_F:
            s_new[j] = STATE_F
        elif s_prev[j] == STATE_O:
            s_new[j] = STATE_F
        elif x_current[j] >= 1.0:
            s_new[j] = STATE_F
        elif x_current[j] >= C[j] and s_prev[j] == STATE_N:
            s_new[j] = STATE_O
        else:
            s_new[j] = STATE_N
    return s_new


def init_state(n: int) -> np.ndarray:
    """s(-1) = (N, N, ..., N) до применения первого update_state."""
    return np.array([STATE_N] * n, dtype="<U1")
