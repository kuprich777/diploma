#!/usr/bin/env python3
"""
run_factorial_experiment.py — 2×2 Factorial: State (binary/continuous) × Propagation (one-step/iterative).

Design:
  Factor A: State representation — Binary (classical) vs Continuous (quantitative)
  Factor B: Propagation — One-step vs Iterative

  Cell mapping (available cells):
    Classical:              Binary × Iterative topology  → K_cl
    Quantitative one-step:  Continuous × One-step        → K_q
    Quantitative iterative: Continuous × Iterative       → K_qi

All three indicators come from the same MC runs (within-subjects design).

Hypotheses:
  H1: K_qi ≈ K_q  — gap is purely binary vs continuous
  H2: K_qi > K_q  — iterative propagation amplifies sub-threshold cascades

Outputs:
  results/factorial_s3_1000_summary.json     — aggregate metrics
  results/factorial_s3_1000_agreement.json   — 8-cell I_cl/I_q/I_qi agreement matrix
  results/factorial_s3_1000_convergence.json — convergence_steps distribution

Usage:
  python scripts/run_factorial_experiment.py [--runs N] [--scenario ID] [--prefix PREFIX]
"""

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

SIMULATOR_URL = os.getenv("SIMULATOR_URL", "http://localhost:8005")
SNAPSHOT_PATH = Path("results/dependency_matrix_live_snapshot.json")


def run_mc(payload: dict, simulator_url: str) -> dict:
    url = f"{simulator_url}/api/v1/simulator/monte_carlo"
    print(f"[mc] POST {url}  runs={payload.get('runs')}")
    with httpx.Client(timeout=600.0) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
    return resp.json()


def compute_agreement_matrix(runs_data: list[dict]) -> dict:
    """Count occurrences of each (I_cl, I_q, I_qi) triple across all runs."""
    counter: Counter = Counter()
    for r in runs_data:
        key = (int(r.get("I_cl") or 0), int(r.get("I_q") or 0), int(r.get("I_qi") or 0))
        counter[key] += 1

    # Build full 8-cell matrix with labels
    cells = {}
    for icl in (0, 1):
        for iq in (0, 1):
            for iqi in (0, 1):
                label = f"I_cl={icl}_I_q={iq}_I_qi={iqi}"
                cells[label] = counter.get((icl, iq, iqi), 0)

    n = len(runs_data)
    return {
        "n_runs": n,
        "cells": cells,
        "cells_pct": {k: round(v / n * 100, 2) for k, v in cells.items()},
        "interpretation": {
            "I_cl=0_I_q=0_I_qi=0": "No cascade detected by any method",
            "I_cl=0_I_q=1_I_qi=0": "Only quantitative one-step detects cascade",
            "I_cl=0_I_q=0_I_qi=1": "Only iterative detects cascade",
            "I_cl=0_I_q=1_I_qi=1": "Quantitative (both steps) detect, classical misses",
            "I_cl=1_I_q=1_I_qi=1": "All methods agree: cascade detected",
            "I_cl=1_I_q=0_I_qi=0": "Classical false positive (I_q=0 ground truth)",
            "I_cl=1_I_q=1_I_qi=0": "Classical + one-step agree, iterative misses",
            "I_cl=1_I_q=0_I_qi=1": "Classical + iterative agree, one-step misses",
        },
    }


def compute_convergence_distribution(runs_data: list[dict]) -> dict:
    """Histogram of convergence_steps values."""
    steps_vals = [int(r.get("convergence_steps") or 0) for r in runs_data if r.get("convergence_steps") is not None]
    if not steps_vals:
        return {"n": 0, "histogram": {}}

    hist = Counter(steps_vals)
    n = len(steps_vals)
    mean_steps = sum(steps_vals) / n
    max_steps = max(steps_vals)

    # Correlation: convergence_steps vs delta_qi
    delta_qi_vals = [float(r.get("delta_qi") or 0.0) for r in runs_data if r.get("convergence_steps") is not None]
    if len(steps_vals) > 1:
        mean_s = mean_steps
        mean_d = sum(delta_qi_vals) / len(delta_qi_vals)
        cov = sum((s - mean_s) * (d - mean_d) for s, d in zip(steps_vals, delta_qi_vals)) / len(steps_vals)
        var_s = sum((s - mean_s) ** 2 for s in steps_vals) / len(steps_vals)
        var_d = sum((d - mean_d) ** 2 for d in delta_qi_vals) / len(delta_qi_vals)
        corr = cov / ((var_s * var_d) ** 0.5) if var_s > 0 and var_d > 0 else 0.0
    else:
        corr = 0.0

    return {
        "n": n,
        "mean_convergence_steps": round(mean_steps, 3),
        "max_convergence_steps": max_steps,
        "histogram": {str(k): v for k, v in sorted(hist.items())},
        "histogram_pct": {str(k): round(v / n * 100, 2) for k, v in sorted(hist.items())},
        "corr_steps_delta_qi": round(corr, 4),
        "interpretation": "corr_steps_delta_qi: positive = deeper cascades correlate with more iterations needed",
    }


def run_factorial(args) -> None:
    sys.path.insert(0, str(Path(__file__).parent))
    from run_mc_experiment import load_or_create_snapshot, build_model_config, save_artifacts

    snapshot = load_or_create_snapshot(SNAPSHOT_PATH, False)
    model_config = build_model_config(snapshot, SNAPSHOT_PATH)

    print(f"[factorial] matrix={model_config['matrix_version']}  theta_bin={model_config['theta_bin']}")
    print(f"[factorial] scenario={args.scenario}  sector={args.sector}  initiator_action={args.initiator_action}")
    print(f"[factorial] load_amount={args.load_amount}  runs={args.runs}  stochastic_scale={args.stochastic_scale}")

    payload: dict = {
        "scenario_id": args.scenario,
        "sector": args.sector,
        "runs": args.runs,
        "duration_min": 5,
        "duration_max": 30,
        "initiator_action": args.initiator_action,
        "load_amount": args.load_amount,
        "theta_classical": 0.3,
        "stochastic_scale": args.stochastic_scale,
        "mode": "real",
    }

    t0 = time.monotonic()
    try:
        result = run_mc(payload, args.simulator_url)
    except httpx.HTTPStatusError as e:
        print(f"[error] HTTP {e.response.status_code}: {e.response.text[:500]}", file=sys.stderr)
        sys.exit(1)
    except httpx.RequestError as e:
        print(f"[error] Connection failed: {e}", file=sys.stderr)
        sys.exit(1)
    elapsed = time.monotonic() - t0
    print(f"[mc] Done in {elapsed:.1f}s  K_cl={result.get('K_cl')}  K_q={result.get('K_q')}  K_qi={result.get('K_qi', 'N/A')}")

    # Save raw artifacts
    prefix = args.prefix
    save_artifacts(
        result=result,
        model_config=model_config,
        request_payload=payload,
        prefix=prefix,
        elapsed=elapsed,
        simulator_url=args.simulator_url,
    )

    runs_data = result.get("runs_data", [])
    K_cl = result.get("K_cl", 0.0)
    K_q = result.get("K_q", 0.0)
    K_qi = result.get("K_qi", 0.0)

    # Agreement matrix
    agreement = compute_agreement_matrix(runs_data)

    # Convergence distribution
    convergence = compute_convergence_distribution(runs_data)

    # Per-method delta stats
    def _stats(vals: list[float]) -> dict:
        if not vals:
            return {}
        vals_s = sorted(vals)
        n = len(vals)
        mean = sum(vals) / n
        var = sum((v - mean) ** 2 for v in vals) / n
        std = var ** 0.5
        p95 = vals_s[max(0, int(0.95 * (n - 1)))]
        return {"mean": round(mean, 4), "std": round(std, 4), "p95": round(p95, 4), "n": n}

    delta_q_vals = [float(r.get("delta") or 0.0) for r in runs_data]
    delta_qi_vals = [float(r.get("delta_qi") or 0.0) for r in runs_data if r.get("delta_qi") is not None]

    # Hypothesis tests
    eps = 1e-9
    h1_supported = abs(K_qi - K_q) < 0.05  # within 5pp
    h2_supported = K_qi > K_q + 0.02       # K_qi meaningfully greater

    summary = {
        "experiment": "2x2_factorial",
        "scenario": args.scenario,
        "sector": args.sector,
        "initiator_action": args.initiator_action,
        "load_amount": args.load_amount,
        "stochastic_scale": args.stochastic_scale,
        "runs": args.runs,
        "theta_node": 0.70,
        "theta_cascade": 0.3,
        "matrix_version": model_config["matrix_version"],
        "total_runtime_seconds": round(elapsed, 2),
        "factorial_design": {
            "Factor_A": "State representation (Binary=classical, Continuous=quantitative)",
            "Factor_B": "Propagation (one-step=quantitative, iterative=classical+quantitative_iterative)",
            "cells": {
                "Classical (Binary × Iterative topology)": f"K_cl={K_cl}",
                "Quantitative one-step (Continuous × One-step)": f"K_q={K_q}",
                "Quantitative iterative (Continuous × Iterative)": f"K_qi={K_qi}",
            },
        },
        "results": {
            "K_cl": K_cl,
            "K_q": K_q,
            "K_qi": K_qi,
            "delta_K_q_vs_cl": round(K_q - K_cl, 4),
            "delta_K_qi_vs_q": round(K_qi - K_q, 4),
            "delta_K_qi_vs_cl": round(K_qi - K_cl, 4),
            "delta_q_stats": _stats(delta_q_vals),
            "delta_qi_stats": _stats(delta_qi_vals),
            "mean_convergence_steps": convergence.get("mean_convergence_steps"),
            "corr_steps_delta_qi": convergence.get("corr_steps_delta_qi"),
        },
        "hypotheses": {
            "H1_K_qi_approx_K_q": {
                "supported": h1_supported,
                "description": "K_qi ≈ K_q (±5pp): gap is purely binary vs continuous",
                "K_qi": K_qi,
                "K_q": K_q,
                "delta": round(K_qi - K_q, 4),
            },
            "H2_K_qi_gt_K_q": {
                "supported": h2_supported,
                "description": "K_qi > K_q (+2pp): iterative propagation amplifies sub-threshold cascades",
                "K_qi": K_qi,
                "K_q": K_q,
                "delta": round(K_qi - K_q, 4),
            },
        },
        "artifact_files": {
            "full_json": f"{prefix}_full.json",
            "runs_csv": f"{prefix}_runs.csv",
            "metadata": f"{prefix}_meta.json",
            "summary": f"{prefix}_summary.json",
            "agreement": f"{prefix}_agreement.json",
            "convergence": f"{prefix}_convergence.json",
        },
    }

    # Save all outputs
    summary_path = Path(f"{prefix}_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"[save] summary → {summary_path}")

    agreement_path = Path(f"{prefix}_agreement.json")
    with open(agreement_path, "w") as f:
        json.dump(agreement, f, indent=2)
    print(f"[save] agreement → {agreement_path}")

    convergence_path = Path(f"{prefix}_convergence.json")
    with open(convergence_path, "w") as f:
        json.dump(convergence, f, indent=2)
    print(f"[save] convergence → {convergence_path}")

    print("\n" + "=" * 60)
    print("2×2 FACTORIAL RESULTS")
    print("=" * 60)
    print(f"  K_cl  (Binary × Iterative topology): {K_cl:.4f}")
    print(f"  K_q   (Continuous × One-step):        {K_q:.4f}")
    print(f"  K_qi  (Continuous × Iterative):       {K_qi:.4f}")
    print(f"  ΔK(q  vs cl):  {K_q - K_cl:+.4f}")
    print(f"  ΔK(qi vs q):   {K_qi - K_q:+.4f}")
    print(f"  ΔK(qi vs cl):  {K_qi - K_cl:+.4f}")
    print(f"  mean_conv_steps: {convergence.get('mean_convergence_steps')}")
    print(f"  corr(steps, delta_qi): {convergence.get('corr_steps_delta_qi')}")
    print("\nHYPOTHESES:")
    print(f"  H1 (K_qi ≈ K_q): {'SUPPORTED' if h1_supported else 'REJECTED'}")
    print(f"  H2 (K_qi > K_q): {'SUPPORTED' if h2_supported else 'REJECTED'}")
    if h2_supported:
        print("  → Iterative propagation amplifies sub-threshold cascades")
    elif h1_supported:
        print("  → K_q > K_cl gap is entirely about binary vs continuous representation")
    print("=" * 60)


def parse_args():
    p = argparse.ArgumentParser(
        description="2×2 factorial experiment: binary/continuous × one-step/iterative.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--scenario", default="S3_transport_load")
    p.add_argument("--sector", default="transport")
    p.add_argument("--initiator-action", default="load_increase", dest="initiator_action")
    p.add_argument("--load-amount", type=float, default=0.40, dest="load_amount")
    p.add_argument("--runs", type=int, default=1000)
    p.add_argument("--stochastic-scale", type=float, default=0.3, dest="stochastic_scale")
    p.add_argument("--prefix", default="results/factorial_s3_1000")
    p.add_argument("--simulator-url", default=SIMULATOR_URL, dest="simulator_url")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    SIMULATOR_URL = args.simulator_url
    run_factorial(args)
