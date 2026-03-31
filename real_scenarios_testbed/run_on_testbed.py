"""
Шаг 2: Прогон 5 реальных сценариев через микросервисный стенд.

Для каждого сценария:
  1. Одиночный ScenarioRequest → детальный вектор x_T (delta_vec_q)
  2. Монте-Карло:
     - Для energy/transport инициаторов: MonteCarloRequest (API)
     - Для Christchurch (multi-initiator): ручной цикл по ScenarioRequest
  3. Сравнение с ground truth → RMSE
  4. Каскадный мультипликатор

Сохраняет:
  results/testbed_results.json
  results/testbed_run.log

Важные нюансы API:
  - MonteCarloRequest.runs минимум 100 (ge=100)
  - MonteCarloRequest.sector обязателен; steps строятся стендом автоматически
  - ScenarioStep.step_index обязателен (ge=1)
  - dependency_check params: {"source_sector": "...", "source_duration": int}
  - run_id=9001+ (избегать time_ns() overflow в DB integer)
"""

from __future__ import annotations

import json
import logging
import math
import time
from pathlib import Path
from typing import Any

import requests

from scenarios_config import REAL_SCENARIOS, SCENARIO_ORDER, SINGLE_RUN_BASE_ID

# ---------------------------------------------------------------------------
# Настройки
# ---------------------------------------------------------------------------

BASE_RISK = "http://localhost:8004/api/v1/risk"
BASE_SIM  = "http://localhost:8005/api/v1/simulator"

TIMEOUT_SINGLE = 120   # одиночный прогон
TIMEOUT_MC     = 600   # MC (200 прогонов ≈ 5-10 мин)

SECTORS = ["energy", "water", "transport"]
WEIGHTS = [0.4, 0.3, 0.3]

ROOT        = Path(__file__).parent
RESULTS_DIR = ROOT / "results"
LOG_PATH    = RESULTS_DIR / "testbed_run.log"

# ---------------------------------------------------------------------------
# Логгер (файл + консоль)
# ---------------------------------------------------------------------------

def _setup_logger() -> logging.Logger:
    RESULTS_DIR.mkdir(exist_ok=True)
    logger = logging.getLogger("testbed")
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s",
                            datefmt="%H:%M:%S")
    fh = logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8")
    fh.setFormatter(fmt)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


log = _setup_logger()


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _post(url: str, payload: dict, timeout: int, label: str) -> dict | None:
    log.debug(f"POST {url}  payload_keys={list(payload.keys())}")
    try:
        t0 = time.time()
        r = requests.post(url, json=payload, timeout=timeout)
        elapsed = time.time() - t0
        log.debug(f"  → {r.status_code}  {elapsed:.1f}s")
        r.raise_for_status()
        return r.json()
    except requests.ConnectionError:
        log.error(f"[{label}] ConnectionError: стенд недоступен ({url})")
        return None
    except requests.Timeout:
        log.error(f"[{label}] Timeout after {timeout}s ({url})")
        return None
    except requests.HTTPError as e:
        log.error(f"[{label}] HTTP {e.response.status_code}: {e.response.text[:300]}")
        return None
    except Exception as e:
        log.error(f"[{label}] Unexpected error: {e}")
        return None


# ---------------------------------------------------------------------------
# Извлечение модельного вектора из ответа ScenarioRequest
# ---------------------------------------------------------------------------

def extract_x_model(result: dict) -> dict[str, float] | None:
    """
    Извлечь финальный вектор рисков x_T из ScenarioRunResult.

    Приоритет:
      1. after_vec_q  (вектор после сценария, количественный)
      2. delta_vec_q + baseline_x0  (восстановить x_T)
      3. delta_x_q  (legacy поле)
    """
    if result is None:
        return None

    # 1. Прямой вектор after
    after_vec = result.get("after_vec_q")
    if after_vec and all(s in after_vec for s in SECTORS):
        return {s: float(after_vec[s]) for s in SECTORS}

    # 2. Базовый + дельта
    baseline = result.get("baseline_x0") or {}
    delta    = result.get("delta_vec_q") or result.get("delta_x_q") or {}
    if delta and all(s in delta for s in SECTORS):
        return {s: min(1.0, max(0.0, float(baseline.get(s, 0.0)) + float(delta[s])))
                for s in SECTORS}

    # 3. Fallback: поля before/after суммарного риска
    log.warning("  after_vec_q недоступен; модельный вектор не восстановлен")
    return None


# ---------------------------------------------------------------------------
# Одиночный прогон (ScenarioRequest)
# ---------------------------------------------------------------------------

def run_single(scenario_id: str, sc: dict, run_id: int) -> dict | None:
    """Детерминированный одиночный прогон для получения x_model."""
    payload = {
        "scenario_id": scenario_id,
        "run_id": run_id,
        "steps": sc["single_steps"],
        "method": "both",
        "init_all_sectors": True,
        **sc["single_params"],
    }
    log.info(f"  → ScenarioRequest  run_id={run_id}")
    return _post(f"{BASE_SIM}/run_scenario", payload, TIMEOUT_SINGLE, f"{scenario_id}/single")


# ---------------------------------------------------------------------------
# MC через API (MonteCarloRequest) — 4 из 5 сценариев
# ---------------------------------------------------------------------------

def run_mc_api(scenario_id: str, sc: dict) -> dict | None:
    """MonteCarloRequest для energy/transport инициаторов."""
    payload = {
        "scenario_id": scenario_id,
        "mode": "real",
        "start_run_id": 1,
        **sc["mc_params"],
    }
    runs = sc["mc_params"].get("runs", 200)
    log.info(f"  → MonteCarloRequest  sector={sc['mc_params']['sector']}  runs={runs}")
    return _post(f"{BASE_SIM}/monte_carlo", payload, TIMEOUT_MC, f"{scenario_id}/mc_api")


# ---------------------------------------------------------------------------
# MC ручной цикл (ScenarioRequest × N) — Christchurch
# ---------------------------------------------------------------------------

def run_mc_manual(scenario_id: str, sc: dict) -> dict:
    """
    Ручной MC для Christchurch (multi-sector initiator).
    N прогонов через ScenarioRequest с stochastic_scale > 0.
    Вычисляет K_cl, K_q из I_cl/I_q полей каждого прогона.
    """
    n_runs = sc.get("mc_manual_runs", 200)
    start_id = sc.get("mc_start_run_id", 5001)
    stoch    = sc.get("mc_stochastic_scale", 0.3)
    step_params = sc.get("mc_step_params", {})
    delta_thr  = sc["mc_params"].get("delta_sector_threshold", 0.1)
    theta_cl   = sc["mc_params"].get("theta_classical", 0.3)

    log.info(f"  → Manual MC  runs={n_runs}  start_run_id={start_id}  stochastic_scale={stoch}")

    i_cl_list: list[int] = []
    i_q_list: list[int] = []
    delta_r_list: list[float] = []
    ok_runs = 0
    fail_runs = 0

    for i in range(n_runs):
        run_id = start_id + i
        payload = {
            "scenario_id": scenario_id,
            "run_id": run_id,
            "steps": sc["single_steps"],
            "method": "both",
            "init_all_sectors": True,
            "stochastic_scale": stoch,
            "delta_sector_threshold": delta_thr,
            "theta_classical": theta_cl,
            **step_params,
        }
        result = _post(f"{BASE_SIM}/run_scenario", payload, TIMEOUT_SINGLE,
                       f"{scenario_id}/mc_run_{i+1}")
        if result is None:
            fail_runs += 1
            if fail_runs >= 5:
                log.error("  Слишком много ошибок в ручном MC — прерываем")
                break
            continue

        ok_runs += 1
        i_cl = result.get("I_cl", 0) or 0
        i_q  = result.get("I_q", 0) or 0
        dr   = result.get("delta_q") or result.get("delta") or 0.0
        i_cl_list.append(int(i_cl))
        i_q_list.append(int(i_q))
        delta_r_list.append(float(dr))

        if (i + 1) % 20 == 0:
            log.info(f"    прогон {i+1}/{n_runs}: ok={ok_runs} fail={fail_runs}")

    if not delta_r_list:
        return {"error": "все прогоны завершились ошибкой"}

    import statistics
    k_cl = sum(i_cl_list) / len(i_cl_list)
    k_q  = sum(i_q_list)  / len(i_q_list)
    dp   = (k_q - k_cl) / max(k_q, 1e-9) * 100.0
    drs  = sorted(delta_r_list)
    n    = len(drs)
    p95  = drs[int(0.95 * n) - 1]
    p99  = drs[int(0.99 * n) - 1]

    return {
        "scenario_id": scenario_id,
        "sector": "multi",
        "runs": ok_runs,
        "mean_delta": float(sum(delta_r_list) / n),
        "p95_delta": float(p95),
        "p99_delta": float(p99),
        "K_cl": k_cl,
        "K_q": k_q,
        "Delta_percent": dp,
        "_manual_mc": True,
        "_fail_runs": fail_runs,
    }


# ---------------------------------------------------------------------------
# Вычисление RMSE x_model vs ground_truth
# ---------------------------------------------------------------------------

def compute_comparison(
    x_model: dict[str, float] | None,
    gt: dict,
) -> dict:
    severity = gt.get("severity", {})
    sectors = list(severity.keys())

    if x_model is None:
        return {"error": "x_model недоступен", "rmse": None, "per_sector": []}

    per_sector = []
    sq_errors = []
    for s in sectors:
        xm  = x_model.get(s, 0.0)
        xr  = severity.get(s, 0.0)
        ae  = abs(xm - xr)
        re  = ae / max(xr, 1e-6) * 100.0
        sq_errors.append(ae ** 2)
        per_sector.append({
            "sector": s,
            "x_model": xm,
            "severity_real": xr,
            "abs_err": ae,
            "rel_err_pct": re,
        })

    rmse = math.sqrt(sum(sq_errors) / len(sq_errors))
    return {"rmse": rmse, "per_sector": per_sector}


# ---------------------------------------------------------------------------
# Каскадный мультипликатор
# ---------------------------------------------------------------------------

def compute_cascade_multiplier(
    x_model: dict[str, float] | None,
    shock: dict[str, float],
) -> float | None:
    if x_model is None:
        return None
    r_final  = sum(x_model.get(s, 0.0) * w for s, w in zip(SECTORS, WEIGHTS))
    r_direct = sum(shock.get(s, 0.0) * w for s, w in zip(SECTORS, WEIGHTS))
    if r_direct < 1e-9:
        return None
    return r_final / r_direct


# ---------------------------------------------------------------------------
# Агрегация результатов из MonteCarloResult
# ---------------------------------------------------------------------------

def extract_mc_metrics(mc_result: dict) -> dict:
    """Единообразный словарь метрик из MC-ответа (API или ручной)."""
    if mc_result is None:
        return {"error": "MC не выполнен"}

    k_cl = mc_result.get("K_cl")
    k_q  = mc_result.get("K_q")
    dp   = mc_result.get("Delta_percent")
    if dp is None and k_q is not None and k_cl is not None and k_q > 1e-9:
        dp = (k_q - k_cl) / k_q * 100.0

    runs_data = mc_result.get("runs_data", [])
    dr_vals = [r.get("delta_R") or r.get("delta", 0.0) for r in runs_data
               if r.get("delta_R") is not None or r.get("delta") is not None]

    # Также может быть уже в агрегированном ответе
    p95 = mc_result.get("p95_delta")
    mean_dr = mc_result.get("mean_delta")

    if dr_vals and p95 is None:
        dr_sorted = sorted(dr_vals)
        n = len(dr_sorted)
        p95 = dr_sorted[int(0.95 * n) - 1]
    if dr_vals and mean_dr is None:
        mean_dr = sum(dr_vals) / len(dr_vals)

    return {
        "K_cl":      k_cl,
        "K_q":       k_q,
        "delta_pct": dp,
        "mean_dR":   mean_dr,
        "p95_dR":    p95,
        "p99_dR":    mc_result.get("p99_delta"),
        "runs":      mc_result.get("runs", len(runs_data)),
    }


# ---------------------------------------------------------------------------
# Обработка одного сценария
# ---------------------------------------------------------------------------

def process_scenario(scenario_id: str) -> dict:
    sc = REAL_SCENARIOS[scenario_id]
    name = sc["name"]
    gt   = sc["ground_truth"]

    log.info("")
    log.info(f"{'='*55}")
    log.info(f"  {name}")
    log.info(f"{'='*55}")

    # --- 1. Одиночный детерминированный прогон ---
    single_result = run_single(scenario_id, sc, run_id=SINGLE_RUN_BASE_ID)

    x_model = extract_x_model(single_result)
    if x_model:
        log.info(f"  x_model = {{{', '.join(f'{k}:{v:.3f}' for k, v in x_model.items())}}}")
    else:
        log.warning("  x_model не извлечён из single result")

    # Шок для мультипликатора (из single_steps или gt)
    shock_vec = {s: 0.0 for s in SECTORS}
    for step in sc.get("single_steps", []):
        if step["action"] in ("outage", "load_increase"):
            sec = step["sector"]
            dur_or_amount = step["params"].get("duration", step["params"].get("amount", 0))
            # Нормировать duration в [0,1]: 30 мин → ≈ 1.0, используем cap=30
            if step["action"] == "outage":
                shock_vec[sec] = min(1.0, float(dur_or_amount) / 30.0)
            else:
                shock_vec[sec] = float(dur_or_amount)

    # --- 2. MC ---
    mc_mode = sc.get("mc_mode", "api")

    if mc_mode == "api":
        mc_raw = run_mc_api(scenario_id, sc)
        mc_metrics = extract_mc_metrics(mc_raw)
    else:
        # ручной MC (Christchurch)
        mc_raw = run_mc_manual(scenario_id, sc)
        mc_metrics = {
            "K_cl":      mc_raw.get("K_cl"),
            "K_q":       mc_raw.get("K_q"),
            "delta_pct": mc_raw.get("Delta_percent"),
            "mean_dR":   mc_raw.get("mean_delta"),
            "p95_dR":    mc_raw.get("p95_delta"),
            "p99_dR":    mc_raw.get("p99_delta"),
            "runs":      mc_raw.get("runs"),
        }

    log.info(f"  K_cl={mc_metrics.get('K_cl')}  "
             f"K_q={mc_metrics.get('K_q')}  "
             f"Δ%={mc_metrics.get('delta_pct'):.1f}%" if mc_metrics.get("delta_pct") is not None
             else f"  K_cl={mc_metrics.get('K_cl')}  K_q={mc_metrics.get('K_q')}")

    # --- 3. Сравнение с reality ---
    comparison = compute_comparison(x_model, gt)
    rmse = comparison.get("rmse")
    if rmse is not None:
        log.info(f"  RMSE vs reality = {rmse:.4f}")
        for ps in comparison.get("per_sector", []):
            log.info(f"    {ps['sector']:10s}: model={ps['x_model']:.3f}  "
                     f"real={ps['severity_real']:.3f}  "
                     f"|Δ|={ps['abs_err']:.3f}  ({ps['rel_err_pct']:.1f}%)")

    # --- 4. Каскадный мультипликатор ---
    mult = compute_cascade_multiplier(x_model, shock_vec)
    mult_real = gt.get("cascade_multiplier")
    if mult is not None:
        log.info(f"  mult_model={mult:.3f}  mult_real={mult_real}")

    return {
        "id": scenario_id,
        "name": name,
        "initiator": sc.get("initiator", "energy"),
        "mc_mode": mc_mode,
        "single_result_keys": list(single_result.keys()) if single_result else None,
        "x_model": x_model,
        "shock_approx": shock_vec,
        "mc_metrics": mc_metrics,
        "comparison": comparison,
        "mult_model": mult,
        "mult_real": mult_real,
        "ground_truth": gt,
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    RESULTS_DIR.mkdir(exist_ok=True)

    log.info("=" * 55)
    log.info("  Testbed experiment — 5 реальных сценариев")
    log.info("=" * 55)

    # Проверка доступности стенда
    try:
        r = requests.get(f"{BASE_RISK}/dependency_matrix", timeout=5)
        r.raise_for_status()
        log.info("  Стенд доступен ✓")
    except Exception:
        log.error("  Стенд недоступен. Запустите: docker-compose up -d && sleep 30")
        log.error("  Затем повторите: python run_on_testbed.py")
        return

    all_results = []

    for scenario_id in SCENARIO_ORDER:
        try:
            result = process_scenario(scenario_id)
            all_results.append(result)
        except KeyboardInterrupt:
            log.warning("  Прервано пользователем")
            break
        except Exception as e:
            log.error(f"  Ошибка при прогоне {scenario_id}: {e}")
            all_results.append({"id": scenario_id, "error": str(e)})

    # Сводная таблица
    log.info("")
    log.info("=" * 55)
    log.info("  СВОДНАЯ ТАБЛИЦА")
    log.info("=" * 55)
    log.info(f"  {'Сценарий':<28}  {'K_cl':>6}  {'K_q':>6}  {'Δ%':>7}  {'RMSE':>7}")
    log.info("  " + "-" * 56)
    for r in all_results:
        mc = r.get("mc_metrics", {})
        kcl = mc.get("K_cl")
        kq  = mc.get("K_q")
        dp  = mc.get("delta_pct")
        rmse = r.get("comparison", {}).get("rmse")
        kcl_s = f"{kcl:.3f}" if kcl is not None else "   —"
        kq_s  = f"{kq:.3f}"  if kq  is not None else "   —"
        dp_s  = f"{dp:.1f}%" if dp  is not None else "    —"
        rmse_s = f"{rmse:.4f}" if rmse is not None else "     —"
        log.info(f"  {r.get('name', r['id']):<28}  {kcl_s:>6}  {kq_s:>6}  {dp_s:>7}  {rmse_s:>7}")

    # Сохранение
    output = {
        "testbed_params": {
            "base_risk_url": BASE_RISK,
            "base_sim_url": BASE_SIM,
            "sectors": SECTORS,
            "weights": WEIGHTS,
        },
        "scenarios": all_results,
    }
    out_path = RESULTS_DIR / "testbed_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    log.info(f"\n  Сохранено: {out_path}")
    log.info(f"  Лог: {LOG_PATH}")


if __name__ == "__main__":
    main()
