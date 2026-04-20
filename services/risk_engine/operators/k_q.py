"""K_q — стохастический динамический оператор. METHODOLOGY §3.4.

Дискретизация Эйлера–Маруямы:
    x_{t+1} = clip_{[0,1]}( x_t + u_t + A(t) x_t + σ ⊙ √Δt ε_t ),
    ε_t ~ N(0, I_n).

Динамическая матрица:
    A(t)_{ij} = a_{ij} · φ_j(t),
    φ_j(t)     = exp(-α · max(0, x_j(t) - C_j) / (1 - C_j)).

Две версии:
  * K_q^deg — без state machine; сумма A(t) x_t по всем j;
  * K_q^abs — с state machine §2.3; только j с s_j(t) = O вносят вклад;
              если s_i(t) = F — drift_i = 0 (узел заморожен).

σ_transport = 0 детерминированно (§8.2, Decision D1). Транспорт эволюционирует
без броуновской компоненты; шум energy/water влияет на transport через матрицу A.

Индикатор каскада (§3.4):
    I^(q) = 1{ ∃ i ≠ i_0 : max_{t ≤ T} (x_i(t) - x_i(0)) ≥ δ }.

Замечание: «x_i(0)» в индикаторе — pre-shock baseline inp.x0.
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


def _phi(x: np.ndarray, C: np.ndarray, alpha: float) -> np.ndarray:
    """φ_j(t) = exp(-α · max(0, x_j - C_j) / (1 - C_j))."""
    if alpha == 0.0:
        return np.ones_like(x)
    denom = np.clip(1.0 - C, 1e-12, None)
    over = np.clip(x - C, 0.0, None)
    return np.exp(-alpha * over / denom)


def _validate_sigma(sigma: np.ndarray | None, n: int) -> np.ndarray:
    if sigma is None:
        return np.zeros(n)
    sigma = np.asarray(sigma, dtype=float)
    if sigma.shape != (n,):
        raise ValueError(f"sigma must be ({n},), got {sigma.shape}")
    return sigma


def compute_K_q_deg(inp: OperatorInput) -> OperatorResult:
    """K_q^deg — плавная деградация через φ, без state machine."""
    rng = np.random.default_rng(inp.seed)
    n = inp.n
    A = inp.A
    C = inp.C
    alpha = inp.alpha
    sigma = _validate_sigma(inp.sigma, n)
    sqrt_dt = np.sqrt(inp.dt)

    x = inp.x0.copy()
    # Применяем одноразовый шок (если u задан как 1D) перед итерацией.
    # При u 2D — u_t прибавляется пошагово в цикле.
    traj = [x.copy()]
    max_delta = np.zeros(n)

    for t in range(inp.T):
        u_t = inp.u_at(t)
        phi = _phi(x, C, alpha)
        drift = (A * phi[np.newaxis, :]) @ x          # A(t) x_t
        noise = sigma * sqrt_dt * rng.standard_normal(n)
        x_new = np.clip(x + u_t + drift + noise, 0.0, 1.0)
        dx_from_baseline = x_new - inp.x0
        max_delta = np.maximum(max_delta, dx_from_baseline)
        x = x_new
        traj.append(x.copy())

    i0 = inp.initiator_index()
    cascade = any(max_delta[i] >= inp.delta for i in range(n) if i != i0)
    return OperatorResult(
        x_final=x,
        I=int(cascade),
        trajectory=np.array(traj, dtype=float),
        s_final=None,
        metadata={
            "operator_name": "K_q_deg",
            "seed": inp.seed,
            "initiator": int(i0),
            "alpha": float(alpha),
            "max_delta": max_delta.tolist(),
        },
    )


def compute_K_q_abs(inp: OperatorInput) -> OperatorResult:
    """K_q^abs — с absorbing state machine §2.3.

    Дрейф с маской по состоянию (§3.4):
        (A(t) x_t)^abs_i = 0,                                          если s_i(t) = F
                         = Σ_{j: s_j(t) = O} a_{ij} φ_j(t) x_{j,t},    иначе.

    Инвариант (test_Kq_abs_reduces_to_KDR): при σ = 0, α = 0 K_q^abs ≡ K_DR.
    Для K_DR инициализация s(0) = update_state(x_0 + u, (N,...,N), C).
    Для сохранения эквивалентности здесь применяем одноразовый шок (если u 1D)
    тоже на шаге 0 и инициализируем s сразу post-shock.
    """
    rng = np.random.default_rng(inp.seed)
    n = inp.n
    A = inp.A
    C = inp.C
    alpha = inp.alpha
    sigma = _validate_sigma(inp.sigma, n)
    sqrt_dt = np.sqrt(inp.dt)

    # Эквивалентная K_DR инициализация: h(0) = x_0 + u_total_для_1D_шока.
    if inp.u.ndim == 1:
        x = np.clip(inp.x0 + inp.u, 0.0, 1.0)
        u_step_mode = False
    else:
        x = inp.x0.copy()
        u_step_mode = True

    s = update_state(x, init_state(n), C)
    traj = [x.copy()]
    max_delta = np.maximum(np.zeros(n), x - inp.x0)

    for t in range(inp.T):
        phi = _phi(x, C, alpha)
        # Маскированный дрейф: только j с s[j]=O передают; i с s[i]=F заморожен.
        drift = np.zeros(n)
        for i in range(n):
            if s[i] == STATE_F:
                drift[i] = 0.0
                continue
            acc = 0.0
            for j in range(n):
                if s[j] == STATE_O:
                    acc += A[i, j] * phi[j] * x[j]
            drift[i] = acc

        noise = sigma * sqrt_dt * rng.standard_normal(n)
        u_t = inp.u_at(t) if u_step_mode else np.zeros(n)

        x_new = np.clip(x + u_t + drift + noise, 0.0, 1.0)
        # F-узлы не изменяются (они «заморожены» — ни шум, ни u их не двигают).
        frozen = s == STATE_F
        x_new[frozen] = x[frozen]

        dx_from_baseline = x_new - inp.x0
        max_delta = np.maximum(max_delta, dx_from_baseline)
        x = x_new
        s = update_state(x, s, C)
        traj.append(x.copy())

    i0 = inp.initiator_index()
    cascade = any(max_delta[i] >= inp.delta for i in range(n) if i != i0)
    return OperatorResult(
        x_final=x,
        I=int(cascade),
        trajectory=np.array(traj, dtype=float),
        s_final=s,
        metadata={
            "operator_name": "K_q_abs",
            "seed": inp.seed,
            "initiator": int(i0),
            "alpha": float(alpha),
            "max_delta": max_delta.tolist(),
        },
    )
