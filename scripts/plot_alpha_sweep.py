"""
plot_alpha_sweep.py
===================
Visualise results/alpha_sweep.json produced by scripts/sweep_alpha.py.

Generates:
  results/figures/alpha_sweep_K_cl.png   — K_cl(α) for S3 and S4
  results/figures/alpha_sweep_mean_delta.png — mean Δx(α) for S3 and S4
  results/figures/alpha_sweep_combined.png   — 2×2 combined panel

Usage
-----
  python scripts/plot_alpha_sweep.py
"""
import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.gridspec as gridspec
except ImportError:
    print("[error] matplotlib not installed. Run: pip install matplotlib")
    sys.exit(1)

# ──────────────────────────────────────────────────────────────────────────
# Load data
# ──────────────────────────────────────────────────────────────────────────

json_path = REPO_ROOT / "results" / "alpha_sweep.json"
if not json_path.exists():
    print(f"[error] {json_path} not found. Run scripts/sweep_alpha.py first.")
    sys.exit(1)

with open(json_path, encoding="utf-8") as f:
    data = json.load(f)

scenarios = data["scenarios"]
alpha_vals = data["alpha_values"]
N = data["N_runs"]
T = data["T_steps"]

out_dir = REPO_ROOT / "results" / "figures"
out_dir.mkdir(parents=True, exist_ok=True)

COLORS = {"S3_transport": "#1f77b4", "S4_water": "#d62728"}
LABELS = {"S3_transport": "S3: transport shock (+0.25)",
          "S4_water":     "S4: water shock (+0.20)"}

# ──────────────────────────────────────────────────────────────────────────
# Combined 2×2 panel
# ──────────────────────────────────────────────────────────────────────────

fig = plt.figure(figsize=(11, 8))
gs  = gridspec.GridSpec(2, 2, hspace=0.38, wspace=0.32)

ax_kcl_s3  = fig.add_subplot(gs[0, 0])
ax_kcl_s4  = fig.add_subplot(gs[0, 1])
ax_mdelta  = fig.add_subplot(gs[1, 0])
ax_dk      = fig.add_subplot(gs[1, 1])


def extract(sc_rows, key):
    return np.array([r[key] for r in sc_rows])


for sc_name, sc_rows in scenarios.items():
    α   = np.array(alpha_vals)
    kcl = extract(sc_rows, "K_cl")
    kq  = extract(sc_rows, "K_q")
    dk  = extract(sc_rows, "delta_K")
    md  = extract(sc_rows, "mean_delta")
    se  = extract(sc_rows, "se_cl")
    col = COLORS[sc_name]
    lab = LABELS[sc_name]

    ax = ax_kcl_s3 if "S3" in sc_name else ax_kcl_s4

    # K_cl panel per scenario
    ax.errorbar(α, kcl, yerr=1.96 * se, fmt="o-", color=col,
                capsize=4, label="K_cl ± 95% CI")
    ax.axhline(kcl[0], ls="--", color=col, alpha=0.4, lw=1)
    ax.set_xlabel("α (degradation rate)", fontsize=10)
    ax.set_ylabel("K_cl (cascade probability)", fontsize=10)
    ax.set_title(f"Classical cascade prob.\n{lab}", fontsize=10)
    ax.set_xticks(α)
    ax.set_ylim(0, 1.05)
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)

# mean_delta — both scenarios on one axes
for sc_name, sc_rows in scenarios.items():
    α  = np.array(alpha_vals)
    md = extract(sc_rows, "mean_delta")
    col = COLORS[sc_name]
    lab = LABELS[sc_name]
    ax_mdelta.plot(α, md, "s-", color=col, label=lab, linewidth=1.8, markersize=6)

ax_mdelta.set_xlabel("α (degradation rate)", fontsize=10)
ax_mdelta.set_ylabel("Mean max Δx (non-initiator)", fontsize=10)
ax_mdelta.set_title("Mean cascade magnitude", fontsize=10)
ax_mdelta.set_xticks(α)
ax_mdelta.legend(fontsize=9)
ax_mdelta.grid(alpha=0.3)

# ΔK = K_q − K_cl — both scenarios
for sc_name, sc_rows in scenarios.items():
    α  = np.array(alpha_vals)
    dk = extract(sc_rows, "delta_K")
    col = COLORS[sc_name]
    lab = LABELS[sc_name]
    ax_dk.plot(α, dk, "^-", color=col, label=lab, linewidth=1.8, markersize=6)

ax_dk.axhline(0, color="k", lw=0.8, ls=":")
ax_dk.set_xlabel("α (degradation rate)", fontsize=10)
ax_dk.set_ylabel("ΔK = K_q − K_cl", fontsize=10)
ax_dk.set_title("Quantitative–classical gap ΔK", fontsize=10)
ax_dk.set_xticks(α)
ax_dk.legend(fontsize=9)
ax_dk.grid(alpha=0.3)

fig.suptitle(
    f"Effect of supply-chain degradation α on cascade probabilities\n"
    f"(N={N} MC runs per point, T={T} steps, marginal regime)",
    fontsize=11, y=1.01,
)

combined_path = out_dir / "alpha_sweep_combined.png"
fig.savefig(combined_path, dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"[save] {combined_path}")

# ──────────────────────────────────────────────────────────────────────────
# Standalone mean_delta plot (clearest signal)
# ──────────────────────────────────────────────────────────────────────────

fig2, ax2 = plt.subplots(figsize=(7, 4))
for sc_name, sc_rows in scenarios.items():
    α  = np.array(alpha_vals)
    md = extract(sc_rows, "mean_delta")
    col = COLORS[sc_name]
    lab = LABELS[sc_name]
    ax2.plot(α, md, "o-", color=col, label=lab, linewidth=2, markersize=7)

ax2.set_xlabel("α (supply-chain degradation rate)", fontsize=11)
ax2.set_ylabel("Mean max Δx (non-initiator sectors)", fontsize=11)
ax2.set_title(
    "Supply-chain degradation dampens cascade magnitude\n"
    f"(N={N} MC, T={T} steps, marginal regime)",
    fontsize=11,
)
ax2.set_xticks(alpha_vals)
ax2.legend(fontsize=10)
ax2.grid(alpha=0.3)

md_path = out_dir / "alpha_sweep_mean_delta.png"
fig2.savefig(md_path, dpi=150, bbox_inches="tight")
plt.close(fig2)
print(f"[save] {md_path}")

print("\nDone.")
