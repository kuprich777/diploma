"""plot_baseline_comparison_v23e.py — forest-plot со scope refinement (v2.3.e).

Источник: results/baselines_comparison_v23e.json
Выход:    results/figures/baseline_forest_v23e.{png,pdf}

Структура:
  • Две главные панели (in-scope, |A| >= 0.10): Δb vs DIIM, Δc vs DR.
  • Диагностическая секция снизу (out-of-scope, |A| < 0.10) — серым.
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
DIAG_COLOR = "#888888"


def _draw_panel(ax, rows, y_pos, title, point_key, ci_key, holm_key,
                acc_label, verdict_label, *, label_y=False, ylabels=None,
                color_override=None):
    for y, r in zip(y_pos, rows):
        color = color_override or ZONE_COLORS.get(r["zone"], "#444")
        point = float(r[point_key])
        lo, hi = float(r[ci_key][0]), float(r[ci_key][1])
        if holm_key is None:
            holm_ok = (lo > 0)
        else:
            holm_ok = bool(r[holm_key])
        ax.hlines(y, lo, hi, color=color, lw=1.8,
                  alpha=0.85 if color_override is None else 0.55, zorder=2)
        marker = "o" if holm_ok else "s"
        face = color if holm_ok else "white"
        ax.plot(point, y, marker=marker, color=color, markerfacecolor=face,
                markersize=7, markeredgewidth=1.4, zorder=3,
                alpha=0.85 if color_override is None else 0.6)
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
    ap.add_argument("--out-suffix", type=str, default="e")
    args = ap.parse_args()
    suffix = args.out_suffix
    src = RESULTS / f"baselines_comparison_v23{suffix}.json"
    obj = json.loads(src.read_text(encoding="utf-8"))
    in_rows = obj["data_included"]
    out_rows = obj["data_excluded_diagnostic"]
    summary = obj["summary"]
    n_in = len(in_rows)
    n_out = len(out_rows)
    y_in = np.arange(n_in)[::-1]
    y_out = np.arange(n_out)[::-1]
    ylabels_in = [f"{r['sid']}\n→ {r['i_recv']} ({r['zone']}) |A|={r['A_value']:.2f}"
                  for r in in_rows]
    ylabels_out = [f"{r['sid']}\n→ {r['i_recv']} ({r['zone']}) |A|={r['A_value']:.3f}"
                   for r in out_rows]

    mpl.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10.0,
        "axes.spines.top": False, "axes.spines.right": False,
    })

    h_in = max(4.5, 0.4 * n_in + 1.5)
    h_out = max(3.0, 0.32 * n_out + 1.2) if n_out > 0 else 0.0
    fig_h = h_in + h_out + 1.5
    height_ratios = [h_in, h_out] if n_out > 0 else [h_in]

    fig = plt.figure(figsize=(16, fig_h))
    if n_out > 0:
        gs = fig.add_gridspec(
            2, 2,
            height_ratios=height_ratios,
            width_ratios=[1.0, 1.0],
            hspace=0.55, wspace=0.18,
            left=0.20, right=0.98, top=0.94, bottom=0.06,
        )
        ax_b = fig.add_subplot(gs[0, 0])
        ax_c = fig.add_subplot(gs[0, 1], sharey=ax_b)
        ax_diag = fig.add_subplot(gs[1, :])
    else:
        gs = fig.add_gridspec(1, 2, width_ratios=[1.0, 1.0], wspace=0.18,
                              left=0.20, right=0.98, top=0.92, bottom=0.10)
        ax_b = fig.add_subplot(gs[0, 0])
        ax_c = fig.add_subplot(gs[0, 1], sharey=ax_b)
        ax_diag = None

    _draw_panel(
        ax_b, in_rows, y_in,
        title=f"Δb = K_q^centered − K_DIIM   [in-scope, Holm m={summary['n_tests_in_holm']}]",
        point_key="diff_b_point", ci_key="ci95_b",
        holm_key="ci_b_lo_positive_holm",
        acc_label=summary["h1_b_acceptance"],
        verdict_label=summary["verdict_h1_b"],
        label_y=True, ylabels=ylabels_in,
    )
    _draw_panel(
        ax_c, in_rows, y_in,
        title=f"Δc = K_q^centered − K_DR   [in-scope, Holm m={summary['n_tests_in_holm']}]",
        point_key="diff_c_point", ci_key="ci95_c",
        holm_key="ci_c_lo_positive_holm",
        acc_label=summary["h1_c_acceptance"],
        verdict_label=summary["verdict_h1_c"],
    )
    plt.setp(ax_c.get_yticklabels(), visible=False)

    if ax_diag is not None and n_out > 0:
        # Объединённая диагностическая панель: показываем Δb и Δc out-of-scope
        # двумя цветами (тонко, как «scatter» интервалов).
        for k, r in enumerate(out_rows):
            y = y_out[k]
            ax_diag.hlines(y - 0.15, r["ci95_b"][0], r["ci95_b"][1],
                           color="#7570b3", lw=1.2, alpha=0.55)
            ax_diag.plot(r["diff_b_point"], y - 0.15, "o",
                         color="#7570b3", markersize=5, alpha=0.7)
            ax_diag.hlines(y + 0.15, r["ci95_c"][0], r["ci95_c"][1],
                           color="#d95f02", lw=1.2, alpha=0.55)
            ax_diag.plot(r["diff_c_point"], y + 0.15, "s",
                         color="#d95f02", markersize=5, alpha=0.7)
        ax_diag.axvline(0.0, color="#a40000", lw=1.2, ls="--", alpha=0.7)
        ax_diag.set_yticks(y_out)
        ax_diag.set_yticklabels(ylabels_out, fontsize=7.0, color=DIAG_COLOR)
        ax_diag.set_ylim(-0.8, n_out - 0.2)
        ax_diag.set_title(
            f"Out-of-scope (диагностика): {n_out} пар с |A[recv, init]| < 0,10 — "
            "не входят в формальный тест H₁",
            fontsize=10.5, color=DIAG_COLOR, weight="bold",
        )
        ax_diag.set_xlabel("Разность метрик (Δb синий, Δc оранжевый)",
                           color=DIAG_COLOR)
        ax_diag.grid(axis="x", alpha=0.2)
        ax_diag.tick_params(axis="x", colors=DIAG_COLOR)
        for spine in ax_diag.spines.values():
            spine.set_color(DIAG_COLOR)

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
        f"Forest-plot v2.3.e: scope refinement |A| ≥ 0,10  "
        f"(in-scope: {n_in}/{n_in + n_out};  Holm m = {summary['n_tests_in_holm']}, "
        f"FWER 5%).  Семейная H₁: {summary['h1_family_verdict']}",
        fontsize=12.5, weight="bold", y=0.985,
    )
    fig.text(0.5, 0.015,
             "Из формального теста H₁ исключены пары с |A[recv, init]| < 0,10 "
             "(METHODOLOGY §2.4.3).",
             ha="center", fontsize=9, style="italic", color="#444")
    out = FIGDIR / f"baseline_forest_v23{suffix}.png"
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor="white")
    fig.savefig(out.with_suffix(".pdf"), bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"[ok] {out.relative_to(REPO_ROOT)} + .pdf")


if __name__ == "__main__":
    main()
