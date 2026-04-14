"""
generate_plots.py
=================
Generates all thesis figures from experiment results.
All labels, titles, and annotations are in Russian (ВКР МФТИ requirement).

Figures produced
----------------
  fig_01_barchart.png          — K_cl vs K_q по сценариям
  fig_02_trajectories.png      — Динамика секторов (S3, S4)
  fig_03_heatmap_A.png         — Тепловая карта матрицы A
  fig_04_cascade_dist.png      — Распределение max Δx
  fig_05_alpha_sensitivity.png — Влияние параметра α
  fig_06_dependency_graph.png  — Граф зависимостей
  fig_07_summary_table.png     — Сводная таблица H₁
  fig_08_sigma_sensitivity.png — Чувствительность к σ

Usage
-----
  python scripts/generate_plots.py
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
    import matplotlib.patches as mpatches
    import matplotlib.gridspec as gridspec
    from matplotlib.colors import LinearSegmentedColormap
except ImportError:
    print("[error] matplotlib not installed.")
    sys.exit(1)

# ── Font / style ──────────────────────────────────────────────────────────
plt.rcParams.update({
    "font.family":       "sans-serif",
    "font.sans-serif":   ["DejaVu Sans", "Arial", "Liberation Sans"],
    "font.size":         11,
    "axes.unicode_minus": False,
    "axes.spines.top":   False,
    "axes.spines.right": False,
    "figure.dpi":        200,
})

# ── Colour palette ────────────────────────────────────────────────────────
C_Q   = "#2196F3"   # синий  — количественный
C_CL  = "#FF9800"   # оранжевый — классический
C_ENE = "#E53935"   # красный — энергетика
C_WAT = "#1E88E5"   # синий  — водоснабжение
C_TRA = "#43A047"   # зелёный — транспорт

SECT_COLORS = [C_ENE, C_WAT, C_TRA]
SECT_LABELS = ["Энергетика", "Водоснабжение", "Транспорт"]

OUT_DIR = REPO_ROOT / "results" / "figures"
OUT_DIR.mkdir(parents=True, exist_ok=True)

A_WIOD_V3 = np.array([
    [0.000, 0.350, 0.304],
    [0.006, 0.000, 0.001],
    [0.500, 0.332, 0.000],
])
C_CAP = np.array([0.8832, 0.6463, 0.9280])
SIGMA = np.array([0.259, 0.232, 0.259])
RHO   = np.zeros(3)

# ─────────────────────────────────────────────────────────────────────────
# Load experiment data
# ─────────────────────────────────────────────────────────────────────────

def load_summary() -> list[dict]:
    p = REPO_ROOT / "results" / "experiment_summary.json"
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def load_traj(scenario_id: str) -> list[np.ndarray]:
    """Return list of (T+1, 3) arrays from saved trajectories."""
    p = REPO_ROOT / "results" / "mc_runs" / f"{scenario_id}.json"
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    return [np.array(t) for t in d["trajectories_sample"]]


def load_alpha() -> dict:
    p = REPO_ROOT / "results" / "alpha_sweep.json"
    with open(p, encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────────────────────
# Fig 01 — Барплот K_cl vs K_q
# ─────────────────────────────────────────────────────────────────────────

def fig_01_barchart(summary: list[dict]) -> None:
    # Define display order and Russian labels
    DISPLAY = [
        ("S1_energy_outage",       "S1: полный\nотказ энерг."),
        ("S3_transport_marginal",  "S3: нагрузка\nна транспорт"),
        ("S4_water_marginal",      "S4: деградация\nводоснабж."),
        ("S5_combined",            "S5: комбин.\nшок"),
        ("REAL_baltimore_2024",    "Baltimore\n2024"),
        ("REAL_europe_2006",       "UCTE\n2006"),
        ("REAL_texas_2021",        "Texas\n2021"),
        ("REAL_india_2012",        "India\n2012"),
        ("REAL_christchurch_2011", "Christchurch\n2011"),
    ]
    sc_map = {r["scenario_id"]: r for r in summary}

    labels = []
    kcl_vals, kq_vals = [], []
    dk_labels = []
    for sc_id, label in DISPLAY:
        if sc_id not in sc_map:
            continue
        r = sc_map[sc_id]
        labels.append(label)
        kcl_vals.append(r["K_cl"])
        kq_vals.append(r["K_q"])
        dp = r["delta_pct"]
        if dp == "inf":
            dk_labels.append("∞")
        else:
            dk_labels.append(f"+{dp:.0f}%")

    n = len(labels)
    x = np.arange(n)
    w = 0.35

    fig, ax = plt.subplots(figsize=(13, 5.5))

    bars_cl = ax.bar(x - w/2, kcl_vals, width=w, color=C_CL,
                     label="$K_{cl}$ (классический)", zorder=3)
    bars_q  = ax.bar(x + w/2, kq_vals,  width=w, color=C_Q,
                     label="$K_q$ (количественный)",  zorder=3)

    # ΔK annotations
    for i, (kcl, kq, dk) in enumerate(zip(kcl_vals, kq_vals, dk_labels)):
        top = max(kcl, kq) + 0.02
        ax.text(i, min(top + 0.04, 1.08), f"$\\Delta$%={dk}",
                ha="center", va="bottom", fontsize=7.5, color="#555")

    # Vertical separator: synthetic | real
    n_synth = sum(1 for s, _ in DISPLAY if s.startswith("S"))
    sep_x = n_synth - 0.5
    ax.axvline(sep_x, color="gray", lw=1.2, ls="--", alpha=0.6)
    ax.text(n_synth / 2 - 0.5, 1.12, "Синтетические сценарии",
            ha="center", va="center", fontsize=9.5,
            color="gray", fontstyle="italic")
    real_center = (n_synth + n - 1) / 2
    ax.text(real_center, 1.12, "Реальные кейсы",
            ha="center", va="center", fontsize=9.5,
            color="gray", fontstyle="italic")

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylim(0, 1.18)
    ax.set_ylabel("Полнота выявления каскадов ($K$)", fontsize=11)
    ax.set_title("Полнота выявления каскадных эффектов по сценариям",
                 fontsize=12, pad=12)
    ax.legend(fontsize=10, loc="upper left")
    ax.grid(axis="y", alpha=0.3, zorder=0)
    ax.set_axisbelow(True)

    fig.tight_layout()
    p = OUT_DIR / "fig_01_barchart.png"
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    print(f"[save] {p}")


# ─────────────────────────────────────────────────────────────────────────
# Fig 02 — Динамика секторов (траектории)
# ─────────────────────────────────────────────────────────────────────────

def fig_02_trajectories() -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharey=False)

    pairs = [
        ("S3_transport_marginal", "S3: нагрузка на транспорт (+0.25)", axes[0]),
        ("S4_water_marginal",     "S4: деградация водоснабжения (+0.20)",  axes[1]),
    ]

    for sc_id, title, ax in pairs:
        trajs = load_traj(sc_id)
        if not trajs:
            continue
        stack = np.stack(trajs, axis=0)   # (n_traj, T+1, 3)
        T1 = stack.shape[1]
        t  = np.arange(T1)

        for j, (col, lab) in enumerate(zip(SECT_COLORS, SECT_LABELS)):
            med = np.median(stack[:, :, j], axis=0)
            p5  = np.percentile(stack[:, :, j], 5,  axis=0)
            p95 = np.percentile(stack[:, :, j], 95, axis=0)
            ax.plot(t, med, color=col, lw=2, label=lab)
            ax.fill_between(t, p5, p95, color=col, alpha=0.12)

        # Capacity thresholds
        for j, (col, lab) in enumerate(zip(SECT_COLORS, SECT_LABELS)):
            c_label = f"$C_{{{lab[0]}}}$={C_CAP[j]:.3f}"
            ax.axhline(C_CAP[j], color=col, ls=":", lw=1.0, alpha=0.7)

        # Shock moment
        ax.axvline(1, color="black", ls="--", lw=1.2, alpha=0.6,
                   label="Момент шока")

        ax.set_xlabel("Шаг интегрирования $t$", fontsize=10)
        ax.set_ylabel("Уровень риска $x_j$", fontsize=10)
        ax.set_title(title, fontsize=10)
        ax.set_ylim(-0.02, 1.05)
        ax.legend(fontsize=8.5, loc="upper left")
        ax.grid(alpha=0.25)

    fig.suptitle("Динамика уровня риска $x_j(t)$ по секторам\n"
                 "(медиана ± 90% ДИ, N=20 траекторий)", fontsize=11)
    fig.tight_layout()
    p = OUT_DIR / "fig_02_trajectories.png"
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    print(f"[save] {p}")


# ─────────────────────────────────────────────────────────────────────────
# Fig 03 — Тепловая карта матрицы A
# ─────────────────────────────────────────────────────────────────────────

def fig_03_heatmap_A() -> None:
    A = A_WIOD_V3
    fig, ax = plt.subplots(figsize=(6, 5))

    cmap = LinearSegmentedColormap.from_list("blue_white",
           ["#ffffff", "#1565C0"], N=256)
    im = ax.imshow(A, cmap=cmap, vmin=0, vmax=0.5, aspect="auto")

    tick_labels = ["Энергетика", "Водоснабжение", "Транспорт"]
    ax.set_xticks(range(3))
    ax.set_yticks(range(3))
    ax.set_xticklabels(tick_labels, fontsize=10)
    ax.set_yticklabels(tick_labels, fontsize=10)
    ax.set_xlabel("Источник влияния ($j$)", fontsize=11)
    ax.set_ylabel("Получатель влияния ($i$)", fontsize=11)

    # Cell values
    for i in range(3):
        for j in range(3):
            v = A[i, j]
            color = "white" if v > 0.25 else "black"
            ax.text(j, i, f"{v:.3f}", ha="center", va="center",
                    fontsize=13, fontweight="bold", color=color)

    cbar = plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("Интенсивность зависимости $a_{ij}$", fontsize=10)

    ax.set_title("Калиброванная матрица зависимостей $A$\n"
                 "(WIOD 2016 NIOT, метод Леонтьева, RUS+DEU+USA, 2014)",
                 fontsize=11)
    fig.tight_layout()
    p = OUT_DIR / "fig_03_heatmap_A.png"
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    print(f"[save] {p}")


# ─────────────────────────────────────────────────────────────────────────
# Fig 04 — Распределение max Δx
# ─────────────────────────────────────────────────────────────────────────

def fig_04_cascade_dist() -> None:
    """Distribution of max Δx across all MC runs for S3 and S4."""
    from services.risk_engine.sde_integrator import SDEConfig, SDEIntegrator

    scenarios = {
        "S3_transport_marginal": {
            "x0": np.array([0.667, 0.400, 0.333]),
            "shock": np.array([0.0, 0.0, 0.25]),
            "initiator": 2, "T": 7,
            "label": "S3: нагрузка на транспорт",
            "color": C_TRA,
        },
        "S4_water_marginal": {
            "x0": np.array([0.667, 0.400, 0.333]),
            "shock": np.array([0.0, 0.20, 0.0]),
            "initiator": 1, "T": 7,
            "label": "S4: деградация водоснабжения",
            "color": C_WAT,
        },
    }

    N_RUNS = 1000
    fig, ax = plt.subplots(figsize=(8, 4.5))

    for sc_id, sc in scenarios.items():
        cfg = SDEConfig(A=A_WIOD_V3, sigma=SIGMA, rho=RHO, C=C_CAP,
                        dt=0.1, T_steps=sc["T"], delta=0.10, alpha=0.0)
        ig = SDEIntegrator(cfg)
        deltas = []
        for r in range(N_RUNS):
            seed = SDEIntegrator.make_seed(sc_id + "_fig04", r)
            traj = ig.run(x0=sc["x0"], shock=sc["shock"], seed=seed)
            res  = ig.detect_cascade(traj, initiator=sc["initiator"])
            deltas.append(res.max_delta)

        deltas = np.array(deltas)
        ax.hist(deltas, bins=40, density=True, alpha=0.55,
                color=sc["color"], label=sc["label"])
        mu = float(np.mean(deltas))
        p95_val = float(np.percentile(deltas, 95))
        ax.axvline(mu,    color=sc["color"], lw=1.8, ls="-",  alpha=0.9,
                   label=f"Среднее ({sc['label'][:2]}): {mu:.3f}")
        ax.axvline(p95_val, color=sc["color"], lw=1.8, ls="--", alpha=0.9,
                   label=f"$p_{{95}}$ ({sc['label'][:2]}): {p95_val:.3f}")

    ax.axvline(0.10, color="black", lw=1.2, ls=":", alpha=0.7,
               label="Порог $\\delta$=0.10")
    ax.set_xlabel("Максимальный прирост риска $\\max_t(x_j(t)-x_j(0))$", fontsize=11)
    ax.set_ylabel("Плотность", fontsize=11)
    ax.set_title("Распределение прироста интегрального риска\n"
                 "по несекторам-инициаторам (N=1000, T=7 шагов)", fontsize=11)
    ax.legend(fontsize=8.5)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    p = OUT_DIR / "fig_04_cascade_dist.png"
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    print(f"[save] {p}")


# ─────────────────────────────────────────────────────────────────────────
# Fig 05 — Чувствительность к α (из alpha_sweep.json)
# ─────────────────────────────────────────────────────────────────────────

def fig_05_alpha_sensitivity() -> None:
    alpha_data = load_alpha()
    alpha_vals = np.array(alpha_data["alpha_values"])
    scenarios  = alpha_data["scenarios"]

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharey=False)

    pairs = [
        ("S4_water",    "S4: деградация водоснабжения",   axes[0]),
        ("S3_transport","S3: нагрузка на транспорт",      axes[1]),
    ]

    for sc_name, title, ax in pairs:
        rows = scenarios[sc_name]
        kcl  = np.array([r["K_cl"]  for r in rows])
        kq   = np.array([r["K_q"]   for r in rows])
        se   = np.array([r["se_cl"] for r in rows])
        md   = np.array([r["mean_delta"] for r in rows])

        ax.errorbar(alpha_vals, kcl, yerr=1.96*se, fmt="o-",
                    color=C_CL, capsize=4, lw=1.8, label="$K_{cl}$ ± 95% ДИ")
        ax.plot(alpha_vals, kq, "s--", color=C_Q, lw=1.8,
                label="$K_q$")

        ax2 = ax.twinx()
        ax2.plot(alpha_vals, md, "^:", color="#9C27B0", lw=1.4, alpha=0.8,
                 label="mean $\\Delta x$")
        ax2.set_ylabel("Среднее max $\\Delta x$", fontsize=9, color="#9C27B0")
        ax2.tick_params(labelcolor="#9C27B0")
        ax2.set_ylim(0, 0.6)

        ax.set_xlabel("Параметр затухания $\\alpha$", fontsize=10)
        ax.set_ylabel("Полнота выявления каскадов ($K$)", fontsize=10)
        ax.set_title(title, fontsize=10)
        ax.set_xticks(alpha_vals)
        ax.legend(fontsize=9, loc="upper right")
        ax.grid(alpha=0.25)

    fig.suptitle("Влияние динамической матрицы $A(t)$ на полноту выявления каскадов\n"
                 "(N=1000 MC, T=7 шагов, маргинальный режим)", fontsize=11)
    fig.tight_layout()
    p = OUT_DIR / "fig_05_alpha_sensitivity.png"
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    print(f"[save] {p}")


# ─────────────────────────────────────────────────────────────────────────
# Fig 06 — Граф зависимостей
# ─────────────────────────────────────────────────────────────────────────

def fig_06_dependency_graph() -> None:
    fig, ax = plt.subplots(figsize=(7, 6))
    ax.set_xlim(-0.1, 1.1)
    ax.set_ylim(-0.05, 1.05)
    ax.axis("off")

    # Node positions (equilateral triangle)
    nodes = {
        0: (0.5, 0.88, "Энергетика",    C_ENE),
        1: (0.12, 0.15, "Водоснабжение", C_WAT),
        2: (0.88, 0.15, "Транспорт",     C_TRA),
    }
    r_node = 0.11

    # Draw edges first
    A = A_WIOD_V3
    for j in range(3):
        for i in range(3):
            if i == j or A[i, j] < 1e-6:
                continue
            xj, yj = nodes[j][:2]
            xi, yi = nodes[i][:2]

            # Direction unit vector
            dx, dy = xi - xj, yi - yj
            dist = np.hypot(dx, dy)
            ux, uy = dx/dist, dy/dist

            # Start/end points (at node boundary)
            sx, sy = xj + ux * r_node, yj + uy * r_node
            ex, ey = xi - ux * r_node, yi - uy * r_node

            lw = 1.5 + A[i, j] * 8
            ax.annotate("", xy=(ex, ey), xytext=(sx, sy),
                         arrowprops=dict(
                             arrowstyle=f"->,head_width=0.015,head_length=0.02",
                             color="gray", lw=lw,
                             connectionstyle="arc3,rad=0.12",
                         ))

            # Edge label
            mx = (sx + ex) / 2 + uy * 0.05
            my = (sy + ey) / 2 - ux * 0.05
            ax.text(mx, my, f"{A[i,j]:.3f}", fontsize=8.5,
                    ha="center", va="center", color="#333",
                    bbox=dict(boxstyle="round,pad=0.1", fc="white",
                              ec="none", alpha=0.8))

    # Draw nodes
    for idx, (xn, yn, label, col) in nodes.items():
        circle = plt.Circle((xn, yn), r_node, color=col, alpha=0.85,
                             zorder=5)
        ax.add_patch(circle)
        ax.text(xn, yn, label, ha="center", va="center",
                fontsize=10, fontweight="bold", color="white", zorder=6)

    ax.set_title("Граф межотраслевых зависимостей\n"
                 "(матрица $A$, метод Леонтьева, WIOD 2016)", fontsize=11)
    fig.tight_layout()
    p = OUT_DIR / "fig_06_dependency_graph.png"
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    print(f"[save] {p}")


# ─────────────────────────────────────────────────────────────────────────
# Fig 07 — Сводная таблица результатов
# ─────────────────────────────────────────────────────────────────────────

def fig_07_summary_table(summary: list[dict]) -> None:
    DISPLAY = [
        ("S1_energy_outage",       "S1: полный отказ энергетики"),
        ("S3_transport_marginal",  "S3: нагрузка на транспорт"),
        ("S4_water_marginal",      "S4: деградация водоснабжения"),
        ("S5_combined",            "S5: комбинированный шок"),
        ("REAL_baltimore_2024",    "Baltimore 2024 (мост FSK)"),
        ("REAL_europe_2006",       "UCTE 2006 (Европа)"),
        ("REAL_texas_2021",        "Texas 2021 (Storm Uri)"),
        ("REAL_india_2012",        "India 2012 (Северная сеть)"),
        ("REAL_christchurch_2011", "Christchurch 2011 (M6.3)"),
    ]
    sc_map = {r["scenario_id"]: r for r in summary}

    STATUS_RU = {
        "confirmed":       "Подтверждена ✓",
        "saturated":       "Насыщение",
        "degenerate_cl":   "К_cl≈0 (деград.)",
        "below_threshold": "Ниже порога",
        "reverse":         "Обратный разрыв",
    }
    STATUS_COLOR = {
        "confirmed":       "#C8E6C9",   # green
        "saturated":       "#E0E0E0",   # grey
        "degenerate_cl":   "#E3F2FD",   # light blue
        "below_threshold": "#FFF9C4",   # yellow
        "reverse":         "#FFCDD2",   # red
    }

    col_labels = ["Сценарий", "$K_{cl}$", "$K_q$", "$\\Delta K$", "$\\Delta$%", "Статус $H_1$"]
    rows = []
    colors = []
    for sc_id, label in DISPLAY:
        if sc_id not in sc_map:
            continue
        r = sc_map[sc_id]
        dp = r["delta_pct"]
        dp_str = f"+{dp:.0f}%" if isinstance(dp, (int, float)) else "∞"
        status = r["H1_actual"]
        rows.append([label,
                     f"{r['K_cl']:.3f}",
                     f"{r['K_q']:.3f}",
                     f"{r['delta_K']:+.3f}",
                     dp_str,
                     STATUS_RU.get(status, status)])
        colors.append(STATUS_COLOR.get(status, "#FFFFFF"))

    fig, ax = plt.subplots(figsize=(13, 4.8))
    ax.axis("off")

    tbl = ax.table(
        cellText=rows,
        colLabels=col_labels,
        loc="center",
        cellLoc="center",
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9.5)
    tbl.scale(1, 1.55)

    # Header styling
    for j in range(len(col_labels)):
        cell = tbl[0, j]
        cell.set_facecolor("#1565C0")
        cell.set_text_props(color="white", fontweight="bold")

    # Row colours
    for i, col in enumerate(colors):
        for j in range(len(col_labels)):
            tbl[i + 1, j].set_facecolor(col)

    # Wide first column
    tbl.auto_set_column_width([0])
    for i in range(len(rows) + 1):
        tbl[i, 0].set_width(0.38)

    ax.set_title("Сводные результаты проверки гипотезы $H_1$\n"
                 "($H_1$: $\\Delta\\% \\geq 25\\%$ на маргинальных сценариях)",
                 fontsize=12, pad=18)

    # Legend
    legend_items = [
        mpatches.Patch(facecolor=c, label=l, edgecolor="#999")
        for l, c in [
            ("Подтверждена", "#C8E6C9"),
            ("Насыщение / обе → 1", "#E0E0E0"),
            ("$K_{cl}$≈0 (деградация классического)", "#E3F2FD"),
            ("Ниже порога 25%", "#FFF9C4"),
        ]
    ]
    ax.legend(handles=legend_items, loc="lower center",
              bbox_to_anchor=(0.5, -0.06), ncol=4, fontsize=8.5,
              frameon=True)

    fig.tight_layout()
    p = OUT_DIR / "fig_07_summary_table.png"
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    print(f"[save] {p}")


# ─────────────────────────────────────────────────────────────────────────
# Fig 08 — Чувствительность к σ
# ─────────────────────────────────────────────────────────────────────────

def fig_08_sigma_sensitivity() -> None:
    from services.risk_engine.sde_integrator import SDEConfig, SDEIntegrator

    sigma_multipliers = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0]
    N_RUNS = 500

    # S4 (water marginal): x0, shock, initiator, T
    sc = {
        "x0":      np.array([0.667, 0.400, 0.333]),
        "shock":   np.array([0.0, 0.20, 0.0]),
        "init":    1,
        "T":       7,
    }

    kcl_vals, kq_vals = [], []
    for mult in sigma_multipliers:
        sig = SIGMA * mult
        cfg = SDEConfig(A=A_WIOD_V3, sigma=sig, rho=RHO, C=C_CAP,
                        dt=0.1, T_steps=sc["T"], delta=0.10, alpha=0.0)
        ig  = SDEIntegrator(cfg)
        I_cl = I_q = 0
        for r in range(N_RUNS):
            seed = SDEIntegrator.make_seed(f"sigma_sweep_{mult:.2f}", r)
            traj = ig.run(x0=sc["x0"], shock=sc["shock"], seed=seed)
            res  = ig.detect_cascade(traj, initiator=sc["init"])
            I_cl += res.I_cl
            I_q  += res.I_q
        kcl_vals.append(I_cl / N_RUNS)
        kq_vals.append(I_q  / N_RUNS)

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(sigma_multipliers, kcl_vals, "o-", color=C_CL, lw=2, markersize=7,
            label="$K_{cl}$ (классический)")
    ax.plot(sigma_multipliers, kq_vals,  "s-", color=C_Q,  lw=2, markersize=7,
            label="$K_q$ (количественный)")
    ax.axvline(1.0, color="gray", ls="--", lw=1.2,
               label="Калиброванная $\\sigma$")
    ax.set_xlabel("Множитель волатильности (относительно калиброванной σ)",
                  fontsize=11)
    ax.set_ylabel("Полнота выявления каскадов (K)", fontsize=11)
    ax.set_title("Чувствительность к волатильности σ\n"
                 "(сценарий S4: деградация водоснабжения, N=500, T=7)", fontsize=11)
    ax.legend(fontsize=10)
    ax.grid(alpha=0.3)
    ax.set_ylim(-0.02, 1.05)

    fig.tight_layout()
    p = OUT_DIR / "fig_08_sigma_sensitivity.png"
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    print(f"[save] {p}")


# ─────────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────────

def main() -> None:
    print("Loading experiment data …")
    summary = load_summary()
    print(f"  {len(summary)} scenarios loaded.\n")

    print("Fig 01: барплот K_cl vs K_q …")
    fig_01_barchart(summary)

    print("Fig 02: динамика траекторий …")
    fig_02_trajectories()

    print("Fig 03: тепловая карта A …")
    fig_03_heatmap_A()

    print("Fig 04: распределение max Δx …")
    fig_04_cascade_dist()

    print("Fig 05: чувствительность к α …")
    fig_05_alpha_sensitivity()

    print("Fig 06: граф зависимостей …")
    fig_06_dependency_graph()

    print("Fig 07: сводная таблица H₁ …")
    fig_07_summary_table(summary)

    print("Fig 08: чувствительность к σ …")
    fig_08_sigma_sensitivity()

    print("\n✓ Все рисунки сохранены в", OUT_DIR)


if __name__ == "__main__":
    main()
