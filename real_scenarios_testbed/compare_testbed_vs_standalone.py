"""
Шаг 3: Сравнение результатов стенда с автономным скриптом.

Загружает:
  results/testbed_results.json                   (прогон через стенд)
  ../real_scenarios/results/experiment_results.json  (автономный numpy-скрипт)

Генерирует:
  results/COMPARISON_REPORT.md
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT        = Path(__file__).parent
RESULTS_DIR = ROOT / "results"
STANDALONE  = ROOT.parent / "real_scenarios" / "results" / "experiment_results.json"

SECTORS = ["energy", "water", "transport"]

# Маппинг id стенда → id автономного скрипта
ID_MAP = {
    "REAL_texas_2021":       "texas_2021",
    "REAL_india_2012":       "india_2012",
    "REAL_europe_2006":      "europe_2006",
    "REAL_baltimore_2024":   "baltimore_2024",
    "REAL_christchurch_2011": "christchurch_2011",
}


def load_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _fmt(v: float | None, prec: int = 3) -> str:
    return f"{v:.{prec}f}" if v is not None else "—"


def _diff(a: float | None, b: float | None) -> str:
    if a is None or b is None:
        return "—"
    return f"{abs(a - b):.3f}"


def generate_comparison(testbed: dict, standalone: dict) -> str:
    tb_scenarios = {s["id"]: s for s in testbed.get("scenarios", [])}
    sa_scenarios = {s["id"]: s for s in standalone.get("scenarios", [])}

    lines: list[str] = []

    lines += [
        "# Сравнительный отчёт: стенд vs автономный скрипт",
        "",
        "> Сгенерировано: `compare_testbed_vs_standalone.py`",
        "",
        "**Два уровня модели:**",
        "- **Стенд** — `risk_engine` + `scenario_simulator` (HTTP-сервисы, domain weights)",
        "- **Скрипт** — чистый numpy: `x' = clip(x + shock + A·x)` (абстрактный уровень)",
        "",
        "---",
        "",
    ]

    # -----------------------------------------------------------------------
    # §1: Метрики K_cl, K_q
    # -----------------------------------------------------------------------
    lines += [
        "## 1. Сравнение K_cl и K_q",
        "",
        "| Сценарий | K_cl (стенд) | K_cl (скрипт) | Δ K_cl | "
        "K_q (стенд) | K_q (скрипт) | Δ K_q |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]

    for tb_id, sa_id in ID_MAP.items():
        tb = tb_scenarios.get(tb_id, {})
        sa = sa_scenarios.get(sa_id, {})
        tb_mc = tb.get("mc_metrics", {})
        sa_mc = sa.get("mc_base", {})

        name = tb.get("name", tb_id.replace("REAL_", ""))
        tb_kcl = tb_mc.get("K_cl")
        sa_kcl = sa_mc.get("K_cl")
        tb_kq  = tb_mc.get("K_q")
        sa_kq  = sa_mc.get("K_q")

        lines.append(
            f"| {name} | {_fmt(tb_kcl)} | {_fmt(sa_kcl)} | {_diff(tb_kcl, sa_kcl)} | "
            f"{_fmt(tb_kq)} | {_fmt(sa_kq)} | {_diff(tb_kq, sa_kq)} |"
        )

    lines += [""]

    # -----------------------------------------------------------------------
    # §2: Вектор x_model
    # -----------------------------------------------------------------------
    lines += [
        "## 2. Сравнение модельного вектора x_model",
        "",
        "| Сценарий | Сектор | x_model (стенд) | x_model (скрипт) | Δ |",
        "|---|---|---:|---:|---:|",
    ]

    for tb_id, sa_id in ID_MAP.items():
        tb = tb_scenarios.get(tb_id, {})
        sa = sa_scenarios.get(sa_id, {})

        x_tb = tb.get("x_model") or {}
        x_sa_list = sa.get("x_model") or []
        # x_model в скрипте хранится как список [e, w, t]
        x_sa = dict(zip(SECTORS, x_sa_list)) if isinstance(x_sa_list, list) else {}

        name = tb.get("name", tb_id.replace("REAL_", ""))
        for i, s in enumerate(SECTORS):
            tb_val = x_tb.get(s)
            sa_val = x_sa.get(s)
            row_name = name if i == 0 else ""
            lines.append(
                f"| {row_name} | {s} | {_fmt(tb_val)} | {_fmt(sa_val)} | "
                f"{_diff(tb_val, sa_val)} |"
            )

    lines += [""]

    # -----------------------------------------------------------------------
    # §3: RMSE
    # -----------------------------------------------------------------------
    lines += [
        "## 3. RMSE vs реальность",
        "",
        "| Сценарий | RMSE (стенд) | RMSE (скрипт) | Δ RMSE |",
        "|---|---:|---:|---:|",
    ]

    for tb_id, sa_id in ID_MAP.items():
        tb = tb_scenarios.get(tb_id, {})
        sa = sa_scenarios.get(sa_id, {})

        tb_rmse = tb.get("comparison", {}).get("rmse")
        sa_rmse = sa.get("rmse_vs_real")
        name = tb.get("name", tb_id.replace("REAL_", ""))

        lines.append(
            f"| {name} | {_fmt(tb_rmse)} | {_fmt(sa_rmse)} | {_diff(tb_rmse, sa_rmse)} |"
        )

    lines += [""]

    # -----------------------------------------------------------------------
    # §4: Согласованность K_q
    # -----------------------------------------------------------------------
    lines += [
        "## 4. Оценка согласованности",
        "",
        "**Критерий**: K_q(стенд) ≈ K_q(скрипт) ± 0.05 → системы эквивалентны.",
        "",
        "| Сценарий | K_q(стенд) | K_q(скрипт) | |Δ| | Согласован? |",
        "|---|---:|---:|---:|:---:|",
    ]

    all_consistent = True
    for tb_id, sa_id in ID_MAP.items():
        tb = tb_scenarios.get(tb_id, {})
        sa = sa_scenarios.get(sa_id, {})
        tb_kq = tb.get("mc_metrics", {}).get("K_q")
        sa_kq = sa.get("mc_base", {}).get("K_q")
        name  = tb.get("name", tb_id.replace("REAL_", ""))

        if tb_kq is not None and sa_kq is not None:
            diff = abs(tb_kq - sa_kq)
            ok = diff <= 0.05
            if not ok:
                all_consistent = False
            mark = "✓" if ok else "✗"
        else:
            diff = None
            mark = "?"

        lines.append(
            f"| {name} | {_fmt(tb_kq)} | {_fmt(sa_kq)} | "
            f"{_fmt(diff)} | {mark} |"
        )

    lines += [""]

    verdict = (
        "**Системы эквивалентны** по K_q (|Δ| ≤ 0.05 во всех сценариях)."
        if all_consistent else
        "**Расхождение > 0.05** в одном или нескольких сценариях (см. §5)."
    )
    lines += [verdict, ""]

    # -----------------------------------------------------------------------
    # §5: Объяснение расхождений
    # -----------------------------------------------------------------------
    lines += [
        "## 5. Методологические причины расхождений",
        "",
        "| Аспект | Автономный скрипт | Стенд |",
        "|---|---|---|",
        "| Оператор | clip(x + shock + A·x), чистый numpy | risk_engine + domain services (HTTP) |",
        "| Каскад | матричное умножение A | interaction queue + dep_check endpoints |",
        "| Веса energy→water | A[water][energy] = 0.4 | domain-layer weight = 0.40 (aligned) |",
        "| Веса energy→transport | A[transport][energy] = 0.5 | domain-layer weight = 0.50 (aligned) |",
        "| Шум | gaussian σ = 0.03 на x | stochastic_scale × N(1, σ) на duration |",
        "| Скорость | ~2 сек на 1000 прогонов | ~5–10 мин на 200 прогонов |",
        "",
        "**Domain-layer weights** (0.40 / 0.50) выровнены с матричными A-weights (0.4 / 0.5) "
        "начиная с доработки реалистичности (2026-03-29). "
        "Стенд реализует двухуровневую архитектуру:",
        "- *Абстрактный уровень*: матрица A (скрипт) — параметры эксперимента",
        "- *Domain уровень*: физические dep_check weights — реализация в конкретных сервисах",
        "",
        "Если |Δ K_q| ≤ 0.05: оба уровня дают статистически неразличимый результат.",
        "Если |Δ K_q| > 0.05: domain weights доминируют над A, что само по себе "
        "является методологическим наблюдением об архитектурной чувствительности модели.",
        "",
        "---",
        "",
        "_Воспроизведение: `python run_on_testbed.py && python compare_testbed_vs_standalone.py`_",
        "",
    ]

    return "\n".join(lines)


def main() -> None:
    print("=" * 60)
    print("  Генерация COMPARISON_REPORT.md")
    print("=" * 60)

    tb_path = RESULTS_DIR / "testbed_results.json"
    if not tb_path.exists():
        print(f"  ОШИБКА: {tb_path} не найден.")
        print("  Сначала запустите: python run_on_testbed.py")
        return

    if not STANDALONE.exists():
        print(f"  ПРЕДУПРЕЖДЕНИЕ: {STANDALONE} не найден.")
        print("  Сначала запустите: cd ../real_scenarios && python run_experiment.py")
        # Создаём отчёт только по стенду
        standalone = {"scenarios": []}
    else:
        standalone = load_json(STANDALONE)

    testbed = load_json(tb_path)

    md = generate_comparison(testbed, standalone)

    out = RESULTS_DIR / "COMPARISON_REPORT.md"
    out.write_text(md, encoding="utf-8")
    print(f"  Сохранён: {out}")
    print("  Готово.")


if __name__ == "__main__":
    main()
