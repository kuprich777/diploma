"""
mc_harness.py
=============
Единый Monte Carlo harness для сравнения трёх каскадных операторов (SDE, IIM, NEVA)
на одних и тех же сценариях.

Цель: корректное cross-method сравнение — один σ-шум, одинаковые x0/shock,
seed-reproducible RNG. SDE остаётся primary; IIM/NEVA — альтернативные базлайны.

Architecture
------------
Каждый оператор реализует паттерн:
    run(x0, shock, rng) -> trajectory: (T_steps+1, N)

После прогона вычисляется единый набор индикаторов (classical, quantitative).

В рамках одного MC-прогона все три оператора получают одну и ту же RNG
(через split), поэтому реализации их стохастических компонент идентичны там,
где это применимо (IIM и NEVA — детерминированные, но могут обогащаться
аддитивным σ-шумом для fair comparison).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from services.risk_engine.cascade_operators import (
    ClassicalOperator,
    IIMOperator,
    NevaOperator,
)
from services.risk_engine.sde_integrator import SDEConfig, SDEIntegrator


# ---------------------------------------------------------------------------
# Scenario specification
# ---------------------------------------------------------------------------

@dataclass
class Scenario:
    """Единичный MC-сценарий."""
    id: str
    initiator: int            # индекс инициаторного сектора
    severity: float           # амплитуда шока [0,1]
    x0: np.ndarray            # начальное состояние (N,)
    description: str = ""


# ---------------------------------------------------------------------------
# Indicator helpers (shared across operators)
# ---------------------------------------------------------------------------

def indicators(traj: np.ndarray, C: np.ndarray, delta: float, initiator: int) -> tuple[int, int, float]:
    """Возвращает (I_cl, I_q, max_delta) для одной траектории."""
    N = traj.shape[1]
    x0 = traj[0]
    I_cl, I_q = 0, 0
    max_d = 0.0
    for j in range(N):
        if j == initiator:
            continue
        if np.any(traj[:, j] >= C[j]):
            I_cl = 1
        gain = float(np.max(traj[:, j] - x0[j]))
        if gain > max_d:
            max_d = gain
        if gain >= delta:
            I_q = 1
    return I_cl, I_q, max_d


def make_seed(scenario_id: str, run_idx: int, op_name: str) -> int:
    """Детерминированный seed из (scenario, run, operator)."""
    h = hashlib.sha256(f"{scenario_id}:{run_idx}:{op_name}".encode()).digest()
    return int.from_bytes(h[:8], "big") % (2**32)


# ---------------------------------------------------------------------------
# Per-operator single-run wrappers
# ---------------------------------------------------------------------------

def run_sde_once(
    A: np.ndarray,
    sigma: np.ndarray,
    rho: np.ndarray,
    C: np.ndarray,
    x0: np.ndarray,
    shock: np.ndarray,
    dt: float,
    T_steps: int,
    alpha: float,
    seed: int,
) -> np.ndarray:
    cfg = SDEConfig(A=A, sigma=sigma, rho=rho, C=C, dt=dt, T_steps=T_steps, alpha=alpha)
    integ = SDEIntegrator(cfg)
    return integ.run(x0=x0, shock=shock, seed=seed)


def run_iim_once(
    A: np.ndarray,
    sigma: np.ndarray,
    x0: np.ndarray,
    shock: np.ndarray,
    T_steps: int,
    seed: int,
    noise_scale: float = 1.0,
) -> np.ndarray:
    """
    IIM с аддитивным σ-шумом для fair comparison:
        q(t+1) = clip(A q(t) + c(t) + σ · Z)
    c(t) = shock только при t=0 (импульс); шум на каждом шаге.
    """
    rng = np.random.default_rng(seed)
    N = len(x0)

    def c_func(t: int) -> np.ndarray:
        return shock if t == 0 else np.zeros(N)

    op = IIMOperator(A, c_func)
    q = x0.copy()
    traj = [q.copy()]
    for t in range(T_steps):
        q_raw = op.A_star @ q + c_func(t) + noise_scale * sigma * rng.standard_normal(N)
        q = np.clip(q_raw, 0.0, 1.0)
        traj.append(q.copy())
    return np.array(traj)


def run_neva_once(
    A: np.ndarray,
    sigma: np.ndarray,
    x0: np.ndarray,
    shock: np.ndarray,
    T_steps: int,
    beta: float,
    seed: int,
    noise_scale: float = 1.0,
) -> np.ndarray:
    """
    NEVA с аддитивным σ-шумом:
        x(t+1) = clip(x0 + A · stress(1-x(t)) + σ · Z)
    """
    rng = np.random.default_rng(seed)
    N = len(x0)
    op = NevaOperator(A, beta=beta)
    x_base = x0 + shock  # начальное возмущённое состояние
    x_base = np.clip(x_base, 0.0, 1.0)
    x = x_base.copy()
    traj = [x.copy()]
    for _ in range(T_steps):
        h = 1.0 - x
        s = op.stress(h)
        x_raw = x_base + A @ s + noise_scale * sigma * rng.standard_normal(N)
        x = np.clip(x_raw, 0.0, 1.0)
        traj.append(x.copy())
    return np.array(traj)


# ---------------------------------------------------------------------------
# Full harness
# ---------------------------------------------------------------------------

@dataclass
class MCConfig:
    A: np.ndarray
    sigma: np.ndarray
    rho: np.ndarray
    C: np.ndarray
    delta: float = 0.10
    dt: float = 0.1
    T_steps: int = 50
    alpha: float = 3.0
    neva_beta: float = 2.0
    operator_noise_scale: float = 1.0  # σ-multiplier for IIM/NEVA


def run_mc(
    scenario: Scenario,
    cfg: MCConfig,
    n_runs: int,
) -> dict:
    """
    Запустить MC для одного сценария, все 3 оператора.
    Returns dict с per-operator массивами I_cl, I_q, max_delta + summary.
    """
    ops = ["sde", "iim", "neva"]
    results = {op: {"I_cl": [], "I_q": [], "max_delta": []} for op in ops}

    shock = np.zeros(len(scenario.x0))
    shock[scenario.initiator] = scenario.severity

    for k in range(n_runs):
        traj_sde = run_sde_once(
            cfg.A, cfg.sigma, cfg.rho, cfg.C,
            scenario.x0, shock,
            cfg.dt, cfg.T_steps, cfg.alpha,
            make_seed(scenario.id, k, "sde"),
        )
        traj_iim = run_iim_once(
            cfg.A, cfg.sigma,
            scenario.x0, shock,
            cfg.T_steps,
            make_seed(scenario.id, k, "iim"),
            noise_scale=cfg.operator_noise_scale,
        )
        traj_neva = run_neva_once(
            cfg.A, cfg.sigma,
            scenario.x0, shock,
            cfg.T_steps, cfg.neva_beta,
            make_seed(scenario.id, k, "neva"),
            noise_scale=cfg.operator_noise_scale,
        )

        for name, traj in [("sde", traj_sde), ("iim", traj_iim), ("neva", traj_neva)]:
            I_cl, I_q, md = indicators(traj, cfg.C, cfg.delta, scenario.initiator)
            results[name]["I_cl"].append(I_cl)
            results[name]["I_q"].append(I_q)
            results[name]["max_delta"].append(md)

    summary = {}
    for op in ops:
        icl = np.array(results[op]["I_cl"])
        iq = np.array(results[op]["I_q"])
        md = np.array(results[op]["max_delta"])
        summary[op] = {
            "K_cl": float(icl.mean()),
            "K_q": float(iq.mean()),
            "mean_delta": float(md.mean()),
            "p95_delta": float(np.quantile(md, 0.95)),
            "n": n_runs,
        }

    return {
        "scenario": {
            "id": scenario.id,
            "initiator": int(scenario.initiator),
            "severity": float(scenario.severity),
            "x0": scenario.x0.tolist(),
            "description": scenario.description,
        },
        "per_operator": summary,
        "raw": {op: {k: results[op][k] for k in results[op]} for op in ops},
    }


def bootstrap_ci(values: list[int] | list[float], n_resamples: int = 1000, ci: float = 0.95,
                 seed: int = 0) -> tuple[float, float]:
    """Непараметрический bootstrap для среднего."""
    rng = np.random.default_rng(seed)
    arr = np.array(values)
    if len(arr) == 0:
        return (0.0, 0.0)
    resamples = rng.choice(arr, size=(n_resamples, len(arr)), replace=True).mean(axis=1)
    lo = float(np.quantile(resamples, (1 - ci) / 2))
    hi = float(np.quantile(resamples, 1 - (1 - ci) / 2))
    return lo, hi
