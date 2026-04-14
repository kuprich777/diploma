"""
generate_presentation_plots.py
─────────────────────────────
Generates 13 publication-ready figures for the pre-defense presentation.

Output: results/figures/fig_01_barchart_results.png  …  fig_13_phase_comparison.png

Usage:
    python scripts/generate_presentation_plots.py

All labels in Russian; DPI=200.
Colors: NAVY=#1A3C8B  ORANGE=#E87722  GREEN=#2E7D32  RED=#C41E3A
"""

import json
import os
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.ticker as mticker
from matplotlib.gridspec import GridSpec
from scipy.stats import norm

# ──────────────────────────────────────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MC_DIR   = os.path.join(ROOT, "results", "mc_runs")
RES_DIR  = os.path.join(ROOT, "results")
FIG_DIR  = os.path.join(ROOT, "results", "figures")
os.makedirs(FIG_DIR, exist_ok=True)

# ──────────────────────────────────────────────────────────────────────────────
# Model constants
# ──────────────────────────────────────────────────────────────────────────────
NAVY   = "#1A3C8B"
ORANGE = "#E87722"
GREEN  = "#2E7D32"
RED    = "#C41E3A"
GRAY   = "#7F7F7F"
SECTORS = ["Энергетика", "Водоснабжение", "Транспорт"]
SECTORS_EN = ["energy", "water", "transport"]

# A_wiod_v3 (row = recipient, col = source)
A_LEONTIEF = np.array([
    [0.0,   0.350, 0.304],
    [0.006, 0.0,   0.001],
    [0.500, 0.332, 0.0  ],
])
C = np.array([0.8832, 0.6463, 0.9280])       # capacity thresholds
SIGMA = np.array([0.259, 0.232, 0.259])       # volatilities
DT    = 0.1
DELTA = 0.10                                  # quantitative threshold

# ──────────────────────────────────────────────────────────────────────────────
# Load data
# ──────────────────────────────────────────────────────────────────────────────
def load_json(path):
    with open(path) as f:
        return json.load(f)

def load_scenario(sid):
    return load_json(os.path.join(MC_DIR, f"{sid}.json"))

# Experiment summary
_exp_raw = load_json(os.path.join(RES_DIR, "experiment_summary.json"))
EXPERIMENTS = _exp_raw   # list of dicts

ALPHA_DATA = load_json(os.path.join(RES_DIR, "alpha_sweep.json"))
VAL_DATA   = load_json(os.path.join(RES_DIR, "validation_real_events.json"))

S3_DATA = load_scenario("S3_transport_marginal")
S4_DATA = load_scenario("S4_water_marginal")

BAYES_DATA = load_json(os.path.join(ROOT, "matrix_doc", "A_bayesian_posterior.json"))

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
plt.rcParams.update({
    "font.size": 11,
    "axes.titlesize": 12,
    "axes.labelsize": 11,
    "legend.fontsize": 10,
    "figure.dpi": 200,
    "savefig.dpi": 200,
    "savefig.bbox": "tight",
})


def spectral_radius(A):
    ev = np.linalg.eigvals(A)
    return float(np.max(np.abs(ev)))


def save(fig, name):
    path = os.path.join(FIG_DIR, name)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved {name}")


# ══════════════════════════════════════════════════════════════════════════════
# VIZ 1 — Main barchart K_cl vs K_q (all 9 scenarios)
# ══════════════════════════════════════════════════════════════════════════════
def viz_01_barchart():
    ids   = [e["scenario_id"] for e in EXPERIMENTS]
    k_cl  = [e["K_cl"]     for e in EXPERIMENTS]
    k_q   = [e["K_q"]      for e in EXPERIMENTS]
    dpct  = [e["delta_pct"] for e in EXPERIMENTS]
    h1    = [e["H1_actual"] for e in EXPERIMENTS]

    short_labels = [
        "S1\n(энергетика)", "S3\n(транспорт)", "S4\n(вода)",
        "S5\n(комбо)", "Baltimore\n2024", "UCTE\n2006",
        "Texas\n2021", "India\n2012", "Christchurch\n2011",
    ]
    n = len(ids)
    x = np.arange(n)
    w = 0.35

    fig, ax = plt.subplots(figsize=(13, 5))

    bars_cl = ax.bar(x - w/2, k_cl, w, color=NAVY,   label="$K_{cl}$ — классический", zorder=3)
    bars_q  = ax.bar(x + w/2, k_q,  w, color=ORANGE, label="$K_q$ — количественный",  zorder=3)

    # Δ% annotations
    for i, (dp, h) in enumerate(zip(dpct, h1)):
        ymax = max(k_cl[i], k_q[i])
        if h == "saturated":
            ax.text(x[i], ymax + 0.03, "нас.", ha="center", va="bottom",
                    fontsize=8.5, color=GRAY)
        elif h == "confirmed":
            ax.text(x[i], ymax + 0.03, f"+{dp:.0f}%", ha="center", va="bottom",
                    fontsize=8.5, color=GREEN, fontweight="bold")
        elif h == "below_threshold":
            ax.text(x[i], ymax + 0.03, f"+{dp:.0f}%", ha="center", va="bottom",
                    fontsize=8.5, color=GRAY)

    # H₁=25% threshold line
    ax.axhline(1.0, color="black", lw=0.5, ls="--", alpha=0.4)

    # Separator between synthetic and real
    ax.axvline(3.5, color=GRAY, lw=1.2, ls=":", alpha=0.7)
    ax.text(1.5, 1.07, "Синтетические сценарии", ha="center", fontsize=9.5,
            color=GRAY, transform=ax.get_xaxis_transform())
    ax.text(6.5, 1.07, "Реальные события", ha="center", fontsize=9.5,
            color=GRAY, transform=ax.get_xaxis_transform())

    ax.set_xticks(x)
    ax.set_xticklabels(short_labels, fontsize=9)
    ax.set_ylabel("Вероятность обнаружения каскада")
    ax.set_ylim(0, 1.14)
    ax.set_title("Рис. 1. $K_{cl}$ vs $K_q$ по всем сценариям (N=1000 MC, T=7/50)")
    ax.legend(loc="upper left", framealpha=0.9)
    ax.grid(axis="y", alpha=0.3, zorder=0)

    save(fig, "fig_01_barchart_results.png")


# ══════════════════════════════════════════════════════════════════════════════
# VIZ 2 — Trajectory panels S3 and S4
# ══════════════════════════════════════════════════════════════════════════════
def _plot_trajectories(mc_data, title_suffix, outname):
    trajs = mc_data["trajectories_sample"]   # list of (T+1) × 3
    T1 = len(trajs[0])
    traj_arr = np.array(trajs)               # (n_sample, T+1, 3)
    steps = np.arange(T1)

    p10 = np.percentile(traj_arr, 10, axis=0)
    p50 = np.percentile(traj_arr, 50, axis=0)
    p90 = np.percentile(traj_arr, 90, axis=0)

    colors_s = [NAVY, GREEN, ORANGE]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4), sharey=True)
    fig.suptitle(f"Рис. 2. Траектории секторов — {title_suffix} (N={len(trajs)} выборок)",
                 fontsize=11)

    for j, (ax, sec, col) in enumerate(zip(axes, SECTORS, colors_s)):
        ax.fill_between(steps, p10[:, j], p90[:, j], alpha=0.25, color=col,
                        label="10–90%")
        ax.plot(steps, p50[:, j], color=col, lw=2, label="медиана")
        ax.axhline(C[j], color=RED, lw=1.2, ls="--", label=f"$C_{j+1}$={C[j]:.3f}")
        ax.axhline(DELTA, color=GRAY, lw=0.8, ls=":", alpha=0.6)
        ax.set_title(sec)
        ax.set_xlabel("Шаг t")
        if j == 0:
            ax.set_ylabel("Уровень нагрузки $x_j$")
        ax.set_ylim(0, 1.05)
        ax.legend(fontsize=8.5, loc="upper left")
        ax.grid(alpha=0.25)

    save(fig, outname)


def viz_02_trajectories():
    _plot_trajectories(S3_DATA, "S3 (транспорт +0.25, T=7)",
                       "fig_02_trajectories_s3.png")
    _plot_trajectories(S4_DATA, "S4 (вода +0.20, T=7)",
                       "fig_02_trajectories_s4.png")


# ══════════════════════════════════════════════════════════════════════════════
# VIZ 3 — Heatmap A_leontief
# ══════════════════════════════════════════════════════════════════════════════
def viz_03_heatmap():
    A = A_LEONTIEF
    rho = spectral_radius(A)

    fig, ax = plt.subplots(figsize=(5.5, 4.5))
    im = ax.imshow(A, cmap="Blues", vmin=0, vmax=0.55, aspect="equal")

    for i in range(3):
        for j in range(3):
            val = A[i, j]
            col = "white" if val > 0.3 else "black"
            ax.text(j, i, f"{val:.3f}", ha="center", va="center",
                    color=col, fontsize=11, fontweight="bold")

    ax.set_xticks([0, 1, 2])
    ax.set_yticks([0, 1, 2])
    ax.set_xticklabels(["Энерг.", "Вода", "Транспорт"])
    ax.set_yticklabels(["Энерг.", "Вода", "Транспорт"])
    ax.set_xlabel("Источник воздействия (j)")
    ax.set_ylabel("Получатель (i)")
    ax.set_title(
        f"Рис. 3. Матрица зависимостей $A_{{wiod}}$\n"
        f"$\\rho(A)={rho:.4f}$   (WIOD 2016 NIOT, Леонтьев, rescale max=0.5)"
    )
    plt.colorbar(im, ax=ax, fraction=0.045, pad=0.04, label="$A_{ij}$")

    save(fig, "fig_03_heatmap_A.png")


# ══════════════════════════════════════════════════════════════════════════════
# VIZ 4 — Cascade distribution (max_delta histograms from sample trajectories)
# ══════════════════════════════════════════════════════════════════════════════
def viz_04_cascade_distribution():
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))

    for ax, mc_data, label, col in zip(
        axes,
        [S3_DATA, S4_DATA],
        ["S3 (транспорт +0.25)", "S4 (вода +0.20)"],
        [NAVY, ORANGE],
    ):
        trajs = np.array(mc_data["trajectories_sample"])  # (n, T+1, 3)
        x0 = trajs[:, 0, :]                               # initial state
        max_delta = np.max(np.max(trajs[:, 1:, :] - x0[:, np.newaxis, :], axis=1), axis=1)
        # exclude initiator sector to get cross-sector max
        # for S3: initiator=transport(2), for S4: initiator=water(1)

        ax.hist(max_delta, bins=12, color=col, alpha=0.75, edgecolor="white", zorder=3)
        ax.axvline(DELTA, color=RED, lw=2, ls="--", label=f"δ={DELTA}")
        mean_val = mc_data["mean_max_delta"]
        ax.axvline(mean_val, color=NAVY if col==ORANGE else ORANGE,
                   lw=1.5, ls="-", label=f"μ={mean_val:.3f}")
        ax.set_xlabel("max $\\Delta x$ (по секторам и шагам)")
        ax.set_ylabel("Число прогонов")
        ax.set_title(f"{label}")
        ax.legend(fontsize=9)
        ax.grid(alpha=0.3, zorder=0)

    fig.suptitle("Рис. 4. Распределение max Δx (выборка 20 из N=1000 MC прогонов)", fontsize=11)
    save(fig, "fig_04_cascade_distribution.png")


# ══════════════════════════════════════════════════════════════════════════════
# VIZ 5 — Alpha sensitivity
# ══════════════════════════════════════════════════════════════════════════════
def viz_05_alpha_sensitivity():
    alphas = ALPHA_DATA["alpha_values"]
    s3 = ALPHA_DATA["scenarios"]["S3_transport"]
    s4 = ALPHA_DATA["scenarios"]["S4_water"]

    s3_kcl = [d["K_cl"]       for d in s3]
    s3_kq  = [d["K_q"]        for d in s3]
    s3_md  = [d["mean_delta"]  for d in s3]
    s4_kcl = [d["K_cl"]       for d in s4]
    s4_kq  = [d["K_q"]        for d in s4]
    s4_md  = [d["mean_delta"]  for d in s4]

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharey=False)
    fig.suptitle("Рис. 5. Чувствительность к α (динамическая матрица A(t))", fontsize=11)

    for ax, kcl, kq, md, title, col_cl, col_q, col_md in [
        (axes[0], s3_kcl, s3_kq, s3_md, "S3: транспорт +0.25", NAVY, ORANGE, GREEN),
        (axes[1], s4_kcl, s4_kq, s4_md, "S4: вода +0.20",      NAVY, ORANGE, GREEN),
    ]:
        ax2 = ax.twinx()
        ax.plot(alphas, kcl, "o-", color=col_cl, lw=1.8, ms=5, label="$K_{cl}$")
        ax.plot(alphas, kq,  "s-", color=col_q,  lw=1.8, ms=5, label="$K_q$")
        ax2.plot(alphas, md, "^--", color=col_md, lw=1.4, ms=4, label="mean $\\Delta x$")
        ax.set_xlabel("Коэффициент деградации α")
        ax.set_ylabel("Вероятность обнаружения K", color="black")
        ax2.set_ylabel("mean max $\\Delta x$", color=col_md)
        ax2.tick_params(axis="y", labelcolor=col_md)
        ax.set_ylim(0, 1.1)
        ax.set_title(title)
        ax.grid(alpha=0.3)
        lines1, labs1 = ax.get_legend_handles_labels()
        lines2, labs2 = ax2.get_legend_handles_labels()
        ax.legend(lines1 + lines2, labs1 + labs2, fontsize=9, loc="upper right")

    save(fig, "fig_05_alpha_sensitivity.png")


# ══════════════════════════════════════════════════════════════════════════════
# VIZ 6 — Dependency graph
# ══════════════════════════════════════════════════════════════════════════════
def viz_06_dependency_graph():
    A = A_LEONTIEF
    pos = {0: (0.5, 0.9), 1: (0.1, 0.1), 2: (0.9, 0.1)}
    node_colors = [NAVY, GREEN, ORANGE]
    labels = ["Энерг.", "Вода", "Транспорт"]

    fig, ax = plt.subplots(figsize=(6, 5))
    ax.set_xlim(-0.05, 1.05)
    ax.set_ylim(-0.05, 1.05)
    ax.axis("off")
    ax.set_title("Рис. 6. Граф зависимостей инфраструктурных секторов\n"
                 "(толщина → $A_{ij}$, цвет → источник)")

    r = 0.075
    # Draw nodes
    for i, (x, y) in pos.items():
        circle = plt.Circle((x, y), r, color=node_colors[i], zorder=5, ec="white", lw=1.5)
        ax.add_patch(circle)
        ax.text(x, y, labels[i], ha="center", va="center", fontsize=9.5,
                color="white", fontweight="bold", zorder=6)

    # Draw directed edges
    for i in range(3):
        for j in range(3):
            if i == j or A[i, j] < 1e-4:
                continue
            x0, y0 = pos[j]   # source j
            x1, y1 = pos[i]   # target i
            dx, dy = x1 - x0, y1 - y0
            length = np.sqrt(dx**2 + dy**2)
            # shorten to node boundary
            sx = x0 + r * dx / length
            sy = y0 + r * dy / length
            ex = x1 - r * dx / length
            ey = y1 - r * dy / length
            lw_edge = 1.5 + A[i, j] * 8
            ax.annotate(
                "", xy=(ex, ey), xytext=(sx, sy),
                arrowprops=dict(arrowstyle="-|>", lw=lw_edge,
                                color=node_colors[j], mutation_scale=16),
                zorder=3,
            )
            mx, my = (sx + ex) / 2, (sy + ey) / 2
            offset_x = -0.06 * dy / length
            offset_y =  0.06 * dx / length
            ax.text(mx + offset_x, my + offset_y, f"{A[i,j]:.3f}",
                    fontsize=8, ha="center", va="center", color=node_colors[j],
                    bbox=dict(fc="white", ec="none", alpha=0.75, pad=1))

    save(fig, "fig_06_dependency_graph.png")


# ══════════════════════════════════════════════════════════════════════════════
# VIZ 7 — H₁ summary table
# ══════════════════════════════════════════════════════════════════════════════
def viz_07_summary_table():
    rows = [
        ["S1_energy_outage",      "1.000", "1.000", " 0.0%", "насыщение",     "#D9D9D9"],
        ["S3_transport_marginal", "0.595", "0.883", "+48.4%", "✓ подтв.",      "#C8E6C9"],
        ["S4_water_marginal",     "0.620", "1.000", "+61.3%", "✓ подтв.",      "#C8E6C9"],
        ["S5_combined",           "0.832", "1.000", "+20.2%", "ниже порога",   "#FFF9C4"],
        ["REAL_baltimore_2024",   "0.606", "0.884", "+45.9%", "✓ подтв.",      "#C8E6C9"],
        ["REAL_europe_2006",      "0.038", "1.000", "+2532%", "✓ выр. Kcl",   "#C8E6C9"],
        ["REAL_texas_2021",       "1.000", "1.000", " 0.0%", "насыщение",     "#D9D9D9"],
        ["REAL_india_2012",       "0.142", "1.000", "+604%",  "✓ подтв.",      "#C8E6C9"],
        ["REAL_christchurch_2011","1.000", "1.000", " 0.0%", "насыщение",     "#D9D9D9"],
    ]
    col_labels = ["Сценарий", "$K_{cl}$", "$K_q$", "Δ%", "Статус H₁"]

    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.axis("off")
    ax.set_title("Рис. 7. Сводная таблица статусов H₁ (N=1000 MC, δ=0.10)", fontsize=11, pad=10)

    cell_text = [r[:-1] for r in rows]
    cell_colors = [[r[-1]] * 5 for r in rows]

    tbl = ax.table(
        cellText=cell_text,
        colLabels=col_labels,
        cellLoc="center",
        loc="center",
        cellColours=cell_colors,
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9.5)
    tbl.scale(1, 1.6)

    # Header styling
    for j in range(len(col_labels)):
        tbl[(0, j)].set_facecolor(NAVY)
        tbl[(0, j)].set_text_props(color="white", fontweight="bold")

    save(fig, "fig_07_summary_table.png")


# ══════════════════════════════════════════════════════════════════════════════
# VIZ 8 — Validation scatter (predicted vs real sector deltas)
# ══════════════════════════════════════════════════════════════════════════════
def viz_08_validation_scatter():
    events = VAL_DATA["events"]
    event_labels = {
        "baltimore_2024": "Baltimore '24",
        "texas_2021":     "Texas '21",
        "india_2012":     "India '12",
        "europe_2006":    "UCTE '06",
    }
    markers = {"energy": "o", "water": "s", "transport": "^"}
    sec_colors = {"energy": NAVY, "water": GREEN, "transport": ORANGE}

    predicted, real, correct, event_sec_labels = [], [], [], []
    for eid, ev in events.items():
        for sec in ["energy", "water", "transport"]:
            model_delta  = abs(ev["model"]["median_final_delta"][SECTORS_EN.index(sec)])
            real_delta   = ev["reality"][sec]["delta_approx"]
            match        = ev["comparison"]["sector_matches"][sec]
            predicted.append(model_delta)
            real.append(real_delta)
            correct.append(match)
            event_sec_labels.append(f"{event_labels[eid]}\n{sec}")

    fig, ax = plt.subplots(figsize=(6, 5.5))
    for i, (xr, yp, ok, lbl) in enumerate(zip(real, predicted, correct, event_sec_labels)):
        sec_idx = i % 3
        sec = ["energy", "water", "transport"][sec_idx]
        marker = markers[sec]
        col    = sec_colors[sec] if ok else RED
        ms     = 10 if ok else 9
        ax.scatter(xr, yp, marker=marker, color=col, s=ms**2, zorder=4,
                   edgecolors="white" if ok else RED, linewidths=0.5)

    # Identity line
    lim = 0.78
    ax.plot([0, lim], [0, lim], "k--", lw=1.2, alpha=0.5, label="Идеальное предсказание")
    ax.set_xlim(0, lim)
    ax.set_ylim(0, lim)
    ax.set_xlabel("Реальная амплитуда деградации Δ$x_{real}$")
    ax.set_ylabel("Предсказанная моделью Δ$x_{model}$")
    ax.set_title(f"Рис. 8. Точность предсказания деградации секторов\n"
                 f"MAE = 0.203; 11/12 совпадений (92%)")

    # Legend
    handles = [
        mpatches.Patch(color=NAVY,   label="Энергетика"),
        mpatches.Patch(color=GREEN,  label="Водоснабжение"),
        mpatches.Patch(color=ORANGE, label="Транспорт"),
        mpatches.Patch(color=RED,    label="✗ промах"),
        plt.Line2D([0],[0], ls="--", color="black", label="Идеальное совпадение"),
    ]
    ax.legend(handles=handles, fontsize=9, loc="upper left")
    ax.grid(alpha=0.3, zorder=0)

    save(fig, "fig_08_validation_scatter.png")


# ══════════════════════════════════════════════════════════════════════════════
# VIZ 9 — Spectral radius: Leontief vs Bayesian
# ══════════════════════════════════════════════════════════════════════════════
def viz_09_spectral_radius():
    A_bayes = np.array(BAYES_DATA["posterior"]["mu"])
    rho_l   = spectral_radius(A_LEONTIEF)
    rho_b   = spectral_radius(A_bayes)

    # ρ^k decay curves
    k_vals = np.arange(0, 12)
    decay_l = rho_l ** k_vals
    decay_b = rho_b ** k_vals

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    fig.suptitle("Рис. 9. Спектральный радиус ρ(A): Леонтьев vs Байес", fontsize=11)

    # Left: bar comparison
    ax = axes[0]
    bars = ax.bar(["$A_{Leontief}$\n(WIOD v3)", "$A_{Bayes}$\n(постериор)"],
                  [rho_l, rho_b], color=[NAVY, ORANGE], width=0.45, zorder=3)
    for bar, val in zip(bars, [rho_l, rho_b]):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.005,
                f"ρ = {val:.4f}", ha="center", va="bottom", fontsize=11, fontweight="bold")
    ax.axhline(1.0, color=RED, ls="--", lw=1.3, label="ρ=1 (граница устойчивости)")
    ax.set_ylim(0, 1.1)
    ax.set_ylabel("Спектральный радиус ρ(A)")
    ax.set_title("Значение спектрального радиуса")
    ax.legend(fontsize=9)
    ax.grid(axis="y", alpha=0.3, zorder=0)

    # Right: ρ^k decay
    ax = axes[1]
    ax.plot(k_vals, decay_l, "o-", color=NAVY,   lw=2, ms=5, label=f"Леонтьев ρ={rho_l:.4f}")
    ax.plot(k_vals, decay_b, "s-", color=ORANGE, lw=2, ms=5, label=f"Байес ρ={rho_b:.4f}")
    ax.axhline(0.01, color=GRAY, ls=":", lw=0.8, alpha=0.6, label="порог 0.01")
    ax.set_xlabel("Степень k")
    ax.set_ylabel("$\\rho^k$")
    ax.set_title("Убывание $\\rho^k$ (скорость затухания каскада)")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)

    save(fig, "fig_09_spectral_radius.png")


# ══════════════════════════════════════════════════════════════════════════════
# VIZ 10 — Bayesian posterior distributions (6 panels)
# ══════════════════════════════════════════════════════════════════════════════
def viz_10_bayesian_posteriors():
    prior_mu  = np.array(BAYES_DATA["prior"]["mu"])
    prior_sig = np.array(BAYES_DATA["prior"]["sigma"])
    post_mu   = np.array(BAYES_DATA["posterior"]["mu"])
    post_sig  = np.array(BAYES_DATA["posterior"]["sigma"])

    # nonzero off-diagonal elements: (i, j) where A[i,j] > 0 in at least one matrix
    nonzero = [(0,1),(0,2),(1,0),(2,0),(2,1),(1,2)]
    ijlabels = ["$A_{12}$: Вода→Энерг.",
                "$A_{13}$: Транспорт→Энерг.",
                "$A_{21}$: Энерг.→Вода",
                "$A_{31}$: Энерг.→Транспорт",
                "$A_{32}$: Вода→Транспорт",
                "$A_{23}$: Транспорт→Вода"]

    fig, axes = plt.subplots(2, 3, figsize=(13, 7))
    fig.suptitle("Рис. 10. Байесовское обновление параметров матрицы A\n"
                 "(приор: WIOD; данные: Texas 2021 + India 2012; σ_ε=1.2)",
                 fontsize=11)

    for ax, (i, j), lbl in zip(axes.flatten(), nonzero, ijlabels):
        mu_pr = prior_mu[i, j]
        sg_pr = prior_sig[i, j]
        mu_po = post_mu[i, j]
        sg_po = post_sig[i, j]

        xmin = max(0, min(mu_pr - 3.5*sg_pr, mu_po - 3.5*sg_po))
        xmax = max(mu_pr + 3.5*sg_pr, mu_po + 3.5*sg_po) + 0.02
        x = np.linspace(xmin, xmax, 300)

        ax.plot(x, norm.pdf(x, mu_pr, sg_pr), "--", color=GRAY,  lw=1.8, label=f"Приор μ={mu_pr:.3f}")
        ax.plot(x, norm.pdf(x, mu_po, sg_po), "-",  color=NAVY,  lw=2.2, label=f"Постериор μ={mu_po:.3f}")
        ax.fill_between(x, norm.pdf(x, mu_po, sg_po), alpha=0.15, color=NAVY)
        ax.axvline(mu_pr, color=GRAY, lw=0.9, ls="--", alpha=0.5)
        ax.axvline(mu_po, color=NAVY, lw=1.2, alpha=0.8)

        ax.set_title(lbl, fontsize=10)
        ax.set_xlabel("Значение коэффициента", fontsize=9)
        ax.legend(fontsize=8)
        ax.grid(alpha=0.25)
        ax.set_ylim(bottom=0)

    save(fig, "fig_10_bayesian_posteriors.png")


# ══════════════════════════════════════════════════════════════════════════════
# VIZ 11 — One-step SDE decomposition (S3 scenario)
# ══════════════════════════════════════════════════════════════════════════════
def viz_11_sde_decomposition():
    # S3: x0 before shock = [0.667, 0.4, 0.333], shock = [0, 0, +0.25]
    x0    = np.array([0.667, 0.4, 0.333])
    shock = np.array([0.0,   0.0, 0.25])
    x_s   = x0 + shock     # post-shock: [0.667, 0.4, 0.583]

    # Drift: A·x * dt  (row i = sum_j A[i,j]*x_s[j])
    drift  = A_LEONTIEF @ x_s * DT
    # Diffusion RMS: sigma * x * sqrt(dt)
    diffus = SIGMA * x_s * np.sqrt(DT)
    # Expected x1
    x1_exp = x_s + drift

    fig, ax = plt.subplots(figsize=(8, 5))
    x_idx = np.arange(3)
    w = 0.55

    # Stacked bar: x0 + shock + drift ± diffusion
    b_x0    = ax.bar(x_idx, x0,    w, color=NAVY,          label="$x_0$ (исходное состояние)")
    b_shock = ax.bar(x_idx, shock, w, bottom=x0,            color=RED,   alpha=0.7, label="Шок $u_j$")
    b_drift = ax.bar(x_idx, drift, w, bottom=x0 + shock,    color=GREEN, alpha=0.8, label=f"Дрейф $(A\\cdot x)\\Delta t$")

    # Error bar for diffusion
    ax.errorbar(x_idx, x1_exp, yerr=diffus, fmt="none",
                ecolor=ORANGE, elinewidth=2, capsize=8, capthick=2,
                label=f"Диффузия $\\sigma x\\sqrt{{\\Delta t}}$ (±1σ)")

    # C thresholds
    for j, cj in enumerate(C):
        ax.hlines(cj, j - w/2, j + w/2, colors=RED, lw=1.5, ls="--")

    ax.set_xticks(x_idx)
    ax.set_xticklabels(SECTORS)
    ax.set_ylabel("Уровень нагрузки $x_j$")
    ax.set_ylim(0, 1.05)
    ax.set_title("Рис. 11. Разложение одного шага СДУ (Эйлер–Маруяма)\n"
                 "Сценарий S3: транспортный шок +0.25, шаг t=0→1 (dt=0.1)")
    ax.legend(fontsize=9.5, loc="upper left")
    ax.grid(axis="y", alpha=0.3, zorder=0)

    # Annotations
    for j in range(3):
        ax.text(j, x0[j]/2,         f"{x0[j]:.3f}",  ha="center", va="center",
                fontsize=9, color="white", fontweight="bold")
        if drift[j] > 0.005:
            ax.text(j, x0[j] + shock[j] + drift[j]/2, f"+{drift[j]:.3f}",
                    ha="center", va="center", fontsize=8.5, color="white", fontweight="bold")

    save(fig, "fig_11_sde_decomposition.png")


# ══════════════════════════════════════════════════════════════════════════════
# VIZ 12 — Baltimore validation: model median vs real
# ══════════════════════════════════════════════════════════════════════════════
def viz_12_baltimore_validation():
    ev = VAL_DATA["events"]["baltimore_2024"]
    sectors_plot = ["energy", "transport"]   # water≈0, less interesting
    sec_labels   = ["Энергетика", "Транспорт"]

    model_med = [abs(ev["model"]["median_final_delta"][SECTORS_EN.index(s)]) for s in sectors_plot]
    model_p25 = [abs(ev["model"]["p25_final"][SECTORS_EN.index(s)])          for s in sectors_plot]
    model_p75 = [abs(ev["model"]["p75_final"][SECTORS_EN.index(s)])          for s in sectors_plot]
    real_vals  = [ev["reality"][s]["delta_approx"]                           for s in sectors_plot]

    x = np.arange(len(sectors_plot))
    w = 0.35

    fig, ax = plt.subplots(figsize=(6.5, 4.5))

    yerr_lo = [model_med[i] - model_p25[i] for i in range(len(sectors_plot))]
    yerr_hi = [model_p75[i] - model_med[i] for i in range(len(sectors_plot))]

    bars_m = ax.bar(x - w/2, model_med, w, color=NAVY,   label="Модель (медиана MC)")
    bars_r = ax.bar(x + w/2, real_vals, w, color=ORANGE, label="Реальные данные")
    ax.errorbar(x - w/2, model_med,
                yerr=[yerr_lo, yerr_hi],
                fmt="none", ecolor="black", elinewidth=1.5, capsize=5)

    ax.set_xticks(x)
    ax.set_xticklabels(sec_labels)
    ax.set_ylabel("Амплитуда деградации Δ$x$")
    ax.set_ylim(0, 0.85)
    ax.set_title("Рис. 12. Baltimore 2024: предсказание модели vs реальность\n"
                 "(шок транспорт +0.30; N=1000 MC; планки: Q25–Q75)")
    ax.legend(fontsize=10)
    ax.grid(axis="y", alpha=0.3, zorder=0)

    # Match annotations
    matches = ev["comparison"]["sector_matches"]
    for i, sec in enumerate(sectors_plot):
        mark = "✓" if matches[sec] else "✗"
        col  = GREEN if matches[sec] else RED
        ax.text(i, max(model_med[i], real_vals[i]) + 0.04, mark,
                ha="center", va="bottom", fontsize=14, color=col)

    save(fig, "fig_12_baltimore_validation.png")


# ══════════════════════════════════════════════════════════════════════════════
# VIZ 13 — Phase 1 vs Phase 2 comparison
# ══════════════════════════════════════════════════════════════════════════════
def viz_13_phase_comparison():
    # Phase 1: discrete operator, theta_node=0.75
    ph1 = {
        "S3": {"K_cl": 0.331, "K_q": 0.368},
        "S4": {"K_cl": 0.353, "K_q": 0.798},
    }
    # Phase 2: SDE Euler-Maruyama, T=7
    ph2 = {
        "S3": {"K_cl": 0.595, "K_q": 0.883},
        "S4": {"K_cl": 0.620, "K_q": 1.000},
    }

    scenarios  = ["S3\n(транспорт)", "S4\n(вода)"]
    x = np.arange(len(scenarios))
    w = 0.2

    fig, ax = plt.subplots(figsize=(8, 4.5))

    ax.bar(x - 1.5*w, [ph1["S3"]["K_cl"], ph1["S4"]["K_cl"]], w,
           color=NAVY,   alpha=0.55, label="Фаза 1: $K_{cl}$ (дискретный)")
    ax.bar(x - 0.5*w, [ph1["S3"]["K_q"],  ph1["S4"]["K_q"]],  w,
           color=ORANGE, alpha=0.55, label="Фаза 1: $K_q$ (дискретный)")
    ax.bar(x + 0.5*w, [ph2["S3"]["K_cl"], ph2["S4"]["K_cl"]], w,
           color=NAVY,   alpha=1.0,  label="Фаза 2: $K_{cl}$ (СДУ)")
    ax.bar(x + 1.5*w, [ph2["S3"]["K_q"],  ph2["S4"]["K_q"]],  w,
           color=ORANGE, alpha=1.0,  label="Фаза 2: $K_q$ (СДУ)")

    # Delta annotations
    for i, scen in enumerate(["S3", "S4"]):
        dp1 = (ph1[scen]["K_q"] - ph1[scen]["K_cl"]) / ph1[scen]["K_cl"] * 100
        dp2 = (ph2[scen]["K_q"] - ph2[scen]["K_cl"]) / ph2[scen]["K_cl"] * 100
        y1  = max(ph1[scen]["K_q"], ph1[scen]["K_cl"])
        y2  = max(ph2[scen]["K_q"], ph2[scen]["K_cl"])
        ax.text(x[i] - w, y1 + 0.025, f"Δ={dp1:.0f}%", ha="center", fontsize=8.5, color=GRAY)
        ax.text(x[i] + w, y2 + 0.025, f"Δ={dp2:.0f}%", ha="center", fontsize=8.5, color=GREEN,
                fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels(scenarios)
    ax.set_ylabel("Вероятность обнаружения K")
    ax.set_ylim(0, 1.15)
    ax.set_title("Рис. 13. Сравнение Фаза 1 (дискретный оператор) vs Фаза 2 (СДУ)\n"
                 "(θ=0.75, A_wiod_v3, N=1000 для обеих фаз)")
    ax.legend(fontsize=8.5, ncol=2)
    ax.grid(axis="y", alpha=0.3, zorder=0)

    save(fig, "fig_13_phase_comparison.png")


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("Generating presentation figures …")

    funcs = [
        (viz_01_barchart,              "VIZ 1  — Main barchart"),
        (viz_02_trajectories,          "VIZ 2  — Trajectory panels S3+S4"),
        (viz_03_heatmap,               "VIZ 3  — Heatmap A"),
        (viz_04_cascade_distribution,  "VIZ 4  — Cascade distribution"),
        (viz_05_alpha_sensitivity,     "VIZ 5  — Alpha sensitivity"),
        (viz_06_dependency_graph,      "VIZ 6  — Dependency graph"),
        (viz_07_summary_table,         "VIZ 7  — H1 summary table"),
        (viz_08_validation_scatter,    "VIZ 8  — Validation scatter"),
        (viz_09_spectral_radius,       "VIZ 9  — Spectral radius"),
        (viz_10_bayesian_posteriors,   "VIZ 10 — Bayesian posteriors"),
        (viz_11_sde_decomposition,     "VIZ 11 — SDE decomposition"),
        (viz_12_baltimore_validation,  "VIZ 12 — Baltimore validation"),
        (viz_13_phase_comparison,      "VIZ 13 — Phase comparison"),
    ]

    failed = []
    for fn, label in funcs:
        print(f"\n{label}")
        try:
            fn()
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback; traceback.print_exc()
            failed.append(label)

    print(f"\n{'='*55}")
    total = len(funcs)
    ok    = total - len(failed)
    print(f"Done: {ok}/{total} figures saved to results/figures/")
    if failed:
        print("FAILED:")
        for f in failed:
            print(f"  - {f}")
