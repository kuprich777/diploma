"""
Генерация прокси-данных для двух исторических каскадных событий.

Источники:
  - Texas 2021: FERC/NERC «The February 2021 Cold Weather Outages in Texas and
    the South-Central United States» (November 2021)
  - India 2012: CEA «Report on the Grid Disturbance on 30th July 2012 and
    31st July 2012» (August 2012)

Методика: на основе открытых отчётов строятся детерминированные огибающие
деградации каждого сектора, к которым добавляется реалистичный гауссовский шум
(σ = 0.03) с фиксированным seed=42 для воспроизводимости.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path


RNG = np.random.default_rng(seed=42)
NOISE_SIGMA = 0.03
DATA_DIR = Path(__file__).parent / "data"


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def logistic_rise(t: np.ndarray, onset: float, rate: float, peak: float) -> np.ndarray:
    """Логистический рост от 0 до peak с началом onset и скоростью rate."""
    return peak / (1.0 + np.exp(-rate * (t - onset)))


def exp_decay(t: np.ndarray, t_peak: float, tau: float, peak_val: float) -> np.ndarray:
    """Экспоненциальное затухание от peak_val начиная с t_peak."""
    return peak_val * np.exp(-(t - t_peak) / tau)


def envelope(
    t: np.ndarray,
    onset: float,
    peak_time: float,
    peak_val: float,
    rise_rate: float,
    decay_tau: float,
) -> np.ndarray:
    """
    Комбинированная огибающая: логистический рост до peak_time,
    затем экспоненциальное затухание.
    """
    y = np.where(
        t <= peak_time,
        logistic_rise(t, onset + (peak_time - onset) * 0.4, rise_rate, peak_val),
        exp_decay(t, peak_time, decay_tau, peak_val),
    )
    return np.clip(y, 0.0, 1.0)


def add_noise(signal: np.ndarray, sigma: float = NOISE_SIGMA) -> np.ndarray:
    return np.clip(signal + RNG.normal(0.0, sigma, size=signal.shape), 0.0, 1.0)


# ---------------------------------------------------------------------------
# Texas 2021: 168 ч (7 суток)
# ---------------------------------------------------------------------------

def generate_texas() -> pd.DataFrame:
    """
    Прокси-данные блэкаута в Техасе (8–15 февраля 2021).

    Хронология по FERC/NERC (2021):
      - ~10 Feb 00:00 UTC: начало отказов генерации
      - Пик дефицита мощности ~34 ГВт через ~12 ч
      - Постепенное восстановление энергосистемы за 4–5 суток
      - Водоснабжение: сбои с задержкой ~12 ч (замерзание трубопроводов)
      - Транспорт: обледенение дорог с задержкой ~6 ч
    """
    hours = np.arange(168, dtype=float)  # 0..167
    start = pd.Timestamp("2021-02-10 00:00:00")
    timestamps = [start + pd.Timedelta(hours=int(h)) for h in hours]

    # --- Энергетика ---
    energy = envelope(hours, onset=0, peak_time=12, peak_val=0.87,
                      rise_rate=0.45, decay_tau=72)

    # --- Водоснабжение ---  задержка ~12 ч, пик на ~36 ч
    water = envelope(hours, onset=12, peak_time=36, peak_val=0.61,
                     rise_rate=0.35, decay_tau=80)

    # --- Транспорт --- задержка ~6 ч, пик на ~24 ч
    transport = envelope(hours, onset=6, peak_time=24, peak_val=0.52,
                         rise_rate=0.40, decay_tau=68)

    df = pd.DataFrame({
        "timestamp": timestamps,
        "energy_degradation": add_noise(energy),
        "water_degradation": add_noise(water),
        "transport_degradation": add_noise(transport),
    })
    return df


# ---------------------------------------------------------------------------
# India 2012: 48 ч (быстрый каскад)
# ---------------------------------------------------------------------------

def generate_india() -> pd.DataFrame:
    """
    Прокси-данные блэкаута в Индии (30–31 июля 2012).

    Хронология по CEA (2012):
      - 30 Jul 02:33 IST: первый крупный отказ Northern Grid (~35 ГВт)
      - 31 Jul 13:00 IST: второй отказ, охватил Northern + Eastern + NE Grid
      - Быстрый каскадный эффект (2–6 ч задержки между секторами)
      - Полное восстановление за ~15 ч после каждого события
    """
    hours = np.arange(48, dtype=float)  # 0..47
    start = pd.Timestamp("2012-07-30 02:33:00")
    timestamps = [start + pd.Timedelta(hours=int(h)) for h in hours]

    # --- Энергетика --- быстрый подъём: пик через ~6 ч
    energy = envelope(hours, onset=0, peak_time=6, peak_val=0.78,
                      rise_rate=0.90, decay_tau=22)

    # --- Водоснабжение --- задержка ~4 ч, пик через ~12 ч
    water = envelope(hours, onset=4, peak_time=12, peak_val=0.56,
                     rise_rate=0.70, decay_tau=26)

    # --- Транспорт --- задержка ~2 ч, пик через ~8 ч
    transport = envelope(hours, onset=2, peak_time=8, peak_val=0.47,
                         rise_rate=0.80, decay_tau=24)

    df = pd.DataFrame({
        "timestamp": timestamps,
        "energy_degradation": add_noise(energy),
        "water_degradation": add_noise(water),
        "transport_degradation": add_noise(transport),
    })
    return df


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)

    texas = generate_texas()
    texas_path = DATA_DIR / "texas_2021_proxy.csv"
    texas.to_csv(texas_path, index=False, float_format="%.4f")
    print(f"Записан: {texas_path}  ({len(texas)} строк)")

    india = generate_india()
    india_path = DATA_DIR / "india_2012_proxy.csv"
    india.to_csv(india_path, index=False, float_format="%.4f")
    print(f"Записан: {india_path}  ({len(india)} строк)")


if __name__ == "__main__":
    main()
