#!/usr/bin/env python3
"""
run_theta_sweep.py — Sweep theta_node values for S3_transport_load scenario.

Runs N=500 Monte Carlo experiments at 15 theta_node values from 0.20 to 0.90,
producing a K_cl(theta) vs K_q curve to characterise whether the K_q > K_cl gap
is an artifact of theta_node choice or a fundamental property of the scenario.

Outputs:
  results/theta_sweep_s3_summary.json  — per-theta aggregates
  results/theta_sweep_s3_summary.csv   — same in CSV
  results/theta_sweep/theta_<v>_*      — per-theta MC artifacts (full/csv/meta)

Usage:
  python scripts/run_theta_sweep.py [--runs N] [--load-amount L] [--force-refresh-snapshot]
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

THETA_VALUES = [round(v, 2) for v in [
    0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90
]]


def run_mc(payload: dict) -> dict:
    url = f"{SIMULATOR_URL}/api/v1/simulator/monte_carlo"
    print(f"  [mc] POST {url}  theta_node={payload.get('theta_node')}  runs={payload.get('runs')}")
    with httpx.Client(timeout=600.0) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
    return resp.json()


def load_snapshot(snapshot_path: Path, force_refresh: bool) -> dict:
    """Load or fetch snapshot (reuses run_mc_experiment logic)."""
    # Import from sibling script
    sys.path.insert(0, str(Path(__file__).parent))
    from run_mc_experiment import load_or_create_snapshot, build_model_config
    return load_or_create_snapshot(snapshot_path, force_refresh), build_model_config


def run_sweep(args) -> None:
    sys.path.insert(0, str(Path(__file__).parent))
    from run_mc_experiment import load_or_create_snapshot, build_model_config, save_artifacts

    output_dir = Path("results/theta_sweep")
    output_dir.mkdir(parents=True, exist_ok=True)

    snapshot = load_or_create_snapshot(SNAPSHOT_PATH, args.force_refresh)
    model_config = build_model_config(snapshot, SNAPSHOT_PATH)
    print(f"[sweep] matrix={model_config['matrix_version']}  base_theta_bin={model_config['theta_bin']}")
    print(f"[sweep] theta_values={THETA_VALUES}  runs_per_point={args.runs}  load={args.load_amount}")

    summary_rows: list[dict] = []

    for theta in THETA_VALUES:
        print(f"\n[sweep] ─── theta_node={theta:.2f} ────────────────────────────")
        payload = {
            "scenario_id": "S3_transport_load",
            "sector": "transport",
            "runs": args.runs,
            "duration_min": 5,
            "duration_max": 30,
            "initiator_action": "load_increase",
            "load_amount": args.load_amount,
            "theta_classical": 0.3,
            "stochastic_scale": 0.3,
            "mode": "real",
            "theta_node": theta,
        }

        t0 = time.monotonic()
        try:
            result = run_mc(payload)
        except httpx.HTTPStatusError as e:
            print(f"  [error] HTTP {e.response.status_code}: {e.response.text[:300]}", file=sys.stderr)
            summary_rows.append({"theta_node": theta, "error": str(e.response.status_code)})
            continue
        except httpx.RequestError as e:
            print(f"  [error] {e}", file=sys.stderr)
            summary_rows.append({"theta_node": theta, "error": str(e)})
            continue
        elapsed = time.monotonic() - t0

        k_cl = result.get("K_cl")
        k_q = result.get("K_q")
        mean_delta = result.get("mean_delta")
        p95_delta = result.get("p95_delta")
        delta_pct = result.get("Delta_percent")
        print(f"  K_cl={k_cl}  K_q={k_q}  mean_delta={mean_delta}  p95_delta={p95_delta}  Δ%={delta_pct}  t={elapsed:.1f}s")

        # Save per-theta artifacts
        theta_str = f"{theta:.2f}".replace(".", "")
        prefix = str(output_dir / f"theta_{theta_str}")
        save_artifacts(
            result=result,
            model_config=model_config,
            request_payload=payload,
            prefix=prefix,
            elapsed=elapsed,
            simulator_url=SIMULATOR_URL,
        )

        summary_rows.append({
            "theta_node": theta,
            "K_cl": k_cl,
            "K_q": k_q,
            "delta_K": round(float(k_q or 0) - float(k_cl or 0), 4) if k_q is not None and k_cl is not None else None,
            "Delta_percent": delta_pct,
            "mean_delta": mean_delta,
            "p95_delta": p95_delta,
            "runs": result.get("runs", args.runs),
            "elapsed_s": round(elapsed, 1),
        })

    # Save summary JSON
    summary_json = Path("results/theta_sweep_s3_summary.json")
    summary_meta = {
        "experiment": "theta_node_sweep",
        "scenario": "S3_transport_load",
        "load_amount": args.load_amount,
        "stochastic_scale": 0.3,
        "runs_per_point": args.runs,
        "theta_values": THETA_VALUES,
        "matrix_version": model_config["matrix_version"],
        "results": summary_rows,
    }
    with open(summary_json, "w") as f:
        json.dump(summary_meta, f, indent=2)
    print(f"\n[sweep] Summary JSON → {summary_json}")

    # Save summary CSV
    summary_csv = Path("results/theta_sweep_s3_summary.csv")
    if summary_rows:
        fieldnames = list(summary_rows[0].keys())
        with open(summary_csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(summary_rows)
        print(f"[sweep] Summary CSV → {summary_csv}")

    print("\n[sweep] Done.")
    print("\nTheta sweep results:")
    print(f"{'theta_node':>10}  {'K_cl':>6}  {'K_q':>6}  {'ΔK':>6}  {'Δ%':>6}")
    for row in summary_rows:
        if "error" in row:
            print(f"{row['theta_node']:>10.2f}  ERROR: {row['error']}")
        else:
            print(f"{row['theta_node']:>10.2f}  {row['K_cl']:>6.3f}  {row['K_q']:>6.3f}  "
                  f"{row['delta_K']:>6.3f}  {row['Delta_percent']:>6.1f}")


def parse_args():
    p = argparse.ArgumentParser(
        description="Sweep theta_node for S3_transport_load and record K_cl, K_q per point.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--runs", type=int, default=500, help="MC runs per theta point")
    p.add_argument("--load-amount", type=float, default=0.40, dest="load_amount",
                   help="load_increase amount (initiator load)")
    p.add_argument("--force-refresh-snapshot", action="store_true", dest="force_refresh")
    p.add_argument("--simulator-url", default=SIMULATOR_URL, dest="simulator_url")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    SIMULATOR_URL = args.simulator_url
    run_sweep(args)
