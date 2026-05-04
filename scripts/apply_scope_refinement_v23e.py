"""apply_scope_refinement_v23e.py — фильтрация каталога по |A[recv, init]| >= 0.10.

METHODOLOGY v2.4 §2.4.3. Критерий включения пар в каталог формальной проверки H₁:
    |A[i_recv, i_init]| >= THRESHOLD = 0.10
где A — матрица из data/calibration/A_5sector.json (A_scaled).

Применяется СИММЕТРИЧНО ко всем семействам и до просмотра статистических результатов.

Запуск:
    docker compose exec -w /repo risk_engine python scripts/apply_scope_refinement_v23e.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from services.risk_engine.params import SCENARIOS_V23, SECTOR_KEYS_5, sector_index_5
from services.risk_engine.utils import get_execution_environment

RESULTS = REPO_ROOT / "results"
A5_PATH = REPO_ROOT / "data" / "calibration" / "A_5sector.json"
THRESHOLD = 0.10


def main() -> None:
    A = np.array(json.loads(A5_PATH.read_text())["A_scaled"], dtype=float)

    in_scope: list[dict] = []
    out_scope: list[dict] = []
    for sid, init, alpha, theta, recv, zone in SCENARIOS_V23:
        i_init = sector_index_5(init)
        i_recv = sector_index_5(recv)
        a_val = float(abs(A[i_recv, i_init]))
        rec = {
            "sid": sid, "init": init, "recv": recv,
            "alpha": float(alpha), "theta_node": float(theta),
            "zone": zone, "A_value": round(a_val, 6),
        }
        if a_val >= THRESHOLD:
            in_scope.append(rec)
        else:
            rec["reason"] = f"|A| = {a_val:.4f} < {THRESHOLD}"
            out_scope.append(rec)

    n_total = len(SCENARIOS_V23)
    n_in = len(in_scope)
    n_out = len(out_scope)

    print("=" * 80)
    print(f"SCOPE REFINEMENT v2.3.e  |A[recv, init]| >= {THRESHOLD}")
    print("=" * 80)
    print(f"  Каталог: {n_total} пар  →  in-scope: {n_in}  out-of-scope: {n_out}")
    print(f"  m_holm (двух-семейная) = {n_in} × 2 = {2 * n_in}")
    print()
    print("In-scope pairs (|A| >= 0.10):")
    for r in in_scope:
        print(f"  ✓ {r['sid']:30s} {r['init']:>4s} → {r['recv']:<4s} "
              f"({r['zone']:<6s}) |A|={r['A_value']:.3f}")
    print()
    print("Out-of-scope pairs (|A| < 0.10) — диагностические:")
    for r in out_scope:
        print(f"  · {r['sid']:30s} {r['init']:>4s} → {r['recv']:<4s} "
              f"({r['zone']:<6s}) |A|={r['A_value']:.3f}")

    out = {
        "version": "v2.3.e (scope-refined)",
        "methodology_ref": "METHODOLOGY.md v2.4 §2.4.3",
        "criterion": "|A[recv, init]| >= 0.10",
        "threshold": THRESHOLD,
        "matrix_source": "data/calibration/A_5sector.json (A_scaled, 5×5)",
        "sector_keys": list(SECTOR_KEYS_5),
        "n_total": n_total,
        "n_included": n_in,
        "n_excluded": n_out,
        "n_tests_in_holm_dual": 2 * n_in,
        "included_pairs": in_scope,
        "excluded_pairs": out_scope,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "execution_environment": get_execution_environment(),
    }
    out_path = RESULTS / "scope_refinement_v23e.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    print(f"\n  [save] {out_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
