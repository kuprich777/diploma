"""
Генерация 5 графиков по результатам эксперимента.

Считывает:
  results/experiment_results.json

Генерирует:
  results/figures/fig1_model_vs_reality.png
  results/figures/fig2_cascade_multipliers.png
  results/figures/fig3_Kcl_vs_Kq_real.png
  results/figures/fig4_risk_distribution.png
  results/figures/fig5_delta_sensitivity.png
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

ROOT = Path(__file__).parent
RESULTS_DIR = ROOT / "results"
FIGURES_DIR = RESULTS_DIR / "figures"

SECTORS = ["energy", "water", "transport"]
SECTOR_LABELS = ["Энергетика", "Водоснабжение", "Транспорт"]
SECTOR_COLORS = ["#e05c2f", "#2f7be0", "#2fa832"]

STYLE = {
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "font.family": "DejaVu Sans",
    "font.size": 10,
}


def load_results() -> dict:
    with open(RESULTS_DIR / "experiment_results.json", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Рисунок 1: grouped bar — модель vs реальность по секторам
# ---------------------------------------------------------------------------

def fig1_model_vs_reality(scenarios: list[dict]) -> None:
    """
    Для каждого сценария × сектора: x_model (синий) vs severity_real (оранжевый).
    """
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    with plt.rc_context(STYLE):
        n_scenarios = len(scenarios)
        n_sectors = 3
        group_width = 0.7
        bar_w = group_width / (2 * n_sectors)

        fig, ax = plt.subplots(figsize=(14, 6))

        x_base = np.arange(n_scenarios)

        for s_idx, sector in enumerate(SECTORS):
            offsets = np.linspace(
                -group_width / 2 + bar_w / 2 + s_idx * 2 * bar_w,
                -group_width / 2 + bar_w / 2 + s_idx * 2 * bar_w,
                1,
            )[0]

            model_vals = [sc["comparison"][s_idx]["x_model"] for sc in scenarios]
            real_vals = [sc["comparison"][s_idx]["severity_real"] for sc in scenarios]

            pos_model = x_base + offsets
            pos_real = x_base + offsets + bar_w

            color = SECTOR_COLORS[s_idx]
            ax.bar(pos_model, model_vals, width=bar_w * 0.9,
                   color=color, alpha=0.9, label=f"{SECTOR_LABELS[s_idx]} (модель)" if s_idx == 0 else "_")
            ax.bar(pos_real, real_vals, width=bar_w * 0.9,
                   color=color, alpha=0.45, hatch="///",
                   label=f"{SECTOR_LABELS[s_idx]} (реальность)" if s_idx == 0 else "_")

        # Легенда секторов
        sector_patches = [
            mpatches.Patch(color=SECTOR_COLORS[i], label=SECTOR_LABELS[i])
            for i in range(3)
        ]
        model_patch = mpatches.Patch(color="gray", alpha=0.9, label="Модель (сплошной)")
        real_patch = mpatches.Patch(color="gray", alpha=0.45, hatch="///", label="Реальность (штриховка)")
        ax.legend(handles=sector_patches + [model_patch, real_patch],
                  fontsize=8, loc="upper right", ncol=2)

        ax.set_xticks(x_base)
        ax.set_xticklabels([sc["name"] for sc in scenarios], fontsize=9, rotation=10)
        ax.set_ylabel("Деградация [0, 1]")
        ax.set_ylim(0, 1.15)
        ax.axhline(1.0, color="k", ls=":", lw=0.7, alpha=0.3)
        ax.set_title(
            "Рис. 1. Модельный выход vs реальный исход: все сценарии и секторы\n"
            "(сплошной = модель, штриховка = реальность; цвет = сектор)",
            fontsize=11,
        )

        plt.tight_layout()
        out = FIGURES_DIR / "fig1_model_vs_reality.png"
        plt.savefig(out, dpi=300, bbox_inches="tight")
        plt.close()
        print(f"  Сохранён: {out}")


# ---------------------------------------------------------------------------
# Рисунок 2: scatter — модельный vs реальный мультипликатор
# ---------------------------------------------------------------------------

def fig2_cascade_multipliers(scenarios: list[dict]) -> None:
    with plt.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(7, 6))

        has_data = False
        for sc in scenarios:
            mm = sc.get("mult_model")
            mr = sc.get("mult_real")
            if mm is None or mr is None:
                continue
            ax.scatter(mm, mr, s=80, zorder=3, color="#2f7be0")
            ax.annotate(
                sc["name"],
                xy=(mm, mr),
                xytext=(8, 4),
                textcoords="offset points",
                fontsize=8,
            )
            has_data = True

        if not has_data:
            ax.text(0.5, 0.5, "Нет данных для обоих мультипликаторов",
                    ha="center", va="center", transform=ax.transAxes)
        else:
            # Диагональ y = x
            all_vals = []
            for sc in scenarios:
                mm = sc.get("mult_model")
                mr = sc.get("mult_real")
                if mm is not None:
                    all_vals.append(mm)
                if mr is not None:
                    all_vals.append(mr)
            if all_vals:
                lim = (0, max(all_vals) * 1.2)
                ax.plot(lim, lim, "k--", lw=1.0, alpha=0.5, label="y = x (идеал)")
                ax.set_xlim(lim)
                ax.set_ylim(lim)

        ax.set_xlabel("Мультипликатор модели (R_final / R_direct)")
        ax.set_ylabel("Реальный мультипликатор (из источника)")
        ax.set_title("Рис. 2. Каскадный мультипликатор: модель vs реальность")
        ax.legend(fontsize=9)

        plt.tight_layout()
        out = FIGURES_DIR / "fig2_cascade_multipliers.png"
        plt.savefig(out, dpi=300, bbox_inches="tight")
        plt.close()
        print(f"  Сохранён: {out}")


# ---------------------------------------------------------------------------
# Рисунок 3: K_cl vs K_q для всех сценариев
# ---------------------------------------------------------------------------

def fig3_Kcl_vs_Kq(scenarios: list[dict]) -> None:
    with plt.rc_context(STYLE):
        names = [sc["name"] for sc in scenarios]
        k_cl = [sc["mc_base"]["K_cl"] for sc in scenarios]
        k_q = [sc["mc_base"]["K_q"] for sc in scenarios]
        dp = [sc["mc_base"]["delta_pct"] for sc in scenarios]

        x = np.arange(len(names))
        width = 0.35

        fig, ax = plt.subplots(figsize=(10, 6))
        bars_cl = ax.bar(x - width / 2, k_cl, width,
                         label="K_cl (классический)", color="#e05c2f", alpha=0.85)
        bars_q = ax.bar(x + width / 2, k_q, width,
                        label="K_q (количественный)", color="#2f7be0", alpha=0.85)

        # Подписи значений
        for bar in bars_cl:
            h = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2, h + 0.01,
                    f"{h:.3f}", ha="center", va="bottom", fontsize=8)
        for bar in bars_q:
            h = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2, h + 0.01,
                    f"{h:.3f}", ha="center", va="bottom", fontsize=8)

        # Аннотация Δ%
        for i, (kcl_v, kq_v, dp_v) in enumerate(zip(k_cl, k_q, dp)):
            top = max(kcl_v, kq_v) + 0.07
            ax.annotate(
                f"Δ={dp_v:.0f}%",
                xy=(i, top),
                ha="center",
                fontsize=7.5,
                color="#555",
            )

        ax.set_xticks(x)
        ax.set_xticklabels(names, fontsize=9, rotation=10)
        ax.set_ylabel("Доля прогонов с обнаруженным каскадом")
        ax.set_ylim(0, 1.25)
        ax.axhline(1.0, color="k", ls=":", lw=0.7, alpha=0.3)
        ax.legend(fontsize=10)
        ax.set_title(
            "Рис. 3. K_cl vs K_q: классический и количественный операторы\n"
            "(δ = 0.10, N = 1000)",
            fontsize=11,
        )

        plt.tight_layout()
        out = FIGURES_DIR / "fig3_Kcl_vs_Kq_real.png"
        plt.savefig(out, dpi=300, bbox_inches="tight")
        plt.close()
        print(f"  Сохранён: {out}")


# ---------------------------------------------------------------------------
# Рисунок 4: распределение ΔR из MC (violin / box)
# ---------------------------------------------------------------------------

def fig4_risk_distribution(scenarios: list[dict]) -> None:
    with plt.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(10, 6))

        data = [sc["mc_base"]["all_dR"] for sc in scenarios]
        names = [sc["name"] for sc in scenarios]

        vp = ax.violinplot(
            data,
            positions=range(1, len(names) + 1),
            showmedians=True,
            showextrema=True,
        )

        # Раскраска
        for i, body in enumerate(vp["bodies"]):
            body.set_facecolor(SECTOR_COLORS[i % len(SECTOR_COLORS)])
            body.set_alpha(0.65)
        vp["cmedians"].set_color("black")
        vp["cmedians"].set_linewidth(1.5)
        vp["cmins"].set_color("#888")
        vp["cmaxes"].set_color("#888")
        vp["cbars"].set_color("#888")

        # Аннотация p95
        for i, sc in enumerate(scenarios):
            p95 = sc["mc_base"]["p95_dR"]
            ax.annotate(
                f"p95={p95:.3f}",
                xy=(i + 1, p95),
                xytext=(5, 0),
                textcoords="offset points",
                fontsize=7.5,
                color="#333",
            )

        ax.set_xticks(range(1, len(names) + 1))
        ax.set_xticklabels(names, fontsize=9, rotation=10)
        ax.set_ylabel("ΔR = R_final − R_initial")
        ax.axhline(0.0, color="k", ls="--", lw=0.7, alpha=0.4)
        ax.set_title(
            "Рис. 4. Распределение прироста агрегированного риска ΔR\n"
            "(Монте-Карло, N = 1000, σ = 0.03)",
            fontsize=11,
        )

        plt.tight_layout()
        out = FIGURES_DIR / "fig4_risk_distribution.png"
        plt.savefig(out, dpi=300, bbox_inches="tight")
        plt.close()
        print(f"  Сохранён: {out}")


# ---------------------------------------------------------------------------
# Рисунок 5: heatmap δ-sensitivity (K_q по сценариям × δ)
# ---------------------------------------------------------------------------

def fig5_delta_sensitivity(scenarios: list[dict], delta_vals: list[float]) -> None:
    with plt.rc_context(STYLE):
        names = [sc["name"] for sc in scenarios]
        delta_strs = [str(d) for d in delta_vals]

        # Матрица K_q: строки = δ, столбцы = сценарии
        kq_matrix = np.zeros((len(delta_vals), len(scenarios)))
        for j, sc in enumerate(scenarios):
            for i, d in enumerate(delta_strs):
                kq_matrix[i, j] = sc["delta_sweep"].get(d, {}).get("K_q", np.nan)

        fig, ax = plt.subplots(figsize=(10, 4))

        im = ax.imshow(kq_matrix, cmap="RdYlGn", vmin=0.0, vmax=1.0, aspect="auto")

        # Подписи значений
        for i in range(len(delta_vals)):
            for j in range(len(scenarios)):
                val = kq_matrix[i, j]
                text_color = "black" if 0.3 < val < 0.8 else "white"
                ax.text(j, i, f"{val:.3f}", ha="center", va="center",
                        fontsize=9, color=text_color, fontweight="bold")

        ax.set_xticks(range(len(names)))
        ax.set_xticklabels(names, fontsize=9, rotation=10)
        ax.set_yticks(range(len(delta_vals)))
        ax.set_yticklabels([f"δ = {d}" for d in delta_vals], fontsize=9)
        ax.set_xlabel("Сценарий")
        ax.set_ylabel("Порог δ")
        ax.set_title(
            "Рис. 5. Чувствительность K_q к порогу δ\n"
            "(красный < 0.5, зелёный > 0.9; K_cl не зависит от δ)",
            fontsize=11,
        )

        plt.colorbar(im, ax=ax, label="K_q", fraction=0.03, pad=0.02)
        plt.tight_layout()
        out = FIGURES_DIR / "fig5_delta_sensitivity.png"
        plt.savefig(out, dpi=300, bbox_inches="tight")
        plt.close()
        print(f"  Сохранён: {out}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  Генерация графиков")
    print("=" * 60)

    exp = load_results()
    scenarios = exp["scenarios"]
    delta_vals = exp["model_params"]["delta_sweep_vals"]

    print("\n  Рис. 1: model vs reality...")
    fig1_model_vs_reality(scenarios)

    print("  Рис. 2: cascade multipliers...")
    fig2_cascade_multipliers(scenarios)

    print("  Рис. 3: K_cl vs K_q...")
    fig3_Kcl_vs_Kq(scenarios)

    print("  Рис. 4: risk distribution...")
    fig4_risk_distribution(scenarios)

    print("  Рис. 5: delta sensitivity...")
    fig5_delta_sensitivity(scenarios, delta_vals)

    print("\n  Готово.")


if __name__ == "__main__":
    main()
