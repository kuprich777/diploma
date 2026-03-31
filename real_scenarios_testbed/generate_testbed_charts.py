"""
Шаг 4: Генерация 3 графиков по результатам стенда.

Считывает:
  results/testbed_results.json
  ../real_scenarios/results/experiment_results.json

Генерирует:
  results/figures/fig_testbed_Kcl_Kq.png
  results/figures/fig_testbed_vs_standalone.png
  results/figures/fig_testbed_model_vs_reality.png
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

ROOT        = Path(__file__).parent
RESULTS_DIR = ROOT / "results"
FIGURES_DIR = RESULTS_DIR / "figures"
STANDALONE  = ROOT.parent / "real_scenarios" / "results" / "experiment_results.json"

SECTORS       = ["energy", "water", "transport"]
SECTOR_LABELS = ["Энергетика", "Водоснабжение", "Транспорт"]
SECTOR_COLORS = ["#e05c2f", "#2f7be0", "#2fa832"]

STYLE = {
    "figure.facecolor": "white",
    "axes.facecolor":   "white",
    "axes.spines.top":  False,
    "axes.spines.right": False,
    "font.family":      "DejaVu Sans",
    "font.size":        10,
}

ID_MAP = {
    "REAL_texas_2021":        "texas_2021",
    "REAL_india_2012":        "india_2012",
    "REAL_europe_2006":       "europe_2006",
    "REAL_baltimore_2024":    "baltimore_2024",
    "REAL_christchurch_2011": "christchurch_2011",
}


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Рис. 1: K_cl vs K_q (стенд)
# ---------------------------------------------------------------------------

def fig_Kcl_Kq(scenarios: list[dict]) -> None:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    valid = [s for s in scenarios if s.get("mc_metrics", {}).get("K_q") is not None]
    if not valid:
        print("  Нет данных для fig_testbed_Kcl_Kq — пропуск")
        return

    names = [s["name"].replace(" (", "\n(") for s in valid]
    k_cl  = [s["mc_metrics"].get("K_cl", 0.0) or 0.0 for s in valid]
    k_q   = [s["mc_metrics"].get("K_q",  0.0) or 0.0 for s in valid]
    dp    = [s["mc_metrics"].get("delta_pct") for s in valid]

    x     = np.arange(len(names))
    width = 0.35

    with plt.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(10, 6))

        bars_cl = ax.bar(x - width / 2, k_cl, width,
                         label="K_cl (классический)", color="#e05c2f", alpha=0.85)
        bars_q  = ax.bar(x + width / 2, k_q,  width,
                         label="K_q (количественный)", color="#2f7be0", alpha=0.85)

        for bar in bars_cl:
            h = bar.get_height()
            if h > 0.01:
                ax.text(bar.get_x() + bar.get_width() / 2, h + 0.01,
                        f"{h:.3f}", ha="center", va="bottom", fontsize=8)
        for bar in bars_q:
            h = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2, h + 0.01,
                    f"{h:.3f}", ha="center", va="bottom", fontsize=8)

        for i, (kcl_v, kq_v, dp_v) in enumerate(zip(k_cl, k_q, dp)):
            if dp_v is not None:
                top = max(kcl_v, kq_v) + 0.08
                ax.annotate(f"Δ={dp_v:.0f}%", xy=(i, top), ha="center",
                            fontsize=7.5, color="#444")

        ax.set_xticks(x)
        ax.set_xticklabels(names, fontsize=9)
        ax.set_ylabel("Доля прогонов с каскадом")
        ax.set_ylim(0, 1.25)
        ax.axhline(1.0, color="k", ls=":", lw=0.7, alpha=0.3)
        ax.legend(fontsize=10)
        ax.set_title(
            "Рис. 1. K_cl vs K_q: стенд\n(MC через микросервисы, N ≈ 200)",
            fontsize=11,
        )

        plt.tight_layout()
        out = FIGURES_DIR / "fig_testbed_Kcl_Kq.png"
        plt.savefig(out, dpi=300, bbox_inches="tight")
        plt.close()
        print(f"  Сохранён: {out}")


# ---------------------------------------------------------------------------
# Рис. 2: K_q(стенд) vs K_q(скрипт) — scatter с диагональю
# ---------------------------------------------------------------------------

def fig_testbed_vs_standalone(tb_scenarios: list[dict], sa_scenarios_map: dict) -> None:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    tb_kq_vals = []
    sa_kq_vals = []
    labels     = []

    for sc in tb_scenarios:
        tb_id = sc.get("id")
        sa_id = ID_MAP.get(tb_id)
        if sa_id is None:
            continue
        sa_sc = sa_scenarios_map.get(sa_id, {})
        tb_kq = sc.get("mc_metrics", {}).get("K_q")
        sa_kq = sa_sc.get("mc_base", {}).get("K_q")
        if tb_kq is not None and sa_kq is not None:
            tb_kq_vals.append(tb_kq)
            sa_kq_vals.append(sa_kq)
            labels.append(sc["name"].split(" (")[0].split(" 20")[0])

    if not tb_kq_vals:
        print("  Нет данных для fig_testbed_vs_standalone — пропуск")
        return

    with plt.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(7, 6))

        ax.scatter(sa_kq_vals, tb_kq_vals, s=90, color="#2f7be0", zorder=3)
        for x, y, lbl in zip(sa_kq_vals, tb_kq_vals, labels):
            ax.annotate(lbl, xy=(x, y), xytext=(6, 4),
                        textcoords="offset points", fontsize=8)

        # Диагональ y = x
        lim = (-0.05, 1.1)
        ax.plot(lim, lim, "k--", lw=1.0, alpha=0.5, label="y = x (идеал)")
        ax.fill_between(lim, [l - 0.05 for l in lim], [l + 0.05 for l in lim],
                        color="gray", alpha=0.08, label="±0.05 коридор")

        ax.set_xlim(lim)
        ax.set_ylim(lim)
        ax.set_xlabel("K_q (автономный скрипт)")
        ax.set_ylabel("K_q (стенд)")
        ax.legend(fontsize=9)
        ax.set_title(
            "Рис. 2. Согласованность K_q: стенд vs скрипт\n"
            "(серая полоса = ±0.05 коридор допустимого расхождения)",
            fontsize=11,
        )

        plt.tight_layout()
        out = FIGURES_DIR / "fig_testbed_vs_standalone.png"
        plt.savefig(out, dpi=300, bbox_inches="tight")
        plt.close()
        print(f"  Сохранён: {out}")


# ---------------------------------------------------------------------------
# Рис. 3: x_model(стенд) vs severity_real — grouped bars
# ---------------------------------------------------------------------------

def fig_model_vs_reality(scenarios: list[dict]) -> None:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    valid = [s for s in scenarios if s.get("x_model") is not None]
    if not valid:
        print("  Нет данных для fig_testbed_model_vs_reality — пропуск")
        return

    n_sc    = len(valid)
    n_sec   = 3
    g_width = 0.7
    bar_w   = g_width / (2 * n_sec)

    with plt.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(14, 6))
        x_base  = np.arange(n_sc)

        for s_idx, sector in enumerate(SECTORS):
            offset = -g_width / 2 + bar_w / 2 + s_idx * 2 * bar_w
            model_vals = [s["x_model"].get(sector, 0.0) for s in valid]
            real_vals  = [s["ground_truth"]["severity"].get(sector, 0.0) for s in valid]
            color = SECTOR_COLORS[s_idx]

            ax.bar(x_base + offset, model_vals, width=bar_w * 0.9,
                   color=color, alpha=0.9)
            ax.bar(x_base + offset + bar_w, real_vals, width=bar_w * 0.9,
                   color=color, alpha=0.40, hatch="///")

        sector_patches = [
            mpatches.Patch(color=SECTOR_COLORS[i], label=SECTOR_LABELS[i])
            for i in range(3)
        ]
        model_patch = mpatches.Patch(color="gray", alpha=0.9,  label="Модель (стенд)")
        real_patch  = mpatches.Patch(color="gray", alpha=0.40, hatch="///", label="Реальность")
        ax.legend(handles=sector_patches + [model_patch, real_patch],
                  fontsize=8, loc="upper right", ncol=2)

        names = [s["name"].replace(" (", "\n(") for s in valid]
        ax.set_xticks(x_base)
        ax.set_xticklabels(names, fontsize=9, rotation=5)
        ax.set_ylabel("Деградация [0, 1]")
        ax.set_ylim(0, 1.15)
        ax.axhline(1.0, color="k", ls=":", lw=0.7, alpha=0.3)
        ax.set_title(
            "Рис. 3. Стенд: x_model vs реальность\n"
            "(сплошной = модель/стенд; штриховка = задокументированный исход)",
            fontsize=11,
        )

        plt.tight_layout()
        out = FIGURES_DIR / "fig_testbed_model_vs_reality.png"
        plt.savefig(out, dpi=300, bbox_inches="tight")
        plt.close()
        print(f"  Сохранён: {out}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  Генерация графиков стенда")
    print("=" * 60)

    tb_path = RESULTS_DIR / "testbed_results.json"
    if not tb_path.exists():
        print(f"  ОШИБКА: {tb_path} не найден.")
        print("  Сначала запустите: python run_on_testbed.py")
        return

    testbed   = load_json(tb_path)
    tb_scens  = testbed.get("scenarios", [])

    sa_scens_map: dict = {}
    if STANDALONE.exists():
        sa_data    = load_json(STANDALONE)
        sa_scens_map = {s["id"]: s for s in sa_data.get("scenarios", [])}
    else:
        print("  ПРЕДУПРЕЖДЕНИЕ: standalone results не найдены "
              "— рис. 2 будет пустым.")

    print("\n  Рис. 1: K_cl vs K_q (стенд)...")
    fig_Kcl_Kq(tb_scens)

    print("  Рис. 2: K_q стенд vs скрипт...")
    fig_testbed_vs_standalone(tb_scens, sa_scens_map)

    print("  Рис. 3: x_model vs reality...")
    fig_model_vs_reality(tb_scens)

    print("\n  Готово.")


if __name__ == "__main__":
    main()
