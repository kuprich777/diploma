"""Калибровка σ_j в x-пространстве по METHODOLOGY §8.2 (ревизия 2026-04-20).

Пайплайн на representative sensor:
    0. x_from_scada(sector, raw_value) — нормировка SCADA → x ∈ [0,1]
       (degradation score, как в services/*/routers/*.py)
    1. Δx_t = x_{t+1} - x_t — арифметические приращения (filter 0<x<1)
    2. AR(p)-фильтрация (p ∈ {0,1,2} по BIC) → residuals ε̂_t
    3. Newey-West HAC variance с L = floor(4*(n/100)^{2/9})
    4. σ = sqrt(σ²_NW / Δt_SCADA)   [ч^{-1/2}, x-пространство, арифметические]
       БЕЗ /(1-C_j) — σ уже в правильном пространстве x ∈ [0,1].
    5. SNR = δ / (σ · √Δt_experiment)

Секторные значения: один representative sensor на сектор.
σ_transport = 0 (§8.2 Decision D1).

Правка 2026-04-20 (A): σ калибруется на x = f(raw_scada), не на raw SCADA.
Правка 2026-04-20 (B): арифметические приращения Δx, а не log-returns
(SDE §3.4 арифметическая, шум прибавляется к x — см. §11.7).

Вход:
    datasets/dataset hai /hai/...       — HAI 21.03 CSV, attack_flag==0
    datasets/kelmarsh/...               — Kelmarsh Farm SCADA (опционально, для σ_wind)
    data/calibration/capacity_thresholds.json — C_j (§8.1)

Выход:
    data/calibration/sigma_calibrated_v2.json
"""
from __future__ import annotations

import json
import os
import sys
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

try:
    import pandas as pd
    from statsmodels.tsa.arima.model import ARIMA
except ImportError as e:
    print(f"pip install pandas statsmodels  ({e})")
    sys.exit(1)

REPO_ROOT = Path(__file__).resolve().parent.parent
DATASETS_ROOT = Path(os.environ.get("DATASETS_ROOT", "/Users/kuprich/Documents/diploma_repo/datasets"))
HAI_PATH = DATASETS_ROOT / "dataset hai " / "hai"
KELMARSH_PATH = DATASETS_ROOT / "kelmarsh"
CAPACITY_IN = REPO_ROOT / "data" / "calibration" / "capacity_thresholds.json"
CALIB_OUT = REPO_ROOT / "data" / "calibration" / "sigma_calibrated_v2.json"

HAI_DT_HOURS = 1 / 3600.0           # 1-second sampling
KELMARSH_DT_HOURS = 10 / 60.0        # 10-minute sampling
DT_EXPERIMENT_HOURS = 1.0            # SDE шаг §3.4
DELTA_PREREG = 0.10                  # §0.4

MIN_ROWS = 2000                      # ряд для ARIMA
MAX_ROWS = 50_000                    # cap per sensor (ARIMA на 1.3M строк — overkill)

# §8.2: ОДИН representative sensor на сектор, выбранный как output/state variable.
# Остальные — диагностика, сохраняются в артефакте, но не усредняются в σ_j.
REPRESENTATIVE_SENSOR: dict[str, str] = {
    "energy": "P4_ST_PO",   # steam turbine power output
    "water":  "P3_LIT01",   # water level (state variable)
}
DIAGNOSTIC_SENSORS: dict[str, list[str]] = {
    "energy": ["P4_HT_PO", "P4_ST_LD", "P4_HT_LD"],
    "water":  ["P3_PIT01", "P3_FIT01"],
}

# Nominal values from HAI 21.03 (см. scripts/calibrate_capacity.py HAI_NOMINAL).
# Используются для нормировки SCADA → degradation score x ∈ [0,1] в соответствии
# с логикой services/*/routers/*.py.
HAI_NOMINAL: dict[str, float] = {
    "P4_ST_PO": 498.9,    # steam turbine power output, MW (nominal)
    "P4_HT_PO": 89.6,
    "P4_ST_LD": 499.6,
    "P4_HT_LD": 83.1,
    "P3_LIT01": 20489.0,  # water level, mm (nominal = full reservoir)
    "P3_PIT01": 7090.0,
    "P3_FIT01": 7761.0,
}

# Energy util thresholds (energy_service.routers.energy):
#   util = cons/prod; x = clip((util - 0.7)/0.3, 0, 1)
# Для SCADA power-output сенсора используем util ≡ output/nominal как proxy загрузки.
UTIL_LOW = 0.7
UTIL_HIGH = 1.0


def x_from_scada(sector: str, sensor: str, raw: np.ndarray) -> np.ndarray:
    """SCADA raw → x ∈ [0,1] (degradation score, совместимо с services/*/routers/*.py).

    energy (power output sensors): util = raw/nominal, x = clip((util-0.7)/0.3, 0, 1).
    water (level sensor P3_LIT01):  level_norm = raw/nominal, x = clip(1 - level_norm, 0, 1).
    water (pressure/flow P3_*):     аналогично, как state-variable с full=nominal, empty=0.
    """
    nominal = HAI_NOMINAL.get(sensor)
    if nominal is None or nominal <= 0:
        raise ValueError(f"Нет nominal для {sensor}")
    if sector == "energy":
        util = raw / nominal
        x = (util - UTIL_LOW) / (UTIL_HIGH - UTIL_LOW)
    elif sector == "water":
        # Все P3-сенсоры трактуются как state-variable: 0 при full=nominal, 1 при empty
        level_norm = raw / nominal
        x = 1.0 - level_norm
    else:
        raise ValueError(f"x_from_scada не определена для сектора {sector}")
    return np.clip(x, 0.0, 1.0)


def _fail(param: str, needed: str, found: str, reason: str, recommendation: str) -> None:
    print(f"""
🔴 ДАННЫЕ НЕДОСТАТОЧНЫ / ВЫХОД ЗА РАМКИ МЕТОДОЛОГИИ

Параметр:           {param}
Что нужно:          {needed}
Что есть:           {found}
Почему не подходит: {reason}
Рекомендация:       {recommendation}
""")
    sys.exit(1)


def load_capacity() -> dict[str, float]:
    if not CAPACITY_IN.exists():
        _fail("σ_j (калибровка)", f"{CAPACITY_IN}", "Отсутствует",
              "σ_dim = σ_raw/(1-C_j) требует C_j из §8.1",
              "Запустить scripts/calibrate_capacity.py до σ-калибровки")
    payload = json.loads(CAPACITY_IN.read_text(encoding="utf-8"))
    out = {}
    for sec in ("energy", "water", "transport"):
        try:
            out[sec] = float(payload["sectors"][sec]["C"])
        except KeyError:
            _fail(f"σ_{sec} (C_j)", f"payload.sectors.{sec}.C",
                  f"Ключ не найден в {CAPACITY_IN}",
                  "Неполная калибровка C_j", "Перезапустить §8.1")
    return out


def newey_west_variance(eps: np.ndarray, L: int | None = None) -> tuple[float, int]:
    """HAC-оценка дисперсии: γ_0 + 2·Σ_{ℓ=1}^L (1-ℓ/(L+1))·γ_ℓ.

    Bartlett kernel; L = floor(4·(n/100)^{2/9}) по умолчанию (§8.2).
    """
    eps = np.asarray(eps, dtype=float)
    eps = eps - eps.mean()
    n = len(eps)
    if L is None:
        L = int(np.floor(4 * (n / 100) ** (2 / 9)))
        L = max(L, 1)
    gamma0 = float(np.mean(eps * eps))
    var = gamma0
    for lag in range(1, L + 1):
        g = float(np.mean(eps[lag:] * eps[:-lag]))
        w = 1.0 - lag / (L + 1)
        var += 2.0 * w * g
    return max(var, 0.0), L


def fit_ar_best_bic(series: np.ndarray, max_p: int = 2) -> tuple[np.ndarray, int, float]:
    """AR(p) pre-filter; p подбирается по BIC, p ∈ {0,..,max_p}.

    Возвращает (residuals, p*, BIC*). p=0 означает отсутствие фильтрации.
    """
    best_p, best_bic, best_resid = 0, np.inf, None
    for p in range(0, max_p + 1):
        try:
            if p == 0:
                resid = series - series.mean()
                # Use empirical log-likelihood for BIC at p=0 (null model)
                n = len(series)
                sigma2 = float(np.var(series, ddof=1))
                ll = -0.5 * n * (np.log(2 * np.pi * sigma2) + 1.0)
                bic = -2 * ll + np.log(n) * 1
            else:
                model = ARIMA(series, order=(p, 0, 0), trend="c").fit()
                resid = np.asarray(model.resid)
                bic = float(model.bic)
            if bic < best_bic:
                best_bic, best_p, best_resid = bic, p, resid
        except Exception:
            continue
    if best_resid is None:
        best_resid = series - series.mean()
    return best_resid, best_p, float(best_bic)


def calibrate_sensor(x: np.ndarray, dt_hours: float, sensor: str) -> dict | None:
    """Полный пайплайн §8.2 для одного ряда (уже в x-пространстве). Возвращает dict или None.

    Filter 0 < x < 1: исключаем клипованные края, где Δx=0 искусственно
    занизил бы дисперсию.

    Правка 2026-04-20: арифметические приращения Δx_t, не log-returns.
    Обоснование: SDE §3.4 арифметическая (x_{t+1}=x_t+u_t+A·x_t+σ√Δt·ε),
    шум прибавляется к x, не к log(x). Калибровка в тех же единицах.
    """
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x) & (x > 0.0) & (x < 1.0)]
    if len(x) < MIN_ROWS:
        return None
    # Arithmetic increments в x-пространстве (было log-returns; см. докстринг)
    lr = np.diff(x)
    lr = lr[np.isfinite(lr)]
    if len(lr) < MIN_ROWS:
        return None
    if len(lr) > MAX_ROWS:
        lr = lr[:MAX_ROWS]

    n_raw = len(lr)
    acf1_raw = float(np.corrcoef(lr[:-1], lr[1:])[0, 1]) if n_raw > 2 else float("nan")

    # Шаг 1: ARIMA(p,0,0) по BIC
    resid, p_star, bic = fit_ar_best_bic(lr, max_p=2)

    acf1_resid = (
        float(np.corrcoef(resid[:-1], resid[1:])[0, 1])
        if len(resid) > 2
        else float("nan")
    )

    # Шаг 2: Newey-West HAC variance
    nw_var, nw_L = newey_west_variance(resid)
    if nw_var <= 0 or not np.isfinite(nw_var):
        return None

    # Шаг 3: переход к ч^{-1/2}
    sigma_raw = float(np.sqrt(nw_var / dt_hours))

    return {
        "sensor": sensor,
        "n": int(n_raw),
        "acf1_raw": round(acf1_raw, 4) if np.isfinite(acf1_raw) else None,
        "acf1_resid": round(acf1_resid, 4) if np.isfinite(acf1_resid) else None,
        "ar_order_p": p_star,
        "bic": round(bic, 3),
        "nw_L": nw_L,
        "nw_variance": round(nw_var, 8),
        "sigma_raw_per_sqrt_hour": round(sigma_raw, 6),
    }


# --- HAI loader ---

def _detect_attack_col(columns: list[str]) -> str | None:
    """HAI 21.03 → 'attack'; другие релизы могут иметь 'attack_flag' или 'label'."""
    lc = {c.lower(): c for c in columns}
    for cand in ("attack_flag", "attack", "label"):
        if cand in lc:
            return lc[cand]
    return None


def load_hai_normal() -> tuple[pd.DataFrame, str]:
    if not HAI_PATH.exists():
        _fail("σ (HAI)", f"{HAI_PATH}",
              "Каталог отсутствует", "HAI не загружен",
              "Скачать HAI 21.03 с Kaggle: icsdataset/hai-security-dataset")
    csvs = sorted(HAI_PATH.rglob("*.csv")) + sorted(HAI_PATH.rglob("*.csv.gz"))
    csvs = [p for p in csvs if "21.03" in str(p)] or csvs
    if not csvs:
        _fail("σ (HAI)", "CSV в HAI каталоге",
              f"{HAI_PATH} пуст", "Нет данных",
              "Скачать HAI 21.03")

    # Detect attack-marker column from the first file's header
    head = pd.read_csv(csvs[0], nrows=1, compression="infer")
    attack_col = _detect_attack_col(list(head.columns))
    if attack_col is None:
        _fail("σ (HAI) — attack marker",
              "Колонка attack / attack_flag / label",
              f"Колонки: {list(head.columns)[:10]}...",
              "Не удалось распознать маркер нормального режима",
              "Добавить кандидат в _detect_attack_col")
    print(f"[HAI] attack-marker column: '{attack_col}'")

    all_sensors = sorted(
        set(REPRESENTATIVE_SENSOR.values())
        | {s for group in DIAGNOSTIC_SENSORS.values() for s in group}
    )
    keep = set(all_sensors) | {attack_col}
    dfs = []
    for p in csvs:
        try:
            df = pd.read_csv(p, usecols=lambda c: c in keep, compression="infer")
            if attack_col in df.columns:
                dfs.append(df)
            else:
                print(f"  [skip] {p.name}: нет '{attack_col}'")
        except Exception as e:
            print(f"  [warn] {p.name}: {e}")
    if not dfs:
        _fail("σ (HAI)", f"CSV с колонкой '{attack_col}'",
              f"{len(csvs)} файлов, ни один не распарсен",
              "Повреждённые данные", "Проверить целостность HAI")
    full = pd.concat(dfs, ignore_index=True)
    normal = full[full[attack_col] == 0].copy()
    if len(normal) < MIN_ROWS:
        _fail("σ (HAI)", f"≥{MIN_ROWS} строк {attack_col}==0",
              f"{len(normal)} строк", "Слишком мало", "Загрузить больше файлов HAI")
    print(f"[HAI] {len(full)} всего; {len(normal)} normal-mode ({attack_col}==0)")
    return normal, attack_col


# --- Kelmarsh loader (для energy_wind, опционально) ---

def load_kelmarsh_power() -> list[np.ndarray] | None:
    if not KELMARSH_PATH.exists():
        print("[Kelmarsh] каталог отсутствует — σ_wind пропущен")
        return None
    files = sorted(KELMARSH_PATH.rglob("Turbine_Data_Kelmarsh_*.csv"))
    if not files:
        print("[Kelmarsh] файлов не найдено — σ_wind пропущен")
        return None
    series_list: list[np.ndarray] = []
    for p in files:
        try:
            df = pd.read_csv(p, skiprows=9)
            df.columns = [c.lstrip("#").strip() for c in df.columns]
            if "Power (kW)" not in df.columns:
                continue
            vals = df["Power (kW)"].dropna().values.astype(float)
            vals = vals[vals > 50.0]  # operational
            if len(vals) < MIN_ROWS:
                continue
            series_list.append(vals)
        except Exception:
            continue
    print(f"[Kelmarsh] {len(series_list)} рядов прошли фильтр")
    return series_list or None


# --- Main ---

def main() -> None:
    print("=" * 70)
    print("σ-калибровка v2 (x-space arithmetic Δx: ARIMA + Newey-West, без /(1-C_j)), METHODOLOGY §8.2")
    print("=" * 70)

    C = load_capacity()
    print(f"[C_j] energy={C['energy']:.4f}  water={C['water']:.4f}  transport={C['transport']:.4f}")

    # --- HAI-based sensors (energy + water) ---
    hai, attack_col = load_hai_normal()

    per_sensor: dict[str, dict] = {}

    def _run_sensor(sector: str, s: str, role: str) -> None:
        if s not in hai.columns:
            print(f"  {s} [{role}]: нет колонки в HAI — пропуск")
            return
        raw = hai[s].dropna().values.astype(float)
        try:
            x_score = x_from_scada(sector, s, raw)
        except ValueError as e:
            print(f"  {s} [{role}]: {e} — пропуск")
            return
        n_in_range = int(((x_score > 0) & (x_score < 1)).sum())
        n_zero = int((x_score == 0).sum())
        n_one = int((x_score == 1).sum())
        print(
            f"  {s:10s} [{role:10s}] raw_n={len(raw)}  x∈(0,1): {n_in_range}  x=0: {n_zero}  x=1: {n_one}"
        )
        res = calibrate_sensor(x_score, dt_hours=HAI_DT_HOURS, sensor=s)
        if res is None:
            print(f"                 не удалось откалибровать (MIN_ROWS=2000 для x∈(0,1) или NW)")
            return
        print(
            f"                 n_Δx={res['n']:>6d}  acf1={res['acf1_raw']}→{res['acf1_resid']}  "
            f"p*={res['ar_order_p']}  L_NW={res['nw_L']}  σ_x(arith)={res['sigma_raw_per_sqrt_hour']:.6f} /√h"
        )
        res["sector"] = sector
        res["role"] = role
        res["n_x_in_range"] = n_in_range
        res["n_x_zero"] = n_zero
        res["n_x_one"] = n_one
        per_sensor[s] = res

    for sector, rep in REPRESENTATIVE_SENSOR.items():
        print(f"\n[{sector}] representative = {rep}; diagnostic = {DIAGNOSTIC_SENSORS.get(sector, [])}")
        _run_sensor(sector, rep, "representative")
        for s in DIAGNOSTIC_SENSORS.get(sector, []):
            _run_sensor(sector, s, "diagnostic")

    if not per_sensor:
        _fail("σ_j (пайплайн §8.2)",
              "≥1 откалиброванный сенсор",
              "Все сенсоры отбракованы",
              "ARIMA не сходится или MIN_ROWS не выполнен",
              "Проверить данные HAI; увеличить MIN_ROWS или изменить max_p")

    # --- Kelmarsh wind (supplement for energy) ---
    wind_series = load_kelmarsh_power()
    wind_results: list[dict] = []
    if wind_series:
        print("\n[energy_wind] Kelmarsh Senvion MM92 (dt=10 мин)")
        for i, vals in enumerate(wind_series):
            res = calibrate_sensor(vals, dt_hours=KELMARSH_DT_HOURS, sensor=f"kelmarsh_turbine_{i+1}")
            if res is None:
                continue
            print(
                f"  t{i+1}: n={res['n']:>6d}  acf1={res['acf1_raw']}→{res['acf1_resid']}  "
                f"p*={res['ar_order_p']}  σ_raw={res['sigma_raw_per_sqrt_hour']:.4f} /√h"
            )
            wind_results.append(res)

    # --- Sector aggregation: σ из representative sensor, уже в x-пространстве ---
    # БЕЗ /(1-C_j) — σ откалибровано напрямую на x = f(raw_scada) ∈ [0,1].
    sector_out: dict[str, dict] = {}

    for sector in ("energy", "water"):
        rep = REPRESENTATIVE_SENSOR[sector]
        if rep not in per_sensor:
            _fail(f"σ_{sector}", f"representative sensor {rep}",
                  f"не откалиброван",
                  "SCADA-ряд не прошёл MIN_ROWS или NW",
                  f"Проверить {rep} в HAI normal-mode")
        sigma_x = float(per_sensor[rep]["sigma_raw_per_sqrt_hour"])
        snr = DELTA_PREREG / (sigma_x * np.sqrt(DT_EXPERIMENT_HOURS)) if sigma_x > 0 else float("inf")
        sector_out[sector] = {
            "representative_sensor": rep,
            "aggregation_rule": "single representative sensor (§8.2, x-space)",
            "sigma_x_per_sqrt_hour": round(sigma_x, 6),
            "sigma_dim": round(sigma_x, 6),  # kept for backward compat with downstream loaders
            "C_j": C[sector],
            "SNR_at_delta_0.10_dt_1h": round(snr, 4) if np.isfinite(snr) else None,
            "diagnostic_sensors": {
                s: per_sensor[s]["sigma_raw_per_sqrt_hour"]
                for s in DIAGNOSTIC_SENSORS.get(sector, [])
                if s in per_sensor
            },
        }

    # Transport σ = 0 (Decision D1, §8.2)
    sector_out["transport"] = {
        "sigma_x_per_sqrt_hour": 0.0,
        "sigma_dim": 0.0,
        "C_j": C["transport"],
        "SNR_at_delta_0.10_dt_1h": float("inf"),
        "n_sensors": 0,
        "sensors_used": [],
        "decision": "D1 strict: σ_transport = 0 (§8.2, no open high-freq ops data)",
    }

    # energy_wind (supplement) — калибруется на raw power, не в x-пространстве.
    # Оставляем как справочную оценку в единицах 1/√h на raw ряде.
    if wind_results:
        wraws = [r["sigma_raw_per_sqrt_hour"] for r in wind_results]
        sigma_wind_raw = float(np.median(wraws))
        sector_out["energy_wind"] = {
            "sigma_raw_per_sqrt_hour": round(sigma_wind_raw, 6),
            "n_turbines": len(wind_results),
            "note": "Kelmarsh kW raw (не в x-пространстве) — supplementary only",
        }

    # --- Report ---
    print("\n" + "=" * 70)
    print("Секторные σ (после §8.2 процедуры):")
    print("=" * 70)
    print(f"{'sector':12s}  {'σ_x(arith) /√h':>16s}  {'SNR (δ=0.10, Δt=1ч)':>20s}  gate")
    for sec, row in sector_out.items():
        sigma_val = row.get("sigma_x_per_sqrt_hour", row.get("sigma_raw_per_sqrt_hour", 0.0))
        snr = row.get("SNR_at_delta_0.10_dt_1h")
        if snr is None:
            snr_str, gate = "n/a", "—"
        elif snr == float("inf"):
            snr_str, gate = "inf", "✓"
        else:
            snr_str = f"{snr:.4f}"
            gate = "✓" if snr >= 1.0 else "🔴 SNR<1"
        print(f"{sec:12s}  {sigma_val:>16.6f}  {snr_str:>20s}  {gate}")

    # SNR gate — soft, per §8.2 end
    low_snr = [
        sec for sec, row in sector_out.items()
        if row.get("SNR_at_delta_0.10_dt_1h") is not None
        and row["SNR_at_delta_0.10_dt_1h"] != float("inf")
        and row["SNR_at_delta_0.10_dt_1h"] < 1.0
    ]
    if low_snr:
        print(
            f"\n⚠️  SNR<1 в секторах: {low_snr}. По §8.2 это acceptance gate (§13.3):\n"
            f"   возможные меры: переход на Δt=0.01ч или увеличение N_runs.\n"
            f"   Результат записан в артефакт для решения автором."
        )

    # --- Save ---
    result = {
        "method": "METHODOLOGY §8.2 (x-space arithmetic Δx: x=f(raw_scada) → Δx → ARIMA(p,0,0) by BIC → Newey-West HAC → /√Δt_SCADA; БЕЗ /(1-C_j); см. §11.7)",
        "sources": {
            "hai": str(HAI_PATH),
            "kelmarsh": str(KELMARSH_PATH),
            "capacity": str(CAPACITY_IN),
        },
        "params": {
            "dt_hai_hours": HAI_DT_HOURS,
            "dt_kelmarsh_hours": KELMARSH_DT_HOURS,
            "dt_experiment_hours": DT_EXPERIMENT_HOURS,
            "delta_prereg": DELTA_PREREG,
            "min_rows": MIN_ROWS,
            "max_rows": MAX_ROWS,
            "ar_max_p": 2,
            "NW_bandwidth": "floor(4*(n/100)^{2/9})",
        },
        "sectors": sector_out,
        "per_sensor_hai": per_sensor,
        "kelmarsh_per_turbine": wind_results,
    }
    CALIB_OUT.parent.mkdir(parents=True, exist_ok=True)
    CALIB_OUT.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"\n[save] {CALIB_OUT}")


if __name__ == "__main__":
    main()
