"""Единый контракт входа/выхода операторов — METHODOLOGY §9.2.

Все четыре оператора (K_Leontief, K_cl, K_DR, K_q) принимают OperatorInput и
возвращают OperatorResult. Это обеспечивает сопоставимость метрик по §5.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np


@dataclass
class OperatorInput:
    """Общий вход, см. §9.2.

    Для детерминированных операторов (Leontief, cl, DR) seed/N_runs игнорируются.
    Для K_q — обязателен seed; N_runs задаётся внешним MC-оркестратором.
    """

    x0: np.ndarray                 # shape (n,), начальное состояние
    u: np.ndarray                  # shape (n,) или (T, n); сценарное воздействие
    A: np.ndarray                  # shape (n, n), матрица зависимостей
    C: np.ndarray                  # shape (n,), пороги перегрузки
    T: int                         # горизонт (число шагов)
    delta: float                   # порог значимого прироста (§0.4: 0.10)
    theta_node: float = 0.75       # только для K_cl (§0.4)
    epsilon_cl: float = 0.05       # только для K_cl (§3.2, §0.4)
    sigma: Optional[np.ndarray] = None  # только для K_q; shape (n,), σ_transport=0
    alpha: float = 0.0             # только для K_q (§3.4, §8.3)
    dt: float = 1.0                # шаг интеграции, час (§0.4)
    seed: Optional[int] = None     # только для K_q

    def __post_init__(self) -> None:
        self.x0 = np.asarray(self.x0, dtype=float).copy()
        self.A = np.asarray(self.A, dtype=float).copy()
        self.C = np.asarray(self.C, dtype=float).copy()
        self.u = np.asarray(self.u, dtype=float).copy()
        if self.sigma is not None:
            self.sigma = np.asarray(self.sigma, dtype=float).copy()
        n = self.x0.shape[0]
        if self.A.shape != (n, n):
            raise ValueError(f"A must be ({n},{n}), got {self.A.shape}")
        if self.C.shape != (n,):
            raise ValueError(f"C must be ({n},), got {self.C.shape}")
        # u может быть (n,) — одноразовый шок на t=0 — или (T, n) — пошаговое воздействие
        if self.u.ndim == 1 and self.u.shape[0] != n:
            raise ValueError(f"u (1D) must have length n={n}, got {self.u.shape}")
        if self.u.ndim == 2 and self.u.shape[1] != n:
            raise ValueError(f"u (2D) must have shape (T, n), got {self.u.shape}")

    def u_at(self, t: int) -> np.ndarray:
        """Возвращает u_t. Если u задан как (n,) — подаётся только на t=0."""
        if self.u.ndim == 1:
            n = self.x0.shape[0]
            return self.u if t == 0 else np.zeros(n)
        # u.ndim == 2
        if t < self.u.shape[0]:
            return self.u[t]
        return np.zeros(self.x0.shape[0])

    @property
    def n(self) -> int:
        return self.x0.shape[0]

    def initiator_index(self) -> int:
        """Индекс инициатора — сектор с максимальным суммарным |u|."""
        if self.u.ndim == 1:
            return int(np.argmax(np.abs(self.u)))
        return int(np.argmax(np.abs(self.u).sum(axis=0)))


@dataclass
class OperatorResult:
    """Общий выход, см. §9.2."""

    x_final: np.ndarray            # shape (n,)
    I: int                         # каскадный индикатор 0/1
    trajectory: Optional[np.ndarray] = None  # (T+1, n), опционально
    s_final: Optional[np.ndarray] = None     # shape (n,), '<U1' — для K_DR / K_q^abs
    metadata: dict[str, Any] = field(default_factory=dict)
