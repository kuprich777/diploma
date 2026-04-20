# Этап 4 — LOO + полный Monte Carlo 15×3: итоговый отчёт

**Дата:** 2026-04-19
**Ветка:** `methodology-overhaul`
**Статус:** ✅ Этап 4 завершён, готов к Этапу 5

## Сводка артефактов

| Файл | Назначение |
|---|---|
| `scripts/matrix_calibration/loo_calibration.py` | LOO posterior: 4 матрицы A^(−k) + full |
| `data/calibration/A_loo_v1.json` | Выход LOO-калибровки |
| `services/risk_engine/mc_harness.py` | Единый MC-harness для SDE/IIM/NEVA |
| `scripts/run_stage4_mc.py` | Полный experiment runner |
| `results/stage4_mc_15x3.json` | 15 сценариев × 3 оператора × N=1000 + bootstrap CI |
| `results/stage4_loo_robustness.json` | LOO-пробник: primary × 5 matrices × 3 ops |

## Методология

### LOO-калибровка
Для каждого события k ∈ {EUROPE_2006, TEXAS_2021, INDIA_2012, BALTIMORE_2024}:
1. Исключить k из датасета.
2. Beta-Binomial posterior (prior Beta(1,1), likelihood Beta(α+Σx, β+n−Σx)) на 3 оставшихся.
3. Спектральная нормализация (cap ρ=0.95).

Результат: 4 LOO-матрицы + full-data референс.

### Сценарный каталог (15)
3 initiator-сектора × 5 severity-уровней = 15:
- initiators: energy / water / transport
- severity: {0.10, 0.25, 0.50, 0.75, 1.00} (intensity scale из `cascade_events.yaml`)
- x0_base = [0.3, 0.3, 0.3] (generic operational baseline)

### Конфигурация MC
| Параметр | Значение | Источник |
|---|---|---|
| A | posterior-mean spectral capped | `A_empirical_bayesian_v1.json` (Этап 1) |
| σ | [0.1012, 0.1218, 0.0232] | `sigma_empirical_v1.json` (Этап 2) |
| ρ_recovery | [0.02, 0.02, 0.02]/step | mild mean-reversion |
| C | [0.75, 0.75, 0.75] | θ=0.75 из pre-reform sweep |
| δ | 0.10 | H₁ quantitative threshold |
| dt | 0.1 | EM numerical step |
| T_steps | 50 | ≈5 часов модельного времени |
| α | 3.0 | dynamic matrix degradation |
| β_NEVA | 2.0 | non-linear stress |
| N_runs | 1000 | bootstrap 95% CI |

### Операторы в harness
- **SDE**: Euler-Maruyama + reflecting [0,1], dynamic A(t) через α.
- **IIM**: Haimes-Santos 2005, `q(t+1) = clip(A·q(t) + c(t) + σZ)`, c = impulse.
- **NEVA**: Barucca 2020, `x(t+1) = clip(x0 + A·(1 − (1−x)^β) + σZ)`.

Все три — один σ-вектор, один seed per (scenario, run, op), единые индикаторы.

## Таблица 15 × 3 (N=1000, 95% CI bootstrap)

| Сценарий | SDE K_cl | SDE K_q | IIM K_cl | IIM K_q | NEVA K_cl | NEVA K_q |
|---|---|---|---|---|---|---|
| S_energy_sev010    | **1.000** | **1.000** | 0.038 | 0.914 | **1.000** | **1.000** |
| S_energy_sev025    | **1.000** | **1.000** | 0.047 | 0.965 | **1.000** | **1.000** |
| S_energy_sev050    | **1.000** | **1.000** | 0.156 | 0.994 | **1.000** | **1.000** |
| S_energy_sev075    | **1.000** | **1.000** | 0.321 | **1.000** | **1.000** | **1.000** |
| S_energy_sev100    | **1.000** | **1.000** | 0.377 | **1.000** | **1.000** | **1.000** |
| S_water_sev010     | **1.000** | **1.000** | 0.009 | 0.821 | **1.000** | **1.000** |
| S_water_sev025     | **1.000** | **1.000** | 0.020 | 0.922 | **1.000** | **1.000** |
| S_water_sev050     | **1.000** | **1.000** | 0.053 | 0.993 | **1.000** | **1.000** |
| S_water_sev075     | **1.000** | **1.000** | 0.105 | **1.000** | **1.000** | **1.000** |
| S_water_sev100     | **1.000** | **1.000** | 0.104 | **1.000** | **1.000** | **1.000** |
| S_transport_sev010 | **1.000** | **1.000** | 0.033 | 0.946 | **1.000** | **1.000** |
| S_transport_sev025 | **1.000** | **1.000** | 0.070 | 0.983 | **1.000** | **1.000** |
| S_transport_sev050 | **1.000** | **1.000** | 0.173 | 0.999 | **1.000** | **1.000** |
| S_transport_sev075 | **1.000** | **1.000** | 0.397 | **1.000** | **1.000** | **1.000** |
| S_transport_sev100 | **1.000** | **1.000** | 0.417 | **1.000** | **1.000** | **1.000** |

**Примечание по CI**: для всех ячеек K=1.000 95% CI вырожденный [1.0, 1.0]. Bootstrap CI для IIM K_cl порядка ±0.02–0.03 (n=1000). Полная таблица CI в `results/stage4_mc_15x3.json`.

## LOO-robustness пробник

Primary сценарий: **S_energy_sev075** (аналог Texas-2021 по инициатору и амплитуде).

| Held-out | SDE K_cl | SDE K_q | IIM K_cl | IIM K_q | NEVA K_cl | NEVA K_q |
|---|---|---|---|---|---|---|
| full (no hold-out) | 1.000 | 1.000 | 0.365 | 0.999 | 1.000 | 1.000 |
| EUROPE_2006 | 1.000 | 1.000 | 0.365 | 0.999 | 1.000 | 1.000 |
| **TEXAS_2021** | 1.000 | 1.000 | **0.217** | 1.000 | 1.000 | 1.000 |
| INDIA_2012 | 1.000 | 1.000 | 0.365 | 0.999 | 1.000 | 1.000 |
| BALTIMORE_2024 | 1.000 | 1.000 | 0.365 | 0.999 | 1.000 | 1.000 |

**Ключевое наблюдение**: только `held_out=TEXAS_2021` изменяет MC-результат (IIM K_cl: 0.365 → 0.217, Δ=−0.148). Причина: TEXAS_2021 — единственное событие с документированными off-diagonal impacts (2 из 12 ячеек). Остальные 3 события не добавляют cell-level информации, поэтому их исключение не меняет posterior.

Это прямое следствие coverage-gap из Этапа 1 и честный маркер ограничения датасета.

## Ключевые наблюдения

### 1. SDE и NEVA насыщаются → K_cl=K_q=1.0 во всех 15 сценариях
Причина структурная:
- ρ(A) = 0.95 (spectral cap) — близко к нестабильности,
- σ = [0.10, 0.12, 0.02]/час × √5 час ≈ аккумулированная диффузия 0.22–0.27,
- x0 = 0.3, C = 0.75 → требуется рост 0.45, который достигается за счёт drift + diffusion при почти-единичном ρ.

**Интерпретация**: при эмпирическом prior-dominated posterior (по 2/12 документированным ячейкам) структура матрицы A максимально каскадная (все off-diagonals ≈0.4–0.55). В таком режиме SDE генерирует каскад почти неизбежно на 5-часовом горизонте.

### 2. IIM — единственный оператор с severity-дискриминацией
Монотонный рост K_cl с severity:
- energy: 0.038 → 0.377
- water: 0.009 → 0.104
- transport: 0.033 → 0.417

Причина: в IIM с импульсным c(0)=severity нет drift-амплификации через `x + Ax` (чистая линейная релаксация `A q + noise`). Спектральный радиус 0.95 < 1 обеспечивает затухание, а σ-шум даёт лишь вероятностный выход за C.

**Для диплома**: IIM даёт нижнюю границу (conservative estimate); SDE + NEVA — верхние границы (aggressive). Realistic estimate лежит в IIM-коридоре для «типичного» события.

### 3. Water как инициатор — самый «слабый» сектор
IIM K_cl для water-шоков насыщается на 0.10 (против 0.38 для energy и 0.42 для transport) при severity=1.0. Это эффект столбца `A[:, water] = [0.475, 0.0, 0.475]`: water → energy и water → transport сравнимы, но оба ниже столбцов energy и transport. Матрица не симметрична — water имеет меньшее «исходящее» влияние в posterior.

### 4. K_q ≫ K_cl для IIM — классический threshold более консервативный
Quantitative (Δ≥0.10) срабатывает уже на severity=0.10 (0.82–0.95 probability), classical — требует severity ≥0.50 для K_cl > 0.10. Подтверждает тезис: **quantitative индикатор чувствительнее classical** (согласуется с memory `project_sde_experiments.md` для SDE).

## Связь с результатами предыдущих этапов

| Источник | A используется | ρ(A) | Характер матрицы |
|---|---|---|---|
| pre-reform `A_wiod_v3` | WIOD 2016 NIOT | ~0.56 | Сильно асимметричная (energy-transport dominant) |
| pre-reform `A_calibrated_v2.0` | OLS Росстат+Eurostat | 0.82 | Умеренно асимметричная |
| **`A_empirical_bayesian_v1` (Этап 1)** | Pescaroli + 4 событий Bayesian | **0.95 (capped)** | **Почти симметричная** (prior-dominated) |

Pre-reform не наблюдал насыщения потому что использовал матрицы с меньшим спектральным радиусом и асимметричной структурой (WIOD/OLS концентрируют влияние в 1–2 доминирующих связях). Эмпирический Bayesian posterior при n=1 для 2 ячеек и uninformative prior для 4 других — равномерно распределяет влияние по всем связям, максимизируя ρ.

**Это ключевой концептуальный результат**: scarcity of cross-sector data → uninformative prior → uniform A → maximum caspadic potential.

## Ограничения

1. **SDE/NEVA насыщение** исключает severity-дискриминацию этими операторами. Для сравнительного анализа нужен либо (а) меньший ρ (на sensitivity-матрице A_WIOD), (б) меньший T_steps/горизонт наблюдения, либо (в) больший C/меньший σ. Sensitivity-анализ запланирован в Этапе 5.
2. **LOO эффект концентрирован в TEXAS_2021** — 3 из 4 LOO-прогонов дают identical результат. Это свойство датасета (не метода) — честно фиксируется в методической части.
3. **Операторный σ-шум** (noise_scale=1.0) в IIM/NEVA аддитивный, в SDE — мультипликативный (σx). Разница масштабов может давать artefacts при малых x. Калибровка noise_scale отдельной задачей не ставится — выбран режим «equal nominal σ».

## Pre-reform ↔ Stage 4: что сохраняется, что обновляется

| Компонент | Pre-reform | Stage 4 | Статус |
|---|---|---|---|
| SDE integrator | `sde_integrator.py` (Euler-Maruyama + reflecting) | тот же | ✅ сохраняется |
| Индикаторы I_cl, I_q | `CascadeResult` | те же | ✅ сохраняется |
| Matrix source | A_wiod_v3 | A_empirical_bayesian_v1 | ⚠ заменён (WIOD → sensitivity в 2.3.4) |
| σ-калибровка | std(Δlog x) / √dt (≈6.5 для energy) | std(Δx_hourly) per-hour (0.10) | ✅ заменена (dimensionally corrected) |
| Операторы сравнения | только SDE | +IIM +NEVA | ✅ расширено |
| LOO-валидация | ❌ отсутствовала | ✅ 4 матрицы | ✅ добавлено |

## ⏸ Pause перед Этапом 5

Этап 5 — Переписывание документации. План:
1. `docs/MATH_MODEL.md` — добавить секции IIM (§1.6) и NEVA (§1.7); переписать §1.2 для новой A-калибровки.
2. `docs/DATA_SOURCES.md` — заменить WIOD-как-основной на Pescaroli+4 events; WIOD → 2.3.4 sensitivity.
3. `docs/ARCHITECTURE.md` — добавить операторы cascade_operators.py и mc_harness.
4. `docs/RESULTS.md` — заменить на Stage 4 таблицу + LOO + интерпретацию насыщения.
5. `readme.md` — обновить quick-start и цитирование.
6. `docs/legacy/` — переместить pre-reform отчёты с суффиксом `_legacy_2026-04-19`.

Готов к запуску Этапа 5 по команде.
