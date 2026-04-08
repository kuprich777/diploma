#!/usr/bin/env python3
"""
Generate result figures for calibrated matrix v2.0 experiments.
Uses completed N=1000 MC results and sweep summaries.
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

BASE = Path(__file__).parent.parent
RES = BASE / "results"
FIGS = RES / "figures"
FIGS.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# 1. K_cl vs K_q bar chart by scenario, both matrices
# ---------------------------------------------------------------------------

SCENARIOS_EXPERT = {
    "S3 (transport\nload=0.40)": {"K_cl": 0.534, "K_q": 0.956},
    "S4 (water\nload=0.70)":    {"K_cl": 0.416, "K_q": 0.876},
}

# Results from N=1000 runs with calibrated v2.0
def load_mc_result(fname: str) -> dict:
    p = RES / fname
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return {}


s1b_cal = load_mc_result("mc_s1b_calibrated_1000_full.json")
s3_cal  = load_mc_result("mc_s3_calibrated_1000_full.json")
s4_cal  = load_mc_result("mc_s4_calibrated_1000_full.json")
s5_cal  = load_mc_result("mc_s5_calibrated_1000_full.json")
s1_cal  = load_mc_result("calib_v2_s1_full.json")

SCENARIOS_V2 = {
    "S1 (energy\noutage)":       {"K_cl": s1_cal.get("K_cl",  1.000), "K_q": s1_cal.get("K_q",  0.980)},
    "S1b (energy\nload=0.01)":   {"K_cl": s1b_cal.get("K_cl", 0.381), "K_q": s1b_cal.get("K_q", 0.000)},
    "S3 (transport\nload=0.40)": {"K_cl": s3_cal.get("K_cl",  0.454), "K_q": s3_cal.get("K_q",  0.355)},
    "S4 (water\nload=0.70)":     {"K_cl": s4_cal.get("K_cl",  0.399), "K_q": s4_cal.get("K_q",  0.812)},
    "S5 (transport\nload=0.35)": {"K_cl": s5_cal.get("K_cl",  0.341), "K_q": s5_cal.get("K_q",  0.238)},
}

# Full comparison figure (4 scenarios that have expert baseline)
fig, axes = plt.subplots(1, 2, figsize=(13, 5))

# Left: expert v1.0
ax = axes[0]
labels = list(SCENARIOS_EXPERT.keys())
k_cl_e = [v["K_cl"] for v in SCENARIOS_EXPERT.values()]
k_q_e  = [v["K_q"]  for v in SCENARIOS_EXPERT.values()]
x = np.arange(len(labels))
ax.bar(x - 0.2, k_cl_e, 0.35, label="K_cl (classical)", color="#e63946", alpha=0.85)
ax.bar(x + 0.2, k_q_e,  0.35, label="K_q (quantitative)", color="#457b9d", alpha=0.85)
ax.set_xticks(x); ax.set_xticklabels(labels, fontsize=10)
ax.set_ylim(0, 1.1); ax.set_ylabel("Cascade indicator K")
ax.set_title("A_expert v1.0 (N=1000)", fontsize=11, fontweight="bold")
ax.legend(); ax.grid(axis="y", alpha=0.3)
ax.axhline(0.25, ls="--", color="gray", alpha=0.5, lw=1, label="H₁ threshold")
for xi, (kc, kq) in zip(x, zip(k_cl_e, k_q_e)):
    ax.text(xi - 0.2, kc + 0.02, f"{kc:.3f}", ha="center", fontsize=8)
    ax.text(xi + 0.2, kq + 0.02, f"{kq:.3f}", ha="center", fontsize=8)

# Right: calibrated v2.0
ax = axes[1]
labels2 = list(SCENARIOS_V2.keys())
k_cl_v2 = [v["K_cl"] for v in SCENARIOS_V2.values()]
k_q_v2  = [v["K_q"]  for v in SCENARIOS_V2.values()]
x2 = np.arange(len(labels2))
ax.bar(x2 - 0.2, k_cl_v2, 0.35, label="K_cl (classical)", color="#e63946", alpha=0.85)
ax.bar(x2 + 0.2, k_q_v2,  0.35, label="K_q (quantitative)", color="#457b9d", alpha=0.85)
ax.set_xticks(x2); ax.set_xticklabels(labels2, fontsize=9)
ax.set_ylim(0, 1.1); ax.set_ylabel("Cascade indicator K")
ax.set_title("A_calibrated v2.0 (N=1000)", fontsize=11, fontweight="bold")
ax.legend(); ax.grid(axis="y", alpha=0.3)
for xi, (kc, kq) in zip(x2, zip(k_cl_v2, k_q_v2)):
    ax.text(xi - 0.2, kc + 0.02, f"{kc:.3f}", ha="center", fontsize=8)
    ax.text(xi + 0.2, kq + 0.02, f"{kq:.3f}", ha="center", fontsize=8)

plt.suptitle("K_cl vs K_q by Scenario: Expert vs Calibrated Matrix", fontsize=13, fontweight="bold")
plt.tight_layout()
plt.savefig(FIGS / "K_cl_vs_K_q_by_scenario.png", dpi=150, bbox_inches="tight")
plt.close()
print("Saved K_cl_vs_K_q_by_scenario.png")


# ---------------------------------------------------------------------------
# 2. Load sweep S3 (calibrated v2.0)
# ---------------------------------------------------------------------------
sweep_path = RES / "load_sweep_s3_calibrated.json"
if not sweep_path.exists():
    # Try reading from existing summary
    sweep_path2 = RES / "load_sweep_s3_summary.json"
    if sweep_path2.exists():
        sweep_path = sweep_path2

if sweep_path.exists():
    with open(sweep_path) as f:
        sweep_data = json.load(f)
    if isinstance(sweep_data, list):
        loads = [d["load_amount"] for d in sweep_data]
        k_cl_s = [d["K_cl"] for d in sweep_data]
        k_q_s  = [d["K_q"] for d in sweep_data]
    elif isinstance(sweep_data, dict) and "rows" in sweep_data:
        loads = [d["load_amount"] for d in sweep_data["rows"]]
        k_cl_s = [d["K_cl"] for d in sweep_data["rows"]]
        k_q_s  = [d["K_q"] for d in sweep_data["rows"]]
    else:
        loads, k_cl_s, k_q_s = [], [], []

    if loads:
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(loads, k_cl_s, "o-", color="#e63946", lw=2, label="K_cl (classical)", markersize=6)
        ax.plot(loads, k_q_s,  "s-", color="#457b9d", lw=2, label="K_q (quantitative)", markersize=6)
        ax.fill_between(loads, k_cl_s, k_q_s, where=[kq > kc for kc, kq in zip(k_cl_s, k_q_s)],
                        alpha=0.15, color="#457b9d", label="K_q > K_cl zone")
        ax.fill_between(loads, k_cl_s, k_q_s, where=[kc > kq for kc, kq in zip(k_cl_s, k_q_s)],
                        alpha=0.15, color="#e63946", label="K_cl > K_q zone")
        ax.axhline(0.25, ls="--", color="gray", alpha=0.5, lw=1)
        ax.axvline(0.40, ls=":", color="purple", alpha=0.6, lw=1.5, label="N=1000 experiment point")
        ax.set_xlabel("load_amount (transport sector)", fontsize=11)
        ax.set_ylabel("Cascade indicator K", fontsize=11)
        ax.set_title("S3 Load Sweep: K_cl vs K_q (A_calibrated v2.0, N=500/point)", fontsize=12, fontweight="bold")
        ax.legend(fontsize=9); ax.grid(alpha=0.3)
        plt.tight_layout()
        plt.savefig(FIGS / "load_sweep_s3_calibrated.png", dpi=150, bbox_inches="tight")
        plt.close()
        print("Saved load_sweep_s3_calibrated.png")
else:
    print(f"Load sweep data not found at {sweep_path}, skipping figure")


# ---------------------------------------------------------------------------
# 3. Severity sweep S4 (calibrated v2.0)
# ---------------------------------------------------------------------------
sev_path = RES / "severity_sweep_s4_calibrated.json"
if not sev_path.exists():
    sev_path2 = RES / "severity_sweep_water_summary.json"
    if sev_path2.exists():
        sev_path = sev_path2

if sev_path.exists():
    with open(sev_path) as f:
        sev_data = json.load(f)
    if isinstance(sev_data, list):
        sevs = [d["load_amount"] for d in sev_data]
        k_cl_sv = [d["K_cl"] for d in sev_data]
        k_q_sv  = [d["K_q"] for d in sev_data]
    elif isinstance(sev_data, dict) and "rows" in sev_data:
        sevs = [d["load_amount"] for d in sev_data["rows"]]
        k_cl_sv = [d["K_cl"] for d in sev_data["rows"]]
        k_q_sv  = [d["K_q"] for d in sev_data["rows"]]
    else:
        sevs, k_cl_sv, k_q_sv = [], [], []

    if sevs:
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(sevs, k_cl_sv, "o-", color="#e63946", lw=2, label="K_cl (classical)", markersize=6)
        ax.plot(sevs, k_q_sv,  "s-", color="#457b9d", lw=2, label="K_q (quantitative)", markersize=6)
        ax.fill_between(sevs, k_cl_sv, k_q_sv,
                        where=[kq > kc for kc, kq in zip(k_cl_sv, k_q_sv)],
                        alpha=0.2, color="#457b9d", label="K_q advantage zone")
        ax.axhline(0.25, ls="--", color="gray", alpha=0.5, lw=1)
        # Annotate Jackson MS 2022 (water crisis) at severity ~0.70
        ax.axvline(0.70, ls=":", color="purple", alpha=0.6, lw=1.5, label="N=1000 experiment (0.70)")
        ax.set_xlabel("load_amount (water sector)", fontsize=11)
        ax.set_ylabel("Cascade indicator K", fontsize=11)
        ax.set_title("S4 Severity Sweep: K_cl vs K_q (A_calibrated v2.0, N=500/point)", fontsize=12, fontweight="bold")
        ax.legend(fontsize=9); ax.grid(alpha=0.3)
        plt.tight_layout()
        plt.savefig(FIGS / "severity_sweep_s4_calibrated.png", dpi=150, bbox_inches="tight")
        plt.close()
        print("Saved severity_sweep_s4_calibrated.png")
else:
    print(f"Severity sweep data not found at {sev_path}, skipping figure")


# ---------------------------------------------------------------------------
# 4. Expert vs Calibrated comparison scatter
# ---------------------------------------------------------------------------
# Compare 6 off-diagonal elements
A_expert = np.array([[0.0, 0.2, 0.3], [0.4, 0.0, 0.2], [0.5, 0.3, 0.0]])
A_cal    = np.array([[0.0, 0.3246, 0.1357], [0.0824, 0.0, 0.0199], [0.5, 0.1998, 0.0]])
SECTORS = ["energy", "water", "transport"]
mask = ~np.eye(3, dtype=bool)
edge_labels = [f"A[{SECTORS[i]}][{SECTORS[j]}]"
               for i in range(3) for j in range(3) if i != j]
exp_vals = A_expert[mask].flatten()
cal_vals = A_cal[mask].flatten()

fig, ax = plt.subplots(figsize=(6, 6))
colors = ["#e63946","#457b9d","#2a9d8f","#f4a261","#264653","#e9c46a"]
for i, (lbl, ev, cv, col) in enumerate(zip(edge_labels, exp_vals, cal_vals, colors)):
    ax.scatter(ev, cv, s=120, color=col, zorder=3)
    ax.annotate(lbl, (ev, cv), textcoords="offset points", xytext=(5, 5), fontsize=8)
ax.plot([0, 0.5], [0, 0.5], "k--", alpha=0.3, lw=1, label="y=x (equal)")
ax.set_xlabel("A_expert v1.0 coefficient", fontsize=11)
ax.set_ylabel("A_calibrated v2.0 coefficient", fontsize=11)
ax.set_title("Expert vs Calibrated: Off-diagonal Elements", fontsize=12, fontweight="bold")
ax.grid(alpha=0.3); ax.legend()
ax.set_xlim(-0.02, 0.55); ax.set_ylim(-0.02, 0.55)
plt.tight_layout()
plt.savefig(FIGS / "comparison_expert_vs_calibrated.png", dpi=150, bbox_inches="tight")
plt.close()
print("Saved comparison_expert_vs_calibrated.png")

print(f"\nAll result figures saved to {FIGS}")
