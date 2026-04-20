"""Четыре оператора METHODOLOGY §3.

Единый контракт — services.risk_engine.contract.
State machine — services.risk_engine.state_machine (§2.3).
"""
from services.risk_engine.operators.k_leontief import compute_K_leontief
from services.risk_engine.operators.k_cl import compute_K_cl
from services.risk_engine.operators.k_dr import compute_K_DR
from services.risk_engine.operators.k_q import compute_K_q_deg, compute_K_q_abs

__all__ = [
    "compute_K_leontief",
    "compute_K_cl",
    "compute_K_DR",
    "compute_K_q_deg",
    "compute_K_q_abs",
]
