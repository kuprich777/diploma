"""
calibrate_capacity.py
=====================
Calibrate capacity thresholds C_j from HAI Dataset.

Method
------
For each power sensor in normal operating mode (attack_flag == 0):
    C_j = quantile(x_j, 0.95)

Validation: check that max(x_j) during attacks exceeds C_j (confirms
the threshold is meaningful for anomaly detection).

Output
------
    data/calibration/capacity_thresholds.json

Protocol: stops with 🔴 message if data is insufficient.
"""

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
REPO_ROOT       = Path(__file__).resolve().parent.parent
DATASETS_ROOT   = Path(os.environ.get(
    "DATASETS_ROOT", "/Users/kuprich/Documents/diploma_repo/datasets"
))
HAI_PATH        = DATASETS_ROOT / "dataset hai " / "hai"
ROAD_SAFETY_DIR = DATASETS_ROOT / "Road safety open data"
CALIB_OUT       = REPO_ROOT / "data" / "calibration" / "capacity_thresholds.json"

QUANTILE        = 0.95
MIN_ROWS        = 500

# Sensors to use per sector (subset of power/level sensors, excluding valves/flags)
POWER_SENSORS = {
    "energy": ["P2_CO_rpm", "P2_VT01", "P4_ST_LD", "P4_HT_LD", "P4_ST_PO", "P4_HT_PO"],
    "water":  ["P3_LIT01", "P3_PIT01", "P3_FIT01"],
}

# HAI nominal values — derived from max(all_data[sensor]) across full HAI 21.03 dataset.
# These serve as per-sensor capacity denominators so all x_j are normalised to [0, 1].
# Values verified against HAI 21.03 full dataset (1 323 608 rows, all conditions).
HAI_NOMINAL: dict[str, float] = {
    # --- Energy process (P2: rotor kit, P4: HIL steam + hydro) ---
    "P2_CO_rpm":  54822.0,   # turbine shaft speed, rpm
    "P2_VT01":       13.1,   # vibration voltage, V
    "P4_ST_LD":     499.6,   # HIL steam turbine load,  MW (simulated)
    "P4_HT_LD":      83.1,   # HIL hydro turbine load,  MW (simulated)
    "P4_ST_PO":     498.9,   # HIL steam power output,  MW (simulated)
    "P4_HT_PO":      89.6,   # HIL hydro power output,  MW (simulated)
    # --- Water treatment process (P3: pumped reservoir) ---
    "P3_LIT01":   20489.0,   # water level, mm
    "P3_PIT01":    7090.0,   # pressure, mbar
    "P3_FIT01":    7761.0,   # flow rate, L/min
}

# DfT vehicle_type codes for Heavy Goods Vehicles
HGV_TYPES = [20, 21]  # 20=Goods 3.5-7.5t, 21=Goods ≥7.5t


def _insufficient(param, needed, found, reason, recommendation):
    print(f"""
🔴 ДАННЫЕ НЕДОСТАТОЧНЫ

Параметр:           {param}
Что нужно:          {needed}
Что есть:           {found}
Почему не подходит: {reason}
Рекомендация:       {recommendation}
""")
    sys.exit(1)


def load_hai_full() -> pd.DataFrame:
    """Load all HAI 21.03 CSV/gz files, return combined DataFrame."""
    if not HAI_PATH.exists():
        _insufficient(
            param="C_j (HAI)",
            needed="Каталог HAI dataset с CSV/gz файлами",
            found=f"Каталог {HAI_PATH} не существует",
            reason="HAI данные не загружены",
            recommendation="Скачать CSV с https://www.kaggle.com/datasets/icsdataset/hai-security-dataset"
        )

    csvs = sorted((HAI_PATH / "hai-21.03").glob("*.csv.gz")) + \
           sorted((HAI_PATH / "hai-21.03").glob("*.csv"))

    if not csvs:
        _insufficient(
            param="C_j (HAI)",
            needed="CSV/gz файлы в hai-21.03/",
            found=f"Файлов нет в {HAI_PATH / 'hai-21.03'}",
            reason="Каталог пуст",
            recommendation="Проверить загрузку HAI 21.03 с Kaggle"
        )

    dfs = []
    for p in csvs:
        df = pd.read_csv(p, compression="infer")
        dfs.append(df)
    combined = pd.concat(dfs, ignore_index=True)

    # Verify attack column
    if "attack" not in combined.columns:
        candidates = [c for c in combined.columns if "attack" in c.lower() or "label" in c.lower()]
        _insufficient(
            param="C_j — фильтр нормального режима",
            needed="Колонка 'attack' (0=normal, >0=attack)",
            found=f"Колонки: {list(combined.columns)[:15]}...",
            reason="Колонка 'attack' не найдена",
            recommendation=f"Кандидаты: {candidates}"
        )
    return combined


def calibrate_threshold(series: pd.Series, nominal: float | None = None,
                        q: float = QUANTILE) -> dict | None:
    """
    Compute capacity threshold from normal-mode time series.

    If `nominal` is provided, the series is normalised to [0, 1] before
    computing statistics: x_norm = x / nominal.  All returned C values are
    then in the normalised [0, 1] space, ready for the SDE model.

    If `nominal` is None, raw physical-unit values are returned (legacy mode).
    """
    vals = series.dropna().values.astype(float)
    finite = vals[np.isfinite(vals)]
    if len(finite) < 50:
        return None

    if nominal is not None and nominal > 0:
        finite = finite / nominal

    return {
        "C_q95":      round(float(np.quantile(finite, q)),               6),
        "C_mean2std": round(float(np.mean(finite) + 2 * np.std(finite)), 6),
        "mean":       round(float(np.mean(finite)),  6),
        "std":        round(float(np.std(finite)),   6),
        "min":        round(float(finite.min()),     6),
        "max":        round(float(finite.max()),     6),
        "n_normal":   len(finite),
        "nominal":    nominal,
        "normalised": nominal is not None,
    }


# ---------------------------------------------------------------------------
# Transport sector: C calibration from DfT Road Safety Data (HGV)
# ---------------------------------------------------------------------------

def calibrate_transport_C_hgv() -> dict | None:
    """
    Calibrate C_transport using UK DfT Road Safety Open Data (HGV collisions).

    Method
    ------
    1. Filter vehicle records by HGV vehicle_type (codes 20 and 21).
    2. Join with collision records to obtain dates.
    3. Aggregate HGV-involved collisions into monthly counts.
    4. Normalise counts to [0, 1]: x_t = monthly_count / max_monthly_count.
    5. C_transport = quantile(x_t, 0.95).

    Rationale: HGV collision rate is a positive-exposure proxy for transport
    network stress — higher HGV volumes produce higher incident rates.
    The q95 threshold marks "high but historically normal" transport load.

    Returns None (with 🔴 message) if required CSV files are missing.
    """
    veh_file  = ROAD_SAFETY_DIR / "dft-road-casualty-statistics-vehicle-last-5-years.csv"
    coll_file = ROAD_SAFETY_DIR / "dft-road-casualty-statistics-collision-last-5-years.csv"

    for f in [veh_file, coll_file]:
        if not f.exists():
            _insufficient(
                param="C_transport (HGV)",
                needed=f"Файл {f.name}",
                found=f"Не найден: {f}",
                reason="DfT Road Safety Open Data не загружены",
                recommendation="Скачать с https://www.data.gov.uk/dataset/"
                               "road-accidents-safety-data"
            )

    print(f"\n[Transport] Загружаем DfT Road Safety данные из {ROAD_SAFETY_DIR.name}/...")

    veh = pd.read_csv(veh_file, usecols=["collision_index", "vehicle_type"])
    hgv = veh[veh["vehicle_type"].isin(HGV_TYPES)][["collision_index"]].drop_duplicates()
    print(f"  HGV collision IDs: {len(hgv):,}  (vehicle_type ∈ {HGV_TYPES})")

    if len(hgv) < 100:
        _insufficient(
            param="C_transport (HGV)",
            needed="≥ 100 HGV-involved collisions",
            found=f"{len(hgv)} строк",
            reason="Слишком мало данных для оценки ёмкости транспортной сети",
            recommendation="Проверить фильтр HGV_TYPES и содержимое vehicle-файла"
        )

    coll = pd.read_csv(coll_file, usecols=["collision_index", "date"])
    coll["date"] = pd.to_datetime(coll["date"], dayfirst=True)

    merged = hgv.merge(coll, on="collision_index")
    merged["year_month"] = merged["date"].dt.to_period("M")
    monthly = merged.groupby("year_month").size().sort_index()

    n_months    = len(monthly)
    max_monthly = float(monthly.max())
    monthly_norm = monthly / max_monthly              # normalise to [0, 1]
    C_transport  = float(np.quantile(monthly_norm, QUANTILE))

    print(f"  Временной охват: {monthly.index[0]} — {monthly.index[-1]} ({n_months} месяцев)")
    print(f"  Ежемесячные HGV аварии: min={monthly.min()}  max={int(max_monthly)}  "
          f"mean={monthly.mean():.1f}")
    print(f"  C_transport (q{int(QUANTILE*100)} нормированных ежемесячных частот) = "
          f"{C_transport:.4f}")

    return {
        "C": round(C_transport, 6),
        "method": f"q{int(QUANTILE*100)} of normalised monthly HGV collision counts",
        "source": "DfT Road Safety Open Data (last 5 years)",
        "hgv_vehicle_types": HGV_TYPES,
        "n_months": n_months,
        "n_hgv_collisions": len(merged),
        "max_monthly_count": int(max_monthly),
        "monthly_mean": round(float(monthly.mean()), 1),
        "normalisation": "monthly_count / max_monthly_count",
    }


def main() -> None:
    print("=" * 60)
    print("Calibrate capacity thresholds C from HAI Dataset")
    print("Normalisation: sensor_value / HAI_NOMINAL  → x ∈ [0, 1]")
    print("=" * 60)

    combined = load_hai_full()
    normal = combined[combined["attack"] == 0]
    attack = combined[combined["attack"] >  0]

    print(f"\nRows total: {len(combined):,}  |  normal: {len(normal):,}  |  attack: {len(attack):,}")

    if len(normal) < MIN_ROWS:
        _insufficient(
            param="C_j",
            needed=f"≥ {MIN_ROWS} строк нормального режима",
            found=f"{len(normal)} строк",
            reason="Недостаточно данных",
            recommendation="Загрузить все файлы HAI 21.03"
        )

    all_cols = list(combined.columns)

    # ---- Per-sector calibration (normalised) ----
    sectors_out = {}
    validation  = {}

    for sector, sensor_list in POWER_SENSORS.items():
        present = [s for s in sensor_list if s in all_cols]
        missing = [s for s in sensor_list if s not in all_cols]
        if missing:
            print(f"\n[{sector}] Sensors NOT found: {missing}")
        if not present:
            print(f"\n[{sector}] ⚠ No sensors available — skipping C_{sector}")
            continue

        print(f"\n[{sector}] Sensors: {present}")
        thresholds = {}
        valid_checks = {}

        for s in present:
            nominal = HAI_NOMINAL.get(s)   # None → raw units (legacy fallback)
            stats = calibrate_threshold(normal[s], nominal=nominal, q=QUANTILE)
            if stats is None:
                print(f"  {s}: too few non-null values")
                continue
            thresholds[s] = stats

            # Validation in normalised space: do attack values exceed C_norm?
            C = stats["C_q95"]
            if s in attack.columns:
                atk_vals = attack[s].dropna().values.astype(float)
                if nominal:
                    atk_vals = atk_vals / nominal
                if len(atk_vals) > 0:
                    pct_exceed = float(np.mean(atk_vals > C)) * 100
                    valid_checks[s] = {
                        "C_q95":               C,
                        "pct_attack_exceeds_C": round(pct_exceed, 1),
                        "max_attack_norm":      round(float(atk_vals.max()), 6),
                    }

            print(f"  {s:<20}  nominal={nominal or '—':>8}  "
                  f"C_q95={stats['C_q95']:.4f}  mean={stats['mean']:.4f}  "
                  f"std={stats['std']:.4f}  n={stats['n_normal']}")

        # Aggregate: median of normalised per-sensor C values
        c_values = [thresholds[s]["C_q95"] for s in thresholds]
        if c_values:
            C_sector = float(np.median(c_values))
            sectors_out[sector] = {
                "C":          round(C_sector, 6),
                "method":     f"median of per-sensor normalised q{int(QUANTILE*100)} thresholds",
                "normalised": True,
                "sensors_used": list(thresholds.keys()),
                "per_sensor": thresholds,
            }
            print(f"\n  → C_{sector} (normalised) = {C_sector:.4f}"
                  f"  (median over {len(c_values)} sensors)")

        if valid_checks:
            validation[sector] = valid_checks
            for s, vc in valid_checks.items():
                print(f"  Validation {s}: {vc['pct_attack_exceeds_C']:.1f}% of attack rows "
                      f"exceed C={vc['C_q95']:.4f}")

    # ---- Transport sector: DfT Road Safety (HGV) ----
    transport_result = calibrate_transport_C_hgv()
    if transport_result:
        sectors_out["transport"] = transport_result
    else:
        sectors_out["transport"] = {
            "C": None,
            "status": "pending",
            "reason": "Road Safety data unavailable",
        }

    # Summary
    print("\n" + "=" * 60)
    print("CAPACITY THRESHOLDS SUMMARY (normalised [0, 1])")
    print("=" * 60)
    for sec, v in sectors_out.items():
        C_val = v.get("C")
        src   = v.get("source", v.get("method", "—"))
        if C_val is not None:
            print(f"  C_{sec:<12} = {C_val:.4f}   [{src[:60]}]")
        else:
            print(f"  C_{sec:<12} = PENDING")

    # Save
    result = {
        "method":     f"normalised q{int(QUANTILE*100)} thresholds",
        "note":       "All C values in [0, 1] space (sensor / nominal or monthly_count / max)",
        "sources": {
            "energy": "HAI 21.03 (P2+P4 sensors, attack_flag == 0, normalised by HAI_NOMINAL)",
            "water":  "HAI 21.03 (P3 sensors, attack_flag == 0, normalised by HAI_NOMINAL)",
            "transport": "DfT Road Safety Open Data — monthly HGV-involved collision counts",
        },
        "sectors": sectors_out,
        "validation_vs_attacks": validation,
    }
    CALIB_OUT.parent.mkdir(parents=True, exist_ok=True)
    CALIB_OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\n[save] {CALIB_OUT}")


if __name__ == "__main__":
    main()
