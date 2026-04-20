"""
Inoperability Input-Output Model — canonical Haimes-Santos 2005 form.

    q = (I - A*)^{-1} * c*

where A* = A * (x_j / x_i) (Haimes 2005 Part I eq. 11), q is the stationary
inoperability vector, c* is the direct perturbation vector.

No Monte Carlo, no temporal dynamics, no stochasticity — one linear solve
per scenario. The iterative/stochastic IIM implementation used in
mc_harness.py (services/risk_engine/cascade_operators.py::IIMOperator)
remains for cross-method comparison; this module is the canonical baseline
used for MAE validation against NLDR.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np


class IIMCanonical:
    """Canonical IIM, Haimes-Santos 2005."""

    def __init__(self, matrix_A_star: np.ndarray, sectors: list[str]) -> None:
        self.A_star = np.asarray(matrix_A_star, dtype=float)
        self.sectors = list(sectors)
        self.n = len(self.sectors)
        assert self.A_star.shape == (self.n, self.n), (
            f"A* shape {self.A_star.shape} mismatches {self.n} sectors"
        )
        self.I = np.eye(self.n)

        rho = float(np.max(np.abs(np.linalg.eigvals(self.A_star))))
        assert rho < 1.0, f"rho(A*) = {rho} >= 1.0, (I - A*) not invertible"
        self.spectral_radius = rho

    @classmethod
    def from_json(cls, path: str | Path) -> "IIMCanonical":
        data = json.loads(Path(path).read_text())
        return cls(np.array(data["matrix"]), data["sectors"])

    def predict(self, c_star: np.ndarray) -> np.ndarray:
        """Stationary inoperability q = (I - A*)^{-1} c*, clipped to [0, 1]."""
        c = np.asarray(c_star, dtype=float)
        assert c.shape == (self.n,), f"c* shape {c.shape} != ({self.n},)"
        q = np.linalg.solve(self.I - self.A_star, c)
        return np.clip(q, 0.0, 1.0)

    def predict_for_event(self, event: dict) -> dict[str, float]:
        """Prediction for a cascade_events.yaml record."""
        initiator = event["initiator"]["sector"]
        amplitude = float(event["initiator"]["amplitude"])
        c_star = np.zeros(self.n)
        c_star[self.sectors.index(initiator)] = amplitude
        q = self.predict(c_star)
        return {self.sectors[i]: float(q[i]) for i in range(self.n)}
