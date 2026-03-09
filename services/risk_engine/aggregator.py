"""Risk aggregation: compute the integral infrastructure risk R_t = Agg(x_t, w).

The :class:`RiskAggregator` accepts a weights mapping and exposes two
aggregation methods:

- :meth:`~RiskAggregator.aggregate` — dict-based (sector name → risk value)
- :meth:`~RiskAggregator.aggregate_vector` — positional lists of names and values

Weights are normalised internally, so callers may pass raw (un-normalised)
weights without pre-dividing by their sum.  Misconfiguration (empty weights,
negative values, zero total) raises :exc:`ValueError` at construction time,
giving early and explicit failure rather than a silent division-by-zero.
"""

from __future__ import annotations


class RiskAggregator:
    """Compute integral infrastructure risk as a normalised weighted mean.

    Formula::

        R_t = (Σ_i w_i · x_i) / (Σ_i w_i)

    where the sum runs over all sectors present in *weights*, and x_i ∈ [0, 1]
    is the (optionally dependency-adjusted) risk of sector i.

    The result is clipped to [0, 1] as a defensive measure against callers that
    supply x_t values outside the valid range.

    Example::

        agg = RiskAggregator({"energy": 0.4, "water": 0.3, "transport": 0.3})
        R = agg.aggregate({"energy": 0.8, "water": 0.5, "transport": 0.2})
    """

    def __init__(self, weights: dict[str, float]) -> None:
        """Initialise the aggregator.

        Args:
            weights: Mapping from sector name to its non-negative weight.
                     The values do not need to sum to 1 — normalisation is
                     handled internally.  Example::

                         {"energy": 0.4, "water": 0.3, "transport": 0.3}

        Raises:
            ValueError: If *weights* is empty, contains any negative value, or
                        if the total sum of weights is zero.
        """
        if not weights:
            raise ValueError("weights must not be empty")

        for name, value in weights.items():
            if value < 0.0:
                raise ValueError(
                    f"weight for sector '{name}' must be >= 0, got {value!r}"
                )

        total = sum(weights.values())
        if total <= 0.0:
            raise ValueError(
                f"sum of weights must be > 0, got {total!r}"
            )

        self._weights: dict[str, float] = {k: float(v) for k, v in weights.items()}
        self._total: float = float(total)

    @property
    def weights(self) -> dict[str, float]:
        """Read-only copy of the sector weights mapping."""
        return dict(self._weights)

    @property
    def total_weight(self) -> float:
        """Sum of all sector weights (used as the normalisation denominator)."""
        return self._total

    def aggregate(self, x_t: dict[str, float]) -> float:
        """Compute the integral risk R_t from a sector-name → risk mapping.

        Only the sectors present in *self.weights* are included in the
        computation.  Extra keys in *x_t* are silently ignored.

        Args:
            x_t: Mapping from sector name to its current risk value ∈ [0, 1].
                 Every sector listed in *self.weights* must appear in *x_t*.

        Returns:
            R_t ∈ [0, 1] — the normalised weighted mean risk.

        Raises:
            KeyError:  If a sector in *self.weights* is absent from *x_t*.
            TypeError: If a risk value cannot be converted to ``float``.
        """
        numerator = sum(
            self._weights[sector] * float(x_t[sector])
            for sector in self._weights
        )
        result = numerator / self._total
        # Defensive clip in case caller passes values outside [0, 1]
        return max(0.0, min(1.0, result))

    def aggregate_vector(
        self,
        sectors: list[str],
        x_t: list[float],
    ) -> float:
        """Compute the integral risk R_t from positional sector lists.

        Convenience overload for callers that already have the sector names and
        risk values as aligned lists (e.g. after calling
        :meth:`~operators.RiskOperator.compute`).

        Args:
            sectors: Ordered list of sector names, length n.
            x_t:     Risk values aligned with *sectors*, length n.

        Returns:
            R_t ∈ [0, 1].

        Raises:
            KeyError:  If any sector in *self.weights* is absent from *sectors*.
            TypeError: If a risk value cannot be converted to ``float``.
        """
        return self.aggregate(dict(zip(sectors, x_t)))
