"""Research-mode Monte Carlo validation script.

Runs Monte Carlo experiments against the live Docker stack using the
standard research configuration (stochastic_scale=0.3, runs=300) and
prints thesis-quality statistics.

  stochastic_scale = 0.0  →  deterministic / reproducible baseline
  stochastic_scale = 0.3  →  research mode (standard for thesis experiments)

This script uses the research mode.  Unit/regression tests in test_*.py
remain deterministic and do not call this script.

Usage:
    cd services/scenario_simulator
    python tests/validate_mc_research.py [--runs N] [--base-url URL]

Defaults:
    --runs    300   (minimum for stable K(N); use 100 for a quick check)
    --base-url http://localhost:8005

Requires: live Docker stack (docker compose up).
"""

import argparse
import json
import statistics
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Research-mode experiment configuration
# ---------------------------------------------------------------------------

RESEARCH_STOCHASTIC_SCALE: float = 0.3   # standard for thesis runs
BASELINE_STOCHASTIC_SCALE: float = 0.0   # deterministic / debug

THETA_CLASSICAL: float = 0.3
DURATION_MIN: int = 5
DURATION_MAX: int = 30   # calibrated: [5,60] causes 12% ceiling saturation;
                          # [5,30] gives p95=0.67, 0% saturation, std≈0.20

SCENARIOS: list[dict] = [
    {
        "label": "S1 — Energy Outage (outage, energy)",
        "scenario_id": "S1_energy_outage",
        "sector": "energy",
        "initiator_action": "outage",
    },
    {
        "label": "S3 — Transport Load Increase (load_increase, transport)",
        "scenario_id": "S3_transport_load",
        "sector": "transport",
        "initiator_action": "load_increase",
        "load_amount": 0.25,
    },
]


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _post(url: str, payload: dict) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Cannot reach {url}: {exc.reason}\n"
            "Is the Docker stack running?  Run: docker compose up -d"
        ) from exc


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------

@dataclass
class MCStats:
    label: str
    scenario_id: str
    runs: int
    stochastic_scale: float
    mean_delta: float
    std_delta: float
    min_delta: float
    max_delta: float
    p95_delta: float
    K_cl: float
    K_q: float
    Delta_percent: float
    duration_corr: float | None


def _compute_stats(label: str, scenario_id: str, result: dict, stochastic_scale: float) -> MCStats:
    deltas = [r["delta"] for r in result["runs_data"]]
    std = statistics.pstdev(deltas) if len(deltas) > 1 else 0.0
    return MCStats(
        label=label,
        scenario_id=scenario_id,
        runs=result["runs"],
        stochastic_scale=stochastic_scale,
        mean_delta=result["mean_delta"],
        std_delta=std,
        min_delta=result["min_delta"],
        max_delta=result["max_delta"],
        p95_delta=result["p95_delta"],
        K_cl=result.get("K_cl") or 0.0,
        K_q=result.get("K_q") or 0.0,
        Delta_percent=result.get("Delta_percent") or 0.0,
        duration_corr=result.get("duration_correlation"),
    )


def _print_stats(s: MCStats) -> None:
    bar = "═" * 72
    print(f"\n{bar}")
    print(f"  {s.label}")
    print(f"  scenario_id={s.scenario_id}  runs={s.runs}  stochastic_scale={s.stochastic_scale}")
    print(bar)
    print(f"\n  ── ΔR distribution ──────────────────────────────────")
    print(f"     mean_delta  = {s.mean_delta:+.4f}")
    print(f"     std_delta   = {s.std_delta:.4f}")
    print(f"     min_delta   = {s.min_delta:+.4f}")
    print(f"     max_delta   = {s.max_delta:+.4f}")
    print(f"     p95_delta   = {s.p95_delta:+.4f}")
    print(f"\n  ── Cascade indicators ───────────────────────────────")
    print(f"     K_q         = {s.K_q:.4f}")
    print(f"     K_cl        = {s.K_cl:.4f}")
    print(f"     Δ%          = {s.Delta_percent:.2f}%")
    print(f"\n  ── Correlation ──────────────────────────────────────")
    if s.duration_corr is not None:
        print(f"     duration_corr = {s.duration_corr:.4f}")
    else:
        print(f"     duration_corr = N/A")


def _assessment(stats_list: list[MCStats]) -> None:
    print(f"\n\n{'═' * 72}")
    print("  RESEARCH-MODE ASSESSMENT")
    print(f"{'═' * 72}")
    print(f"\n  {'Scenario':<38} {'std':>7} {'K_q':>7} {'K_cl':>7} {'Δ%':>8}")
    print(f"  {'-'*38} {'-'*7} {'-'*7} {'-'*7} {'-'*8}")
    for s in stats_list:
        print(f"  {s.scenario_id:<38} {s.std_delta:>7.4f} {s.K_q:>7.4f} {s.K_cl:>7.4f} {s.Delta_percent:>8.2f}%")

    ok_std   = all(s.std_delta > 0.05 for s in stats_list)
    ok_Kq    = all(s.K_q > 0 for s in stats_list)
    ok_Kcl   = any(s.K_cl > 0 for s in stats_list)
    ok_delta = any(s.Delta_percent > 0 for s in stats_list)

    print()
    print(f"  Non-degenerate ΔR variance (std > 0.05) : {'✓' if ok_std  else '✗'}")
    print(f"  K_q > 0 for all scenarios               : {'✓' if ok_Kq   else '✗'}")
    print(f"  K_cl > 0 for at least one scenario      : {'✓' if ok_Kcl  else '✗'}")
    print(f"  Δ% > 0 (quantitative detects more)      : {'✓' if ok_delta else '✗'}")

    print("""
  MODE DISTINCTION
  ────────────────────────────────────────────────────────────
  stochastic_scale = 0.0  →  deterministic baseline / debug
      • fully reproducible from (scenario_id, run_id) alone
      • used by all unit tests (test_*.py)

  stochastic_scale = 0.3  →  research mode (this script)
      • dependency_multiplier ~ N(1, 0.3) per run
      • required for thesis-quality K(N) convergence plots
      • must be stated explicitly in methodology section
""")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", type=int, default=300,
                        help="Monte Carlo run count (default 300; use 100 for a quick check)")
    parser.add_argument("--base-url", default="http://localhost:8005",
                        help="Base URL of scenario_simulator service")
    args = parser.parse_args()

    mc_url = args.base_url.rstrip("/") + "/api/v1/simulator/monte_carlo"

    print(f"\nResearch-mode Monte Carlo validation")
    print(f"  base_url        = {args.base_url}")
    print(f"  runs            = {args.runs}")
    print(f"  stochastic_scale= {RESEARCH_STOCHASTIC_SCALE}  ← research mode")
    print(f"  duration        = [{DURATION_MIN}, {DURATION_MAX}] min")
    print(f"  theta_classical = {THETA_CLASSICAL}")

    stats_list: list[MCStats] = []
    failed: list[str] = []

    for scen in SCENARIOS:
        label = scen["label"]
        print(f"\n  Running {label} …", end="", flush=True)

        payload: dict = {
            "scenario_id": scen["scenario_id"],
            "sector": scen["sector"],
            "runs": args.runs,
            "duration_min": DURATION_MIN,
            "duration_max": DURATION_MAX,
            "initiator_action": scen["initiator_action"],
            "theta_classical": THETA_CLASSICAL,
            "stochastic_scale": RESEARCH_STOCHASTIC_SCALE,
            "mode": "real",
        }
        if "load_amount" in scen:
            payload["load_amount"] = scen["load_amount"]

        try:
            result = _post(mc_url, payload)
            s = _compute_stats(label, scen["scenario_id"], result, RESEARCH_STOCHASTIC_SCALE)
            stats_list.append(s)
            _print_stats(s)
        except RuntimeError as exc:
            print(f"\n  ✗ FAILED: {exc}")
            failed.append(label)

    if stats_list:
        _assessment(stats_list)

    if failed:
        print(f"\n  ✗ {len(failed)} scenario(s) failed: {failed}")
        sys.exit(1)


if __name__ == "__main__":
    main()
