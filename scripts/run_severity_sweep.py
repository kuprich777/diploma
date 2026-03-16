#!/usr/bin/env python3
"""
run_severity_sweep.py — Severity sweep for partial degradation scenarios.

Sweeps load_amount across 12 severity levels for S4_water_partial (water initiator),
tracking K_cl and K_q at each severity level to characterise the
detection sensitivity curve.

Design:
  Scenario: S4_water_partial, sector=water, initiator_action=load_increase
  Severity axis: load_amount ∈ [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.60, 0.70, 0.80]
  N = 500 per severity level (configurable)
  theta_node = 0.70, stochastic_scale = 0.3
  Sequential execution (no parallel conflicts)

Outputs:
  results/severity_sweep_water_summary.json  — aggregate table across all severity levels
  results/severity_sweep_water_summary.csv   — same in CSV for plotting
  results/severity_sweep_water_<amount>_*    — per-severity MC artifacts

Usage:
  python scripts/run_severity_sweep.py [--runs N] [--scenario ID] [--sector SEC]
"""

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

import httpx

SIMULATOR_URL = os.getenv("SIMULATOR_URL", "http://localhost:8005")
RISK_ENGINE_URL = os.getenv("RISK_ENGINE_URL", "http://localhost:8004")
SNAPSHOT_PATH = Path("results/dependency_matrix_live_snapshot.json")

SEVERITY_LEVELS = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.60, 0.70, 0.80]


def run_mc(payload: dict, simulator_url: str) -> dict:
    url = f"{simulator_url}/api/v1/simulator/monte_carlo"
    print(f"  [mc] POST {url}  runs={payload.get('runs')}")
    with httpx.Client(timeout=600.0) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
    return resp.json()


def load_snapshot(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    raise FileNotFoundError(f"Snapshot not found: {path}. Run run_mc_experiment.py first.")


def run_severity_sweep(args) -> None:
    sys.path.insert(0, str(Path(__file__).parent))
    from run_mc_experiment import load_or_create_snapshot, build_model_config, save_artifacts

    snapshot = load_or_create_snapshot(SNAPSHOT_PATH, False)
    model_config = build_model_config(snapshot, SNAPSHOT_PATH)

    print(f"[sweep] scenario={args.scenario}  sector={args.sector}  runs/point={args.runs}")
    print(f"[sweep] severity levels: {SEVERITY_LEVELS}")
    print(f"[sweep] matrix={model_config['matrix_version']}  theta_bin={model_config['theta_bin']}")

    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)

    summary_rows = []
    t_total = time.monotonic()

    for severity in SEVERITY_LEVELS:
        amt_str = f"{severity:.2f}".replace(".", "p")
        prefix = f"results/severity_sweep_water_{amt_str}"

        print(f"\n[sweep] severity={severity:.2f} → {prefix}")

        payload = {
            "scenario_id": args.scenario,
            "sector": args.sector,
            "runs": args.runs,
            "duration_min": 5,
            "duration_max": 30,
            "initiator_action": "load_increase",
            "load_amount": severity,
            "theta_classical": 0.3,
            "theta_node": 0.70,
            "stochastic_scale": args.stochastic_scale,
            "mode": "real",
        }

        t0 = time.monotonic()
        try:
            result = run_mc(payload, args.simulator_url)
        except httpx.HTTPStatusError as e:
            print(f"  [error] HTTP {e.response.status_code}: {e.response.text[:200]}", file=sys.stderr)
            continue
        except httpx.RequestError as e:
            print(f"  [error] Connection failed: {e}", file=sys.stderr)
            continue
        elapsed = time.monotonic() - t0

        K_cl = result.get("K_cl", 0.0)
        K_q = result.get("K_q", 0.0)
        mean_delta = result.get("mean_delta", 0.0)

        print(f"  [mc] Done in {elapsed:.1f}s  K_cl={K_cl}  K_q={K_q}  mean_delta={mean_delta:.4f}")

        save_artifacts(
            result=result,
            model_config=model_config,
            request_payload=payload,
            prefix=prefix,
            elapsed=elapsed,
            simulator_url=args.simulator_url,
        )

        summary_rows.append({
            "severity": severity,
            "K_cl": K_cl,
            "K_q": K_q,
            "delta_K": round(float(K_q) - float(K_cl), 4),
            "mean_delta": round(float(mean_delta), 4),
            "runs": result.get("runs", args.runs),
            "elapsed_s": round(elapsed, 1),
        })

    elapsed_total = time.monotonic() - t_total
    print(f"\n[sweep] Total runtime: {elapsed_total:.0f}s for {len(SEVERITY_LEVELS)} severity levels")

    # Save summary JSON
    summary = {
        "experiment": "severity_sweep_water",
        "scenario": args.scenario,
        "sector": args.sector,
        "severity_levels": SEVERITY_LEVELS,
        "runs_per_level": args.runs,
        "theta_node": 0.70,
        "theta_cascade": 0.3,
        "stochastic_scale": args.stochastic_scale,
        "matrix_version": model_config["matrix_version"],
        "total_runtime_seconds": round(elapsed_total, 1),
        "data": summary_rows,
    }

    summary_path = Path("results/severity_sweep_water_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"[save] summary JSON → {summary_path}")

    # Save summary CSV
    csv_path = Path("results/severity_sweep_water_summary.csv")
    if summary_rows:
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
            writer.writeheader()
            writer.writerows(summary_rows)
    print(f"[save] summary CSV → {csv_path}")

    # Print table
    print("\n" + "=" * 60)
    print("SEVERITY SWEEP RESULTS — S4_water_partial")
    print("=" * 60)
    print(f"{'Severity':>10}  {'K_cl':>8}  {'K_q':>8}  {'ΔK':>8}")
    print("-" * 42)
    for row in summary_rows:
        print(f"  {row['severity']:.2f}     {row['K_cl']:>8.4f}  {row['K_q']:>8.4f}  {row['delta_K']:>+8.4f}")
    print("=" * 60)


def parse_args():
    p = argparse.ArgumentParser(
        description="Severity sweep for partial degradation scenarios.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--scenario", default="S4_water_partial")
    p.add_argument("--sector", default="water")
    p.add_argument("--runs", type=int, default=500)
    p.add_argument("--stochastic-scale", type=float, default=0.3, dest="stochastic_scale")
    p.add_argument("--simulator-url", default=SIMULATOR_URL, dest="simulator_url")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_severity_sweep(args)
