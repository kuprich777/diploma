"""
calibrate_sigma.py
==================
Calibrate volatility parameters σ_j from HAI (energy/ICS) and
OpenWindSCADA (wind energy) datasets.

Method
------
For each power sensor in normal operating mode (attack_flag == 0):
    σ = std(Δ log x_t) / sqrt(dt)
where Δ log x_t = log(x_{t+1} / x_t) (log-returns).

Output
------
    data/calibration/sigma_calibrated.json

Protocol: if data is insufficient, prints a structured 🔴 DATA INSUFFICIENT
message and exits — NEVER substitutes synthetic or literature values.
"""

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
REPO_ROOT        = Path(__file__).resolve().parent.parent
DATASETS_ROOT    = Path(os.environ.get(
    "DATASETS_ROOT",
    "/Users/kuprich/Documents/diploma_repo/datasets"
))
HAI_PATH         = DATASETS_ROOT / "dataset hai " / "hai"  # note trailing space in dir name
KELMARSH_PATH    = DATASETS_ROOT / "kelmarsh"
CALIB_OUT        = REPO_ROOT / "data" / "calibration" / "sigma_calibrated.json"

# Expected dt in hours (HAI sampling is 1 second = 1/3600 h)
HAI_DT_HOURS     = 1 / 3600.0
KELMARSH_DT_HOURS = 10 / 60.0   # 10-minute intervals
KELMARSH_RATED_KW = 2050.0       # Senvion MM92 rated power (kW)
KELMARSH_MIN_KW   = 50.0         # operational threshold (above cut-in)

# Minimum number of normal-mode rows required
MIN_ROWS = 500

# Representative sensors per sector for sigma aggregation
SIGMA_SENSORS = {
    "energy": ["P4_ST_PO", "P4_HT_PO", "P4_ST_LD", "P4_HT_LD"],
    "water":  ["P3_LIT01", "P3_PIT01", "P3_FIT01"],
}


def _insufficient(param, needed, found, reason, recommendation):
    print(f"""
🔴 ДАННЫЕ НЕДОСТАТОЧНЫ

Параметр:          {param}
Что нужно:         {needed}
Что есть:          {found}
Почему не подходит: {reason}
Рекомендация:      {recommendation}
""")
    sys.exit(1)


# ---------------------------------------------------------------------------
# HAI dataset
# ---------------------------------------------------------------------------

def find_hai_csvs() -> list[Path]:
    if not HAI_PATH.exists():
        _insufficient(
            param="σ_energy (HAI)",
            needed="CSV-файлы HAI dataset с колонкой attack_flag и сенсорами мощности/давления",
            found=f"Каталог {HAI_PATH} не существует",
            reason="HAI git-репозиторий содержит только README; CSV-данные нужно скачать отдельно с Kaggle",
            recommendation="Скачать HAI Security Dataset с https://www.kaggle.com/datasets/icsdataset/hai-security-dataset "
                           "и распаковать в /Users/kuprich/Documents/diploma_repo/datasets/dataset hai /hai/"
        )
    # Support both plain .csv and gzip-compressed .csv.gz
    csvs = sorted(HAI_PATH.rglob("*.csv")) + sorted(HAI_PATH.rglob("*.csv.gz"))
    # Prefer hai-21.03 (largest, most complete version)
    preferred = [p for p in csvs if "21.03" in str(p)]
    return preferred if preferred else csvs


def calibrate_hai_sigma() -> dict:
    """
    Returns dict: {sensor_name: sigma_value} from HAI normal-mode rows.
    """
    csvs = find_hai_csvs()

    if not csvs:
        _insufficient(
            param="σ_energy (HAI)",
            needed="CSV-файлы с временными рядами сенсоров и колонкой attack_flag",
            found=f"Каталог {HAI_PATH} существует, но CSV-файлов не найдено",
            reason="HAI git-репозиторий содержит только README и .gitattributes; данные не загружены",
            recommendation="Скачать CSV с Kaggle: https://www.kaggle.com/datasets/icsdataset/hai-security-dataset"
        )

    print(f"\n[HAI] Найдено CSV: {len(csvs)}")
    for p in csvs[:5]:
        print(f"  {p.relative_to(HAI_PATH)}")
    if len(csvs) > 5:
        print(f"  ... и ещё {len(csvs)-5}")

    # Load first file to inspect columns (supports .gz)
    sample = pd.read_csv(csvs[0], nrows=3, compression="infer")
    print(f"\n[HAI] Колонки в {csvs[0].name}:")
    print(f"  {list(sample.columns)}")

    # Check for attack_flag
    attack_col = None
    for cname in sample.columns:
        if "attack" in cname.lower() or "label" in cname.lower() or "flag" in cname.lower():
            attack_col = cname
            break

    if attack_col is None:
        _insufficient(
            param="σ_energy (HAI) — фильтр нормального режима",
            needed="Колонка с маркером аномалий (attack_flag, label, или аналогичная)",
            found=f"Колонки файла {csvs[0].name}: {list(sample.columns)}",
            reason="Без маркера аномалий нельзя отфильтровать нормальный режим для калибровки σ",
            recommendation="Уточнить название колонки маркера в документации HAI и указать здесь"
        )

    print(f"\n[HAI] Колонка маркера атак: '{attack_col}'")

    # Find power/pressure sensors
    power_keywords = ["p1", "p2", "p3", "p4", "power", "mw", "generation",
                      "press", "turbine", "steam", "flow"]
    power_cols = [c for c in sample.columns
                  if any(kw in c.lower() for kw in power_keywords)
                  and c != attack_col]

    if not power_cols:
        _insufficient(
            param="σ_energy (HAI) — сенсоры мощности",
            needed="Числовые колонки, связанные с генерацией мощности или давлением пара "
                   "(ключевые слова: P1-P4, power, MW, generation, pressure, turbine)",
            found=f"Все колонки: {list(sample.columns)}",
            reason="Ни одна колонка не соответствует ключевым словам сенсоров мощности",
            recommendation="Прочитать документацию HAI (hai_dataset_technical_details.pdf) "
                           "и указать точные имена колонок для сенсоров энергетики"
        )

    print(f"\n[HAI] Найдены сенсоры мощности: {power_cols[:10]}")

    # Load all files and concatenate
    dfs = []
    for p in csvs:
        try:
            df = pd.read_csv(p, usecols=lambda c: c in power_cols + [attack_col],
                             compression="infer")
            dfs.append(df)
        except Exception as e:
            print(f"  [warn] {p.name}: {e}")
    full = pd.concat(dfs, ignore_index=True)

    # Filter normal mode
    normal = full[full[attack_col] == 0].copy()
    print(f"\n[HAI] Строк всего: {len(full)}, нормальный режим: {len(normal)}")

    if len(normal) < MIN_ROWS:
        _insufficient(
            param="σ_energy (HAI)",
            needed=f"≥ {MIN_ROWS} строк в нормальном режиме (attack_flag == 0)",
            found=f"{len(normal)} строк нормального режима",
            reason="Слишком мало точек для надёжной оценки σ",
            recommendation="Загрузить полную версию датасета HAI с Kaggle (все 3 версии)"
        )

    # Compute σ per sensor
    sigmas = {}
    for col in power_cols:
        x = normal[col].dropna().values.astype(float)
        x = x[x > 0]
        if len(x) < MIN_ROWS:
            continue
        log_returns = np.diff(np.log(x))
        log_returns = log_returns[np.isfinite(log_returns)]
        if len(log_returns) < 10:
            continue
        sigma_raw = float(np.std(log_returns))
        sigma_ann = sigma_raw / np.sqrt(HAI_DT_HOURS)
        sigmas[col] = round(sigma_ann, 6)

    if not sigmas:
        _insufficient(
            param="σ_energy (HAI)",
            needed="Числовые ненулевые значения в сенсорах мощности в нормальном режиме",
            found="Сенсоры найдены, но все значения = 0 или NaN после фильтрации",
            reason="Нулевые значения → log(0) не определён → log-returns не вычислимы",
            recommendation="Проверить единицы измерения; возможно нужно нормировать на номинальную мощность"
        )

    return sigmas


# ---------------------------------------------------------------------------
# Kelmarsh Farm wind SCADA calibration
# ---------------------------------------------------------------------------

def calibrate_kelmarsh_sigma() -> dict | None:
    """
    Calibrate σ_wind from Kelmarsh Farm SCADA data (Senvion MM92, 10-min intervals).

    Returns dict with per-turbine sigma values and median, or None if data missing.
    Source: Zenodo record 5841834 — 6 turbines, 2016-2021, ~300K 10-min readings/turbine.

    Method
    ------
    For each turbine data file:
      1. Filter to operational mode: Power > KELMARSH_MIN_KW
      2. Compute log-returns: Δlog P_t = log(P_{t+1} / P_t)
      3. σ_raw = std(Δlog P)
      4. σ_annualised = σ_raw / sqrt(dt_hours)   [dt = 10/60 h]
    Final σ_wind = median over all turbine-year files.
    """
    if not KELMARSH_PATH.exists():
        _insufficient(
            param="σ_wind (Kelmarsh Farm)",
            needed="Каталог Kelmarsh Farm SCADA с Turbine_Data_*.csv файлами",
            found=f"Каталог {KELMARSH_PATH} не существует",
            reason="Данные Kelmarsh не загружены",
            recommendation="Скачать с Zenodo record 5841834 и распаковать в "
                           "/Users/kuprich/Documents/diploma_repo/datasets/kelmarsh/"
        )

    # Find all turbine SCADA files (skip Status files)
    turbine_files = sorted(KELMARSH_PATH.rglob("Turbine_Data_Kelmarsh_*.csv"))
    if not turbine_files:
        _insufficient(
            param="σ_wind (Kelmarsh Farm)",
            needed="Файлы Turbine_Data_Kelmarsh_*.csv",
            found=f"Файлов не найдено в {KELMARSH_PATH}",
            reason="Каталог пуст или файлы в другом формате",
            recommendation="Проверить структуру архива Zenodo 5841834"
        )

    print(f"\n[Kelmarsh] Найдено файлов: {len(turbine_files)}")
    print(f"[Kelmarsh] Турбина: Senvion MM92, P_rated = {KELMARSH_RATED_KW:.0f} kW, dt = 10 мин")

    # Kelmarsh CSVs have 9 comment lines before the header
    # Header row starts with '# Date and time'
    per_file_sigmas: list[float] = []
    errors = 0

    for p in turbine_files:
        try:
            df = pd.read_csv(p, skiprows=9)
            # Strip leading '# ' from first column name
            df.columns = [c.lstrip("#").strip() for c in df.columns]

            if "Power (kW)" not in df.columns:
                continue

            power = df["Power (kW)"].dropna().values.astype(float)
            power = power[power > KELMARSH_MIN_KW]          # operational mode only

            if len(power) < MIN_ROWS:
                continue

            log_returns = np.diff(np.log(power))
            log_returns = log_returns[np.isfinite(log_returns)]

            if len(log_returns) < 10:
                continue

            sigma_ann = float(np.std(log_returns)) / np.sqrt(KELMARSH_DT_HOURS)
            per_file_sigmas.append(sigma_ann)

        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"  [warn] {p.name}: {e}")

    if not per_file_sigmas:
        _insufficient(
            param="σ_wind (Kelmarsh Farm)",
            needed="Числовые значения мощности > 0 в нормальном режиме",
            found="Файлы найдены, но все значения Power = NaN или < min_kW",
            reason="Данные содержат только нерабочие периоды",
            recommendation="Проверить фильтр KELMARSH_MIN_KW или загрузить другой год"
        )

    sigma_median = float(np.median(per_file_sigmas))
    sigma_mean   = float(np.mean(per_file_sigmas))
    sigma_std    = float(np.std(per_file_sigmas))

    print(f"[Kelmarsh] Откалиброваны σ из {len(per_file_sigmas)} файлов")
    print(f"  σ_wind: min={min(per_file_sigmas):.4f}  max={max(per_file_sigmas):.4f}"
          f"  mean={sigma_mean:.4f}  median={sigma_median:.6f}")

    return {
        "sigma_wind_median":      round(sigma_median, 6),
        "sigma_wind_mean":        round(sigma_mean,   6),
        "sigma_wind_std":         round(sigma_std,    6),
        "n_files":                len(per_file_sigmas),
        "rated_power_kw":         KELMARSH_RATED_KW,
        "min_operational_kw":     KELMARSH_MIN_KW,
        "per_file_sigmas":        [round(s, 6) for s in per_file_sigmas],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 60)
    print("Calibrate σ (volatility) from HAI + Kelmarsh Farm")
    print("=" * 60)

    # --- HAI ---
    print("\n[1/2] HAI Dataset (ICS energy/steam turbine)...")
    hai_sigmas = calibrate_hai_sigma()

    print("\n  HAI σ estimates (key sector sensors):")
    print(f"  {'Sensor':<20} {'σ (per sqrt-hour)'}")
    print("  " + "-" * 40)
    for sector, sensors in SIGMA_SENSORS.items():
        for s in sensors:
            if s in hai_sigmas:
                print(f"  {s:<20} {hai_sigmas[s]:.6f}  [{sector}]")

    # --- Kelmarsh wind ---
    print("\n[2/2] Kelmarsh Farm SCADA (wind energy)...")
    kelmarsh_result = calibrate_kelmarsh_sigma()

    # --- Sector-level aggregation ---
    # For ICS energy: median of key power-output sensors (P4_ST_PO, P4_HT_PO)
    # For water: median of P3 process sensors
    # For wind: Kelmarsh median σ
    sector_sigmas: dict[str, float] = {}
    sector_details: dict[str, dict] = {}

    for sector, sensors in SIGMA_SENSORS.items():
        vals = [hai_sigmas[s] for s in sensors if s in hai_sigmas]
        if vals:
            med = float(np.median(vals))
            sector_sigmas[sector] = round(med, 6)
            sector_details[sector] = {
                "sigma_median": round(med, 6),
                "source": "HAI 21.03",
                "sensors": {s: round(hai_sigmas[s], 6) for s in sensors if s in hai_sigmas},
            }

    # Wind sigma supplements energy sector
    if kelmarsh_result:
        sigma_wind = kelmarsh_result["sigma_wind_median"]
        # Combine ICS energy sigma with wind sigma: use min (ICS is more controlled)
        ics_sigma = sector_sigmas.get("energy", sigma_wind)
        combined = float(np.median([ics_sigma, sigma_wind]))
        sector_sigmas["energy_wind"] = round(sigma_wind, 6)
        sector_details["energy_wind"] = {
            "sigma_median": round(sigma_wind, 6),
            "source": "Kelmarsh Farm SCADA (Senvion MM92)",
            **kelmarsh_result,
        }

    print("\n  Sector-level σ (median of representative sensors):")
    for sec, s in sector_sigmas.items():
        print(f"  σ_{sec:<16} = {s:.6f} per sqrt-hour")

    # --- Save ---
    result = {
        "method": "log_returns_std",
        "formula": "sigma = std(delta_log_x) / sqrt(dt_hours)",
        "sector_sigmas": sector_sigmas,
        "hai": {
            "source": str(HAI_PATH),
            "dt_hours": HAI_DT_HOURS,
            "filter": "attack_flag == 0",
            "sigmas": hai_sigmas,
        },
        "kelmarsh": {
            "source": str(KELMARSH_PATH),
            "dt_hours": KELMARSH_DT_HOURS,
            "turbine": "Senvion MM92",
            **(kelmarsh_result or {"status": "not available"}),
        },
        "sector_details": sector_details,
    }

    CALIB_OUT.parent.mkdir(parents=True, exist_ok=True)
    CALIB_OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\n[save] {CALIB_OUT}")


if __name__ == "__main__":
    main()
