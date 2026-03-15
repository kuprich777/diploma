#!/usr/bin/env python3
"""
compute_roc_analysis.py — ROC analysis from theta sweep per-run data.

Treats the quantitative indicator I_q as ground truth (positive = real cascade)
and the classical indicator I_cl as a binary classifier parametrised by theta_node.

For each theta_node point in the sweep:
  - TP = runs where I_cl=1 AND I_q=1
  - FP = runs where I_cl=1 AND I_q=0
  - FN = runs where I_cl=0 AND I_q=1
  - TN = runs where I_cl=0 AND I_q=0
  - sensitivity (TPR) = TP / (TP + FN)   [= K_cl / K_q  when K_q > 0]
  - FPR             = FP / (FP + TN)
  - PPV (precision) = TP / (TP + FP)
  - F1              = 2*TP / (2*TP + FP + FN)

Outputs:
  results/roc_analysis_s3.json  — per-theta ROC metrics
  results/roc_analysis_s3.csv   — same in CSV

Usage:
  python scripts/compute_roc_analysis.py [--sweep-dir results/theta_sweep]
"""

import argparse
import csv
import json
import sys
from pathlib import Path


def load_runs_csv(csv_path: Path) -> list[dict]:
    with open(csv_path, newline="") as f:
        return list(csv.DictReader(f))


def compute_roc_for_theta(runs: list[dict]) -> dict:
    """Compute ROC metrics treating I_q as ground truth."""
    tp = fp = fn = tn = 0
    for row in runs:
        iq = int(float(row.get("I_q", 0) or 0))
        icl = int(float(row.get("I_cl", 0) or 0))
        if icl == 1 and iq == 1:
            tp += 1
        elif icl == 1 and iq == 0:
            fp += 1
        elif icl == 0 and iq == 1:
            fn += 1
        else:
            tn += 1

    n = tp + fp + fn + tn
    k_cl = (tp + fp) / n if n > 0 else 0.0
    k_q = (tp + fn) / n if n > 0 else 0.0
    tpr = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    ppv = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    f1 = 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) > 0 else 0.0
    delta_k = k_q - k_cl

    return {
        "n": n,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "K_cl": round(k_cl, 4),
        "K_q": round(k_q, 4),
        "delta_K": round(delta_k, 4),
        "sensitivity_TPR": round(tpr, 4),
        "FPR": round(fpr, 4),
        "PPV_precision": round(ppv, 4),
        "F1": round(f1, 4),
    }


def run_roc_analysis(args) -> None:
    sweep_dir = Path(args.sweep_dir)
    if not sweep_dir.exists():
        print(f"[error] Sweep directory not found: {sweep_dir}", file=sys.stderr)
        sys.exit(1)

    # Load theta sweep summary to get theta list and ordering
    summary_path = Path("results/theta_sweep_s3_summary.json")
    if not summary_path.exists():
        print(f"[error] Summary file not found: {summary_path}", file=sys.stderr)
        print("[info] Run run_theta_sweep.py first.", file=sys.stderr)
        sys.exit(1)

    with open(summary_path) as f:
        summary = json.load(f)

    theta_values = summary.get("theta_values", [])
    meta = {
        "scenario": summary.get("scenario"),
        "load_amount": summary.get("load_amount"),
        "stochastic_scale": summary.get("stochastic_scale"),
        "runs_per_point": summary.get("runs_per_point"),
        "matrix_version": summary.get("matrix_version"),
        "analysis_note": (
            "ROC analysis: I_q treated as ground truth (positive = real cascade detected by "
            "quantitative model). I_cl is the binary classifier parametrised by theta_node. "
            "Sensitivity=TPR=K_cl/K_q measures classical recall of true cascades."
        ),
    }

    roc_rows: list[dict] = []
    missing: list[float] = []

    for theta in theta_values:
        theta_str = f"{theta:.2f}".replace(".", "")
        csv_path = sweep_dir / f"theta_{theta_str}_runs.csv"
        if not csv_path.exists():
            print(f"[warn] Missing: {csv_path}")
            missing.append(theta)
            continue

        runs = load_runs_csv(csv_path)
        if not runs:
            print(f"[warn] Empty CSV: {csv_path}")
            missing.append(theta)
            continue

        metrics = compute_roc_for_theta(runs)
        row = {"theta_node": theta, **metrics}
        roc_rows.append(row)
        print(f"  theta={theta:.2f}  TPR={metrics['sensitivity_TPR']:.3f}  "
              f"FPR={metrics['FPR']:.3f}  F1={metrics['F1']:.3f}  "
              f"K_cl={metrics['K_cl']:.3f}  K_q={metrics['K_q']:.3f}")

    if missing:
        print(f"[warn] {len(missing)} theta points missing CSV: {missing}")

    # Compute AUC (trapezoidal rule over FPR/TPR)
    if len(roc_rows) >= 2:
        sorted_rows = sorted(roc_rows, key=lambda r: r["FPR"])
        fprs = [r["FPR"] for r in sorted_rows]
        tprs = [r["sensitivity_TPR"] for r in sorted_rows]
        auc = sum(
            (fprs[i + 1] - fprs[i]) * (tprs[i] + tprs[i + 1]) / 2.0
            for i in range(len(fprs) - 1)
        )
        meta["AUC_trapezoidal"] = round(auc, 4)
        print(f"\n[roc] AUC (trapezoidal) = {auc:.4f}")
    else:
        meta["AUC_trapezoidal"] = None

    # Save JSON
    roc_json = Path("results/roc_analysis_s3.json")
    output = {"metadata": meta, "roc_points": roc_rows}
    with open(roc_json, "w") as f:
        json.dump(output, f, indent=2)
    print(f"[roc] JSON → {roc_json}")

    # Save CSV
    roc_csv = Path("results/roc_analysis_s3.csv")
    if roc_rows:
        fieldnames = list(roc_rows[0].keys())
        with open(roc_csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(roc_rows)
        print(f"[roc] CSV  → {roc_csv}")

    print("\n[roc] Done.")
    if roc_rows:
        print("\nROC table:")
        print(f"{'theta_node':>10}  {'K_cl':>6}  {'K_q':>6}  {'TPR':>6}  {'FPR':>6}  {'F1':>6}")
        for row in roc_rows:
            print(f"{row['theta_node']:>10.2f}  {row['K_cl']:>6.3f}  {row['K_q']:>6.3f}  "
                  f"{row['sensitivity_TPR']:>6.3f}  {row['FPR']:>6.3f}  {row['F1']:>6.3f}")


def parse_args():
    p = argparse.ArgumentParser(
        description="Compute ROC metrics from theta sweep per-run CSV files.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--sweep-dir", default="results/theta_sweep", dest="sweep_dir",
                   help="Directory containing per-theta _runs.csv files")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_roc_analysis(args)
