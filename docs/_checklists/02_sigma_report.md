# Этап 2 — Калибровка σ из SCADA: итоговый отчёт

**Дата:** 2026-04-19
**Ветка:** `methodology-overhaul`
**Статус:** ✅ Этап 2 завершён, готов к Этапу 3

## Сводка артефактов

| Файл | Роль |
|---|---|
| `scripts/sigma_calibration/extract_sigma_hourly.py` | Воспроизводимый пайплайн |
| `data/calibration/sigma_empirical_v1.json` | Калиброванный σ-вектор + per-file details + 95% CI |

## Методология

1. Нормализация сигнала к [0, 1] по физической / номинальной шкале (не min-max, чтобы сохранить смысл «доля от capacity»).
2. Агрегация к почасовому разрешению (mean).
3. σ = std(Δx_hourly), где Δx_t = x_{t+1h} - x_t.
4. Bootstrap 95% CI по 1000 ресэмплингов per-file σ (для агрегированных источников).
5. Time convention: σ выражена в per-hour; один шаг модели dt=1 интерпретируется как 1 час реального времени.

## Результаты

| Сектор | σ_per_hour | Источник | n выборки |
|---|---|---|---|
| **energy** | **0.1012** (CI95 [0.0972, 0.1042]) | Kelmarsh Wind Farm SCADA 2016-2021 (Senvion MM92, 2050 kW rated) | 36 файлов × 6 турбин × 6 лет, 281464 почасовых точек |
| **water** | **0.1218** (CI95 [0.1198, 0.1374]) | HAI 21.03 P3_LIT01 (level transmitter, pumped-storage), attack=0 | 3 файла, почасовая агрегация 1-сек данных |
| **transport** | **0.0232** (CI95 [0.0216, 0.0250]) | DfT Road Safety Open Data (dft-road-casualty-statistics-collision-last-5-years.csv) | 1827 дней (≈ 5 лет) |

### Масштабирование для transport

Источник транспортных данных (DfT) — ежедневные агрегаты столкновений. Для перевода к per-hour volatility применено Brownian-scaling:

> σ_hour = σ_day / √24 = 0.1137 / 4.899 ≈ 0.0232

**Ограничение**: под допущении Brownian motion без суточной/недельной сезонности. DfT данные имеют слабую weekly-seasonality (будни vs выходные), что может завышать per-hour σ. Это честная аппроксимация при отсутствии sub-daily транспортных данных.

## Проверка диапазонов

- Все σ в диапазоне [0.02, 0.13] — совместимо с Euler-Maruyama интегрированием при dt=0.1 (переход на step-level: σ_step = σ_hour × √0.1 ≈ 0.032–0.039 для energy/water, 0.007 для transport).
- Значения не взрываются и не тривиальны.
- ω(σ_energy) × √(часов в сутки) ≈ 0.50 — порядок суточного разброса нормализованной мощности, ~50% — это типично для wind.

## Ограничения и честная фиксация

1. **Water сектор** — единственный источник (HAI 21.03 P3 pumped-storage). Это industrial ICS testbed, а не civilian water utility. Волатильность 0.12/час отражает цикличность работы насосов и выше, чем была бы у municipal water system (где load более плавный). Это best available при отсутствии civilian water SCADA.
2. **Transport σ** — proxy через daily collision counts DfT. Brownian rescaling завышает per-hour σ при наличии weekly seasonality. Для Stage 3+ это не критично (σ входит аддитивно в SDE, а не через autocorrelation).
3. **Energy σ** — на основе wind SCADA (Kelmarsh), что является high-variability генерацией. Для репрезентативности общего энергетического сектора (thermal + wind mix) это завышенная оценка. Справедливый worst-case для анализа чувствительности.
4. **OpenWindSCADA и HAI P2/P4** (энергетические сигналы HAI) не использовались для production-калибровки; остались как sensitivity-resources при необходимости.

## Пред-существующая калибровка

`data/calibration/sigma_calibrated.json` (pre-reform baseline, commit f8497b6) содержит значения σ_energy=6.54, σ_water=18.08 — это **аннуализированные** (annualised) величины из financial-style convention `std(Δlog x) / √dt_hours` с dt_hours=0.000278 (1 сек). Они НЕ совместимы с SDE-интегратором при dt=0.1 (взорвут симуляцию). Новая калибровка `sigma_empirical_v1.json` использует прямой `std(Δx_hourly)` на нормализованном [0,1]-сигнале и совместима с моделью.

## ⏸ Pause перед Этапом 3

Этап 3 — NEVA framework оператор + IIM baseline. План:
1. Перенести Bardoscia NEVA `neva/` из dependency (установлен) в единый модуль под `services/risk_engine/neva_operator.py`.
2. Реализовать IIM (Haimes-Santos 2005) inoperability operator: `i(t+1) = A_star · i(t) + c(t)` в отдельном классе.
3. Адаптировать SDE-интегратор: опция использования NEVA-propagator или IIM-propagator вместо текущего `x + Ax`.
4. Тесты: сравнение NEVA / IIM / classical на синтетическом каскаде.

Готов к запуску Этапа 3 по команде.
