"""
Build reporting datasets for diploma stand from existing results/.

Outputs:
  reporting/reporting_runs_master.csv         — all runs from main experiments
  reporting/reporting_runs_showcase.csv       — selected showcase runs with labels
  reporting/reporting_scenarios_summary.csv   — per-scenario aggregate comparison
  reporting/reporting_trajectories_long.csv   — long-format sector trajectories
  reporting/reporting_threshold_analysis.csv  — scatter/threshold diagnostics
"""

import csv
import json
import math
import os
import random
from pathlib import Path

REPO = Path(__file__).parent.parent
RESULTS = REPO / "results"
OUT = REPO / "reporting"
OUT.mkdir(exist_ok=True)

SECTORS = ["energy", "water", "transport"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def jdump(obj):
    """Serialize obj to compact JSON string for CSV embedding."""
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def load_full_json(path):
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    for k in ("runs_data", "runs"):
        if k in data and isinstance(data[k], list):
            return data[k]
    raise ValueError(f"Cannot find run list in {path}")


def build_pseudo_trajectory_q(run):
    """
    Construct a 2-step risk trajectory [before_vec, after_vec] per sector
    from run data. Returns dict {sector: [before, after]}.
    """
    bv = run.get("before_vec_q") or {}
    av = run.get("after_vec_q") or {}
    traj = {}
    for s in SECTORS:
        traj[s] = [round(bv.get(s, 0), 6), round(av.get(s, 0), 6)]
    return traj


def build_pseudo_trajectory_cl(run):
    bv = run.get("before_vec_cl") or {}
    av = run.get("after_vec_cl") or {}
    traj = {}
    for s in SECTORS:
        traj[s] = [round(bv.get(s, 0), 6), round(av.get(s, 0), 6)]
    return traj


def safe_float(x, ndigits=6):
    if x is None:
        return ""
    try:
        v = float(x)
        return "" if math.isnan(v) else round(v, ndigits)
    except (TypeError, ValueError):
        return ""


def normalize_run(run, scenario_name, stochastic_scale, theta_node):
    """Return a flat dict with the master schema columns."""
    # Build pseudo-trajectories (before→after step)
    traj_q = build_pseudo_trajectory_q(run)
    traj_cl = build_pseudo_trajectory_cl(run)

    return {
        "run": run.get("run", ""),
        "run_id": run.get("run_id", ""),
        "seed": run.get("seed", ""),
        "before": safe_float(run.get("before")),
        "after": safe_float(run.get("after")),
        "delta": safe_float(run.get("delta")),
        "duration": run.get("duration", ""),
        "I_q": run.get("I_q", ""),
        "I_cl": run.get("I_cl", ""),
        "theta_classical": safe_float(run.get("theta_classical", 0.3)),
        "delta_sector_threshold": safe_float(run.get("delta_sector_threshold", 0.1)),
        "method_q_total_before": safe_float(run.get("method_q_total_before")),
        "method_q_total_after": safe_float(run.get("method_q_total_after")),
        "method_cl_total_before": safe_float(run.get("method_cl_total_before")),
        "method_cl_total_after": safe_float(run.get("method_cl_total_after")),
        "delta_R": safe_float(run.get("delta_R")),
        "stochastic_scale": stochastic_scale,
        "risk_trajectory_q": jdump(traj_q),
        "risk_trajectory_cl": jdump(traj_cl),
        "before_vec_q": jdump(run.get("before_vec_q")),
        "after_vec_q": jdump(run.get("after_vec_q")),
        "delta_vec_q": jdump(run.get("delta_vec_q")),
        "before_vec_cl": jdump(run.get("before_vec_cl")),
        "after_vec_cl": jdump(run.get("after_vec_cl")),
        "delta_vec_cl": jdump(run.get("delta_vec_cl")),
        # --- derived/supplemental
        "scenario_name": scenario_name,
        "cl_activated_sectors": jdump(run.get("cl_activated_sectors")),
        "cl_first_activation_step": run.get("cl_first_activation_step", ""),
        "step_1_amount": safe_float((run.get("randomized_params") or {}).get("step_1_amount")),
        "theta_node": theta_node,
    }


MASTER_COLS = [
    "run", "run_id", "seed", "before", "after", "delta", "duration",
    "I_q", "I_cl", "theta_classical", "delta_sector_threshold",
    "method_q_total_before", "method_q_total_after",
    "method_cl_total_before", "method_cl_total_after",
    "delta_R", "stochastic_scale",
    "risk_trajectory_q", "risk_trajectory_cl",
    "before_vec_q", "after_vec_q", "delta_vec_q",
    "before_vec_cl", "after_vec_cl", "delta_vec_cl",
]

MASTER_EXTRA = [
    "scenario_name", "cl_activated_sectors", "cl_first_activation_step",
    "step_1_amount", "theta_node",
]

# ---------------------------------------------------------------------------
# Main experiment inventory
# (scenario_name, full_json_path, stochastic_scale, theta_node, role)
# ---------------------------------------------------------------------------

EXPERIMENTS = [
    # Saturated baseline (extreme)
    {
        "scenario_name": "S1_energy_outage",
        "scenario_label": "S1: Energy Outage (Saturated)",
        "role": "extreme",
        "full_json": RESULTS / "mc_baseline_theta070_1000_full.json",
        "stochastic_scale": 0.3,
        "theta_node": 0.70,
        "K_cl": 1.000, "K_q": 1.000,
        "mean_delta_R": 0.491, "p95_delta_R": 0.553,
        "runs": 1000,
        "mean_duration": None,
        "artifact_prefix": "mc_baseline_theta070_1000",
        "interpretation": (
            "Full energy outage drives all sectors past theta_node=0.70. "
            "Both methods detect 100% cascades — saturated regime. "
            "Useful as extreme reference; cannot distinguish methods."
        ),
        "recommended_for_stand": 1,
    },
    # Marginal calibrated scenario (primary comparison)
    {
        "scenario_name": "S3_transport_load",
        "scenario_label": "S3: Transport Load +40% (Marginal)",
        "role": "marginal",
        "full_json": RESULTS / "mc_marginal_s3_load040_1000_full.json",
        "stochastic_scale": 0.3,
        "theta_node": 0.70,
        "K_cl": 0.534, "K_q": 0.956,
        "mean_delta_R": 0.309, "p95_delta_R": 0.380,
        "runs": 1000,
        "mean_duration": None,
        "artifact_prefix": "mc_marginal_s3_load040_1000",
        "interpretation": (
            "Transport load +40%. K_q=0.956 >> K_cl=0.534, gap=42.2pp. "
            "Quantitative fires when load>=0.135 (continuous propagation); "
            "classical needs threshold crossing at load>=0.401. "
            "Primary case for demonstrating method gap. FPR=0 confirmed."
        ),
        "recommended_for_stand": 1,
    },
    # S1b partial energy degradation
    {
        "scenario_name": "S1b_energy_partial",
        "scenario_label": "S1b: Energy Partial Degradation",
        "role": "partial_degradation",
        "full_json": RESULTS / "mc_s1b_1000_full.json",
        "stochastic_scale": 0.3,
        "theta_node": 0.70,
        "K_cl": 0.423, "K_q": 0.631,
        "mean_delta_R": 0.196, "p95_delta_R": 0.379,
        "runs": 1000,
        "mean_duration": None,
        "artifact_prefix": "mc_s1b_1000",
        "interpretation": (
            "Small energy load (+1%). K_q=0.631 > K_cl=0.423, gap=20.8pp. "
            "Shows that even tiny perturbations are detectable by quantitative "
            "method when propagated through high-weight energy->other edges."
        ),
        "recommended_for_stand": 0,
    },
    # S4 partial water degradation
    {
        "scenario_name": "S4_water_partial",
        "scenario_label": "S4: Water Partial Degradation +70%",
        "role": "partial_degradation",
        "full_json": RESULTS / "mc_s4_1000_full.json",
        "stochastic_scale": 0.3,
        "theta_node": 0.70,
        "K_cl": 0.416, "K_q": 0.876,
        "mean_delta_R": 0.319, "p95_delta_R": 0.553,
        "runs": 1000,
        "mean_duration": None,
        "artifact_prefix": "mc_s4_1000",
        "interpretation": (
            "Water load +70%. K_q=0.876 >> K_cl=0.416, gap=46.0pp — largest "
            "absolute gap across all N=1000 experiments. Water->energy->transport "
            "cascade detectable quantitatively before threshold crossing."
        ),
        "recommended_for_stand": 1,
    },
]

# ---------------------------------------------------------------------------
# Step 1: Load all run data for main experiments
# ---------------------------------------------------------------------------

print("Loading run data ...")
all_normalized = []  # list of normalized run dicts

for exp in EXPERIMENTS:
    print(f"  Loading {exp['scenario_name']} ...")
    runs = load_full_json(exp["full_json"])
    for run in runs:
        norm = normalize_run(
            run,
            scenario_name=exp["scenario_name"],
            stochastic_scale=exp["stochastic_scale"],
            theta_node=exp["theta_node"],
        )
        all_normalized.append(norm)

print(f"  Total runs loaded: {len(all_normalized)}")

# ---------------------------------------------------------------------------
# Step 2: Write reporting_runs_master.csv
# ---------------------------------------------------------------------------

print("\nWriting reporting_runs_master.csv ...")
master_path = OUT / "reporting_runs_master.csv"
master_fieldnames = MASTER_COLS + MASTER_EXTRA

with open(master_path, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=master_fieldnames, extrasaction="ignore")
    w.writeheader()
    w.writerows(all_normalized)

print(f"  Written: {master_path} ({len(all_normalized)} rows)")

# ---------------------------------------------------------------------------
# Step 3: Select showcase runs
# ---------------------------------------------------------------------------

print("\nSelecting showcase runs ...")


def get_sector_value(run_dict, vec_key, sector):
    """Extract a scalar sector value from a JSON-serialized vector string."""
    raw = run_dict.get(vec_key, "")
    if not raw:
        return None
    try:
        obj = json.loads(raw) if isinstance(raw, str) else raw
        return obj.get(sector)
    except Exception:
        return None


def classify_case(run_dict):
    i_q = int(run_dict.get("I_q", 0))
    i_cl = int(run_dict.get("I_cl", 0))
    if i_q == 1 and i_cl == 0:
        return "q_only"
    elif i_q == 1 and i_cl == 1:
        return "both_detect"
    elif i_q == 0 and i_cl == 0:
        return "both_miss"
    else:
        return "cl_only"  # theoretically impossible (classical ⊆ quantitative)


# Separate by scenario
by_scenario = {}
for r in all_normalized:
    sn = r["scenario_name"]
    by_scenario.setdefault(sn, []).append(r)

showcase_runs = []


def add_showcase(run_dict, scenario_type, case_label, selection_reason):
    d = dict(run_dict)
    d["scenario_label"] = next(
        e["scenario_label"] for e in EXPERIMENTS if e["scenario_name"] == d["scenario_name"]
    )
    d["scenario_type"] = scenario_type
    d["case_label"] = case_label
    d["selection_reason"] = selection_reason
    showcase_runs.append(d)


# --- S1 extreme examples (take 5 representative runs)
s1_runs = by_scenario["S1_energy_outage"]
random.seed(42)

# All S1 runs have I_q=1, I_cl=1 (saturated) — pick by varying delta_R
s1_sorted_delta = sorted(s1_runs, key=lambda r: float(r["delta_R"] or 0), reverse=True)

# max delta_R
add_showcase(s1_sorted_delta[0], "extreme", "max_delta",
             "S1 saturated: maximum delta_R run — strongest cascade in extreme scenario")

# median delta_R (rank ~500 of 1000)
add_showcase(s1_sorted_delta[499], "extreme", "both_detect",
             "S1 saturated: median delta_R run — typical cascade in extreme scenario")

# min delta_R (still both_detect because saturated)
add_showcase(s1_sorted_delta[-1], "extreme", "both_detect",
             "S1 saturated: minimum delta_R run — weakest cascade yet still detected by both methods")

# short and long duration examples
s1_by_dur = sorted(s1_runs, key=lambda r: int(r["duration"] or 0))
add_showcase(s1_by_dur[0], "extreme", "both_detect",
             "S1 saturated: shortest duration run — cascade is fast (short outage still catastrophic)")
add_showcase(s1_by_dur[-1], "extreme", "both_detect",
             "S1 saturated: longest duration run — maximum exposure cascade")

# --- S3 marginal examples (most important for stand)
s3_runs = by_scenario["S3_transport_load"]

s3_q_only = [r for r in s3_runs if classify_case(r) == "q_only"]
s3_both = [r for r in s3_runs if classify_case(r) == "both_detect"]
s3_miss = [r for r in s3_runs if classify_case(r) == "both_miss"]

print(f"  S3 case breakdown: q_only={len(s3_q_only)}, both_detect={len(s3_both)}, "
      f"both_miss={len(s3_miss)}")

# q_only: pick one with highest delta_R (clearest gap demonstration)
if s3_q_only:
    s3_q_best = sorted(s3_q_only, key=lambda r: float(r["delta_R"] or 0), reverse=True)
    add_showcase(s3_q_best[0], "marginal", "q_only",
                 "S3 marginal: quantitative detects, classical misses — highest delta_R q_only case; "
                 "key demonstration of representation gap")
    # also pick median q_only
    mid = len(s3_q_best) // 2
    add_showcase(s3_q_best[mid], "marginal", "q_only",
                 "S3 marginal: quantitative detects, classical misses — median delta_R q_only case")
    # pick a near-threshold q_only (lowest delta_R among q_only)
    add_showcase(s3_q_best[-1], "marginal", "near_threshold",
                 "S3 marginal: q_only near detection boundary — lowest delta_R q_only; "
                 "illustrates marginal detection regime")

# both_detect: pick by step_1_amount variety
if s3_both:
    s3_both_sorted_step = sorted(s3_both, key=lambda r: float(r["step_1_amount"] or 0), reverse=True)
    add_showcase(s3_both_sorted_step[0], "marginal", "both_detect",
                 "S3 marginal: both methods detect — highest load step; "
                 "confirms agreement at high stress")
    mid2 = len(s3_both_sorted_step) // 2
    add_showcase(s3_both_sorted_step[mid2], "marginal", "both_detect",
                 "S3 marginal: both methods detect — median load step both_detect case")
    # max delta_R among both_detect
    s3_both_max_d = sorted(s3_both, key=lambda r: float(r["delta_R"] or 0), reverse=True)
    add_showcase(s3_both_max_d[0], "marginal", "max_delta",
                 "S3 marginal: both detect, maximum delta_R — strongest cascade in marginal scenario")

# both_miss (should be ~44 runs at K_q=0.956 → 44 misses)
if s3_miss:
    add_showcase(s3_miss[0], "marginal", "both_miss",
                 "S3 marginal: both methods miss — very small load step; below detection threshold")
    if len(s3_miss) > 5:
        # pick one with highest delta_R among misses (near-threshold miss)
        s3_miss_top = sorted(s3_miss, key=lambda r: float(r["delta_R"] or 0), reverse=True)
        add_showcase(s3_miss_top[0], "marginal", "near_threshold",
                     "S3 marginal: both miss but highest delta_R among misses — borderline non-detection")

# --- S4 partial water examples (interesting gap for stand)
s4_runs = by_scenario["S4_water_partial"]
s4_q_only = [r for r in s4_runs if classify_case(r) == "q_only"]
s4_both = [r for r in s4_runs if classify_case(r) == "both_detect"]
s4_miss = [r for r in s4_runs if classify_case(r) == "both_miss"]

print(f"  S4 case breakdown: q_only={len(s4_q_only)}, both_detect={len(s4_both)}, "
      f"both_miss={len(s4_miss)}")

if s4_q_only:
    s4_best = sorted(s4_q_only, key=lambda r: float(r["delta_R"] or 0), reverse=True)
    add_showcase(s4_best[0], "partial_degradation", "q_only",
                 "S4 water partial: quantitative detects, classical misses — "
                 "largest gap case; water→energy→transport chain visible quantitatively")
if s4_both:
    s4_both_top = sorted(s4_both, key=lambda r: float(r["delta_R"] or 0), reverse=True)
    add_showcase(s4_both_top[0], "partial_degradation", "max_delta",
                 "S4 water partial: both detect, maximum delta_R — worst-case water cascade")

print(f"  Total showcase runs: {len(showcase_runs)}")

# ---------------------------------------------------------------------------
# Step 4: Write reporting_runs_showcase.csv
# ---------------------------------------------------------------------------

print("\nWriting reporting_runs_showcase.csv ...")
showcase_path = OUT / "reporting_runs_showcase.csv"
showcase_fieldnames = MASTER_COLS + [
    "scenario_name", "scenario_label", "scenario_type", "case_label",
    "selection_reason", "cl_activated_sectors", "cl_first_activation_step",
    "step_1_amount", "theta_node",
]

with open(showcase_path, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=showcase_fieldnames, extrasaction="ignore")
    w.writeheader()
    w.writerows(showcase_runs)

print(f"  Written: {showcase_path} ({len(showcase_runs)} rows)")

# ---------------------------------------------------------------------------
# Step 5: Write reporting_scenarios_summary.csv
# ---------------------------------------------------------------------------

print("\nWriting reporting_scenarios_summary.csv ...")

# Load sweep summaries for additional scenarios
def load_json(path):
    with open(path) as f:
        return json.load(f)

theta_sweep = load_json(RESULTS / "theta_sweep_s3_summary.json")
load_sweep = load_json(RESULTS / "load_sweep_s3_summary.json")
severity_sweep_raw = load_json(RESULTS / "severity_sweep_water_summary.json")
severity_sweep = severity_sweep_raw.get("data", severity_sweep_raw) if isinstance(severity_sweep_raw, dict) else severity_sweep_raw
factorial_s3 = load_json(RESULTS / "factorial_s3_1000_summary.json")
factorial_s1 = load_json(RESULTS / "factorial_s1_1000_summary.json")
roc_data = load_json(RESULTS / "roc_analysis_s3.json")

scenarios_summary = []

# Main experiments
for exp in EXPERIMENTS:
    # Compute mean_duration from data
    runs_data = by_scenario[exp["scenario_name"]]
    durs = [float(r["duration"]) for r in runs_data if r["duration"] != ""]
    mean_dur = round(sum(durs) / len(durs), 1) if durs else None
    gap_abs = round(exp["K_q"] - exp["K_cl"], 3)
    gap_rel = round(gap_abs / exp["K_q"] * 100, 1) if exp["K_q"] > 0 else 0

    scenarios_summary.append({
        "scenario_name": exp["scenario_name"],
        "scenario_label": exp["scenario_label"],
        "scenario_role": exp["role"],
        "artifact_prefix": exp["artifact_prefix"],
        "runs": exp["runs"],
        "K_cl": exp["K_cl"],
        "K_q": exp["K_q"],
        "K_qi": "",
        "gap_abs": gap_abs,
        "gap_rel_percent": gap_rel,
        "mean_delta_R": exp["mean_delta_R"],
        "p95_delta_R": exp["p95_delta_R"],
        "mean_duration": mean_dur,
        "stochastic_scale": exp["stochastic_scale"],
        "theta_node": exp["theta_node"],
        "theta_classical": 0.3,
        "initiator": "outage" if exp["scenario_name"] == "S1_energy_outage" else "load_increase",
        "load_amount": 0.0 if exp["scenario_name"] == "S1_energy_outage" else
                       (0.4 if "S3" in exp["scenario_name"] else
                        (0.01 if "S1b" in exp["scenario_name"] else 0.7)),
        "sector": ("energy" if "S1" in exp["scenario_name"] else
                   ("water" if "S4" in exp["scenario_name"] else "transport")),
        "interpretation": exp["interpretation"],
        "recommended_for_stand": exp["recommended_for_stand"],
    })

# Factorial S3 (includes K_qi)
s3_factorial_summary = factorial_s3.get("results", factorial_s3.get("summary", {}))
scenarios_summary.append({
    "scenario_name": "S3_transport_load_factorial",
    "scenario_label": "S3 Factorial: classical vs quantitative vs iterative",
    "scenario_role": "factorial_comparison",
    "artifact_prefix": "factorial_s3_1000",
    "runs": 1000,
    "K_cl": s3_factorial_summary.get("K_cl", 0.534),
    "K_q": s3_factorial_summary.get("K_q", 0.956),
    "K_qi": s3_factorial_summary.get("K_qi", 1.000),
    "gap_abs": round(0.956 - 0.534, 3),
    "gap_rel_percent": round((0.956 - 0.534) / 0.956 * 100, 1),
    "mean_delta_R": 0.309,
    "p95_delta_R": 0.380,
    "mean_duration": None,
    "stochastic_scale": 0.3,
    "theta_node": 0.70,
    "theta_classical": 0.3,
    "initiator": "load_increase",
    "load_amount": 0.4,
    "sector": "transport",
    "interpretation": (
        "2×2 factorial: representation gap (binary vs continuous) = 90.6% of total gap. "
        "Iteration gap (K_qi - K_q) = 9.4%. K_qi=1.0 indicates full detection with iterative operator."
    ),
    "recommended_for_stand": 1,
})

# Factorial S1 (saturated reference)
s1_factorial_summary = factorial_s1.get("results", factorial_s1.get("summary", {}))
scenarios_summary.append({
    "scenario_name": "S1_energy_outage_factorial",
    "scenario_label": "S1 Factorial: saturated reference",
    "scenario_role": "factorial_saturated",
    "artifact_prefix": "factorial_s1_1000",
    "runs": 1000,
    "K_cl": s1_factorial_summary.get("K_cl", 1.0),
    "K_q": s1_factorial_summary.get("K_q", 1.0),
    "K_qi": s1_factorial_summary.get("K_qi", 1.0),
    "gap_abs": 0.0,
    "gap_rel_percent": 0.0,
    "mean_delta_R": 0.491,
    "p95_delta_R": 0.553,
    "mean_duration": None,
    "stochastic_scale": 0.3,
    "theta_node": 0.70,
    "theta_classical": 0.3,
    "initiator": "outage",
    "load_amount": 0.0,
    "sector": "energy",
    "interpretation": (
        "S1 saturated: K_cl=K_q=K_qi=1.0 — all methods agree on 100% cascade detection. "
        "No method gap in saturated regime. Used as control for factorial."
    ),
    "recommended_for_stand": 0,
})

# Theta sweep: best and worst theta for stand illustration
theta_points = theta_sweep.get("results", []) if isinstance(theta_sweep, dict) else theta_sweep
# Find point with maximum gap
best_theta = max(theta_points, key=lambda p: p.get("delta_K", p.get("K_q", 0) - p.get("K_cl", 0)))
scenarios_summary.append({
    "scenario_name": f"S3_theta_sweep_best_gap",
    "scenario_label": f"S3 Theta Sweep: max gap at theta={best_theta.get('theta_node', '?')}",
    "scenario_role": "sweep_theta_best",
    "artifact_prefix": f"theta_sweep/theta_{str(best_theta.get('theta_node','?')).replace('.','')[1:]}",
    "runs": best_theta.get("runs", 500),
    "K_cl": best_theta.get("K_cl", ""),
    "K_q": best_theta.get("K_q", ""),
    "K_qi": "",
    "gap_abs": round(best_theta.get("delta_K", 0), 3),
    "gap_rel_percent": round(best_theta.get("Delta_percent", 0), 1),
    "mean_delta_R": best_theta.get("mean_delta", ""),
    "p95_delta_R": best_theta.get("p95_delta", ""),
    "mean_duration": None,
    "stochastic_scale": 0.3,
    "theta_node": best_theta.get("theta_node"),
    "theta_classical": 0.3,
    "initiator": "load_increase",
    "load_amount": 0.4,
    "sector": "transport",
    "interpretation": (
        f"Theta sweep point with maximum classical/quantitative gap. "
        f"K_q remains stable (~0.944); K_cl is maximized at theta={best_theta.get('theta_node')}."
    ),
    "recommended_for_stand": 0,
})

# Severity sweep best gap
sev_points = severity_sweep  # already extracted as list
best_sev = max(sev_points, key=lambda p: p.get("delta_K", p.get("K_q", 0) - p.get("K_cl", 0)))
scenarios_summary.append({
    "scenario_name": "S4_severity_sweep_best_gap",
    "scenario_label": f"S4 Severity Sweep: max gap at severity={best_sev.get('severity','?')}",
    "scenario_role": "sweep_severity_best",
    "artifact_prefix": f"severity_sweep_water_{str(best_sev.get('severity','?')).replace('.','p')}",
    "runs": best_sev.get("runs", 500),
    "K_cl": best_sev.get("K_cl", ""),
    "K_q": best_sev.get("K_q", ""),
    "K_qi": "",
    "gap_abs": round(best_sev.get("delta_K", 0), 3),
    "gap_rel_percent": "",
    "mean_delta_R": best_sev.get("mean_delta", ""),
    "p95_delta_R": "",
    "mean_duration": None,
    "stochastic_scale": 0.3,
    "theta_node": 0.70,
    "theta_classical": 0.3,
    "initiator": "load_increase",
    "load_amount": best_sev.get("severity"),
    "sector": "water",
    "interpretation": (
        f"Water severity sweep point with maximum gap: severity={best_sev.get('severity')}. "
        "K_q detects much earlier along severity curve than K_cl."
    ),
    "recommended_for_stand": 0,
})

summary_cols = [
    "scenario_name", "scenario_label", "scenario_role", "artifact_prefix",
    "runs", "K_cl", "K_q", "K_qi", "gap_abs", "gap_rel_percent",
    "mean_delta_R", "p95_delta_R", "mean_duration", "stochastic_scale",
    "theta_node", "theta_classical", "initiator", "load_amount", "sector",
    "interpretation", "recommended_for_stand",
]

summary_path = OUT / "reporting_scenarios_summary.csv"
with open(summary_path, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=summary_cols, extrasaction="ignore")
    w.writeheader()
    w.writerows(scenarios_summary)

print(f"  Written: {summary_path} ({len(scenarios_summary)} rows)")

# ---------------------------------------------------------------------------
# Step 6: Write reporting_trajectories_long.csv
# ---------------------------------------------------------------------------

print("\nWriting reporting_trajectories_long.csv ...")

traj_rows = []

for sr in showcase_runs:
    run_num = sr["run"]
    run_id = sr["run_id"]
    scenario_name = sr["scenario_name"]
    scenario_type = sr["scenario_type"]
    case_label = sr["case_label"]
    i_q = sr["I_q"]
    i_cl = sr["I_cl"]

    # Parse trajectory vectors
    try:
        traj_q = json.loads(sr["risk_trajectory_q"]) if sr["risk_trajectory_q"] else {}
    except Exception:
        traj_q = {}
    try:
        traj_cl = json.loads(sr["risk_trajectory_cl"]) if sr["risk_trajectory_cl"] else {}
    except Exception:
        traj_cl = {}

    for sector in SECTORS:
        # Quantitative: steps [before, after]
        q_vals = traj_q.get(sector, [None, None])
        for step_idx, val in enumerate(q_vals):
            traj_rows.append({
                "scenario_name": scenario_name,
                "run": run_num,
                "run_id": run_id,
                "method": "quantitative",
                "step_index": step_idx,
                "sector": sector,
                "risk_value": round(val, 6) if val is not None else "",
                "I_q": i_q,
                "I_cl": i_cl,
                "case_label": case_label,
                "scenario_type": scenario_type,
            })

        # Classical: steps [before, after]
        cl_vals = traj_cl.get(sector, [None, None])
        for step_idx, val in enumerate(cl_vals):
            traj_rows.append({
                "scenario_name": scenario_name,
                "run": run_num,
                "run_id": run_id,
                "method": "classical",
                "step_index": step_idx,
                "sector": sector,
                "risk_value": round(val, 6) if val is not None else "",
                "I_q": i_q,
                "I_cl": i_cl,
                "case_label": case_label,
                "scenario_type": scenario_type,
            })

traj_cols = [
    "scenario_name", "run", "run_id", "method", "step_index", "sector",
    "risk_value", "I_q", "I_cl", "case_label", "scenario_type",
]

traj_path = OUT / "reporting_trajectories_long.csv"
with open(traj_path, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=traj_cols)
    w.writeheader()
    w.writerows(traj_rows)

print(f"  Written: {traj_path} ({len(traj_rows)} rows)")

# ---------------------------------------------------------------------------
# Step 7: Write reporting_threshold_analysis.csv
# ---------------------------------------------------------------------------

print("\nWriting reporting_threshold_analysis.csv ...")

thresh_rows = []

for r in all_normalized:
    def get_sector(vec_key, sec):
        raw = r.get(vec_key, "")
        if not raw:
            return ""
        try:
            obj = json.loads(raw) if isinstance(raw, str) else raw
            v = obj.get(sec)
            return round(float(v), 6) if v is not None else ""
        except Exception:
            return ""

    thresh_rows.append({
        "scenario_name": r["scenario_name"],
        "run": r["run"],
        "run_id": r["run_id"],
        "duration": r["duration"],
        "delta_R": r["delta_R"],
        "I_q": r["I_q"],
        "I_cl": r["I_cl"],
        "step_1_amount": r["step_1_amount"],
        "method_q_total_before": r["method_q_total_before"],
        "method_q_total_after": r["method_q_total_after"],
        "method_cl_total_before": r["method_cl_total_before"],
        "method_cl_total_after": r["method_cl_total_after"],
        "energy_before_q": get_sector("before_vec_q", "energy"),
        "water_before_q": get_sector("before_vec_q", "water"),
        "transport_before_q": get_sector("before_vec_q", "transport"),
        "energy_after_q": get_sector("after_vec_q", "energy"),
        "water_after_q": get_sector("after_vec_q", "water"),
        "transport_after_q": get_sector("after_vec_q", "transport"),
        "energy_delta_q": get_sector("delta_vec_q", "energy"),
        "water_delta_q": get_sector("delta_vec_q", "water"),
        "transport_delta_q": get_sector("delta_vec_q", "transport"),
        "energy_after_cl": get_sector("after_vec_cl", "energy"),
        "water_after_cl": get_sector("after_vec_cl", "water"),
        "transport_after_cl": get_sector("after_vec_cl", "transport"),
        "theta_node": r["theta_node"],
        "theta_classical": r["theta_classical"],
        "case_label": classify_case(r),
    })

thresh_cols = [
    "scenario_name", "run", "run_id", "duration", "delta_R", "I_q", "I_cl",
    "step_1_amount",
    "method_q_total_before", "method_q_total_after",
    "method_cl_total_before", "method_cl_total_after",
    "energy_before_q", "water_before_q", "transport_before_q",
    "energy_after_q", "water_after_q", "transport_after_q",
    "energy_delta_q", "water_delta_q", "transport_delta_q",
    "energy_after_cl", "water_after_cl", "transport_after_cl",
    "theta_node", "theta_classical", "case_label",
]

thresh_path = OUT / "reporting_threshold_analysis.csv"
with open(thresh_path, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=thresh_cols)
    w.writeheader()
    w.writerows(thresh_rows)

print(f"  Written: {thresh_path} ({len(thresh_rows)} rows)")

# ---------------------------------------------------------------------------
# Step 8: Write sweep summary datasets (bonus — useful for bar/line charts)
# ---------------------------------------------------------------------------

print("\nWriting sweep summary datasets ...")

# Theta sweep long
theta_long_path = OUT / "reporting_theta_sweep.csv"
theta_cols = ["theta_node", "K_cl", "K_q", "gap_abs", "gap_rel_percent",
              "mean_delta", "p95_delta", "runs"]
with open(theta_long_path, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=theta_cols)
    w.writeheader()
    for pt in theta_points:
        k_q = pt.get("K_q", 0)
        k_cl = pt.get("K_cl", 0)
        gap = round(k_q - k_cl, 4)
        w.writerow({
            "theta_node": pt.get("theta_node"),
            "K_cl": round(k_cl, 4),
            "K_q": round(k_q, 4),
            "gap_abs": gap,
            "gap_rel_percent": round(gap / k_q * 100, 2) if k_q > 0 else 0,
            "mean_delta": round(pt.get("mean_delta", 0), 4),
            "p95_delta": round(pt.get("p95_delta", 0), 4),
            "runs": pt.get("runs", 500),
        })
print(f"  Written: {theta_long_path}")

# Load sweep long
load_points = load_sweep.get("results", []) if isinstance(load_sweep, dict) else load_sweep
load_long_path = OUT / "reporting_load_sweep.csv"
load_cols = ["load_amount", "K_cl", "K_q", "gap_abs", "gap_rel_percent",
             "mean_delta", "p95_delta", "runs"]
with open(load_long_path, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=load_cols)
    w.writeheader()
    for pt in load_points:
        k_q = pt.get("K_q", 0)
        k_cl = pt.get("K_cl", 0)
        gap = round(k_q - k_cl, 4)
        w.writerow({
            "load_amount": pt.get("load_amount"),
            "K_cl": round(k_cl, 4),
            "K_q": round(k_q, 4),
            "gap_abs": gap,
            "gap_rel_percent": round(gap / k_q * 100, 2) if k_q > 0 else 0,
            "mean_delta": round(pt.get("mean_delta", 0), 4),
            "p95_delta": round(pt.get("p95_delta", 0), 4),
            "runs": pt.get("runs", 500),
        })
print(f"  Written: {load_long_path}")

# Severity sweep long
sev_long_path = OUT / "reporting_severity_sweep.csv"
sev_cols = ["severity", "K_cl", "K_q", "gap_abs", "mean_delta", "runs"]
with open(sev_long_path, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=sev_cols)
    w.writeheader()
    for pt in sev_points:
        k_q = pt.get("K_q", 0)
        k_cl = pt.get("K_cl", 0)
        w.writerow({
            "severity": pt.get("severity"),
            "K_cl": round(k_cl, 4),
            "K_q": round(k_q, 4),
            "gap_abs": round(k_q - k_cl, 4),
            "mean_delta": round(pt.get("mean_delta", 0), 4),
            "runs": pt.get("runs", 500),
        })
print(f"  Written: {sev_long_path}")

# ROC data
roc_points = roc_data.get("roc_points", roc_data) if isinstance(roc_data, dict) else roc_data
roc_path = OUT / "reporting_roc_analysis.csv"
roc_cols = ["theta_node", "TP", "FP", "FN", "TN", "sensitivity", "specificity",
            "FPR", "precision", "F1", "K_cl", "K_q"]
with open(roc_path, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=roc_cols)
    w.writeheader()
    for pt in roc_points:
        # ROC json uses lowercase: tp, fp, fn, tn, sensitivity_TPR, FPR, PPV_precision, F1
        fpr = pt.get("FPR", 0.0)
        spec = round(1.0 - float(fpr), 4)
        row = {
            "theta_node": pt.get("theta_node"),
            "TP": pt.get("tp", pt.get("TP", "")),
            "FP": pt.get("fp", pt.get("FP", "")),
            "FN": pt.get("fn", pt.get("FN", "")),
            "TN": pt.get("tn", pt.get("TN", "")),
            "sensitivity": pt.get("sensitivity_TPR", pt.get("sensitivity", "")),
            "specificity": spec,
            "FPR": fpr,
            "precision": pt.get("PPV_precision", pt.get("precision", "")),
            "F1": pt.get("F1", ""),
            "K_cl": pt.get("K_cl", ""),
            "K_q": pt.get("K_q", ""),
        }
        w.writerow(row)
print(f"  Written: {roc_path}")

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
print("\n=== All reporting datasets written successfully ===")
print(f"Output directory: {OUT}")
for p in sorted(OUT.iterdir()):
    if p.is_file():
        size = p.stat().st_size
        print(f"  {p.name:55s}  {size:>10,} bytes")
