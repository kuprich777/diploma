"""
Калибровка матрицы межсекторального влияния A по временным рядам деградации.

Метод: OLS-регрессия для каждой пары (i, j):
    Δx_i(t) ≈ a_ij · x_j(t)

Значения диагонали фиксированы в 0 (самовлияние не моделируется A).
Оценки обрезаются до [0, 1] — только неотрицательное влияние.
При наличии нескольких CSV-файлов матрицы усредняются.

Результат сохраняется в results/A_calibrated.json.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------
# Константы
# --------------------------------------------------------------------------

SECTORS: list[str] = ["energy", "water", "transport"]
SECTOR_COLS: list[str] = [f"{s}_degradation" for s in SECTORS]
N: int = len(SECTORS)

# Экспертная матрица из основного эксперимента
A_EXPERT: np.ndarray = np.array(
    [
        [0.0, 0.2, 0.3],
        [0.4, 0.0, 0.2],
        [0.5, 0.3, 0.0],
    ],
    dtype=float,
)


# --------------------------------------------------------------------------
# Типы
# --------------------------------------------------------------------------

class CalibrationResult(NamedTuple):
    """Результат калибровки матрицы A."""

    A_calibrated: np.ndarray   # усреднённая по всем CSV
    A_expert: np.ndarray
    abs_diff: np.ndarray       # |A_cal - A_exp|
    rel_diff: np.ndarray       # |A_cal - A_exp| / max(|A_exp|, 0.01)
    per_file: dict[str, np.ndarray]  # A для каждого CSV


# --------------------------------------------------------------------------
# Вспомогательные функции
# --------------------------------------------------------------------------

def _print_matrix(M: np.ndarray, label: str = "") -> None:
    """Вывод матрицы в виде таблицы."""
    if label:
        print(f"{label}:")
    header = "       " + "  ".join(f"{s:>12}" for s in SECTORS)
    print(header)
    for i, row in enumerate(M):
        vals = "  ".join(f"{v:12.4f}" for v in row)
        print(f"  {SECTORS[i]:8s} {vals}")


def load_csv(path: Path) -> pd.DataFrame:
    """Загрузка CSV с временным рядом деградации."""
    df = pd.read_csv(path, parse_dates=["timestamp"])
    missing = [c for c in SECTOR_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"{path.name}: отсутствуют колонки {missing}")
    return df


# --------------------------------------------------------------------------
# OLS-калибровка
# --------------------------------------------------------------------------

def estimate_A_ols(df: pd.DataFrame) -> np.ndarray:
    """
    Оценка матрицы A методом OLS по временному ряду.

    Для каждой пары (i, j), i ≠ j, решается задача наименьших квадратов:
        Δx_i(t) = a_ij · x_j(t) + ε_t

    Оценка: a_ij = (X_j^T X_j)^{-1} X_j^T Δx_i,  затем clip(·, 0, 1).

    Args:
        df: DataFrame с колонками *_degradation.

    Returns:
        Матрица A размера (N, N) с нулевой диагональю.
    """
    X = df[SECTOR_COLS].to_numpy(dtype=float)  # (T, N)
    dX = np.diff(X, axis=0)                    # (T-1, N) — приращения Δx
    X_t = X[:-1]                               # регрессоры в момент t

    A_cal = np.zeros((N, N), dtype=float)

    for i in range(N):
        for j in range(N):
            if i == j:
                continue  # диагональ = 0

            xj = X_t[:, j]
            dxi = dX[:, i]

            denom = float(xj @ xj)
            if denom < 1e-12:
                # Нет вариации — коэффициент не идентифицирован
                A_cal[i, j] = 0.0
            else:
                a_hat = float(xj @ dxi) / denom
                A_cal[i, j] = float(np.clip(a_hat, 0.0, 1.0))

    return A_cal


# --------------------------------------------------------------------------
# Основная процедура
# --------------------------------------------------------------------------

def calibrate_from_directory(data_dir: Path) -> CalibrationResult:
    """
    Калибровка по всем *_proxy.csv в data_dir.
    Итоговая A — поэлементное среднее по всем файлам.

    Args:
        data_dir: папка с CSV-файлами.

    Returns:
        CalibrationResult с полями A_calibrated, abs_diff, rel_diff, per_file.
    """
    csv_files = sorted(data_dir.glob("*_proxy.csv"))
    if not csv_files:
        raise FileNotFoundError(f"Нет *_proxy.csv в {data_dir}")

    per_file: dict[str, np.ndarray] = {}
    estimates: list[np.ndarray] = []

    for csv_path in csv_files:
        df = load_csv(csv_path)
        A_est = estimate_A_ols(df)
        key = csv_path.stem  # e.g. "texas_2021_proxy"
        per_file[key] = A_est
        estimates.append(A_est)
        print(f"\n  [{csv_path.name}]  T={len(df)}")
        _print_matrix(A_est)

    A_cal = np.mean(estimates, axis=0)
    abs_diff = np.abs(A_cal - A_EXPERT)
    rel_diff = abs_diff / np.maximum(np.abs(A_EXPERT), 0.01)

    return CalibrationResult(A_cal, A_EXPERT, abs_diff, rel_diff, per_file)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main() -> None:
    root = Path(__file__).parent
    data_dir = root / "data"
    results_dir = root / "results"
    results_dir.mkdir(exist_ok=True)

    print("=" * 60)
    print("  Калибровка матрицы A по историческим прокси-данным")
    print("=" * 60)

    _print_matrix(A_EXPERT, "\nЭкспертная матрица A_expert")

    print("\n--- Оценки по отдельным датасетам ---")
    result = calibrate_from_directory(data_dir)

    print("\n--- Итоговая усреднённая A_calibrated ---")
    _print_matrix(result.A_calibrated)

    print("\n--- Абсолютное отклонение |A_cal - A_exp| ---")
    _print_matrix(result.abs_diff)

    print("\n--- Относительное отклонение, % ---")
    _print_matrix(result.rel_diff * 100)

    # Метрика качества калибровки
    mse = float(np.mean(result.abs_diff[A_EXPERT > 0] ** 2))
    mae = float(np.mean(result.abs_diff[A_EXPERT > 0]))
    print(f"\n  MAE (ненулевые элементы): {mae:.4f}")
    print(f"  MSE (ненулевые элементы): {mse:.4f}")

    # Сохранение
    output: dict = {
        "A_expert": A_EXPERT.tolist(),
        "A_calibrated": result.A_calibrated.tolist(),
        "abs_diff": result.abs_diff.tolist(),
        "rel_diff_pct": (result.rel_diff * 100).tolist(),
        "mae_nonzero": mae,
        "mse_nonzero": mse,
        "sectors": SECTORS,
        "per_file": {k: v.tolist() for k, v in result.per_file.items()},
    }
    out_path = results_dir / "A_calibrated.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nРезультат сохранён: {out_path}")


if __name__ == "__main__":
    main()
