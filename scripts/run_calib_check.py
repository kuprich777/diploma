#!/usr/bin/env python3
"""
Quick calibration check: N=100 per scenario to verify K_cl is in (0.2, 0.7).
For scenarios outside the range, suggests adjusted amount.
"""
import asyncio
import json
import sys
import httpx

SIM_URL = "http://localhost:8005/api/v1/simulator/monte_carlo"

SCENARIOS = [
    # (scenario_id, description, amount override or None)
    ("S1_energy_outage",   "S1 reference (should saturate)",   None),
    ("S1b_energy_partial", "S1b partial energy",               None),
    ("S3_transport_load",  "S3 transport load",                None),
    ("S4_water_partial",   "S4 water partial",                 None),
    ("S5_combined_hurricane", "S5 combined Sandy",             None),
]


async def run_mc(scenario_id: str, n_runs: int = 100, run_id_base: int = 7000,
                 amount: float | None = None) -> dict:
    payload = {
        "scenario_id": scenario_id,
        "n_runs": n_runs,
        "stochastic_scale": 0.3,
        "theta_classical": 0.3,
        "duration_min": 5,
        "duration_max": 30,
        "propagation_depth": 1,
        "run_id": run_id_base,
    }
    if amount is not None:
        payload["load_amount"] = amount

    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(SIM_URL, json=payload)
        resp.raise_for_status()
        return resp.json()


async def main():
    print(f"{'Scenario':<28} {'K_cl':>6} {'K_q':>6} {'ΔK':>6} {'Δ%':>6} {'Status'}")
    print("-" * 70)
    for i, (sid, desc, amount) in enumerate(SCENARIOS):
        try:
            result = await run_mc(sid, n_runs=100, run_id_base=7000 + i * 10, amount=amount)
            k_cl = result.get("K_cl", 0.0)
            k_q  = result.get("K_q",  0.0)
            dk   = k_q - k_cl
            pct  = (dk / k_cl * 100) if k_cl > 0 else float("inf")
            ok   = "OK" if 0.2 <= k_cl <= 0.7 else ("SAT" if k_cl > 0.7 else "LOW")
            print(f"{sid:<28} {k_cl:>6.3f} {k_q:>6.3f} {dk:>6.3f} {pct:>5.0f}% {ok}")
        except Exception as e:
            print(f"{sid:<28} ERROR: {e}")


if __name__ == "__main__":
    asyncio.run(main())
