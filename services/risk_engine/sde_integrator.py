"""
sde_integrator.py
=================
Euler-Maruyama integrator for the stochastic infrastructure risk model.

Mathematical model
------------------
SDE dynamics (per node j):

    dx_j(t) = ( Σ_i a_{ij}(t) x_i(t) - ρ_j x_j(t) ) dt
              + σ_j x_j(t) dW_j(t)

Discretised Euler-Maruyama scheme with reflecting [0,1] boundaries:

    x_j^{k+1} = clip_{[0,1]}(
        x_j^k
        + ( Σ_i A(t)[j,i] x_i^k - ρ_j x_j^k ) * dt
        + σ_j * x_j^k * sqrt(dt) * Z_j^k
    )
    Z_j^k ~ N(0,1) i.i.d.

Dynamic dependency matrix (α > 0)
----------------------------------
When a supplier node j is overloaded (x_j ≥ C_j), its outgoing links are
weakened by a degradation factor φ_j ∈ (0, 1]:

    φ_j(t) = exp( −α · max(0, x_j(t) − C_j) / (1 − C_j) )

    A(t)[:, j] = A_static[:, j] · φ_j(t)

At α=0: A(t) = A_static (static matrix, backward-compatible mode).

Cascade indicators (compatible with H₁)
-----------------------------------------
Classical:
    I_cl(s,r) = 1  iff  ∃ j≠j₀, t≤T : x_j(t) ≥ C_j

Quantitative:
    I_q(s,r)  = 1  iff  ∃ j≠j₀ : max_{t≤T}(x_j(t) - x_j(0)) ≥ δ

References: see docs/MATH_MODEL.md §1–3
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------

@dataclass
class SDEConfig:
    """
    Parameters for the SDE integrator.

    Attributes
    ----------
    A : (N,N) ndarray
        Static dependency matrix. A[i][j] = influence of j on i. Diagonal = 0.
        At runtime a dynamic version A(t) may be derived from this via alpha.
    sigma : (N,) ndarray
        Volatility of each node.
    rho : (N,) ndarray
        Recovery rate of each node (mean-reversion speed).
    C : (N,) ndarray
        Capacity thresholds. Node j fails when x_j >= C_j.
    dt : float
        Time step size (dimensionless, e.g. 0.1).
    T_steps : int
        Number of integration steps.
    delta : float
        Quantitative cascade threshold Δ (default 0.10).
    alpha : float
        Supply-chain degradation rate for dynamic A(t). α=0 (default) disables
        the dynamic matrix, reproducing the static-A behaviour exactly.
        At α=5 a fully overloaded node (x_j=1) retains only exp(−5) ≈ 0.7%
        of its outgoing coupling strength.
    """
    A: np.ndarray
    sigma: np.ndarray
    rho: np.ndarray
    C: np.ndarray
    dt: float     = 0.1
    T_steps: int  = 50
    delta: float  = 0.10
    alpha: float  = 0.0

    def __post_init__(self) -> None:
        self.A     = np.array(self.A,     dtype=float)
        self.sigma = np.array(self.sigma, dtype=float)
        self.rho   = np.array(self.rho,   dtype=float)
        self.C     = np.array(self.C,     dtype=float)
        N = self.A.shape[0]
        assert self.A.shape == (N, N),      "A must be square"
        assert self.sigma.shape == (N,),    "sigma must be length N"
        assert self.rho.shape   == (N,),    "rho must be length N"
        assert self.C.shape     == (N,),    "C must be length N"
        assert self.dt > 0,                 "dt must be positive"
        assert self.T_steps >= 1,           "T_steps must be >= 1"
        assert self.alpha >= 0.0,           "alpha must be non-negative"


# ---------------------------------------------------------------------------
# Cascade result
# ---------------------------------------------------------------------------

@dataclass
class CascadeResult:
    I_cl: int            # classical cascade indicator {0,1}
    I_q:  int            # quantitative cascade indicator {0,1}
    max_delta: float     # max Δx over all non-initiator nodes and time steps
    failed_nodes_cl: list[int]  # nodes that triggered classical threshold
    failed_nodes_q:  list[int]  # nodes that triggered quantitative threshold


# ---------------------------------------------------------------------------
# SDEIntegrator
# ---------------------------------------------------------------------------

class SDEIntegrator:
    """
    Integrates the N-node infrastructure SDE system via Euler-Maruyama.

    Supports both static A (alpha=0) and dynamic A(t) (alpha>0).  With alpha>0
    the coupling strength from overloaded supplier nodes is attenuated on every
    step via a degradation factor φ_j ∈ (0, 1].

    Usage
    -----
    >>> cfg = SDEConfig(A=A, sigma=sigma, rho=rho, C=C)              # static
    >>> cfg = SDEConfig(A=A, sigma=sigma, rho=rho, C=C, alpha=5.0)   # dynamic
    >>> integrator = SDEIntegrator(cfg)
    >>> trajectories = integrator.run(x0=x0, shock=u, seed=42)
    >>> result = integrator.detect_cascade(trajectories, initiator=0)
    """

    def __init__(self, config: SDEConfig) -> None:
        self.cfg    = config
        self._N     = config.A.shape[0]
        # Expose static matrix and alpha as direct attributes for convenience
        self.A_static = config.A       # (N, N) — never mutated
        self.alpha    = config.alpha

    # ------------------------------------------------------------------
    # Dynamic dependency matrix
    # ------------------------------------------------------------------

    def _compute_dynamic_A(self, x: np.ndarray) -> np.ndarray:
        """
        Compute A(t) = A_static * diag(φ), where each supplier column j is
        attenuated by the degradation factor φ_j ∈ (0, 1].

        φ_j = exp(−α · max(0, x_j − C_j) / (1 − C_j))

        Properties
        ----------
        - x_j < C_j  →  φ_j = 1.0  (no attenuation; node is within capacity)
        - x_j = C_j  →  φ_j = 1.0  (boundary: no attenuation)
        - x_j → 1.0  →  φ_j → exp(−α)  (maximum attenuation)
        - φ_j ∈ (0, 1] always — coupling is weakened but never zeroed

        The multiplier is applied **column-wise** (per supplier j): if node j
        is overloaded, ALL its outgoing links to every dependent sector i are
        weakened proportionally, modelling supply-chain disruption.

        Fast path: returns A_static (no copy) when α = 0.
        """
        if self.alpha == 0.0:
            return self.A_static        # fast path — static matrix

        C = self.cfg.C
        phi = np.ones(self._N)
        for j in range(self._N):
            excess = x[j] - C[j]
            if excess > 0.0:
                denom  = max(1e-10, 1.0 - C[j])   # guard against C_j == 1
                phi[j] = np.exp(-self.alpha * excess / denom)

        # Broadcast (N,N) * (1,N) → multiply each column j by phi[j]
        return self.A_static * phi[np.newaxis, :]

    # ------------------------------------------------------------------
    # Single Euler-Maruyama step
    # ------------------------------------------------------------------

    def step(
        self,
        x: np.ndarray,
        rng: np.random.Generator,
        shock: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """
        One step of Euler-Maruyama with reflecting [0,1] boundaries.

        Uses A(t) = _compute_dynamic_A(x) at the current state.  When α=0
        this reduces to the static matrix without any extra computation.

        Parameters
        ----------
        x : (N,) current state
        rng : random generator
        shock : (N,) optional external shock applied at this step only
        """
        cfg = self.cfg
        dt  = cfg.dt

        # Dynamic dependency matrix (α=0 → A_static, no copy)
        A_current = self._compute_dynamic_A(x)

        # Deterministic drift: Σ_i A(t)[j,i] x_i - ρ_j x_j
        drift = A_current @ x - cfg.rho * x      # shape (N,)

        # Diffusion: σ_j x_j sqrt(dt) Z_j
        Z = rng.standard_normal(self._N)
        diffusion = cfg.sigma * x * np.sqrt(dt) * Z

        x_new = x + drift * dt + diffusion

        if shock is not None:
            x_new = x_new + shock

        return np.clip(x_new, 0.0, 1.0)

    # ------------------------------------------------------------------
    # Full trajectory run
    # ------------------------------------------------------------------

    def run(
        self,
        x0: np.ndarray,
        shock: Optional[np.ndarray] = None,
        seed: Optional[int] = None,
        save_A_history: bool = False,
    ) -> np.ndarray:
        """
        Run T_steps of Euler-Maruyama from x0.

        Parameters
        ----------
        x0 : (N,) initial state
        shock : (N,) one-time external shock applied at step 0
        seed : integer seed for reproducibility
        save_A_history : bool
            If True, store the effective A(t) matrix used at each step.
            Access via `integrator.A_history` after the run.
            Default False to save memory in Monte Carlo loops.

        Returns
        -------
        trajectories : (T_steps+1, N) array including x0 as row 0
        """
        rng = np.random.default_rng(seed)
        x   = np.array(x0, dtype=float)

        traj = np.empty((self.cfg.T_steps + 1, self._N), dtype=float)
        traj[0] = x

        self.A_history: list[np.ndarray] = [] if save_A_history else []

        for k in range(self.cfg.T_steps):
            if save_A_history:
                self.A_history.append(self._compute_dynamic_A(x).copy())

            # Shock only at the first step
            s = shock if k == 0 else None
            x = self.step(x, rng, shock=s)
            traj[k + 1] = x

        return traj

    # ------------------------------------------------------------------
    # Cascade detection
    # ------------------------------------------------------------------

    def detect_cascade(
        self,
        trajectories: np.ndarray,
        initiator: int,
        delta: Optional[float] = None,
    ) -> CascadeResult:
        """
        Compute I_cl and I_q from a trajectory array.

        Parameters
        ----------
        trajectories : (T+1, N) state array
        initiator : index of the initiator node (excluded from detection)
        delta : quantitative threshold (overrides cfg.delta if given)

        Returns
        -------
        CascadeResult
        """
        delta_ = delta if delta is not None else self.cfg.delta
        x0     = trajectories[0]          # initial state
        C      = self.cfg.C
        N      = self._N

        failed_cl: list[int] = []
        failed_q:  list[int] = []
        max_delta_val = 0.0

        for j in range(N):
            if j == initiator:
                continue

            # Classical: did x_j ever reach or exceed C_j?
            if np.any(trajectories[:, j] >= C[j]):
                failed_cl.append(j)

            # Quantitative: did max gain exceed delta?
            max_gain = float(np.max(trajectories[:, j] - x0[j]))
            if max_gain > max_delta_val:
                max_delta_val = max_gain
            if max_gain >= delta_:
                failed_q.append(j)

        return CascadeResult(
            I_cl=int(len(failed_cl) > 0),
            I_q=int(len(failed_q) > 0),
            max_delta=max_delta_val,
            failed_nodes_cl=failed_cl,
            failed_nodes_q=failed_q,
        )

    # ------------------------------------------------------------------
    # Seed helper
    # ------------------------------------------------------------------

    @staticmethod
    def make_seed(scenario_id: str, run_idx: int) -> int:
        """SHA-256-based deterministic seed: scenario_id:run_idx → int."""
        h = hashlib.sha256(f"{scenario_id}:{run_idx}".encode()).digest()
        return int.from_bytes(h[:8], "big") % (2**32)
