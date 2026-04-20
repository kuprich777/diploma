"""Тесты §13.1 для state machine §2.3 / §12.3."""
from __future__ import annotations

import numpy as np
import pytest

from services.risk_engine.state_machine import (
    STATE_F,
    STATE_N,
    STATE_O,
    init_state,
    update_state,
)


def test_state_machine_matches_spec():
    """§13.1: все 12 комбинаций (s_prev, x_range) соответствуют §2.3.

    s_prev ∈ {N, O, F} × x ∈ {<C, [C,1), >=1} = 9 пар (mandatory) + 3 граничные.
    """
    C = np.array([0.5, 0.5, 0.5])

    cases = [
        # (s_prev, x, expected)
        ([STATE_N, STATE_N, STATE_N], [0.3, 0.3, 0.3], [STATE_N, STATE_N, STATE_N]),
        ([STATE_N, STATE_N, STATE_N], [0.5, 0.5, 0.5], [STATE_O, STATE_O, STATE_O]),
        ([STATE_N, STATE_N, STATE_N], [0.7, 0.7, 0.7], [STATE_O, STATE_O, STATE_O]),
        ([STATE_N, STATE_N, STATE_N], [1.0, 1.0, 1.0], [STATE_F, STATE_F, STATE_F]),
        # Правило 2: O → F независимо от x
        ([STATE_O, STATE_O, STATE_O], [0.0, 0.4, 0.99], [STATE_F, STATE_F, STATE_F]),
        # Правило 1: F absorbing, даже при x < C
        ([STATE_F, STATE_F, STATE_F], [0.0, 0.3, 0.9], [STATE_F, STATE_F, STATE_F]),
        # Смешанные
        ([STATE_N, STATE_O, STATE_F], [0.6, 0.1, 0.1], [STATE_O, STATE_F, STATE_F]),
        # Граничные: x == C ровно на пороге (>= C → O)
        ([STATE_N, STATE_N, STATE_N], [0.5, 0.4999, 0.5000001], [STATE_O, STATE_N, STATE_O]),
    ]
    for s_prev, x, expected in cases:
        s_new = update_state(np.array(x), np.array(s_prev, dtype="<U1"), C)
        assert list(s_new) == expected, f"s_prev={s_prev}, x={x}: got {list(s_new)}, exp {expected}"


def test_O_to_F_one_step_forced():
    """§13.1: s_prev = O → s_new = F за один шаг, независимо от x."""
    C = np.array([0.5])
    for x in [0.0, 0.49, 0.5, 0.99, 1.0]:
        s_new = update_state(np.array([x]), np.array([STATE_O], dtype="<U1"), C)
        assert s_new[0] == STATE_F


def test_F_is_absorbing():
    """§13.1: s_prev = F → s_new = F навсегда, независимо от x."""
    C = np.array([0.5])
    for x in [0.0, 0.3, 0.5, 0.99, 1.0]:
        s_new = update_state(np.array([x]), np.array([STATE_F], dtype="<U1"), C)
        assert s_new[0] == STATE_F


def test_init_state_is_all_N():
    s = init_state(3)
    assert list(s) == [STATE_N, STATE_N, STATE_N]


def test_update_state_priority_order():
    """Правило 1 (F absorb) приоритетнее правила 3 (x>=1) и 4 (N→O)."""
    C = np.array([0.5])
    # F + x=0.9 (меньше 1) → остаётся F
    s = update_state(np.array([0.9]), np.array([STATE_F], dtype="<U1"), C)
    assert s[0] == STATE_F
    # F + x=1.5 (>=1) → остаётся F
    s = update_state(np.array([1.5]), np.array([STATE_F], dtype="<U1"), C)
    assert s[0] == STATE_F


def test_shape_mismatch_raises():
    with pytest.raises(ValueError, match="shape mismatch"):
        update_state(np.array([0.1, 0.2]), np.array([STATE_N], dtype="<U1"), np.array([0.5]))
