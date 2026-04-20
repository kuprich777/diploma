"""Калибровка A_WIOD^v4 по METHODOLOGY §7 (архитектура B1: одна эталонная страна).

§7.1 — базовый расчёт (Miller & Blair 2009):
    a_ij = X_ij / GO_j
    a_ii ← 0
    (БЕЗ нормировки на a_jj^raw — см. MIGRATION_COMPLETE.md; империческая проверка
    показала, что межстрановой инвариант на 3-секторной агрегации WIOD 2014 не
    существует, что делает шаг нормировки содержательно неоправданным.)

§7.2 — эталонная страна:
    A_WIOD^v4 = A_DEU (архитектурное решение B1, 2026-04-19)

§7.3 — spectral radius normalization:
    A_norm = A_raw · (ρ_target / ρ(A_raw))   если ρ > ρ_target = 0.95
    ε_ρ = 1e-6 — защита от вырожденной A=0 (no-fabrication gate).

Выходы:
    data/calibration/A_WIOD_v4.json        — основная матрица для экспериментов
    data/calibration/A_WIOD_v4_meta.json   — страновые A_c (DEU + 5 остальных) для Серии 9
    data/calibration/sector_weights_v1.json — w_j = GO_j^DEU / Σ GO_k^DEU (§5.2, §5.3)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

try:
    import pandas as pd
except ImportError:
    print("pip install openpyxl pandas")
    sys.exit(1)

REPO_ROOT = Path(__file__).resolve().parent.parent
WIOD_DIR = REPO_ROOT / "matrix_doc" / "sources" / "NIOTS"
CALIB_A = REPO_ROOT / "data" / "calibration" / "A_WIOD_v4.json"
CALIB_META = REPO_ROOT / "data" / "calibration" / "A_WIOD_v4_meta.json"
WEIGHTS_OUT = REPO_ROOT / "data" / "calibration" / "sector_weights_v1.json"

SECTORS_OUT = ["energy", "water", "transport"]
REFERENCE_COUNTRY = "DEU"
ROBUSTNESS_COUNTRIES = ["USA", "GBR", "FRA", "JPN", "CAN"]
YEAR = 2014
SPECTRAL_TARGET = 0.95
SPECTRAL_EPS = 1e-6

SECTOR_CODES: dict[str, list[str]] = {
    "energy": ["D35"],
    "water": ["E36", "E37-E39"],
    "transport": ["H49", "H50", "H51", "H52", "H53"],
}


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


def extract_xij_goj(country: str) -> tuple[np.ndarray, np.ndarray]:
    """Возвращает (X_3x3, GO_3) для страны: промежуточные потоки + валовый выпуск."""
    path = WIOD_DIR / f"{country}_NIOT_nov16.xlsx"
    if not path.exists():
        _fail(
            f"A_WIOD^v4 ({country})",
            f"Файл {country}_NIOT_nov16.xlsx",
            f"Не найден: {path}",
            "Файл отсутствует",
            "Скачать с http://www.wiod.org/database/niots16",
        )

    print(f"  Loading {path.name} ...")
    df = pd.ExcelFile(path, engine="openpyxl").parse("National IO-tables", header=None)

    col_headers = [str(v).strip() for v in df.iloc[0].tolist()]
    code_to_col = {c: i for i, c in enumerate(col_headers)}
    data = df.iloc[1:].copy()
    data.columns = range(len(data.columns))
    data = data.reset_index(drop=True)
    data_y = data[data.iloc[:, 0] == YEAR].copy()

    go_row = data_y[(data_y.iloc[:, 1] == "GO") & (data_y.iloc[:, 3] == "TOT")]
    dom = data_y[data_y.iloc[:, 3] == "Domestic"].copy()
    dom_code_to_row: dict[str, pd.Series] = {}
    for _, row in dom.iterrows():
        dom_code_to_row[str(row.iloc[1]).strip()] = row

    n = len(SECTORS_OUT)
    X = np.zeros((n, n))
    GO = np.zeros(n)

    for j_sec, j_name in enumerate(SECTORS_OUT):
        j_codes = SECTOR_CODES[j_name]
        q_j = 0.0
        for jc in j_codes:
            jcol = code_to_col.get(jc)
            if jcol is not None and not go_row.empty:
                try:
                    q_j += float(go_row.iloc[0, jcol])
                except (TypeError, ValueError):
                    pass
        GO[j_sec] = q_j

        for i_sec, i_name in enumerate(SECTORS_OUT):
            i_codes = SECTOR_CODES[i_name]
            x_ij = 0.0
            for ic in i_codes:
                row_data = dom_code_to_row.get(ic)
                if row_data is None:
                    continue
                for jc in j_codes:
                    jcol = code_to_col.get(jc)
                    if jcol is not None:
                        try:
                            x_ij += float(row_data.iloc[jcol])
                        except (TypeError, ValueError):
                            pass
            X[i_sec, j_sec] = x_ij

    return X, GO


def compute_A_leontief(X: np.ndarray, GO: np.ndarray, country: str) -> np.ndarray:
    """§7.1: a_ij = X_ij / GO_j, a_ii ← 0 (Miller & Blair 2009, без a_jj-нормировки)."""
    if (GO <= 0).any():
        _fail(
            f"A_WIOD^v4 ({country})",
            "GO_j > 0 для всех 3 секторов",
            f"GO = {GO.tolist()}",
            "Сектор с GO=0 делает a_ij неопределённым (пробел в NIOT)",
            "Страна должна быть исключена из кандидатов",
        )
    A = X / GO[np.newaxis, :]
    np.fill_diagonal(A, 0.0)
    return A


def apply_spectral_normalization(A: np.ndarray) -> tuple[np.ndarray, float, float]:
    """§7.3: нормировка к ρ ≤ ρ_target, защита от вырожденной A=0."""
    rho_raw = float(np.max(np.abs(np.linalg.eigvals(A))))
    if rho_raw < SPECTRAL_EPS:
        _fail(
            "A_WIOD^v4 spectral radius",
            f"ρ(A_raw) > ε_ρ = {SPECTRAL_EPS}",
            f"ρ(A_raw) = {rho_raw:.2e} (фактически нулевая матрица)",
            "Вырожденная калибровка (возможная ошибка X_ij=0 в NIOT)",
            "Проверить извлечение X и GO; не выдавать нормированную нулевую матрицу",
        )
    if rho_raw <= SPECTRAL_TARGET:
        A_norm = A.copy()
        rho_new = rho_raw
    else:
        scale = SPECTRAL_TARGET / rho_raw
        A_norm = A * scale
        np.fill_diagonal(A_norm, 0.0)
        rho_new = float(np.max(np.abs(np.linalg.eigvals(A_norm))))
    return A_norm, rho_raw, rho_new


def _print_matrix(label: str, A: np.ndarray) -> None:
    print(f"  {label}:")
    print(f"    {'':10s}  " + "  ".join(f"{s:>10s}" for s in SECTORS_OUT))
    for i, row in enumerate(A):
        print(f"    {SECTORS_OUT[i]:10s}  " + "  ".join(f"{v:10.6f}" for v in row))


def main() -> None:
    print("=" * 70)
    print("Calibrate A_WIOD^v4 per METHODOLOGY §7 (architecture B1)")
    print(f"Year: {YEAR} | Reference country: {REFERENCE_COUNTRY}")
    print(f"Robustness set (Series 9): {ROBUSTNESS_COUNTRIES}")
    print(f"Spectral target: ρ ≤ {SPECTRAL_TARGET}")
    print("=" * 70)

    if not WIOD_DIR.exists():
        _fail("A_WIOD^v4", f"Каталог {WIOD_DIR}", "Не существует", "WIOD NIOT не загружены",
              "Скачать с http://www.wiod.org/database/niots16")

    # --- Reference country: DEU ---
    print(f"\n[{REFERENCE_COUNTRY} — reference]")
    X_ref, GO_ref = extract_xij_goj(REFERENCE_COUNTRY)
    A_ref_raw = compute_A_leontief(X_ref, GO_ref, REFERENCE_COUNTRY)
    print(f"  GO^{REFERENCE_COUNTRY} = {GO_ref.tolist()}")
    _print_matrix("A_raw (after zeroing diag)", A_ref_raw)

    A_norm, rho_raw, rho_new = apply_spectral_normalization(A_ref_raw)
    if rho_raw > SPECTRAL_TARGET:
        print(f"\n  ρ(A_raw) = {rho_raw:.6f}  →  normalized to ρ(A_norm) = {rho_new:.6f}")
    else:
        print(f"\n  ρ(A_raw) = {rho_raw:.6f}  (within target, no scaling)")
    _print_matrix("A_WIOD^v4 (final)", A_norm)

    # --- Robustness set: other countries (raw + normalized), Series 9 ---
    print("\n[Robustness set — calibrated per country for Series 9]")
    robustness: dict[str, dict] = {}
    for country in ROBUSTNESS_COUNTRIES:
        print(f"\n[{country}]")
        X_c, GO_c = extract_xij_goj(country)
        A_c_raw = compute_A_leontief(X_c, GO_c, country)
        A_c_norm, rho_c_raw, rho_c_new = apply_spectral_normalization(A_c_raw)
        print(f"  GO^{country} = {GO_c.tolist()}")
        print(f"  ρ(A_raw) = {rho_c_raw:.6f}" +
              (f"  →  ρ(A_norm) = {rho_c_new:.6f}" if rho_c_raw > SPECTRAL_TARGET else "  (no scaling)"))
        robustness[country] = {
            "GO": GO_c.tolist(),
            "A_raw": A_c_raw.tolist(),
            "A_norm": A_c_norm.tolist(),
            "spectral_radius_raw": round(rho_c_raw, 6),
            "spectral_radius_final": round(rho_c_new, 6),
        }

    # --- Sector weights from DEU GO (§5.2, §5.3) ---
    w = GO_ref / GO_ref.sum()
    print(f"\nsector_weights v1 (w_j = GO_j^{REFERENCE_COUNTRY} / Σ GO_k^{REFERENCE_COUNTRY}):")
    for s, GO_j, w_j in zip(SECTORS_OUT, GO_ref, w):
        print(f"  {s:10s}  GO={GO_j:12.1f}  w={w_j:.4f}")

    # --- Save artefacts ---
    CALIB_A.parent.mkdir(parents=True, exist_ok=True)
    CALIB_A.write_text(json.dumps({
        "method": "METHODOLOGY §7 (Miller & Blair 2009; a_ij=X_ij/GO_j, a_ii=0; spectral norm ≤ 0.95)",
        "source": "WIOD 2016 NIOT (Nov16)",
        "year": YEAR,
        "reference_country": REFERENCE_COUNTRY,
        "architecture": "B1 (single reference country)",
        "sectors": SECTORS_OUT,
        "sector_codes": SECTOR_CODES,
        "A_WIOD_v4": A_norm.tolist(),
        "spectral_radius_raw": round(rho_raw, 6),
        "spectral_radius_final": round(rho_new, 6),
    }, indent=2), encoding="utf-8")
    print(f"\n[save] {CALIB_A}")

    CALIB_META.write_text(json.dumps({
        "architecture": "B1 (single reference country)",
        "reference_country": REFERENCE_COUNTRY,
        "reference": {
            "GO": GO_ref.tolist(),
            "A_raw": A_ref_raw.tolist(),
            "A_norm": A_norm.tolist(),
            "spectral_radius_raw": round(rho_raw, 6),
            "spectral_radius_final": round(rho_new, 6),
        },
        "robustness_set_series_9": robustness,
        "notes": (
            "A_WIOD^v4 = A_DEU (normalized). Остальные страны приведены для Серии 9 "
            "(§9.3) — пересчёт ключевых результатов для теста CountryRobustness."
        ),
    }, indent=2), encoding="utf-8")
    print(f"[save] {CALIB_META}")

    WEIGHTS_OUT.write_text(json.dumps({
        "method": f"w_j = GO_j / Σ_k GO_k (§5.2), GO from {REFERENCE_COUNTRY}",
        "source": "WIOD 2016 NIOT (Nov16), reference country DEU",
        "year": YEAR,
        "reference_country": REFERENCE_COUNTRY,
        "sectors": SECTORS_OUT,
        "GO": GO_ref.tolist(),
        "weights": w.tolist(),
    }, indent=2), encoding="utf-8")
    print(f"[save] {WEIGHTS_OUT}")


if __name__ == "__main__":
    main()
