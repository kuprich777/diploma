# Сравнительный отчёт: стенд vs автономный скрипт

> Сгенерировано: `compare_testbed_vs_standalone.py`

**Два уровня модели:**
- **Стенд** — `risk_engine` + `scenario_simulator` (HTTP-сервисы, domain weights)
- **Скрипт** — чистый numpy: `x' = clip(x + shock + A·x)` (абстрактный уровень)

---

## 1. Сравнение K_cl и K_q

| Сценарий | K_cl (стенд) | K_cl (скрипт) | Δ K_cl | K_q (стенд) | K_q (скрипт) | Δ K_q |
|---|---:|---:|---:|---:|---:|---:|
| Texas 2021 (Winter Storm Uri) | 1.000 | 0.996 | 0.004 | 1.000 | 1.000 | 0.000 |
| India 2012 (Northern Grid Collapse) | 1.000 | 0.029 | 0.971 | 0.995 | 1.000 | 0.005 |
| Europe 2006 (UCTE Split) | 1.000 | 0.000 | 1.000 | 0.970 | 0.997 | 0.027 |
| Baltimore Key Bridge 2024 | 0.095 | 0.000 | 0.095 | 0.995 | 0.202 | 0.793 |
| Christchurch 2011 (M6.3 Earthquake) | 1.000 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 |

## 2. Сравнение модельного вектора x_model

| Сценарий | Сектор | x_model (стенд) | x_model (скрипт) | Δ |
|---|---|---:|---:|---:|
| Texas 2021 (Winter Storm Uri) | energy | 1.000 | 0.780 | 0.220 |
|  | water | 1.000 | 0.040 | 0.960 |
|  | transport | 1.000 | 0.050 | 0.950 |
| India 2012 (Northern Grid Collapse) | energy | 1.000 | 0.643 | 0.357 |
|  | water | 0.400 | 0.046 | 0.354 |
|  | transport | 0.500 | 0.061 | 0.439 |
| Europe 2006 (UCTE Split) | energy | 1.000 | 0.280 | 0.720 |
|  | water | 0.400 | 0.012 | 0.388 |
|  | transport | 0.500 | 0.015 | 0.485 |
| Baltimore Key Bridge 2024 | energy | 0.845 | 0.000 | 0.845 |
|  | water | 0.385 | 0.000 | 0.385 |
|  | transport | 0.927 | 0.300 | 0.627 |
| Christchurch 2011 (M6.3 Earthquake) | energy | 1.000 | 0.400 | 0.600 |
|  | water | 1.000 | 0.400 | 0.600 |
|  | transport | 1.000 | 0.300 | 0.700 |

## 3. RMSE vs реальность

| Сценарий | RMSE (стенд) | RMSE (скрипт) | Δ RMSE |
|---|---:|---:|---:|
| Texas 2021 (Winter Storm Uri) | 0.333 | 0.485 | 0.152 |
| India 2012 (Northern Grid Collapse) | 0.256 | 0.247 | 0.009 |
| Europe 2006 (UCTE Split) | 0.512 | 0.095 | 0.416 |
| Baltimore Key Bridge 2024 | 0.621 | 0.031 | 0.590 |
| Christchurch 2011 (M6.3 Earthquake) | 0.465 | 0.258 | 0.207 |

## 4. Оценка согласованности

**Критерий**: K_q(стенд) ≈ K_q(скрипт) ± 0.05 → системы эквивалентны.

| Сценарий | K_q(стенд) | K_q(скрипт) | |Δ| | Согласован? |
|---|---:|---:|---:|:---:|
| Texas 2021 (Winter Storm Uri) | 1.000 | 1.000 | 0.000 | ✓ |
| India 2012 (Northern Grid Collapse) | 0.995 | 1.000 | 0.005 | ✓ |
| Europe 2006 (UCTE Split) | 0.970 | 0.997 | 0.027 | ✓ |
| Baltimore Key Bridge 2024 | 0.995 | 0.202 | 0.793 | ✗ |
| Christchurch 2011 (M6.3 Earthquake) | 1.000 | 1.000 | 0.000 | ✓ |

**Расхождение > 0.05** в одном или нескольких сценариях (см. §5).

## 5. Методологические причины расхождений

| Аспект | Автономный скрипт | Стенд |
|---|---|---|
| Оператор | clip(x + shock + A·x), чистый numpy | risk_engine + domain services (HTTP) |
| Каскад | матричное умножение A | interaction queue + dep_check endpoints |
| Веса energy→water | A[water][energy] = 0.4 | domain-layer weight = 0.40 (aligned) |
| Веса energy→transport | A[transport][energy] = 0.5 | domain-layer weight = 0.50 (aligned) |
| Шум | gaussian σ = 0.03 на x | stochastic_scale × N(1, σ) на duration |
| Скорость | ~2 сек на 1000 прогонов | ~5–10 мин на 200 прогонов |

**Domain-layer weights** (0.40 / 0.50) выровнены с матричными A-weights (0.4 / 0.5) начиная с доработки реалистичности (2026-03-29). Стенд реализует двухуровневую архитектуру:
- *Абстрактный уровень*: матрица A (скрипт) — параметры эксперимента
- *Domain уровень*: физические dep_check weights — реализация в конкретных сервисах

Если |Δ K_q| ≤ 0.05: оба уровня дают статистически неразличимый результат.
Если |Δ K_q| > 0.05: domain weights доминируют над A, что само по себе является методологическим наблюдением об архитектурной чувствительности модели.

---

_Воспроизведение: `python run_on_testbed.py && python compare_testbed_vs_standalone.py`_
