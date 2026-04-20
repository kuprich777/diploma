"""Тесты §13.1: test_all_operators_same_contract — единый контракт §9.2."""
from __future__ import annotations

import numpy as np

from services.risk_engine.contract import OperatorInput, OperatorResult
from services.risk_engine.operators import (
    compute_K_cl,
    compute_K_DR,
    compute_K_leontief,
    compute_K_q_abs,
    compute_K_q_deg,
)


OPERATORS = [
    ("K_Leontief", compute_K_leontief),
    ("K_cl", compute_K_cl),
    ("K_DR", compute_K_DR),
    ("K_q_deg", compute_K_q_deg),
    ("K_q_abs", compute_K_q_abs),
]


def _standard_input() -> OperatorInput:
    return OperatorInput(
        x0=np.array([0.3, 0.3, 0.3]),
        u=np.array([0.5, 0.0, 0.0]),
        A=np.array(
            [
                [0.00, 0.15, 0.20],
                [0.10, 0.00, 0.10],
                [0.25, 0.15, 0.00],
            ]
        ),
        C=np.array([0.5, 0.5, 0.5]),
        T=7,
        delta=0.10,
        theta_node=0.75,
        epsilon_cl=0.05,
        sigma=np.array([0.2, 0.2, 0.0]),
        alpha=0.0,
        dt=1.0,
        seed=42,
    )


def test_all_operators_same_contract():
    """Все операторы принимают OperatorInput и возвращают OperatorResult."""
    inp = _standard_input()
    for name, fn in OPERATORS:
        res = fn(inp)
        assert isinstance(res, OperatorResult), f"{name}: не OperatorResult"
        assert res.x_final.shape == (3,), f"{name}: x_final shape"
        assert (res.x_final >= 0).all() and (res.x_final <= 1).all(), f"{name}: out of [0,1]"
        assert res.I in (0, 1), f"{name}: I={res.I}"
        assert "operator_name" in res.metadata, f"{name}: отсутствует metadata.operator_name"


def test_all_operators_accept_2D_u():
    """Контракт §9.2: u может быть (n,) или (T, n)."""
    inp_1d = _standard_input()
    inp_2d = OperatorInput(
        x0=inp_1d.x0.copy(),
        u=np.tile(np.array([0.0714, 0.0, 0.0]), (7, 1)),  # суммарно ≈ 0.5
        A=inp_1d.A.copy(),
        C=inp_1d.C.copy(),
        T=7,
        delta=0.10,
        theta_node=0.75,
        epsilon_cl=0.05,
        sigma=np.zeros(3),
        alpha=0.0,
        dt=1.0,
        seed=42,
    )
    for name, fn in OPERATORS:
        # Не проверяем численное равенство 1D и 2D: механика разная
        # (1D шок на t=0 vs равномерное распределение). Проверяем только,
        # что обе формы не падают.
        _ = fn(inp_1d)
        _ = fn(inp_2d)


def test_deterministic_operators_ignore_seed():
    """K_Leontief/K_cl/K_DR детерминированы: результат не зависит от seed."""
    for name, fn in [
        ("K_Leontief", compute_K_leontief),
        ("K_cl", compute_K_cl),
        ("K_DR", compute_K_DR),
    ]:
        inp_a = _standard_input()
        inp_a.seed = 1
        inp_b = _standard_input()
        inp_b.seed = 9999
        r_a = fn(inp_a)
        r_b = fn(inp_b)
        np.testing.assert_allclose(r_a.x_final, r_b.x_final, atol=1e-12, err_msg=name)


def test_operator_metadata_has_initiator():
    """У операторов с шоком должен быть initiator в metadata."""
    inp = _standard_input()
    for name, fn in OPERATORS:
        res = fn(inp)
        assert "initiator" in res.metadata, f"{name}: отсутствует initiator"
        assert res.metadata["initiator"] == 0, f"{name}: initiator должен быть 0 (energy)"


def test_invalid_input_shapes():
    """OperatorInput валидирует shape при создании."""
    import pytest

    # A shape mismatch
    with pytest.raises(ValueError):
        OperatorInput(
            x0=np.array([0.3, 0.3, 0.3]),
            u=np.zeros(3),
            A=np.eye(2),  # wrong shape
            C=np.array([0.5, 0.5, 0.5]),
            T=1,
            delta=0.1,
        )
    # C shape mismatch
    with pytest.raises(ValueError):
        OperatorInput(
            x0=np.array([0.3, 0.3, 0.3]),
            u=np.zeros(3),
            A=np.zeros((3, 3)),
            C=np.array([0.5, 0.5]),
            T=1,
            delta=0.1,
        )
