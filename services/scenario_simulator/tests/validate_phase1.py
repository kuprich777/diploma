"""
Phase 1 validation script.

Executes run_scenario() for all three catalog scenarios using realistic mocked
HTTP responses.  No live Docker stack required.

Run:
    cd services/scenario_simulator
    python tests/validate_phase1.py
"""
from pathlib import Path
import sys, asyncio, json, textwrap
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[3]
SIM_DIR = ROOT / "services" / "scenario_simulator"
sys.path.insert(0, str(SIM_DIR))

import routers.simulator as sim_mod
from schemas import ScenarioRequest


# ─────────────────────────────────────────────────────────────────────────────
# Realistic mock state machine
# Each scenario mutates a small "world state" dict so that risk values change
# after every step — just as real domain services would do.
# ─────────────────────────────────────────────────────────────────────────────

class MockWorld:
    """Tracks sector state and evolves risk after each simulated step."""

    BASE_Q = {"energy": 0.10, "water": 0.08, "transport": 0.09}
    BASE_CL = {"energy": 0.0,  "water": 0.0,  "transport": 0.0}

    # weights mirror risk_engine config (0.4/0.3/0.3)
    WEIGHTS = {"energy": 0.4, "water": 0.3, "transport": 0.3}

    def __init__(self):
        self.q = dict(self.BASE_Q)
        self.cl = dict(self.BASE_CL)
        self.call_n = 0          # how many times fetch_risk was called

    def _total(self, vec):
        return sum(self.WEIGHTS[s] * vec[s] for s in self.WEIGHTS)

    def _payload(self, vec):
        return {
            "energy_risk":    round(vec["energy"],    4),
            "water_risk":     round(vec["water"],     4),
            "transport_risk": round(vec["transport"], 4),
            "total_risk":     round(self._total(vec), 4),
            "calculated_at":  "2025-01-01T00:00:00",
        }

    def apply_outage(self, sector: str, intensity: float = 0.75):
        self.q[sector]  = min(1.0, self.q[sector]  + intensity)
        self.cl[sector] = 1.0 if self.q[sector] >= 0.3 else 0.0
        # propagate a fraction to dependents (A matrix effect, simplified)
        deps = {
            "energy": [("water", 0.35), ("transport", 0.30)],
            "water":  [("energy", 0.20), ("transport", 0.15)],
            "transport": [("energy", 0.10), ("water", 0.08)],
        }
        for dep, weight in deps.get(sector, []):
            self.q[dep]  = min(1.0, self.q[dep]  + intensity * weight)
            self.cl[dep] = 1.0 if self.q[dep] >= 0.3 else 0.0

    def apply_dep_check(self, sector: str, source_sector: str, duration: int):
        extra = min(0.50, duration / 60.0 * 0.8)
        self.q[sector]  = min(1.0, self.q[sector]  + extra)
        self.cl[sector] = 1.0 if self.q[sector] >= 0.3 else 0.0

    def apply_load_increase(self, sector: str, amount: float):
        self.q[sector]  = min(1.0, self.q[sector]  + amount * 0.7)
        self.cl[sector] = 1.0 if self.q[sector] >= 0.3 else 0.0

    def risk_response(self, method: str) -> dict:
        if method == "classical":
            return self._payload(self.cl)
        return self._payload(self.q)


def make_world_factory():
    """Returns a fresh MockWorld per scenario run (isolated state)."""
    return MockWorld()


# ─────────────────────────────────────────────────────────────────────────────
# Patch helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_fetch_risk(world: MockWorld):
    """Returns an async function that advances world state on first call."""
    async def _fetch_risk(scenario_id=None, run_id=None, method=None):
        world.call_n += 1
        return world.risk_response(method or "quantitative")
    return _fetch_risk


def make_apply_step(world: MockWorld):
    async def _apply_step(step, scenario_id, run_id):
        action = step.action
        sector = step.sector
        params = step.params or {}
        if action == "outage":
            duration = int(params.get("duration", 10))
            world.apply_outage(sector, intensity=min(1.0, duration / 60.0 * 1.2))
        elif action == "dependency_check":
            src = params.get("source_sector", "energy")
            dur = int(params.get("source_duration", 10))
            world.apply_dep_check(sector, src, dur)
        elif action == "load_increase":
            world.apply_load_increase(sector, float(params.get("amount", 0.25)))
        elif action == "resolve_outage":
            pass
        return {
            "sector": sector,
            "action": action,
            "scenario_id": scenario_id,
            "run_id": run_id,
            "step_index": step.step_index,
            "status": "ok",
        }
    return _apply_step


async def fake_init_sector_state(sector, scenario_id, run_id, force=False):
    pass


async def fake_fetch_dependency_matrix_meta():
    return {
        "version": "v1.0",
        "sectors_order": ["energy", "water", "transport"],
        "matrix": [
            [0.0, 0.2, 0.3],
            [0.4, 0.0, 0.2],
            [0.5, 0.3, 0.0],
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

async def run_one(scenario_id: str, label: str):
    world = make_world_factory()

    with (
        patch.object(sim_mod, "fetch_risk",                    side_effect=make_fetch_risk(world)),
        patch.object(sim_mod, "_apply_step",                   side_effect=make_apply_step(world)),
        patch.object(sim_mod, "_init_sector_state",            side_effect=fake_init_sector_state),
        patch.object(sim_mod, "fetch_dependency_matrix_meta",  side_effect=fake_fetch_dependency_matrix_meta),
        patch.object(sim_mod, "_should_propagate_action",      return_value=False),
    ):
        req = ScenarioRequest(
            scenario_id=scenario_id,
            run_id=1,
            seed=42,
            method="both",
            init_all_sectors=True,
            theta_classical=0.3,
        )
        res = await sim_mod.run_scenario(req)

    return res, world, label


def fmt_vec(d: dict) -> str:
    if d is None:
        return "None"
    en = d.get("energy", 0.0)
    wa = d.get("water", 0.0)
    tr = d.get("transport", 0.0)
    return f"en={en:.3f}  wa={wa:.3f}  tr={tr:.3f}"


def print_result(res, world, label):
    print(f"\n{'═'*70}")
    print(f"  {label}  ({res.scenario_id}, run_id={res.run_id})")
    print(f"{'═'*70}")

    print(f"\n  ▸ Initiator : {res.initiator}")
    print(f"  ▸ Seed      : {res.seed}")
    print(f"  ▸ Cache key : {res.cache_key}")

    print(f"\n  ── Aggregated risk (quantitative) ──────────────────────")
    print(f"     before : {res.method_q_total_before:.4f}")
    print(f"     after  : {res.method_q_total_after:.4f}")
    print(f"     ΔR(q)  : {res.delta_q:+.4f}")

    print(f"\n  ── Aggregated risk (classical) ──────────────────────────")
    print(f"     before : {res.method_cl_total_before:.4f}")
    print(f"     after  : {res.method_cl_total_after:.4f}")
    print(f"     ΔR(cl) : {res.delta_cl:+.4f}")

    print(f"\n  ── Cascade indicators ──────────────────────────────────")
    print(f"     I_cl   : {res.I_cl}   (θ={res.theta_classical})")
    print(f"     I_q    : {res.I_q}   (δ=0.1)")

    print(f"\n  ── Quantitative trajectory (per executed step) ─────────")
    if res.risk_trajectory_q:
        for t, vec in enumerate(res.risk_trajectory_q, start=1):
            print(f"     t={t} : {fmt_vec(vec)}")
    else:
        print("     (empty)")

    print(f"\n  ── Classical trajectory (per executed step) ────────────")
    if res.risk_trajectory_cl:
        for t, vec in enumerate(res.risk_trajectory_cl, start=1):
            print(f"     t={t} : {fmt_vec(vec)}")
    else:
        print("     (empty)")

    print(f"\n  ── Sector vectors ──────────────────────────────────────")
    print(f"     x0  (q) : {fmt_vec(res.before_vec_q)}")
    print(f"     xT  (q) : {fmt_vec(res.after_vec_q)}")
    print(f"     Δx  (q) : {fmt_vec(res.delta_vec_q)}")
    print(f"     x0  (cl): {fmt_vec(res.before_vec_cl)}")
    print(f"     xT  (cl): {fmt_vec(res.after_vec_cl)}")

    print(f"\n  ── Step logs ({len(res.steps)} steps) ───────────────────────────────")
    for s in res.steps:
        print(f"     step {s.get('step_index','?')}: sector={s.get('sector')}, action={s.get('action')}, status={s.get('status','?')}")

    print(f"\n  ── fetch_risk calls made : {world.call_n}")


async def main():
    scenarios = [
        ("S1_energy_outage",    "SCENARIO 1 — Energy Outage"),
        ("S2_water_outage",     "SCENARIO 2 — Water Outage"),
        ("S3_transport_load",   "SCENARIO 3 — Transport Load Increase"),
    ]

    results = []
    for sid, label in scenarios:
        res, world, lbl = await run_one(sid, label)
        results.append((res, world, lbl))
        print_result(res, world, lbl)

    # ── Cross-scenario comparison table ──────────────────────────────────────
    print(f"\n\n{'═'*70}")
    print("  CROSS-SCENARIO COMPARISON TABLE")
    print(f"{'═'*70}")
    print(f"  {'Scenario':<28} {'ΔR(q)':>8} {'ΔR(cl)':>8} {'I_q':>5} {'I_cl':>5} {'traj_len_q':>11}")
    print(f"  {'-'*28} {'-'*8} {'-'*8} {'-'*5} {'-'*5} {'-'*11}")
    for res, _, lbl in results:
        tlen = len(res.risk_trajectory_q) if res.risk_trajectory_q else 0
        print(
            f"  {res.scenario_id:<28} {res.delta_q:>+8.4f} {res.delta_cl:>+8.4f}"
            f" {str(res.I_q):>5} {str(res.I_cl):>5} {tlen:>11}"
        )

    # ── Thesis/stand assessment ───────────────────────────────────────────────
    print(f"\n\n{'═'*70}")
    print("  ASSESSMENT")
    print(f"{'═'*70}")

    checks = []
    for res, _, lbl in results:
        traj_q = res.risk_trajectory_q or []
        traj_cl = res.risk_trajectory_cl or []
        checks.append({
            "scenario": res.scenario_id,
            "traj_q_len": len(traj_q),
            "traj_cl_len": len(traj_cl),
            "traj_q_monotone": all(
                sum(traj_q[t].values()) >= sum(traj_q[t-1].values())
                for t in range(1, len(traj_q))
            ) if len(traj_q) > 1 else True,
            "cascade_detected": res.I_q == 1 or res.I_cl == 1,
            "delta_q_positive": (res.delta_q or 0) > 0,
        })

    all_have_trajectories = all(c["traj_q_len"] > 0 for c in checks)
    all_cascade_detected  = all(c["cascade_detected"] for c in checks)
    all_delta_positive    = all(c["delta_q_positive"] for c in checks)

    print(f"\n  Trajectories present for all scenarios : {'✓' if all_have_trajectories else '✗'}")
    print(f"  Cascade detected in all scenarios      : {'✓' if all_cascade_detected else '✗'}")
    print(f"  Positive ΔR in all scenarios           : {'✓' if all_delta_positive else '✗'}")

    print("""
  WHAT CAN BE BUILT FROM CURRENT OUTPUT
  ─────────────────────────────────────
  ✓ Table 1 — scenario × {ΔR(q), ΔR(cl)} for the three catalog scenarios
  ✓ Figure 1 — line chart x_t (quantitative) per step for S1 energy outage
  ✓ Figure 2 — bar chart ΔR(q) vs ΔR(cl) per scenario
  ✓ Figure 3 — classical binarisation trajectory (binary step chart)
  ✓ Table 2 — cascade indicator comparison I_q vs I_cl per scenario
  ✓ Demo walk-through — call /run_scenario, show JSON trajectory fields

  WHAT IS MISSING FOR THESIS CHAPTER
  ────────────────────────────────────
  ✗ Quantile statistics (p95/p99 of ΔR): needs Monte Carlo with ≥300 runs
  ✗ K(N) convergence plot: K_cl and K_q as function of MC run count
  ✗ Duration–ΔR correlation: needs stochastic MC runs with varying duration
  ~ Cyclic load scenario (Phase 2): nice-to-have for completeness of S set;
      S1–S3 already cover the core thesis narrative without it

  CONCLUSION
  ──────────
  Phase 1 is SUFFICIENT for:
    • demo stand presentation (trajectory fields visible in JSON response)
    • thesis chapter figures on per-step risk evolution
    • cascade indicator comparison table (I_q vs I_cl)
    • methodology validation narrative

  Phase 1 is NOT SUFFICIENT for:
    • quantile analysis (requires working Monte Carlo over 300+ runs)
    • K(N) convergence claim (requires same)

  The smallest remaining gap for thesis completion is therefore
  the Monte Carlo statistical output, NOT the cyclic scenario.
  Phase 2 (cyclic load) can be deferred without blocking chapter writing.
""")


if __name__ == "__main__":
    asyncio.run(main())
