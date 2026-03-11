"""Risk propagation operators for infrastructure risk modeling.

Two concrete strategies are provided:

- :class:`QuantitativeOperator` — continuous dynamics via the clipped linear map
  ``x_{t+1} = clip_{[0,1]}(x_t + u_t + A · x_t)``

- :class:`ClassicalOperator` — binary (rule-based) dynamics: binarise sector risks
  at threshold θ, then propagate failures one step through the dependency matrix A.

Both classes share the :class:`RiskOperator` abstract interface, which requires:

- :meth:`RiskOperator.compute` — one-step state transition
- :meth:`RiskOperator.detect_cascade` — retrospective cascade detection over a
  recorded trajectory

All algorithm parameters (A, δ, θ) are passed as arguments at call time so that
operators themselves have no dependency on global configuration objects.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _clip01(value: float) -> float:
    """Clip *value* to the closed interval [0, 1]."""
    return max(0.0, min(1.0, value))


def _matmul_vec(
    A: Sequence[Sequence[float]],
    x: Sequence[float],
) -> list[float]:
    """Multiply an n×n matrix *A* by a column vector *x*.

    Args:
        A: Matrix of shape (n, n).
        x: Vector of length n.

    Returns:
        Result vector of length n where result[i] = Σ_j A[i][j] · x[j].
    """
    n = len(A)
    return [
        sum(float(A[i][j]) * float(x[j]) for j in range(n))
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class RiskOperator(ABC):
    """Abstract base class for infrastructure-risk propagation operators.

    Concrete subclasses implement specific risk dynamics and cascade detection
    criteria.  All operator state (matrix A, thresholds) is injected at call
    time rather than stored as instance attributes, keeping operators stateless
    with respect to the evolving runtime configuration.

    Example usage::

        op = QuantitativeOperator()
        x_next = op.compute(x_t=[0.3, 0.0, 0.1],
                            u_t=[0.5, 0.0, 0.0],
                            A=my_matrix)
        cascade = op.detect_cascade(trajectory, i0=0, threshold=0.1)
    """

    @abstractmethod
    def compute(
        self,
        x_t: list[float],
        u_t: list[float],
        A: list[list[float]],
    ) -> list[float]:
        """Compute the next-step risk vector x_{t+1}.

        Args:
            x_t: Current subsystem risk vector, each element ∈ [0, 1].
                 Length n equals the number of subsystems.
            u_t: External disturbance / control-input vector, same length as
                 *x_t*.  A zero vector means no external shock at this step.
            A:   Dependency matrix of shape (n × n).
                 ``A[i][j]`` is the influence weight of sector *j* on sector *i*.

        Returns:
            x_{t+1}: Updated risk vector of length n, values clipped to [0, 1].
        """

    @abstractmethod
    def detect_cascade(
        self,
        trajectory: list[list[float]],
        i0: int,
        threshold: float,
    ) -> bool:
        """Detect whether a cascade failure occurred in a recorded trajectory.

        Args:
            trajectory: Time-ordered list of risk vectors (trajectory[t] = x_t).
                        Must contain at least two elements (x_0 and x_1).
                        If fewer than two elements are provided, returns False.
            i0:        Index of the *initiating* subsystem — the one that
                        received the original shock.  This sector is excluded
                        from the cascade check.
            threshold: Detection threshold.

                        * For :class:`QuantitativeOperator`: δ — the minimum
                          absolute rise ``x_{i,t} - x_{i,0}`` in a
                          non-initiating sector required to declare a cascade.
                        * For :class:`ClassicalOperator`: θ — the activation
                          level at which a non-initiating sector is considered
                          to have failed.

        Returns:
            ``True`` if a cascade was detected in at least one non-initiating
            subsystem at any time step after t = 0.
        """


# ---------------------------------------------------------------------------
# Quantitative operator
# ---------------------------------------------------------------------------


class QuantitativeOperator(RiskOperator):
    """Continuous risk propagation via the clipped linear map.

    **Dynamics** (one step)::

        x_{t+1} = clip_{[0,1]}(x_t + u_t + A · x_t)

    where ``A · x_t`` is the matrix–vector product capturing cross-sector
    dependencies.

    **Cascade detection**:
        A cascade is flagged when, for any time step t > 0 and any
        non-initiating sector i ≠ i₀, the absolute rise satisfies::

            x_{i,t} - x_{i,0} ≥ δ
    """

    def compute(
        self,
        x_t: list[float],
        u_t: list[float],
        A: list[list[float]],
    ) -> list[float]:
        """Apply one time-step of quantitative risk dynamics.

        Args:
            x_t: Current risk vector (length n, values ∈ [0, 1]).
            u_t: External disturbance vector (length n).
            A:   n×n dependency matrix (values typically ∈ [0, 1]).

        Returns:
            ``clip(x_t + u_t + A·x_t)``, length n.
        """
        n = len(x_t)
        Ax = _matmul_vec(A, x_t)
        return [
            _clip01(float(x_t[i]) + float(u_t[i]) + Ax[i])
            for i in range(n)
        ]

    def detect_cascade(
        self,
        trajectory: list[list[float]],
        i0: int,
        threshold: float,
    ) -> bool:
        """Detect cascade in a quantitative trajectory.

        A cascade is declared if any non-initiating sector *i* (i ≠ i₀) rises
        by at least *threshold* = δ above its initial value at any recorded
        time step.

        Args:
            trajectory: Sequence of risk vectors; trajectory[0] = x_0.
            i0:         Index of the initiating sector (excluded from check).
            threshold:  δ — minimum rise to declare a cascade.

        Returns:
            ``True`` if cascade detected; ``False`` otherwise.
        """
        if len(trajectory) < 2:
            return False
        x0 = trajectory[0]
        n = len(x0)
        for x_t in trajectory[1:]:
            for i in range(n):
                if i == i0:
                    continue
                if float(x_t[i]) - float(x0[i]) >= threshold:
                    return True
        return False


# ---------------------------------------------------------------------------
# Classical (binary) operator
# ---------------------------------------------------------------------------


class ClassicalOperator(RiskOperator):
    """Binary (rule-based) risk propagation operator.

    **Step 1 — Binarisation** (per sector, after applying disturbance)::

        ỹ_i = clip_{[0,1]}(x_i + u_i)
        y_i = I(ỹ_i ≥ θ)   →  ∈ {0, 1}

    **Step 2 — One-step cascade propagation**::

        y_i' = y_i  OR  ∃ j ≠ i : (y_j = 1  AND  A[i][j] ≥ θ)

    Returns risk values in {0.0, 1.0} (binary).

    **Cascade detection**:
        A cascade is declared when any non-initiating sector i (i ≠ i₀)
        reaches the activated state (value ≥ *threshold*) at any recorded
        time step after t = 0.
    """

    def __init__(self, theta: float = 0.5) -> None:
        """Initialise the classical operator.

        Args:
            theta: Binarisation and connectivity threshold **θ_bin** ∈ (0, 1].

                   **Role 1 — Sector activation (binarisation)**::

                       ỹ_i = clip(x_i + u_i)
                       y_i = I(ỹ_i ≥ θ_bin)   →  ∈ {0, 1}

                   A sector is considered *failed* (activated) when its
                   pre-disturbance-adjusted risk meets or exceeds θ_bin.

                   **Role 2 — Dependency-edge activation**::

                       edge (j → i) is active  iff  A[i][j] ≥ θ_bin

                   Only edges whose weight is at or above the same threshold
                   participate in the one-step cascade propagation.

                   .. note::

                       This threshold **θ_bin** is set in ``risk_engine`` config
                       (default ``CLASSICAL_THRESHOLD = 0.5``) and governs
                       *state binarisation* and *graph topology*.  It is
                       **distinct** from the cascade-detection threshold
                       **θ_cascade** (default 0.3) used in ``scenario_simulator``
                       to decide whether an observed sector-risk increment
                       constitutes a cascade event (``I_cl = 1``).

                       The two thresholds play complementary roles in the
                       overall methodology:

                       * ``ClassicalOperator(theta=θ_bin)`` — transforms the
                         continuous risk vector x_t into a binary {0,1} vector
                         and propagates failures one step through the dependency
                         graph.  Source of truth: ``risk_engine/config.py``.

                       * ``theta_cascade`` — applied in
                         ``scenario_simulator`` to the binary delta
                         ``Δx_cl_i,t = x_cl_i,t − x_cl_i,0 ∈ {−1, 0, 1}``
                         to flag a cascade: ``I_cl = 1`` iff
                         ``∃ i ≠ i₀, ∃ t : Δx_cl_i,t ≥ θ_cascade``.
                         Because outputs are binary, any ``θ_cascade ∈ (0,1]``
                         is functionally equivalent to the threshold 0 < θ ≤ 1.
                         Source of truth: ``scenario_simulator/schemas.py``
                         field ``theta_classical``.

        Raises:
            ValueError: If *theta* is not in the range (0, 1].
        """
        if not (0.0 < theta <= 1.0):
            raise ValueError(
                f"theta must be in the range (0, 1], got {theta!r}"
            )
        self.theta: float = theta

    def compute(
        self,
        x_t: list[float],
        u_t: list[float],
        A: list[list[float]],
    ) -> list[float]:
        """Apply one time-step of classical binary propagation.

        The external disturbance *u_t* is applied additively before
        binarisation so that a sudden shock can push a sector above the
        threshold even if its base risk was below it.

        Args:
            x_t: Current risk vector (length n, values ∈ [0, 1]).
            u_t: External disturbance vector (length n).
            A:   n×n dependency matrix.

        Returns:
            Binary risk vector of length n, values in {0.0, 1.0}, after
            disturbance application, binarisation, and one-step propagation.
        """
        n = len(x_t)
        theta = self.theta

        # Step 1: apply disturbance, clip, binarise
        y = [
            1.0 if _clip01(float(x_t[i]) + float(u_t[i])) >= theta else 0.0
            for i in range(n)
        ]

        # Step 2: one-step propagation through active dependency edges
        y_next = list(y)
        for i in range(n):
            if y_next[i] >= 1.0:
                continue  # already active; no change needed
            for j in range(n):
                if y[j] >= 1.0 and float(A[i][j]) >= theta:
                    y_next[i] = 1.0
                    break

        return y_next

    def detect_cascade(
        self,
        trajectory: list[list[float]],
        i0: int,
        threshold: float,
    ) -> bool:
        """Detect cascade in a classical (binary) trajectory.

        A cascade is declared when any non-initiating sector i (i ≠ i₀)
        reaches the activated state (value ≥ *threshold*) at any recorded
        time step after t = 0.

        Args:
            trajectory: Sequence of risk vectors (values expected in {0, 1}).
            i0:         Index of the initiating sector.
            threshold:  Activation level for cascade detection (typically the
                        same θ used to construct this operator).

        Returns:
            ``True`` if cascade detected; ``False`` otherwise.
        """
        if len(trajectory) < 2:
            return False
        n = len(trajectory[0])
        for x_t in trajectory[1:]:
            for i in range(n):
                if i == i0:
                    continue
                if float(x_t[i]) >= threshold:
                    return True
        return False
