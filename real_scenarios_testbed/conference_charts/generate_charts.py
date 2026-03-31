"""
Генерация 3 конференционных графиков.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.patheffects as pe
import numpy as np

OUT = Path(__file__).parent

STYLE = {
    "figure.facecolor":   "white",
    "axes.facecolor":     "white",
    "axes.spines.top":    False,
    "axes.spines.right":  False,
    "axes.grid":          True,
    "axes.grid.axis":     "y",
    "grid.color":         "#E0E0E0",
    "grid.linewidth":     0.7,
    "font.family":        ["DejaVu Sans", "sans-serif"],
    "font.size":          11,
}

CLR_CL  = "#E07A3A"   # оранжевый — классический
CLR_Q   = "#2E5B9A"   # синий — количественный
CLR_GAP = "#2D8B57"   # зелёный — разрыв


# ===========================================================================
# ГРАФИК 1
# ===========================================================================

def fig1_Kcl_vs_Kq():
    scenarios = [
        "S1: полный отказ\nэнергетики",
        "S3: нагрузка\nна транспорт",
        "S1b: частичная\nдеградация энерг.",
        "S4: частичная\nдеградация воды",
    ]
    K_cl = [1.000, 0.534, 0.423, 0.416]
    K_q  = [1.000, 0.956, 0.631, 0.876]

    gap_labels = [
        ("ΔK = 0\n(насыщение)", "#888888", False),
        ("ΔK = +0.422\n(Δ% = 79%)",  CLR_GAP, True),
        ("ΔK = +0.208\n(Δ% = 49%)",  CLR_GAP, True),
        ("ΔK = +0.460\n(Δ% = 111%)", CLR_GAP, True),
    ]

    x = np.arange(len(scenarios))
    w = 0.35

    with plt.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(10, 5.5))

        bars_cl = ax.bar(x - w / 2, K_cl, w, label="K_cl (классический)",
                         color=CLR_CL, alpha=0.90, zorder=3)
        bars_q  = ax.bar(x + w / 2, K_q,  w, label="K_q (количественный)",
                         color=CLR_Q,  alpha=0.90, zorder=3)

        # Значения на столбцах
        for bar in list(bars_cl) + list(bars_q):
            h = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2, h + 0.012,
                    f"{h:.3f}", ha="center", va="bottom", fontsize=10,
                    fontweight="bold")

        # Аннотации разрыва над парой
        for i, (lbl, color, bold) in enumerate(gap_labels):
            top = max(K_cl[i], K_q[i]) + 0.075
            ax.text(i, top, lbl, ha="center", va="bottom",
                    fontsize=9.5, color=color,
                    fontweight="bold" if bold else "normal")

        # Горизонтальная линия H₁
        ax.axhline(0.25, color="#AAAAAA", ls=":", lw=1.2, zorder=2)
        ax.text(3.45, 0.255, "порог H₁", va="bottom", ha="right",
                fontsize=8.5, color="#AAAAAA")

        ax.set_xticks(x)
        ax.set_xticklabels(scenarios, fontsize=10.5)
        ax.set_ylabel("Полнота выявления каскадов (K)", fontsize=12)
        ax.set_ylim(0, 1.15)
        ax.legend(loc="upper right", fontsize=10)

        ax.text(0.5, -0.14,
                "N = 1000 прогонов Монте-Карло,  θ = 0.70,  δ = 0.1",
                transform=ax.transAxes, ha="center", fontsize=9,
                color="#777777")

        plt.tight_layout()
        out = OUT / "fig1_Kcl_vs_Kq_scenarios.png"
        plt.savefig(out, dpi=300, bbox_inches="tight")
        plt.close()
        print(f"  Сохранён: {out}")


# ===========================================================================
# ГРАФИК 2
# ===========================================================================

def fig2_severity_sweep():
    severity = [0.10, 0.20, 0.25, 0.30, 0.40, 0.45, 0.50, 0.60, 0.70, 0.80]
    K_cl     = [0.024, 0.024, 0.024, 0.030, 0.072, 0.092, 0.150, 0.286, 0.426, 0.546]
    K_q      = [0.360, 0.380, 0.406, 0.436, 0.564, 0.642, 0.698, 0.796, 0.878, 0.900]

    with plt.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(10, 6))

        ax.plot(severity, K_cl, color=CLR_CL, marker="o", lw=2.5,
                label="K_cl (классический)", zorder=4)
        ax.plot(severity, K_q,  color=CLR_Q,  marker="s", lw=2.5,
                label="K_q (количественный)", zorder=4)

        # Заштрихованная область
        ax.fill_between(severity, K_cl, K_q,
                        color=CLR_Q, alpha=0.12, zorder=2)

        # Текст внутри области
        ax.text(0.35, 0.25, "Слепая зона\nбинарной модели",
                fontsize=12, color="#888888", style="italic",
                ha="center", va="center", zorder=5)

        # Вертикальные линии инцидентов
        incidents = [
            # (x,   color,     label_main,            label_sub,              y_ann,   ha)
            (0.25, "#4CAF50", "Мост Ки-Бридж\n2024", "$1.7B → $2.2B (+30%)", 0.95,  "left"),
            (0.48, "#C0392B", "Техас 2021",           "$80–195 млрд",          0.88,  "right"),
            (0.45, "#7B1FA2", "Крайстчерч\n2011",     "каскад ×1.7–2.3",       0.72,  "left"),
        ]
        for x_v, clr, lbl, sub, y_ann, ha in incidents:
            ax.axvline(x_v, color=clr, ls="--", lw=1.5, alpha=0.70, zorder=3)
            ax.text(x_v + (0.01 if ha == "left" else -0.01), y_ann,
                    lbl, fontsize=10, color=clr, ha=ha, va="top",
                    fontweight="bold", zorder=6)
            ax.text(x_v + (0.01 if ha == "left" else -0.01), y_ann - 0.10,
                    sub, fontsize=8, color="#888888", ha=ha, va="top", zorder=6)

        ax.set_xlabel("Тяжесть шока (severity)", fontsize=13)
        ax.set_ylabel("Полнота выявления каскадов (K)", fontsize=13)
        ax.set_ylim(0, 1.05)
        ax.set_xlim(0.05, 0.85)
        ax.legend(loc="upper left", fontsize=11)

        ax.text(0.5, -0.12,
                "S4_water_partial,  θ = 0.70,  N = 500 прогонов на точку",
                transform=ax.transAxes, ha="center", fontsize=9,
                color="#777777")

        plt.tight_layout()
        out = OUT / "fig2_severity_sweep.png"
        plt.savefig(out, dpi=300, bbox_inches="tight")
        plt.close()
        print(f"  Сохранён: {out}")


# ===========================================================================
# ГРАФИК 3
# ===========================================================================

def fig3_dependency_graph():
    try:
        import networkx as nx
    except ImportError:
        print("  networkx не установлен — пропуск fig3")
        return

    # Узлы и их координаты в пространстве [0,1]²
    labels    = ["Энергетика", "Водоснабжение", "Транспорт"]
    positions = {
        "Энергетика":    (0.50, 0.88),
        "Водоснабжение": (0.12, 0.12),
        "Транспорт":     (0.88, 0.12),
    }
    node_colors = {
        "Энергетика":    "#FFA726",
        "Водоснабжение": "#42A5F5",
        "Транспорт":     "#66BB6A",
    }

    # Рёбра: (source, dest, weight)
    edges = [
        ("Энергетика",    "Водоснабжение", 0.4),
        ("Энергетика",    "Транспорт",     0.5),  # самое сильное
        ("Водоснабжение", "Энергетика",    0.2),
        ("Водоснабжение", "Транспорт",     0.3),
        ("Транспорт",     "Энергетика",    0.3),
        ("Транспорт",     "Водоснабжение", 0.2),
    ]

    G = nx.DiGraph()
    for lbl in labels:
        G.add_node(lbl)
    for src, dst, w in edges:
        G.add_edge(src, dst, weight=w)

    with plt.rc_context({**STYLE, "axes.grid": False}):
        fig, ax = plt.subplots(figsize=(7, 6))
        ax.set_xlim(-0.05, 1.05)
        ax.set_ylim(-0.05, 1.05)
        ax.axis("off")

        # Узлы
        for lbl, (x, y) in positions.items():
            circle = plt.Circle((x, y), 0.115, color=node_colors[lbl],
                                 ec="#333333", lw=2, zorder=4)
            ax.add_patch(circle)
            ax.text(x, y, lbl, ha="center", va="center",
                    fontsize=10.5, fontweight="bold", color="white",
                    zorder=5, wrap=True)

        # Рёбра — FancyArrowPatch
        rad_map = {
            ("Энергетика",    "Водоснабжение"): 0.15,
            ("Водоснабжение", "Энергетика"):    0.15,
            ("Энергетика",    "Транспорт"):     -0.15,
            ("Транспорт",     "Энергетика"):    -0.15,
            ("Водоснабжение", "Транспорт"):     0.15,
            ("Транспорт",     "Водоснабжение"): 0.15,
        }

        # Явные позиции меток весов (в координатах осей 0..1)
        # Разнесены вручную чтобы встречные рёбра не перекрывались
        label_pos = {
            ("Энергетика",    "Водоснабжение"): (0.18, 0.58),  # левее дуги E→W
            ("Водоснабжение", "Энергетика"):    (0.41, 0.38),  # правее дуги W→E
            ("Энергетика",    "Транспорт"):     (0.82, 0.58),  # правее дуги E→T
            ("Транспорт",     "Энергетика"):    (0.59, 0.38),  # левее дуги T→E
            ("Водоснабжение", "Транспорт"):     (0.50, 0.24),  # над дугой W→T
            ("Транспорт",     "Водоснабжение"): (0.50, 0.05),  # под дугой T→W
        }

        NODE_R = 0.115

        for src, dst, w in edges:
            xs, ys = positions[src]
            xd, yd = positions[dst]
            rad = rad_map.get((src, dst), 0.15)
            lw  = w * 8

            # Точки на поверхности окружностей
            angle = np.arctan2(yd - ys, xd - xs)
            xs2 = xs + NODE_R * np.cos(angle)
            ys2 = ys + NODE_R * np.sin(angle)
            xd2 = xd - NODE_R * np.cos(angle)
            yd2 = yd - NODE_R * np.sin(angle)

            arrow = mpatches.FancyArrowPatch(
                (xs2, ys2), (xd2, yd2),
                connectionstyle=f"arc3,rad={rad}",
                arrowstyle=mpatches.ArrowStyle(
                    "Simple",
                    head_width=max(6, lw * 2),
                    head_length=max(8, lw * 2.5),
                    tail_width=lw,
                ),
                color="#555555",
                zorder=3,
                alpha=0.85,
            )
            ax.add_patch(arrow)

            lx, ly = label_pos[(src, dst)]

            is_strongest = (src == "Энергетика" and dst == "Транспорт")
            fc = "#C0392B" if is_strongest else "#1A2744"
            txt = ax.text(lx, ly, str(w), ha="center", va="center",
                          fontsize=14, fontweight="bold", color=fc, zorder=6)
            if is_strongest:
                txt.set_path_effects([
                    pe.withStroke(linewidth=3, foreground="white"),
                ])

        ax.text(0.5, -0.03,
                "Матрица межотраслевых зависимостей A (v1.0)",
                transform=ax.transAxes, ha="center",
                fontsize=10, color="#777777")

        fig.patch.set_alpha(1.0)   # белый фон
        plt.tight_layout()
        out = OUT / "fig3_dependency_graph.png"
        plt.savefig(out, dpi=300, bbox_inches="tight")
        plt.close()
        print(f"  Сохранён: {out}")


# ===========================================================================

def main():
    print("=" * 50)
    print("  Генерация конференционных графиков")
    print("=" * 50)
    print("\n  Рис. 1: K_cl vs K_q по сценариям...")
    fig1_Kcl_vs_Kq()
    print("  Рис. 2: severity sweep...")
    fig2_severity_sweep()
    print("  Рис. 3: граф зависимостей...")
    fig3_dependency_graph()
    print("\n  Готово.")


if __name__ == "__main__":
    main()
