"""run_baseline_comparison_v23e.py — двух-семейная H₁ на отфильтрованном каталоге (v2.3.e).

METHODOLOGY v2.4 §2.4.3 (scope refinement) + §2.4.2 (двух-семейная рамка).

Источники:
    results/scope_refinement_v23e.json — список in-scope пар (|A| >= 0.10)
    results/baselines_comparison_v23c.json — raw bootstrap p-values + CI95
        (переиспользуем; пересчитываем только Holm на отфильтрованном m).

Holm-Bonferroni: m = N_filtered × 2 (DIIM + DR).
Контекстный H₁⁽ᵃ⁾ vs IIM считается отдельной Holm на m = N_filtered (для отчёта).

Запуск:
    docker compose exec -w /repo risk_engine python scripts/run_baseline_comparison_v23e.py
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from services.risk_engine.stats import holm_bonferroni
from services.risk_engine.utils import get_execution_environment

RESULTS = REPO_ROOT / "results"
SCOPE_PATH = RESULTS / "scope_refinement_v23e.json"
SOURCE_PATH = RESULTS / "baselines_comparison_v23c.json"
FWER_ALPHA = 0.05
ACCEPTANCE_THRESHOLD = 0.90


def _key(sid: str, recv: str) -> tuple[str, str]:
    return (sid, recv)


def run(out_suffix: str = "e") -> None:
    if not SCOPE_PATH.exists():
        raise FileNotFoundError(
            f"scope artifact not found: {SCOPE_PATH}. "
            "Сначала запусти scripts/apply_scope_refinement_v23e.py"
        )
    if not SOURCE_PATH.exists():
        raise FileNotFoundError(f"source artifact not found: {SOURCE_PATH}")

    scope = json.loads(SCOPE_PATH.read_text(encoding="utf-8"))
    src = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))

    in_keys = {_key(p["sid"], p["recv"]) for p in scope["included_pairs"]}
    out_keys = {_key(p["sid"], p["recv"]) for p in scope["excluded_pairs"]}
    a_lookup = {_key(p["sid"], p["recv"]): p["A_value"] for p in
                (*scope["included_pairs"], *scope["excluded_pairs"])}

    src_by_key: dict[tuple[str, str], dict] = {}
    for r in src["data"]:
        src_by_key[_key(r["sid"], r["i_recv"])] = r

    in_rows_src = [src_by_key[k] for k in src_by_key if k in in_keys]
    out_rows_src = [src_by_key[k] for k in src_by_key if k in out_keys]

    n_in = len(in_rows_src)
    n_out = len(out_rows_src)
    n_tests_dual = 2 * n_in

    t_start = time.time()
    print("=" * 80)
    print(f"BASELINE COMPARISON v2.3.e (scope-refined)  in-scope={n_in}  m_holm={n_tests_dual}")
    print(f"  scope:  {SCOPE_PATH.relative_to(REPO_ROOT)}")
    print(f"  source: {SOURCE_PATH.relative_to(REPO_ROOT)} (reusing raw p-values, CIs)")
    print("=" * 80)

    # H1^(b) и H1^(c) — двух-семейная Holm на m = 2 * n_in.
    p_b_in = [r["p_b_raw"] for r in in_rows_src]
    p_c_in = [r["p_c_raw"] for r in in_rows_src]
    holm_dual = holm_bonferroni([*p_b_in, *p_c_in], alpha=FWER_ALPHA)
    p_dual_adj = holm_dual["p_adj"]
    rejected_dual = holm_dual["rejected"]
    p_b_adj = p_dual_adj[:n_in]
    p_c_adj = p_dual_adj[n_in:]
    rejected_b = rejected_dual[:n_in]
    rejected_c = rejected_dual[n_in:]

    # Контекстный H1^(a) vs IIM — отдельная Holm на m = n_in.
    p_a_in = [r["p_a_raw"] for r in in_rows_src]
    holm_a_ctx = holm_bonferroni(p_a_in, alpha=FWER_ALPHA)
    p_a_adj = holm_a_ctx["p_adj"]
    rejected_a = holm_a_ctx["rejected"]

    data_in: list[dict] = []
    n_a = n_b = n_c = 0
    for k, r in enumerate(in_rows_src):
        ci_a, ci_b, ci_c = r["ci95_a"], r["ci95_b"], r["ci95_c"]
        ci_a_pos = bool(ci_a[0] > 0 and rejected_a[k])
        ci_b_pos = bool(ci_b[0] > 0 and rejected_b[k])
        ci_c_pos = bool(ci_c[0] > 0 and rejected_c[k])
        n_a += int(ci_a_pos); n_b += int(ci_b_pos); n_c += int(ci_c_pos)
        data_in.append({
            "sid": r["sid"], "zone": r["zone"], "initiator": r["initiator"],
            "i_recv": r["i_recv"], "alpha": r["alpha"], "theta_node": r["theta_node"],
            "i_recv_index": r["i_recv_index"],
            "A_value": a_lookup[_key(r["sid"], r["i_recv"])],
            "K_cl_IIM": r["K_cl_IIM"], "K_DIIM": r["K_DIIM"],
            "K_DebtRank": r["K_DebtRank"], "K_q_centered": r["K_q_centered"],
            "diff_a_point": r["diff_a_point"], "ci95_a": ci_a, "p_a_raw": r["p_a_raw"],
            "p_a_holm_context": float(p_a_adj[k]), "ci_a_lo_positive_context": ci_a_pos,
            "diff_b_point": r["diff_b_point"], "ci95_b": ci_b, "p_b_raw": r["p_b_raw"],
            "p_b_holm_dual": float(p_b_adj[k]), "ci_b_lo_positive_holm": ci_b_pos,
            "diff_c_point": r["diff_c_point"], "ci95_c": ci_c, "p_c_raw": r["p_c_raw"],
            "p_c_holm_dual": float(p_c_adj[k]), "ci_c_lo_positive_holm": ci_c_pos,
        })

    # Out-of-scope — диагностика, без Holm-теста.
    data_out: list[dict] = []
    for r in out_rows_src:
        data_out.append({
            "sid": r["sid"], "zone": r["zone"], "initiator": r["initiator"],
            "i_recv": r["i_recv"], "alpha": r["alpha"], "theta_node": r["theta_node"],
            "A_value": a_lookup[_key(r["sid"], r["i_recv"])],
            "K_cl_IIM": r["K_cl_IIM"], "K_DIIM": r["K_DIIM"],
            "K_DebtRank": r["K_DebtRank"], "K_q_centered": r["K_q_centered"],
            "diff_a_point": r["diff_a_point"], "ci95_a": r["ci95_a"],
            "diff_b_point": r["diff_b_point"], "ci95_b": r["ci95_b"],
            "diff_c_point": r["diff_c_point"], "ci95_c": r["ci95_c"],
            "out_of_scope_reason": f"|A| = {a_lookup[_key(r['sid'], r['i_recv'])]:.4f} < 0.10",
        })

    threshold_pass = int(np.ceil(ACCEPTANCE_THRESHOLD * n_in))
    h1_b_accepted = n_b >= threshold_pass
    h1_c_accepted = n_c >= threshold_pass
    h1_family_accepted = bool(h1_b_accepted and h1_c_accepted)

    summary = {
        "n_pairs_total": n_in + n_out,
        "n_included": n_in,
        "n_excluded": n_out,
        "n_tests_in_holm": n_tests_dual,
        "primary_baselines": ["K_DIIM", "K_DebtRank"],
        "context_baseline": "K_cl_IIM",
        "acceptance_threshold": ACCEPTANCE_THRESHOLD,
        "threshold_pass_count": threshold_pass,
        "h1_b_acceptance": f"{n_b}/{n_in}",
        "h1_c_acceptance": f"{n_c}/{n_in}",
        "verdict_h1_b": "ПРИНЯТА" if h1_b_accepted else "ОТВЕРГНУТА",
        "verdict_h1_c": "ПРИНЯТА" if h1_c_accepted else "ОТВЕРГНУТА",
        "h1_family_verdict": "ПРИНЯТА" if h1_family_accepted else "ОТВЕРГНУТА",
        "context_h1_a_vs_iim": f"{n_a}/{n_in}",
        "context_note": (
            "K_cl_IIM (Хаймса–Сантос 2001) — equilibrium-метод; "
            "не входит в семейную гипотезу H₁ (см. METHODOLOGY §2.4.4)."
        ),
        "min_ci_lo_a_context": float(min(r["ci95_a"][0] for r in data_in)) if data_in else None,
        "min_ci_lo_b": float(min(r["ci95_b"][0] for r in data_in)) if data_in else None,
        "min_ci_lo_c": float(min(r["ci95_c"][0] for r in data_in)) if data_in else None,
        "weakest_pairs": {
            "b": (min(data_in, key=lambda r: r["ci95_b"][0])["sid"]
                  + " → " + min(data_in, key=lambda r: r["ci95_b"][0])["i_recv"]) if data_in else None,
            "c": (min(data_in, key=lambda r: r["ci95_c"][0])["sid"]
                  + " → " + min(data_in, key=lambda r: r["ci95_c"][0])["i_recv"]) if data_in else None,
        },
    }
    elapsed = time.time() - t_start

    out = {
        "version": "v2.3.e (scope-refined)",
        "methodology_ref": "METHODOLOGY.md v2.4 §2.4.3 (scope) + §2.4.2 (dual-family)",
        "scope_criterion": "|A[recv, init]| >= 0.10",
        "scope_artifact": str(SCOPE_PATH.relative_to(REPO_ROOT)),
        "source_artifact": str(SOURCE_PATH.relative_to(REPO_ROOT)),
        "metric_form": src.get("metric_form"),
        "params": {
            **src.get("params", {}),
            "fwer_correction": "Holm-Bonferroni",
            "n_tests_in_holm": int(n_tests_dual),
            "FWER_alpha": float(FWER_ALPHA),
            "acceptance_threshold": ACCEPTANCE_THRESHOLD,
            "primary_baselines": ["K_DIIM", "K_DebtRank"],
            "context_baseline": "K_cl_IIM",
            "scope_threshold": 0.10,
            "n_included": int(n_in),
            "n_excluded": int(n_out),
        },
        "data_included": data_in,
        "data_excluded_diagnostic": data_out,
        "summary": summary,
        "elapsed_sec": round(elapsed, 3),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "execution_environment": get_execution_environment(),
    }
    out_path = RESULTS / f"baselines_comparison_v23{out_suffix}.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")

    print("\n" + "=" * 80)
    print(f"VERDICT (scope-refined, двух-семейная Holm m={n_tests_dual}, FWER={FWER_ALPHA}):")
    print(f"  H1^(b) vs K_DIIM:        {summary['h1_b_acceptance']}  → {summary['verdict_h1_b']}")
    print(f"  H1^(c) vs K_DR:          {summary['h1_c_acceptance']}  → {summary['verdict_h1_c']}")
    print(f"  СЕМЕЙНАЯ H1:             → {summary['h1_family_verdict']}")
    print(f"  [context] H1^(a) vs IIM: {summary['context_h1_a_vs_iim']}")
    print(f"  Threshold pass count:    ⌈{ACCEPTANCE_THRESHOLD}·{n_in}⌉ = {threshold_pass}")
    if summary["min_ci_lo_b"] is not None:
        print(f"  Min CI_lo: b={summary['min_ci_lo_b']:+.4f}  "
              f"c={summary['min_ci_lo_c']:+.4f}  [a={summary['min_ci_lo_a_context']:+.4f}]")
    print(f"\n  ELAPSED: {elapsed:.2f} сек")
    print(f"  [save] {out_path.relative_to(REPO_ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-suffix", type=str, default="e")
    args = ap.parse_args()
    run(out_suffix=args.out_suffix)


if __name__ == "__main__":
    main()
