"""Тесты §13.1: математическая корректность операторов §3."""
from __future__ import annotations

import numpy as np
import pytest

from services.risk_engine.contract import OperatorInput
from services.risk_engine.operators import (
    compute_K_cl,
    compute_K_DR,
    compute_K_leontief,
    compute_K_q_abs,
    compute_K_q_deg,
)
from services.risk_engine.state_machine import STATE_F


# Тестовая матрица: 3 сектора, ρ(A) < 1, диагональ = 0.
# Имитирует порядок [energy, water, transport].
A_TEST = np.array(
    [
        [0.00, 0.15, 0.20],
        [0.10, 0.00, 0.10],
        [0.25, 0.15, 0.00],
    ]
)
C_TEST = np.array([0.50, 0.50, 0.50])
X0_TEST = np.array([0.30, 0.30, 0.30])


def _make_input(**kwargs) -> OperatorInput:
    defaults = dict(
        x0=X0_TEST.copy(),
        u=np.array([0.5, 0.0, 0.0]),
        A=A_TEST.copy(),
        C=C_TEST.copy(),
        T=7,
        delta=0.10,
        theta_node=0.75,
        epsilon_cl=0.05,
        dt=1.0,
    )
    defaults.update(kwargs)
    return OperatorInput(**defaults)


# ---------- test_K_leontief_convergence ----------


def test_K_leontief_convergence():
    inp = _make_input()
    res = compute_K_leontief(inp)
    assert res.x_final.shape == (3,)
    assert (res.x_final >= 0).all() and (res.x_final <= 1).all()
    assert res.I in (0, 1)


def test_K_leontief_rejects_bad_A():
    bad_A = np.array([[0.0, 0.6, 0.6], [0.6, 0.0, 0.6], [0.6, 0.6, 0.0]])
    inp = _make_input(A=bad_A)
    with pytest.raises(ValueError, match="ρ"):
        compute_K_leontief(inp)


def test_K_leontief_rejects_nonzero_diag():
    bad_A = A_TEST.copy()
    bad_A[0, 0] = 0.1
    inp = _make_input(A=bad_A)
    with pytest.raises(ValueError, match="diag"):
        compute_K_leontief(inp)


# ---------- test_K_cl ----------


def test_K_cl_shock_triggers_cascade():
    """Большой шок в energy выталкивает его за θ_node; распространение по ã."""
    inp = _make_input(u=np.array([0.6, 0.0, 0.0]), theta_node=0.75)
    res = compute_K_cl(inp)
    # x_0_energy + u = 0.30 + 0.60 = 0.90 >= θ_node → y_energy = 1
    # ã_energy,water=0.15 > 0 и ã_energy,transport=0.25 > 0 → каскад во все
    assert res.I == 1
    assert res.x_final[0] == 1.0


def test_K_cl_epsilon_thresholding():
    """Рёбра < ε_cl не проводят каскад."""
    A_weak = np.array(
        [
            [0.0, 0.04, 0.04],  # все < ε_cl = 0.05
            [0.04, 0.0, 0.04],
            [0.04, 0.04, 0.0],
        ]
    )
    inp = _make_input(A=A_weak, u=np.array([0.6, 0.0, 0.0]))
    res = compute_K_cl(inp)
    # y_energy = 1, но рёбра обнулены → каскад не передаётся
    # initiator = energy, не в счёте каскада; other = 0
    assert res.I == 0


def test_K_cl_subthreshold_no_cascade():
    """Слабый шок не выводит за θ_node — каскада нет."""
    inp = _make_input(u=np.array([0.2, 0.0, 0.0]), theta_node=0.75)
    res = compute_K_cl(inp)
    # x_0_energy + u = 0.50 < 0.75
    assert res.I == 0


# ---------- test_K_DR ----------


def test_K_DR_absorbing_F():
    """Если s_j(t_0) = F, то s_j(t) = F для всех t > t_0."""
    # Шок = 1.0 для energy выводит сразу на 1 → F на инициализации
    inp = _make_input(u=np.array([1.0, 0.0, 0.0]))
    res = compute_K_DR(inp)
    assert res.s_final is not None
    assert res.s_final[0] == STATE_F
    # h_energy не превышает 1
    assert res.x_final[0] <= 1.0 + 1e-12


def test_K_DR_no_double_counting_absorbed_origin():
    """s(0)=F для узла j → его вклад a_ij*h_j не входит в h_i на шаге 1."""
    x0 = np.array([0.0, 0.0, 0.0])
    u = np.array([1.0, 0.0, 0.0])  # energy сразу в F
    inp = _make_input(x0=x0, u=u, T=1)
    res = compute_K_DR(inp)
    # s(0) для energy = F; h_energy(0) = 1
    # Для water: i=1, s[0]=F → j=0 не в O → contribution = 0 → h_water(1) = h_water(0) = 0
    # Для transport: аналогично → 0
    assert res.x_final[1] == pytest.approx(0.0)
    assert res.x_final[2] == pytest.approx(0.0)


def test_K_DR_forced_O_to_F():
    """Узел, попавший в O, на следующем шаге → F."""
    # Шок выводит energy в [C, 1) → O → на следующем шаге F
    inp = _make_input(u=np.array([0.4, 0.0, 0.0]), T=2)  # x0+u = 0.70 ∈ [0.5, 1) → O
    res = compute_K_DR(inp)
    assert res.s_final is not None
    assert res.s_final[0] == STATE_F


# ---------- test_K_q ----------


def test_K_q_clip_bounds():
    inp = _make_input(
        u=np.array([0.3, 0.0, 0.0]),
        sigma=np.array([0.5, 0.5, 0.0]),  # σ_transport = 0
        seed=42,
        T=7,
    )
    res = compute_K_q_deg(inp)
    assert res.trajectory is not None
    assert ((res.trajectory >= 0) & (res.trajectory <= 1)).all()


def test_K_q_transport_deterministic_sigma_zero():
    """σ_transport = 0 → transport эволюционирует детерминированно (D1)."""
    inp1 = _make_input(
        u=np.array([0.4, 0.0, 0.0]),
        sigma=np.array([0.0, 0.0, 0.0]),  # все σ = 0
        seed=1,
    )
    inp2 = _make_input(
        u=np.array([0.4, 0.0, 0.0]),
        sigma=np.array([0.0, 0.0, 0.0]),
        seed=99999,
    )
    r1 = compute_K_q_deg(inp1)
    r2 = compute_K_q_deg(inp2)
    # При σ=0 результаты детерминистичны и не зависят от seed
    np.testing.assert_allclose(r1.x_final, r2.x_final, atol=1e-12)


def test_K_q_abs_reduces_to_K_DR():
    """§13.1: при σ=0, α=0 K_q^abs ≡ K_DR численно (инвариант консистентности)."""
    u = np.array([0.4, 0.0, 0.0])
    inp_dr = _make_input(u=u, T=7)
    inp_q = _make_input(u=u, T=7, sigma=np.zeros(3), alpha=0.0, seed=0)
    r_dr = compute_K_DR(inp_dr)
    r_q = compute_K_q_abs(inp_q)
    np.testing.assert_allclose(r_dr.x_final, r_q.x_final, atol=1e-12)
    assert list(r_dr.s_final) == list(r_q.s_final)
    assert r_dr.I == r_q.I


def test_K_q_abs_reduces_to_K_DR_multiple_scenarios():
    """Инвариант K_q^abs ≡ K_DR на нескольких u."""
    for u_vec in [
        np.array([0.3, 0.0, 0.0]),
        np.array([0.0, 0.3, 0.0]),
        np.array([0.0, 0.0, 0.3]),
        np.array([0.2, 0.1, 0.1]),
    ]:
        inp_dr = _make_input(u=u_vec.copy(), T=5)
        inp_q = _make_input(u=u_vec.copy(), T=5, sigma=np.zeros(3), alpha=0.0, seed=0)
        r_dr = compute_K_DR(inp_dr)
        r_q = compute_K_q_abs(inp_q)
        np.testing.assert_allclose(
            r_dr.x_final, r_q.x_final, atol=1e-12,
            err_msg=f"Mismatch on u={u_vec}: K_DR={r_dr.x_final}, K_q^abs={r_q.x_final}",
        )


def test_K_q_deterministic_at_sigma_zero():
    """§13.1 первая часть: при σ=0 K_q детерминирован (seed безразличен)."""
    inp_a = _make_input(u=np.array([0.3, 0.0, 0.0]), sigma=np.zeros(3), seed=1)
    inp_b = _make_input(u=np.array([0.3, 0.0, 0.0]), sigma=np.zeros(3), seed=9999)
    r_a = compute_K_q_deg(inp_a)
    r_b = compute_K_q_deg(inp_b)
    np.testing.assert_allclose(r_a.x_final, r_b.x_final, atol=1e-12)


# NOTE: §13.1 вторая часть «K_q^det при T→∞ → K_Leontief» НЕ РЕАЛИЗУЕМА
# литерально под формулой §3.4: x_{t+1} = clip(x_t + u_t + A(t) x_t + σε),
# без mean-reversion -ρx, состояние накапливает A·x и уходит в насыщение.
# Несоответствие между §3.4 и §13.1 задокументировано в PHASE_1_REPORT.md
# (требуется решение автора: либо восстановить -ρx в §3.4, либо удалить
# инвариант из §13.1).


def test_K_q_seed_reproducibility():
    inp1 = _make_input(u=np.array([0.3, 0.0, 0.0]), sigma=np.array([0.2, 0.2, 0.0]), seed=123)
    inp2 = _make_input(u=np.array([0.3, 0.0, 0.0]), sigma=np.array([0.2, 0.2, 0.0]), seed=123)
    r1 = compute_K_q_deg(inp1)
    r2 = compute_K_q_deg(inp2)
    np.testing.assert_allclose(r1.x_final, r2.x_final, atol=1e-12)
