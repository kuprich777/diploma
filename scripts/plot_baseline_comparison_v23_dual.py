"""plot_baseline_comparison_v23_dual.py — forest-plot двух-семейной рамки H₁ (v2.3.d).

Источник: results/baselines_comparison_v23d.json
Выход:    results/figures/baseline_forest_v23d.{png,pdf}

Структура:
  • Две главные панели сверху: Δb vs DIIM и Δc vs DR (формальная семейная гипотеза, Holm m=58).
  • Одна компактная панель снизу: Δa vs IIM (контекстный baseline, не входит в семейную гипотезу).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

RESULTS = REPO_ROOT / "results"
FIGDIR = RESULTS / "figures"
FIGDIR.mkdir(parents=True, exist_ok=True)

ZONE_COLORS = {"M*": "#1f77b4", "out_M*": "#2ca02c", "hist": "#ff7f0e"}


def _draw_panel(ax, rows, y_pos, title, point_key, ci_key, holm_key,
                acc_label, verdict_label, *, label_y=False, ylabels=None):
    for y, r in zip(y_pos, rows):
        color = ZONE_COLORS.get(r["zone"], "#444")
        point = float(r[point_key])
        lo, hi = float(r[ci_key][0]), float(r[ci_key][1])
        holm_ok = bool(r[holm_key])
        ax.hlines(y, lo, hi, color=color, lw=1.8, alpha=0.85, zorder=2)
        marker = "o" if holm_ok else "s"
        face = color if holm_ok else "white"
        ax.plot(point, y, marker=marker, color=color, markerfacecolor=face,
                markersize=7, markeredgewidth=1.4, zorder=3)
    ax.axvline(0.0, color="#a40000", lw=1.4, ls="--", alpha=0.85, zorder=1)
    ax.set_title(title, fontsize=11.5, weight="bold")
    ax.text(0.5, 1.03, f"{acc_label} — {verdict_label}", transform=ax.transAxes,
            ha="center", va="bottom", fontsize=10, color="#444")
    ax.set_xlabel("Разность метрик")
    ax.grid(axis="x", alpha=0.25, zorder=0)
    if label_y and ylabels is not None:
        ax.set_yticks(y_pos)
        ax.set_yticklabels(ylabels, fontsize=7.5)
    ax.set_ylim(-0.7, len(rows) - 0.3)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-suffix", type=str, default="d",
                    help="suffix for baselines_comparison_v23<suffix>.json (input)"
                         " and baseline_forest_v23<suffix>.{png,pdf} (output)")
    args = ap.parse_args()
    suffix = args.out_suffix
    src = RESULTS / f"baselines_comparison_v23{suffix}.json"
    obj = json.loads(src.read_text(encoding="utf-8"))
    rows = obj["data"]
    summary = obj["summary"]
    n = len(rows)
    y_pos = np.arange(n)[::-1]
    ylabels = [f"{r['sid']}\n→ {r['i_recv']} ({r['zone']})" for r in rows]

    mpl.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10.0,
        "axes.spines.top": False, "axes.spines.right": False,
    })

    fig = plt.figure(figsize=(16, 14))
    gs = fig.add_gridspec(
        2, 2,
        height_ratios=[1.6, 1.0],
        width_ratios=[1.0, 1.0],
        hspace=0.42, wspace=0.18,
        left=0.18, right=0.98, top=0.94, bottom=0.06,
    )
    ax_b = fig.add_subplot(gs[0, 0])
    ax_c = fig.add_subplot(gs[0, 1], sharey=ax_b)
    ax_a = fig.add_subplot(gs[1, :], sharey=ax_b)

    _draw_panel(
        ax_b, rows, y_pos,
        title="Δb = K_q^centered − K_DIIM   [семейство H₁⁽ᵇ⁾, Holm m=58]",
        point_key="diff_b_point", ci_key="ci95_b",
        holm_key="ci_b_lo_positive_holm",
        acc_label=summary["h1_b_acceptance"],
        verdict_label=summary["verdict_h1_b"],
        label_y=True, ylabels=ylabels,
    )
    _draw_panel(
        ax_c, rows, y_pos,
        title="Δc = K_q^centered − K_DR   [семейство H₁⁽ᶜ⁾, Holm m=58]",
        point_key="diff_c_point", ci_key="ci95_c",
        holm_key="ci_c_lo_positive_holm",
        acc_label=summary["h1_c_acceptance"],
        verdict_label=summary["verdict_h1_c"],
    )
    plt.setp(ax_c.get_yticklabels(), visible=False)

    _draw_panel(
        ax_a, rows, y_pos,
        title="Δa = K_q^centered − K_cl^IIM   [контекстный baseline, не в семейной гипотезе]",
        point_key="diff_a_point", ci_key="ci95_a",
        holm_key="ci_a_lo_positive_context",
        acc_label=summary["context_h1_a_vs_iim"],
        verdict_label="контекст",
    )
    plt.setp(ax_a.get_yticklabels(), visible=False)
    ax_a.title.set_color("#666")

    handles = [
        plt.Line2D([], [], marker="o", color=ZONE_COLORS["M*"], lw=2, label="M*"),
        plt.Line2D([], [], marker="o", color=ZONE_COLORS["out_M*"], lw=2, label="out M*"),
        plt.Line2D([], [], marker="o", color=ZONE_COLORS["hist"], lw=2, label="hist"),
        plt.Line2D([], [], marker="s", color="#444", lw=0, markerfacecolor="white",
                   markeredgewidth=1.4, label="Holm не пройден"),
    ]
    fig.legend(handles=handles, loc="lower center", ncol=4, frameon=False,
               bbox_to_anchor=(0.5, 0.005), fontsize=9.5)

    fig.suptitle(
        f"Forest-plot v2.3.d: K_q^centered vs DIIM/DR — двух-семейная рамка H₁, "
        f"n = {n} пар (Holm-Bonferroni m = {summary['n_tests_in_holm']}, FWER 5%). "
        f"Семейная H₁: {summary['h1_family_verdict']}",
        fontsize=12.5, weight="bold", y=0.985,
    )
    out = FIGDIR / f"baseline_forest_v23{suffix}.png"
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor="white")
    fig.savefig(out.with_suffix(".pdf"), bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"[ok] {out.relative_to(REPO_ROOT)} + .pdf")


if __name__ == "__main__":
    main()
