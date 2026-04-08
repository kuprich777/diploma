#!/usr/bin/env python3
"""Generate all figures for matrix_doc/figures/."""

import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

OUT = Path(__file__).parent / "figures"
OUT.mkdir(exist_ok=True)

SECTORS = ["energy", "water", "transport"]
N = 3

# Load matrices
BASE = Path(__file__).parent
A_expert = np.array(json.loads((BASE / "A_expert_v1.json").read_text())["matrix"])
A_russia  = np.array(json.loads((BASE / "A_russia.json").read_text())["matrix"])
A_germany = np.array(json.loads((BASE / "A_germany.json").read_text())["matrix"])
A_usa     = np.array(json.loads((BASE / "A_usa.json").read_text())["matrix"])
A_cal     = np.array(json.loads((BASE / "A_calibrated_v2.json").read_text())["matrix"])


# ---------------------------------------------------------------------------
# 1. Heatmap 2×2: expert + 3 countries
# ---------------------------------------------------------------------------
fig, axes = plt.subplots(2, 2, figsize=(10, 8))
matrices = [
    (A_expert, "A_expert v1.0\n(Expert elicitation)"),
    (A_russia,  "A_russia (Росстат ТЗВ-2019)"),
    (A_germany, "A_germany (Eurostat DE 2019)"),
    (A_usa,     "A_usa (BEA USA 2017)"),
]
for ax, (A, title) in zip(axes.flat, matrices):
    im = ax.imshow(A, cmap="YlOrRd", vmin=0, vmax=0.5)
    ax.set_xticks(range(N)); ax.set_yticks(range(N))
    ax.set_xticklabels(SECTORS, fontsize=9); ax.set_yticklabels(SECTORS, fontsize=9)
    ax.set_xlabel("Source j", fontsize=8); ax.set_ylabel("Dest i", fontsize=8)
    ax.set_title(title, fontsize=10)
    for i in range(N):
        for j in range(N):
            ax.text(j, i, f"{A[i,j]:.3f}", ha="center", va="center",
                    fontsize=8, color="black" if A[i,j] < 0.35 else "white")
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

plt.suptitle("Dependency Matrix A — Expert vs Calibrated (3 Countries)", fontsize=12, fontweight="bold")
plt.tight_layout()
plt.savefig(OUT / "heatmap_3countries.png", dpi=150, bbox_inches="tight")
plt.close()
print("Saved heatmap_3countries.png")


# ---------------------------------------------------------------------------
# 2. Heatmap expert vs calibrated (side-by-side)
# ---------------------------------------------------------------------------
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4))
for ax, (A, title) in [(ax1, (A_expert, "A_expert v1.0")), (ax2, (A_cal, "A_calibrated v2.0"))]:
    im = ax.imshow(A, cmap="YlOrRd", vmin=0, vmax=0.5)
    ax.set_xticks(range(N)); ax.set_yticks(range(N))
    ax.set_xticklabels(SECTORS, fontsize=10); ax.set_yticklabels(SECTORS, fontsize=10)
    ax.set_title(title, fontsize=12, fontweight="bold")
    ax.set_xlabel("Source j"); ax.set_ylabel("Dest i")
    for i in range(N):
        for j in range(N):
            ax.text(j, i, f"{A[i,j]:.3f}", ha="center", va="center",
                    fontsize=10, color="black" if A[i,j] < 0.35 else "white")
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
# Annotate differences
diff = A_cal - A_expert
ax2.set_title(f"A_calibrated v2.0\n(MAE={np.abs(diff[diff!=0]).mean():.3f} vs expert)", fontsize=11)
plt.suptitle("Expert vs Calibrated Dependency Matrix", fontsize=13, fontweight="bold")
plt.tight_layout()
plt.savefig(OUT / "heatmap_expert_vs_calibrated.png", dpi=150, bbox_inches="tight")
plt.close()
print("Saved heatmap_expert_vs_calibrated.png")


# ---------------------------------------------------------------------------
# 3. Rank comparison bar chart
# ---------------------------------------------------------------------------
mask = ~np.eye(N, dtype=bool)
edges = [(SECTORS[i], SECTORS[j]) for i in range(N) for j in range(N) if i != j]
edge_labels = [f"{s[0][:3]}←{s[1][:3]}" for s in edges]

vals_exp = A_expert[mask].flatten()
vals_rus = A_russia[mask].flatten()
vals_ger = A_germany[mask].flatten()
vals_usa = A_usa[mask].flatten()
vals_cal = A_cal[mask].flatten()

x = np.arange(len(edges))
width = 0.15
fig, ax = plt.subplots(figsize=(13, 5))
ax.bar(x - 2*width, vals_exp, width, label="Expert v1.0", color="#e63946", alpha=0.85)
ax.bar(x - width,   vals_rus, width, label="Russia 2019",  color="#457b9d", alpha=0.85)
ax.bar(x,           vals_ger, width, label="Germany 2019", color="#2a9d8f", alpha=0.85)
ax.bar(x + width,   vals_usa, width, label="USA 2017",     color="#e9c46a", alpha=0.85)
ax.bar(x + 2*width, vals_cal, width, label="Calibrated v2 (mean)", color="#264653", alpha=0.95)
ax.set_xticks(x); ax.set_xticklabels(edge_labels, fontsize=10)
ax.set_ylabel("A[i][j] coefficient")
ax.set_title("Dependency Coefficients by Edge: Expert vs 3-Country Calibration", fontsize=12)
ax.legend(fontsize=9); ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
plt.savefig(OUT / "rank_comparison_bar.png", dpi=150, bbox_inches="tight")
plt.close()
print("Saved rank_comparison_bar.png")


# ---------------------------------------------------------------------------
# 4. Dependency graph A_calibrated (circular layout, 3 nodes, 6 edges)
# ---------------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(7, 6))
ax.set_xlim(-1.5, 1.5); ax.set_ylim(-1.4, 1.5)
ax.set_aspect("equal"); ax.axis("off")

# Node positions (triangle)
pos = {
    "energy":    (0.0,  1.1),
    "water":     (-1.0, -0.6),
    "transport": (1.0,  -0.6),
}
node_colors = {"energy": "#e63946", "water": "#457b9d", "transport": "#2a9d8f"}
node_r = 0.22

for name, (x, y) in pos.items():
    circle = plt.Circle((x, y), node_r, color=node_colors[name], zorder=3)
    ax.add_patch(circle)
    ax.text(x, y, name, ha="center", va="center", fontsize=10,
            fontweight="bold", color="white", zorder=4)

def draw_curved_arrow(ax, src, dst, weight, color, offset=0.12):
    sx, sy = pos[src]
    dx, dy = pos[dst]
    mx, my = (sx + dx) / 2, (sy + dy) / 2
    # perpendicular offset for curvature
    length = math.hypot(dx - sx, dy - sy)
    px, py = -(dy - sy) / length * offset, (dx - sx) / length * offset
    # Start/end on node edge
    ang_s = math.atan2(dy - sy, dx - sx)
    ang_d = math.atan2(sy - dy, sx - dx)
    xs = sx + node_r * math.cos(ang_s)
    ys = sy + node_r * math.sin(ang_s)
    xd = dx + node_r * math.cos(ang_d)
    yd = dy + node_r * math.sin(ang_d)
    ax.annotate(
        "", xy=(xd, yd), xytext=(xs, ys),
        arrowprops=dict(
            arrowstyle=f"->, head_width={0.15 + weight * 0.3}, head_length=0.08",
            color=color, lw=1.0 + weight * 2.5,
            connectionstyle=f"arc3,rad={0.25}",
        ), zorder=2,
    )
    lx = mx + px * 1.5
    ly = my + py * 1.5
    ax.text(lx, ly, f"{weight:.3f}", fontsize=8, ha="center", va="center",
            color=color, fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.1", facecolor="white", alpha=0.7, edgecolor="none"))

sector_idx = {s: i for i, s in enumerate(SECTORS)}
edge_colors = ["#e63946", "#457b9d", "#2a9d8f", "#f4a261", "#264653", "#e9c46a"]
ec = 0
for i, dest in enumerate(SECTORS):
    for j, src in enumerate(SECTORS):
        if i != j and A_cal[i, j] > 0:
            draw_curved_arrow(ax, src, dest, A_cal[i, j], edge_colors[ec % len(edge_colors)])
            ec += 1

ax.set_title("Dependency Graph A_calibrated v2.0", fontsize=13, fontweight="bold", pad=10)
plt.tight_layout()
plt.savefig(OUT / "dependency_graph_v2.png", dpi=150, bbox_inches="tight")
plt.close()
print("Saved dependency_graph_v2.png")

print(f"\nAll figures saved to {OUT}")
