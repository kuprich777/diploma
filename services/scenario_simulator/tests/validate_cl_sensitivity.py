"""Classical cascade model — sensitivity analysis and pattern diagnostics.

Methodology note — role of the classical (cl) method
------------------------------------------------------
The classical operator implemented in ``risk_engine/operators.py`` is a
**deterministic threshold cascade model** in the tradition of threshold-based
systemic-failure propagation approaches in the complex-systems and
critical-infrastructure literature (e.g. Watts 2002-style threshold cascades,
rule-based interdependency models in Rinaldi et al. 2001).

Key properties that define its character as a *reference baseline*:

* **Binary activation**: each sector's risk is binarised at θ_bin = 0.5
  (``CLASSICAL_THRESHOLD`` in risk_engine) → sector is either "operational" (0)
  or "failed" (1).  There is no intermediate distress level.

* **One-step deterministic propagation**: a failed sector j propagates failure
  to sector i in one step iff A[i][j] ≥ θ_bin.  No recursive accumulation.

* **Low resolution**: ΔR_cl ∈ {0, 0.3, 0.4, 0.6, 0.7, 1.0} — a small discrete
  set determined by the sector weights w = {e:0.4, w:0.3, t:0.3}.

* **Deterministic given θ_bin**: for fixed sector risks (no stochastic_scale),
  the cascade outcome is fully determined by whether each sector's risk crosses
  θ_bin after applying the disturbance.  Stochasticity enters only through
  Monte Carlo sampling of (duration, dependency_multiplier).

Relationship to the literature:
    The cl model is *conceptually close* to threshold / percolation cascade
    approaches and rule-based systemic propagation models.  It should NOT be
    described as equivalent to Eisenberg-Noe financial contagion,
    Buldyrev interdependent networks, or DebtRank recursive distress unless
    exact equivalence is demonstrable from the code.  DebtRank-style recursive
    distress accumulation is a *future extension* direction (see section 4 below).

Future extension directions (not implemented):
    1. Recursive distress accumulation (DebtRank-inspired): replace binary
       activation with a continuous distress variable d_i ∈ [0,1] that
       accumulates across propagation rounds until convergence.
    2. External benchmark validation on standard interdependent-infrastructure
       datasets or financial network benchmarks.
    3. Heterogeneous θ_bin per sector (currently θ_bin is uniform = 0.5).

Dual-threshold architecture:
    This script distinguishes the two thresholds used in the pipeline:

    * θ_bin = 0.5  (CLASSICAL_THRESHOLD in risk_engine/config.py)
        Applied by ClassicalOperator to binarise sector risks and activate
        dependency edges.  Fixed at the risk_engine level.

    * θ_cascade = theta_classical (default 0.3 in scenario_simulator)
        Applied in scenario_simulator to decide whether an observed
        Δx_cl_i,t ≥ θ_cascade constitutes a cascade event (I_cl=1).
        Since ClassicalOperator outputs {0,1}, Δx_cl ∈ {-1,0,1}, so any
        θ_cascade ∈ (0,1] gives identical I_cl outcomes.  The sensitivity
        over a θ_cascade grid below is included for methodological
        documentation, not because it changes the substantive results.

Usage:
    python tests/validate_cl_sensitivity.py [--json PATH] [--base-url URL]

    --json PATH   : path to a saved mc_*_full.json (default: search results/)
    --base-url URL: live stack URL for a fresh 300-run experiment
                   (only used if --json not provided and no JSON found)

The script does NOT require a live Docker stack if a saved JSON is available.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path


# ---------------------------------------------------------------------------
# Discrete ΔR_cl levels (documentation)
# ---------------------------------------------------------------------------
# With sector weights {energy:0.4, water:0.3, transport:0.3} and binary
# sector risks ∈ {0,1}, the achievable R_cl values are:
#
#   activated sectors     R_cl   ΔR_cl (from R=0 baseline)
#   ──────────────────    ─────  ─────────────────────────
#   {}                    0.0    0.00
#   {water}               0.3    0.30
#   {transport}           0.3    0.30
#   {energy}              0.4    0.40
#   {water, transport}    0.6    0.60
#   {energy, water}       0.7    0.70
#   {energy, transport}   0.7    0.70
#   {all}                 1.0    1.00
#
# This makes ΔR_cl a coarse-grained indicator suitable as a threshold
# reference, not as a continuous severity measure.

DISCRETE_LEVELS: dict[frozenset, float] = {
    frozenset(): 0.0,
    frozenset({"water"}): 0.3,
    frozenset({"transport"}): 0.3,
    frozenset({"energy"}): 0.4,
    frozenset({"water", "transport"}): 0.6,
    frozenset({"energy", "water"}): 0.7,
    frozenset({"energy", "transport"}): 0.7,
    frozenset({"energy", "water", "transport"}): 1.0,
}

SECTOR_WEIGHTS = {"energy": 0.4, "water": 0.3, "transport": 0.3}


# ---------------------------------------------------------------------------
# HTTP helper (for optional live experiment)
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
        with urllib.request.urlopen(req, timeout=900) as resp:
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
# Cascade-detection at arbitrary θ_cascade (post-processing)
# ---------------------------------------------------------------------------

def _recompute_I_cl(run: dict, theta_cascade: float, initiator: str = "energy") -> int:
    """Re-evaluate I_cl for a saved run at a given theta_cascade.

    Uses ``before_vec_cl`` (baseline) and ``risk_trajectory_cl`` (per-step
    binary vectors) already stored in each MonteCarloRun record.  Does not
    require a live Docker stack.

    Because ClassicalOperator outputs {0,1} values, the delta for each sector
    is in {-1, 0, 1}.  Any theta_cascade ∈ (0,1] gives the same result; the
    function is still parameterised for methodological documentation purposes.
    """
    base_vec = run.get("before_vec_cl") or {}
    trajectory = run.get("risk_trajectory_cl") or []
    non_initiators = [s for s in ("energy", "water", "transport") if s != initiator]

    for step_vec in trajectory:
        for s in non_initiators:
            delta = float(step_vec.get(s, 0.0)) - float(base_vec.get(s, 0.0))
            if delta >= theta_cascade:
                return 1
    return 0


def _activated_sectors(run: dict, theta_cascade: float, initiator: str = "energy") -> frozenset:
    """Return frozenset of non-initiating sectors that triggered cascade."""
    base_vec = run.get("before_vec_cl") or {}
    trajectory = run.get("risk_trajectory_cl") or []
    non_initiators = [s for s in ("energy", "water", "transport") if s != initiator]
    activated: set[str] = set()
    for step_vec in trajectory:
        for s in non_initiators:
            delta = float(step_vec.get(s, 0.0)) - float(base_vec.get(s, 0.0))
            if delta >= theta_cascade:
                activated.add(s)
    return frozenset(activated)


def _first_activation_step(run: dict, theta_cascade: float, initiator: str = "energy") -> int | None:
    """Return 1-based step index of the first classical cascade activation."""
    base_vec = run.get("before_vec_cl") or {}
    trajectory = run.get("risk_trajectory_cl") or []
    non_initiators = [s for s in ("energy", "water", "transport") if s != initiator]
    for step_idx, step_vec in enumerate(trajectory, start=1):
        for s in non_initiators:
            delta = float(step_vec.get(s, 0.0)) - float(base_vec.get(s, 0.0))
            if delta >= theta_cascade:
                return step_idx
    return None


# ---------------------------------------------------------------------------
# Analysis functions
# ---------------------------------------------------------------------------

def _threshold_sensitivity_table(runs: list[dict], thresholds: list[float], initiator: str) -> None:
    """Print K_cl vs theta_cascade sensitivity table.

    Note: since ClassicalOperator outputs binary {0,1} values, all thresholds
    in (0,1] produce identical I_cl results.  The table documents this fact
    explicitly; it is not a bug.
    """
    bar = "─" * 68
    print(f"\n{bar}")
    print("  θ_cascade SENSITIVITY — K_cl (fraction of cascade-detected runs)")
    print(f"  Scenario: energy outage (S1), initiator=energy, n={len(runs)}")
    print(f"  Note: x_cl ∈ {{0,1}} ⟹ Δx_cl ∈ {{−1,0,1}}, so K_cl is constant")
    print(f"  for all θ_cascade ∈ (0,1].  θ_bin = 0.5 (risk_engine ClassicalOperator)")
    print(bar)
    print(f"  {'θ_cascade':>12}  {'K_cl':>8}  {'n_cascades':>12}  {'note':>20}")
    print(f"  {'─'*12}  {'─'*8}  {'─'*12}  {'─'*20}")

    K_cl_prev = None
    for theta in thresholds:
        i_cls = [_recompute_I_cl(r, theta, initiator) for r in runs]
        n_cascades = sum(i_cls)
        K_cl = n_cascades / len(i_cls) if i_cls else 0.0
        note = ""
        if K_cl_prev is not None and abs(K_cl - K_cl_prev) < 1e-9:
            note = "← same (binary)"
        else:
            note = "← θ > 1: no cascade" if theta > 1.0 else ""
        print(f"  {theta:>12.2f}  {K_cl:>8.4f}  {n_cascades:>12}  {note:>20}")
        K_cl_prev = K_cl
    print()


def _activated_sector_patterns(runs: list[dict], theta_cascade: float, initiator: str) -> None:
    """Print frequency table of activated non-initiating sector patterns."""
    bar = "─" * 68
    print(f"\n{bar}")
    print(f"  ACTIVATED-SECTOR PATTERN FREQUENCIES (θ_cascade={theta_cascade})")
    print(f"  Initiator='{initiator}' (excluded).  n={len(runs)}")
    print(bar)

    pattern_counter: Counter = Counter()
    delta_R_cl_by_pattern: dict[str, list[float]] = {}

    for run in runs:
        activated = _activated_sectors(run, theta_cascade, initiator)
        label = "{" + ", ".join(sorted(activated)) + "}" if activated else "{}"
        pattern_counter[label] += 1
        delta_R_cl = float(run.get("method_cl_total_after", 0.0)) - float(run.get("method_cl_total_before", 0.0))
        delta_R_cl_by_pattern.setdefault(label, []).append(delta_R_cl)

    print(f"  {'Pattern':<32}  {'Count':>6}  {'Freq%':>7}  {'mean ΔR_cl':>12}")
    print(f"  {'─'*32}  {'─'*6}  {'─'*7}  {'─'*12}")
    for label, count in sorted(pattern_counter.items(), key=lambda x: -x[1]):
        freq = count / len(runs) * 100
        mean_dR = sum(delta_R_cl_by_pattern[label]) / len(delta_R_cl_by_pattern[label])
        print(f"  {label:<32}  {count:>6}  {freq:>6.1f}%  {mean_dR:>12.4f}")
    print()


def _cl_first_activation_distribution(runs: list[dict], theta_cascade: float, initiator: str) -> None:
    """Print distribution of first-activation step index across cascade runs."""
    bar = "─" * 68
    print(f"\n{bar}")
    print(f"  FIRST ACTIVATION STEP DISTRIBUTION (θ_cascade={theta_cascade})")
    print(f"  Only runs where I_cl=1 (n_cascade runs only)")
    print(bar)

    steps = [_first_activation_step(r, theta_cascade, initiator)
             for r in runs
             if _recompute_I_cl(r, theta_cascade, initiator) == 1]
    if not steps:
        print("  No cascade runs found.")
        return

    counter: Counter = Counter(steps)
    total = len(steps)
    print(f"  {'Step':>6}  {'Count':>6}  {'Freq%':>7}")
    print(f"  {'─'*6}  {'─'*6}  {'─'*7}")
    for step_idx in sorted(counter):
        print(f"  {step_idx:>6}  {counter[step_idx]:>6}  {counter[step_idx]/total*100:>6.1f}%")
    print()


def _discrete_delta_R_cl_distribution(runs: list[dict]) -> None:
    """Print distribution of ΔR_cl discrete levels.

    The classical operator with binary sector risks and weights {e:0.4,w:0.3,t:0.3}
    can only produce R_cl in {0.0, 0.3, 0.4, 0.6, 0.7, 1.0}.  This function
    reports how often each level appears and validates that the observed values
    lie on the expected discrete grid.
    """
    bar = "─" * 68
    print(f"\n{bar}")
    print("  DISCRETE ΔR_cl DISTRIBUTION")
    print("  Expected values: {0.0, 0.3, 0.4, 0.6, 0.7, 1.0}")
    print("  (binary sector risks × weights {e:0.4, w:0.3, t:0.3})")
    print(bar)

    EXPECTED = {0.0, 0.3, 0.4, 0.6, 0.7, 1.0}
    counter: Counter = Counter()
    anomalies: list[float] = []

    for run in runs:
        dR = round(
            float(run.get("method_cl_total_after", 0.0)) - float(run.get("method_cl_total_before", 0.0)),
            6,
        )
        rounded = round(dR, 1)
        counter[rounded] += 1
        if rounded not in EXPECTED:
            anomalies.append(dR)

    total = len(runs)
    print(f"  {'ΔR_cl':>8}  {'Count':>6}  {'Freq%':>7}  {'expected':>10}")
    print(f"  {'─'*8}  {'─'*6}  {'─'*7}  {'─'*10}")
    for level in sorted(counter):
        in_exp = "✓" if level in EXPECTED else "! ANOMALY"
        print(f"  {level:>8.1f}  {counter[level]:>6}  {counter[level]/total*100:>6.1f}%  {in_exp:>10}")
    if anomalies:
        print(f"\n  ⚠ {len(anomalies)} anomalous values: {anomalies[:5]}{'...' if len(anomalies)>5 else ''}")
    else:
        print("\n  ✓ All ΔR_cl values lie on the expected discrete grid.")
    print()


def _summary_assessment(runs: list[dict], theta_cascade: float, initiator: str) -> None:
    """Print a concise methodological summary suitable for thesis reporting."""
    bar = "═" * 68
    print(f"\n{bar}")
    print("  CLASSICAL METHOD — THESIS METHODOLOGY SUMMARY")
    print(f"{bar}")

    i_cls = [_recompute_I_cl(r, theta_cascade, initiator) for r in runs]
    K_cl = sum(i_cls) / len(i_cls) if i_cls else 0.0
    n = len(runs)

    cl_befores = [float(r.get("method_cl_total_before", 0.0)) for r in runs]
    cl_afters  = [float(r.get("method_cl_total_after", 0.0)) for r in runs]
    dR_cl_vals = [a - b for a, b in zip(cl_afters, cl_befores)]
    mean_dR_cl = sum(dR_cl_vals) / n if n else 0.0

    print(f"""
  Method type:     Deterministic threshold cascade (binary, rule-based)
  Reference class: Threshold / percolation cascade models
                   (cf. Rinaldi et al. 2001; Watts 2002-style threshold logic)
  NOT equivalent to: DebtRank, Eisenberg-Noe, Buldyrev interdependent networks

  Architecture:
    θ_bin = 0.5   (ClassicalOperator, risk_engine) — binarisation threshold
    θ_cascade = {theta_cascade}  (scenario_simulator)  — cascade-detection threshold
    Output resolution: ΔR_cl ∈ {{0.0, 0.3, 0.4, 0.6, 0.7, 1.0}} (7 discrete levels)

  Experiment results (n={n}, stochastic_scale=0.3, duration=[5,30]):
    K_cl      = {K_cl:.4f}  (fraction of runs with classical cascade detected)
    mean ΔR_cl = {mean_dR_cl:.4f}

  Interpretation:
    K_cl measures how often the disturbance pushes at least one non-initiating
    sector above θ_bin and through an active dependency edge — a necessary
    condition for a binary cascade in this model.

  Role in thesis:
    The classical method serves as a LOW-RESOLUTION REFERENCE BASELINE.
    It is methodologically comparable to rule-based systemic-propagation models
    and provides a conservative lower bound on cascade frequency.
    Comparison K_q vs K_cl (Δ%) quantifies the additional sensitivity gained
    by the quantitative operator.

  Future extensions (not implemented):
    1. Recursive distress accumulation (DebtRank-inspired feedback)
    2. Heterogeneous θ_bin per sector
    3. External benchmark validation on infrastructure / financial-network data
""")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--json",
        default=None,
        help="Path to saved mc_*_full.json (default: auto-detect in results/)",
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8005",
        help="Base URL for live experiment (used only if no JSON found)",
    )
    parser.add_argument(
        "--initiator",
        default="energy",
        help="Initiator sector (default: energy)",
    )
    args = parser.parse_args()

    # ── 1. Load or acquire experiment data ──────────────────────────────────
    json_path: Path | None = None
    if args.json:
        json_path = Path(args.json)
    else:
        # Auto-detect: prefer the most recent S1 research file in results/
        candidates = sorted(Path(".").glob("results/mc_s1_research_*_full.json"))
        if not candidates:
            candidates = sorted(Path(".").glob("results/*full*.json"))
        if candidates:
            json_path = candidates[-1]

    if json_path and json_path.exists():
        print(f"\nLoading saved experiment data from: {json_path}")
        with open(json_path) as f:
            result = json.load(f)
        print(f"  scenario_id = {result.get('scenario_id')}")
        print(f"  runs        = {result.get('runs')}")
        print(f"  K_cl        = {result.get('K_cl'):.4f}")
        print(f"  K_q         = {result.get('K_q'):.4f}")
        print(f"  θ_cascade   = {result.get('theta_classical', 0.3)}")
    else:
        print("\nNo saved JSON found.  Running fresh 300-run experiment against live stack…")
        url = args.base_url.rstrip("/") + "/api/v1/simulator/monte_carlo"
        print(f"  POST {url}")
        payload = {
            "scenario_id": "S1_energy_outage",
            "sector": "energy",
            "runs": 300,
            "duration_min": 5,
            "duration_max": 30,
            "initiator_action": "outage",
            "theta_classical": 0.3,
            "stochastic_scale": 0.3,
            "mode": "real",
        }
        result = _post(url, payload)
        out = Path("results/mc_s1_cl_sensitivity_full.json")
        out.parent.mkdir(exist_ok=True)
        with open(out, "w") as f:
            json.dump(result, f, indent=2)
        print(f"  Saved → {out}")

    runs = result.get("runs_data", [])
    if not runs:
        print("ERROR: no runs_data in result", file=sys.stderr)
        sys.exit(1)

    initiator = args.initiator
    theta_cascade = float(result.get("theta_classical") or 0.3)

    # ── 2. Threshold sensitivity table ──────────────────────────────────────
    # Includes theta > 1 to show the point where no cascade is possible.
    thresholds = [0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0, 1.01]
    _threshold_sensitivity_table(runs, thresholds, initiator)

    # ── 3. Activated-sector pattern frequencies ──────────────────────────────
    _activated_sector_patterns(runs, theta_cascade, initiator)

    # ── 4. First-activation step distribution ───────────────────────────────
    _cl_first_activation_distribution(runs, theta_cascade, initiator)

    # ── 5. Discrete ΔR_cl distribution ──────────────────────────────────────
    _discrete_delta_R_cl_distribution(runs)

    # ── 6. Thesis methodology summary ───────────────────────────────────────
    _summary_assessment(runs, theta_cascade, initiator)


if __name__ == "__main__":
    main()
