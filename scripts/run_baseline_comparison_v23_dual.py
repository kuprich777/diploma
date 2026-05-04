"""run_baseline_comparison_v23_dual.py — двух-семейная рамка H₁ (v2.3.d).

METHODOLOGY v2.4 §2.4. Семейная гипотеза H₁ декомпозируется на ДВА семейства:
    H₁⁽ᵇ⁾: CI_lo(K_q^centered − K_DIIM) > 0 на ≥90% пар
    H₁⁽ᶜ⁾: CI_lo(K_q^centered − K_DR)   > 0 на ≥90% пар

Holm-Bonferroni на m = N_pairs × 2 = 58 (вместо 87).
Классический IIM (Хаймса-Сантос 2001) — equilibrium-метод; сохраняется как
контекстный baseline (Δa), но НЕ входит в формальную семейную гипотезу.

Оптимизация: переиспользуем raw p-values и CI95 из results/baselines_comparison_v23c.json
(они инвариантны к m_holm). Пересчитываем только Holm-поправку.

Запуск:
    docker compose exec -w /repo risk_engine python scripts/run_baseline_comparison_v23_dual.py
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
SOURCE = RESULTS / "baselines_comparison_v23c.json"
FWER_ALPHA = 0.05
ACCEPTANCE_THRESHOLD = 0.90


def run(out_suffix: str = "d") -> None:
    if not SOURCE.exists():
        raise FileNotFoundError(f"source artifact not found: {SOURCE}")
    src = json.loads(SOURCE.read_text(encoding="utf-8"))
    src_rows = src["data"]
    n_pairs = len(src_rows)
    n_tests_dual = 2 * n_pairs

    t_start = time.time()
    print("=" * 80)
    print(f"BASELINE COMPARISON v2.3.d (dual-family)  pairs={n_pairs}  m_holm={n_tests_dual}")
    print(f"  source: {SOURCE.relative_to(REPO_ROOT)}  (reusing raw p-values, CIs)")
    print("=" * 80)

    # 1) Контекстная Holm на m=29 для Δa (vs IIM) — справочно, не в семейной гипотезе.
    p_a_raw = [r["p_a_raw"] for r in src_rows]
    holm_a = holm_bonferroni(p_a_raw, alpha=FWER_ALPHA)
    p_a_adj = holm_a["p_adj"]
    rejected_a = holm_a["rejected"]

    # 2) Двух-семейная Holm: m=58 на конкатенации [p_b..., p_c...].
    p_b_raw = [r["p_b_raw"] for r in src_rows]
    p_c_raw = [r["p_c_raw"] for r in src_rows]
    holm_dual = holm_bonferroni([*p_b_raw, *p_c_raw], alpha=FWER_ALPHA)
    p_dual_adj = holm_dual["p_adj"]
    rejected_dual = holm_dual["rejected"]
    p_b_adj = p_dual_adj[:n_pairs]
    p_c_adj = p_dual_adj[n_pairs:]
    rejected_b = rejected_dual[:n_pairs]
    rejected_c = rejected_dual[n_pairs:]

    rows: list[dict] = []
    n_a_ctx = n_b = n_c = 0
    for k, r in enumerate(src_rows):
        ci_a = r["ci95_a"]
        ci_b = r["ci95_b"]
        ci_c = r["ci95_c"]

        ci_a_lo_pos_naive = bool(ci_a[0] > 0 and rejected_a[k])
        ci_b_lo_pos_holm = bool(ci_b[0] > 0 and rejected_b[k])
        ci_c_lo_pos_holm = bool(ci_c[0] > 0 and rejected_c[k])

        n_a_ctx += int(ci_a_lo_pos_naive)
        n_b += int(ci_b_lo_pos_holm)
        n_c += int(ci_c_lo_pos_holm)

        rows.append({
            "sid": r["sid"],
            "zone": r["zone"],
            "initiator": r["initiator"],
            "i_recv": r["i_recv"],
            "alpha": r["alpha"],
            "theta_node": r["theta_node"],
            "i_recv_index": r["i_recv_index"],
            "K_cl_IIM": r["K_cl_IIM"],
            "K_DIIM": r["K_DIIM"],
            "K_DebtRank": r["K_DebtRank"],
            "K_q_centered": r["K_q_centered"],
            # Контекстный (vs IIM) — не в семейной гипотезе.
            "diff_a_point": r["diff_a_point"],
            "ci95_a": ci_a,
            "p_a_raw": r["p_a_raw"],
            "p_a_holm_context": float(p_a_adj[k]),
            "ci_a_lo_positive_context": ci_a_lo_pos_naive,
            # H₁⁽ᵇ⁾ vs DIIM — в семейной гипотезе.
            "diff_b_point": r["diff_b_point"],
            "ci95_b": ci_b,
            "p_b_raw": r["p_b_raw"],
            "p_b_holm_dual": float(p_b_adj[k]),
            "ci_b_lo_positive_holm": ci_b_lo_pos_holm,
            # H₁⁽ᶜ⁾ vs DR — в семейной гипотезе.
            "diff_c_point": r["diff_c_point"],
            "ci95_c": ci_c,
            "p_c_raw": r["p_c_raw"],
            "p_c_holm_dual": float(p_c_adj[k]),
            "ci_c_lo_positive_holm": ci_c_lo_pos_holm,
        })

    threshold_pass = int(np.ceil(ACCEPTANCE_THRESHOLD * n_pairs))
    h1_b_accepted = n_b >= threshold_pass
    h1_c_accepted = n_c >= threshold_pass
    h1_family_accepted = bool(h1_b_accepted and h1_c_accepted)

    summary = {
        "n_pairs": n_pairs,
        "n_tests_in_holm": n_tests_dual,
        "primary_baselines": ["K_DIIM", "K_DebtRank"],
        "context_baseline": "K_cl_IIM",
        "acceptance_threshold": ACCEPTANCE_THRESHOLD,
        "threshold_pass_count": threshold_pass,
        "h1_b_acceptance": f"{n_b}/{n_pairs}",
        "h1_c_acceptance": f"{n_c}/{n_pairs}",
        "verdict_h1_b": "ПРИНЯТА" if h1_b_accepted else "ОТВЕРГНУТА",
        "verdict_h1_c": "ПРИНЯТА" if h1_c_accepted else "ОТВЕРГНУТА",
        "h1_family_verdict": "ПРИНЯТА" if h1_family_accepted else "ОТВЕРГНУТА",
        "context_h1_a_vs_iim": f"{n_a_ctx}/{n_pairs}",
        "context_note": (
            "K_cl_IIM (Хаймса-Сантос 2001) — equilibrium-метод; "
            "не входит в семейную гипотезу H₁ (см. METHODOLOGY §2.4)."
        ),
        "min_ci_lo_a_context": float(min(r["ci95_a"][0] for r in rows)),
        "min_ci_lo_b": float(min(r["ci95_b"][0] for r in rows)),
        "min_ci_lo_c": float(min(r["ci95_c"][0] for r in rows)),
        "weakest_pairs": {
            "b_min_ci_lo_pair":
                min(rows, key=lambda r: r["ci95_b"][0])["sid"]
                + " → " + min(rows, key=lambda r: r["ci95_b"][0])["i_recv"],
            "c_min_ci_lo_pair":
                min(rows, key=lambda r: r["ci95_c"][0])["sid"]
                + " → " + min(rows, key=lambda r: r["ci95_c"][0])["i_recv"],
            "a_min_ci_lo_pair_context":
                min(rows, key=lambda r: r["ci95_a"][0])["sid"]
                + " → " + min(rows, key=lambda r: r["ci95_a"][0])["i_recv"],
        },
    }
    elapsed = time.time() - t_start

    out = {
        "version": "v2.3.d (dual-family)",
        "methodology_ref": "METHODOLOGY.md v2.4 §2.4 (двух-семейная рамка)",
        "metric_form": src.get("metric_form"),
        "source_artifact": str(SOURCE.relative_to(REPO_ROOT)),
        "params": {
            **src.get("params", {}),
            "fwer_correction": "Holm-Bonferroni",
            "n_tests_in_holm": int(n_tests_dual),
            "FWER_alpha": float(FWER_ALPHA),
            "acceptance_threshold": ACCEPTANCE_THRESHOLD,
            "primary_baselines": ["K_DIIM", "K_DebtRank"],
            "context_baseline": "K_cl_IIM",
        },
        "data": rows,
        "summary": summary,
        "elapsed_sec": round(elapsed, 3),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "execution_environment": get_execution_environment(),
    }
    out_path = RESULTS / f"baselines_comparison_v23{out_suffix}.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")

    print("\n" + "=" * 80)
    print(f"VERDICT (двух-семейная Holm-Bonferroni m={n_tests_dual}, FWER={FWER_ALPHA}):")
    print(f"  H1^(b) vs K_DIIM:        {summary['h1_b_acceptance']}  → {summary['verdict_h1_b']}")
    print(f"  H1^(c) vs K_DR:          {summary['h1_c_acceptance']}  → {summary['verdict_h1_c']}")
    print(f"  СЕМЕЙНАЯ H1:             → {summary['h1_family_verdict']}")
    print(f"  [context] H1^(a) vs IIM: {summary['context_h1_a_vs_iim']}  (не в гипотезе)")
    print(f"  Min CI_lo: b={summary['min_ci_lo_b']:+.4f}  "
          f"c={summary['min_ci_lo_c']:+.4f}  [a={summary['min_ci_lo_a_context']:+.4f}]")
    print(f"\n  ELAPSED: {elapsed:.2f} сек")
    print(f"  [save] {out_path.relative_to(REPO_ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-suffix", type=str, default="d",
                    help="suffix for baselines_comparison_v23<suffix>.json (default: d)")
    args = ap.parse_args()
    run(out_suffix=args.out_suffix)


if __name__ == "__main__":
    main()
