"""
Этап 2 — Калибровка σ (стохастических параметров SDE) из SCADA данных.

Методология:
  1. Для каждого сектора выбираем канонический операционный сигнал.
  2. Нормализуем к [0, 1] по физической/номинальной шкале (не min-max).
  3. Агрегируем к почасовому разрешению (per-hour).
  4. Строим почасовые приращения Δx = x_{t+1h} - x_{t}.
  5. σ_sector = std(Δx) (per-hour units; может трактоваться как σ на 1 шаг модели,
     если dt модели = 1 час).
  6. Bootstrap 95% CI (1000 resamples).

Источники:
  energy:    Kelmarsh Wind Farm SCADA (6 турбин × 6 лет, Senvion MM92, rated=2050 kW)
  water:     HAI 21.03 P3_LIT01 (level transmitter, pumped-storage water treatment,
             nominal=20489), attack_flag == 0
  transport: DfT Road Safety Open Data (last 5 years, daily collision counts;
             per-day σ, далее конвертируется к per-hour через σ_hour = σ_day/√24)

Выход: data/calibration/sigma_empirical_v1.json
"""
from __future__ import annotations

import gzip
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATASETS_ROOT = Path("/Users/kuprich/Documents/diploma_repo/datasets")
KELMARSH_ROOT = DATASETS_ROOT / "kelmarsh"
HAI_21_03 = DATASETS_ROOT / "dataset hai " / "hai" / "hai-21.03"
ROAD_SAFETY_CSV = DATASETS_ROOT / "Road safety open data" / "dft-road-casualty-statistics-collision-last-5-years.csv"
OUTPUT_JSON = ROOT / "data/calibration/sigma_empirical_v1.json"

KELMARSH_RATED_POWER_KW = 2050.0
HAI_P3_LIT01_NOMINAL = 20489.0
HEADER_ROW_KELMARSH = 9  # skip first 9 comment rows, row 10 (0-indexed 9) is header
KELMARSH_TIME_COL = "# Date and time"
KELMARSH_POWER_COL = "Power (kW)"

N_BOOTSTRAP = 1000
RNG = np.random.default_rng(42)


def bootstrap_ci(values: np.ndarray, stat_func, n_resamples: int = N_BOOTSTRAP,
                 ci: float = 0.95) -> tuple[float, float]:
    boots = np.empty(n_resamples)
    n = len(values)
    for i in range(n_resamples):
        sample = RNG.choice(values, size=n, replace=True)
        boots[i] = stat_func(sample)
    lo = float(np.quantile(boots, (1 - ci) / 2))
    hi = float(np.quantile(boots, 1 - (1 - ci) / 2))
    return lo, hi


def sigma_from_increments(x_norm: np.ndarray) -> float:
    dx = np.diff(x_norm)
    dx = dx[np.isfinite(dx)]
    return float(np.std(dx, ddof=1))


# ---------------------------------------------------------------------------
# ENERGY — Kelmarsh Wind Farm SCADA
# ---------------------------------------------------------------------------
def process_kelmarsh_file(path: Path) -> dict[str, Any] | None:
    try:
        df = pd.read_csv(
            path,
            skiprows=HEADER_ROW_KELMARSH,
            low_memory=False,
            usecols=lambda c: c in (KELMARSH_TIME_COL, KELMARSH_POWER_COL),
        )
    except Exception as e:
        return {"error": f"read failed: {e}", "path": str(path)}

    if KELMARSH_POWER_COL not in df.columns or KELMARSH_TIME_COL not in df.columns:
        return {"error": "columns missing", "path": str(path)}

    df[KELMARSH_TIME_COL] = pd.to_datetime(df[KELMARSH_TIME_COL], errors="coerce")
    df = df.dropna(subset=[KELMARSH_TIME_COL, KELMARSH_POWER_COL])
    df = df.set_index(KELMARSH_TIME_COL).sort_index()

    # Clip negative (grid consumption) to 0 — turbine consumes power at idle
    df[KELMARSH_POWER_COL] = df[KELMARSH_POWER_COL].clip(lower=0.0)
    # Aggregate to hourly mean
    hourly = df[KELMARSH_POWER_COL].resample("1h").mean().dropna()
    if len(hourly) < 24:
        return None
    # Normalize to [0, 1] by rated power; clip
    x = np.clip(hourly.values / KELMARSH_RATED_POWER_KW, 0.0, 1.0)
    sigma = sigma_from_increments(x)
    return {
        "file": path.name,
        "n_hourly_samples": int(len(x)),
        "mean_norm_power": float(np.mean(x)),
        "sigma_per_hour": sigma,
    }


def calibrate_energy_kelmarsh() -> dict[str, Any]:
    files = sorted(KELMARSH_ROOT.rglob("Turbine_Data_*.csv"))
    per_file = []
    sigmas = []
    for fp in files:
        result = process_kelmarsh_file(fp)
        if result is None or "error" in result:
            continue
        per_file.append(result)
        sigmas.append(result["sigma_per_hour"])
    sigmas_arr = np.array(sigmas)
    ci_lo, ci_hi = bootstrap_ci(sigmas_arr, np.median)
    return {
        "source": "Kelmarsh Wind Farm SCADA 2016-2021 (Senvion MM92, 2050 kW rated)",
        "signal": "Power (kW) / 2050",
        "aggregation": "hourly mean from 10-min raw",
        "n_files": len(per_file),
        "n_hourly_samples_total": int(sum(r["n_hourly_samples"] for r in per_file)),
        "sigma_per_hour_median": float(np.median(sigmas_arr)),
        "sigma_per_hour_mean": float(np.mean(sigmas_arr)),
        "sigma_per_hour_std_across_files": float(np.std(sigmas_arr, ddof=1)),
        "ci_95_median": {"lo": ci_lo, "hi": ci_hi},
        "per_file": per_file[:10],  # first 10 for audit
        "n_files_reported": len(per_file),
    }


# ---------------------------------------------------------------------------
# WATER — HAI 21.03 P3_LIT01
# ---------------------------------------------------------------------------
def process_hai_file(path: Path) -> dict[str, Any]:
    usecols = ["time", "P3_LIT01", "attack", "attack_P3"]
    with gzip.open(path, "rt") as f:
        df = pd.read_csv(f, usecols=lambda c: c in usecols, low_memory=False)
    # Filter attacks
    if "attack_P3" in df.columns:
        df = df[df["attack_P3"] == 0].copy()
    elif "attack" in df.columns:
        df = df[df["attack"] == 0].copy()
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df = df.dropna(subset=["time", "P3_LIT01"]).set_index("time").sort_index()
    # 1-sec raw, aggregate to hourly
    hourly = df["P3_LIT01"].resample("1h").mean().dropna()
    x = np.clip(hourly.values / HAI_P3_LIT01_NOMINAL, 0.0, 1.0)
    if len(x) < 24:
        return {"file": path.name, "skipped": True}
    return {
        "file": path.name,
        "n_hourly_samples": int(len(x)),
        "mean_norm_level": float(np.mean(x)),
        "sigma_per_hour": sigma_from_increments(x),
    }


def calibrate_water_hai() -> dict[str, Any]:
    files = sorted(HAI_21_03.glob("train*.csv.gz"))
    per_file = []
    sigmas = []
    for fp in files:
        result = process_hai_file(fp)
        if result.get("skipped"):
            continue
        per_file.append(result)
        sigmas.append(result["sigma_per_hour"])
    sigmas_arr = np.array(sigmas)
    ci_lo, ci_hi = bootstrap_ci(sigmas_arr, np.median) if len(sigmas_arr) >= 2 else (float('nan'), float('nan'))
    return {
        "source": "HAI 21.03 P3_LIT01 (water-treatment level transmitter, pumped-storage), attack=0",
        "signal": "P3_LIT01 / 20489 (nominal)",
        "aggregation": "hourly mean from 1-sec raw",
        "n_files": len(per_file),
        "n_hourly_samples_total": int(sum(r["n_hourly_samples"] for r in per_file)),
        "sigma_per_hour_median": float(np.median(sigmas_arr)),
        "sigma_per_hour_mean": float(np.mean(sigmas_arr)),
        "sigma_per_hour_std_across_files": float(np.std(sigmas_arr, ddof=1)) if len(sigmas_arr) >= 2 else float("nan"),
        "ci_95_median": {"lo": ci_lo, "hi": ci_hi},
        "per_file": per_file,
    }


# ---------------------------------------------------------------------------
# TRANSPORT — DfT Road Safety
# ---------------------------------------------------------------------------
def calibrate_transport_dft() -> dict[str, Any]:
    usecols = ["collision_index", "collision_year", "date"]
    # date column may be named differently; inspect
    df_head = pd.read_csv(ROAD_SAFETY_CSV, nrows=1)
    date_col = next((c for c in df_head.columns if "date" in c.lower()), None)
    cols_to_use = [c for c in ["collision_index", date_col, "collision_year"] if c and c in df_head.columns]
    df = pd.read_csv(ROAD_SAFETY_CSV, usecols=cols_to_use, low_memory=False)
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce", dayfirst=True)
    df = df.dropna(subset=[date_col])
    daily = df.groupby(df[date_col].dt.date).size().sort_index()
    # Normalize by max daily count
    max_daily = int(daily.max())
    x = daily.values / max_daily
    sigma_day = sigma_from_increments(x)
    # Brownian scaling to per-hour: σ_hour = σ_day / √24
    sigma_hour = sigma_day / math.sqrt(24.0)
    # Bootstrap CI on daily increments
    dx = np.diff(x)
    ci_lo, ci_hi = bootstrap_ci(dx, lambda a: np.std(a, ddof=1))
    return {
        "source": "DfT Road Safety Open Data — dft-road-casualty-statistics-collision-last-5-years.csv",
        "signal": "daily collision count / max_daily (5-year window)",
        "aggregation": "daily counts (already one observation per day)",
        "n_daily_samples": int(len(x)),
        "max_daily_count": max_daily,
        "mean_daily_count": float(daily.mean()),
        "sigma_per_day": sigma_day,
        "sigma_per_hour_brownian_rescaled": sigma_hour,
        "ci_95_sigma_day": {"lo": ci_lo, "hi": ci_hi},
        "ci_95_sigma_hour": {"lo": ci_lo / math.sqrt(24.0), "hi": ci_hi / math.sqrt(24.0)},
        "rescaling_note": "σ_hour = σ_day / √24 under Brownian scaling assumption",
    }


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main() -> None:
    print("Stage 2: calibrating σ per sector from SCADA...")
    print(f"  energy: Kelmarsh ({KELMARSH_ROOT})")
    energy = calibrate_energy_kelmarsh()
    print(f"    σ_energy (per hour, median) = {energy['sigma_per_hour_median']:.5f}"
          f"  CI95 = [{energy['ci_95_median']['lo']:.5f}, {energy['ci_95_median']['hi']:.5f}]"
          f"  n_files = {energy['n_files']}")

    print(f"  water: HAI 21.03 ({HAI_21_03})")
    water = calibrate_water_hai()
    print(f"    σ_water (per hour, median) = {water['sigma_per_hour_median']:.5f}"
          f"  CI95 = [{water['ci_95_median']['lo']:.5f}, {water['ci_95_median']['hi']:.5f}]"
          f"  n_files = {water['n_files']}")

    print(f"  transport: DfT Road Safety")
    transport = calibrate_transport_dft()
    print(f"    σ_transport (per day) = {transport['sigma_per_day']:.5f}"
          f"  → per hour (√24 rescaled) = {transport['sigma_per_hour_brownian_rescaled']:.5f}"
          f"  n_days = {transport['n_daily_samples']}")

    output = {
        "schema_version": "1.0",
        "time_convention": "σ values expressed per 1 hour (assume model step dt=1 ⇔ 1 hour real time)",
        "methodology": {
            "description": "Normalize signal to [0,1] by physical/nominal scale; aggregate to hourly; compute std of hourly increments.",
            "aggregation": "hourly mean",
            "normalization": "physical/nominal scale (not min-max)",
            "bootstrap_resamples": N_BOOTSTRAP,
        },
        "sectors": {
            "energy": {
                "sigma_per_hour": energy["sigma_per_hour_median"],
                "source_summary": "Kelmarsh (wind SCADA)",
                "details": energy,
            },
            "water": {
                "sigma_per_hour": water["sigma_per_hour_median"],
                "source_summary": "HAI 21.03 P3_LIT01",
                "details": water,
            },
            "transport": {
                "sigma_per_hour": transport["sigma_per_hour_brownian_rescaled"],
                "source_summary": "DfT Road Safety (daily→hourly Brownian rescaled)",
                "details": transport,
            },
        },
        "sigma_vector_per_hour": {
            "energy": energy["sigma_per_hour_median"],
            "water": water["sigma_per_hour_median"],
            "transport": transport["sigma_per_hour_brownian_rescaled"],
        },
    }

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_JSON.open("w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {OUTPUT_JSON.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
