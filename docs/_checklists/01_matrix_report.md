# Этап 1 — Эмпирическая калибровка матрицы A: итоговый отчёт

**Дата:** 2026-04-19
**Ветка:** `methodology-overhaul`
**Статус:** ✅ Этап 1 завершён, готов к проверке и переходу на Этап 2

## Сводка артефактов

| Шаг | Файл | Статус |
|---|---|---|
| 1.1 Level 1 prior | `data/empirical_cascades/matrix_calibration/level1_aggregated.yaml` | ✓ |
| 1.2 Level 2 events | `data/empirical_cascades/historical_dataset/cascade_events.yaml` | ✓ |
| 1.3 Raw empirical | `data/calibration/A_empirical_v1.json` | ✓ |
| 1.4 Bayesian posterior | `data/calibration/A_empirical_bayesian_v1.json` | ✓ |
| 1.5 WIOD sensitivity | `data/calibration/A_wiod_sensitivity.json` | ✓ |
| Script 1.3 | `scripts/matrix_calibration/build_empirical_matrix.py` | ✓ |
| Script 1.4 | `scripts/matrix_calibration/bayesian_posterior.py` | ✓ |

## Level 1 prior (Pescaroli & Alexander 2016, Luiijf 2009)

Primary: `Pescaroli G., Alexander D. (2016). NH 82(1), 175-192`, p. 181.
Underlying: Luiijf et al. 2009, CRITIS 2008, p. 305 (не в репозитории, процитировано через Pescaroli).

Initiator distribution (Luiijf, 3-секторная проекция):
- energy: 0.882, transport: 0.074, water: 0.044 (ренормализация деление на 0.68).

Secondary disruptions per initiation (Luiijf):
- energy_initiated: 2.06, transport/water: NOT_DOCUMENTED_IN_SOURCE.

Cell-level prior: **Beta(1,1) неинформативный** — Luiijf даёт только marginals, не cell-level.

## Level 2 authorial dataset: 4 события

| Событие | Initiator | Primary PDF | Off-diag documented |
|---|---|---|---|
| EUROPE_2006 | energy | UCTE Final Report | 0 (UCTE электроспецифичен) |
| TEXAS_2021 | energy | FERC/NERC + Hobby UH + Waco AAR | 2 (water=0.75, transport=0.25) |
| INDIA_2012 | energy | MoP Annual Report 2012-13 | 0 (1 абзац на p.112) |
| BALTIMORE_2024 | transport | NTSB MIR-25-40 | 0 (maritime-scoped) |

**Покрытие**: 2 из 12 возможных off-diagonal ячеек (16.7%).

## Raw empirical matrix (Этап 1.3)

Rows=affected, cols=initiator, order=(energy, water, transport):

```
  energy     [ 0.000    nan    nan]
  water      [ 0.750  0.000    nan]
  transport  [ 0.250    nan  0.000]
```

`nan` означает «нет наблюдений с таким инициатором». Единственные 2 заполненные ячейки — из TEXAS_2021.

## Bayesian posterior matrix (Этап 1.4)

Beta-Binomial сопряжённое обновление с prior Beta(1,1). Posterior means после спектральной нормализации (ρ до нормализации = 1.0000, множитель 0.95):

```
             energy   water  transport
  energy     0.0000  0.4750  0.4750
  water      0.5542  0.0000  0.4750
  transport  0.3958  0.4750  0.0000
```

**Credible intervals (до нормализации):**

| Ячейка | n | posterior_mean | 95% CI |
|---|---|---|---|
| A[water][energy] | 1 | 0.583 | [0.102, 0.969] |
| A[transport][energy] | 1 | 0.417 | [0.031, 0.898] |
| A[energy][water] | 0 | 0.500 | [0.025, 0.975] |
| A[energy][transport] | 0 | 0.500 | [0.025, 0.975] |
| A[water][transport] | 0 | 0.500 | [0.025, 0.975] |
| A[transport][water] | 0 | 0.500 | [0.025, 0.975] |

**Наблюдение**: 4 ячейки из 6 имеют posterior = prior (n=0 → Beta(1,1), CI=[0.025, 0.975]). Это честное отражение отсутствия кросс-секторальных данных в локальных primary-источниках для Europe 2006, India 2012, Baltimore 2024.

## Spectral normalization

- ρ(A_raw_posterior) = 1.0000 (рядом с порогом)
- Cap = 0.95
- Множитель нормализации = 0.95
- ρ(A_post_capped) = 0.9500

Обоснование cap=0.95: предотвращает расходимость при итерации операторов; соответствует конвенции прежних версий матрицы A_wiod_v3, A_calibrated_v2.

## WIOD sensitivity (Этап 1.5)

Скопирован `results/A_wiod_v3_snapshot.json` → `data/calibration/A_wiod_sensitivity.json` с явным флагом `do_not_use_as_primary: true`. Spectral radius = 0.395. Используется только в разделе 2.3.4 для robustness-check Spearman rank correlation.

## Ограничения и честная фиксация

1. **Only 2/12 off-diagonal cells are informative.** Posterior for 4 cells is identical to uninformative prior. This is acknowledged explicitly in `A_empirical_bayesian_v1.json` → `notes`.
2. **Credible intervals are very wide** (width ≥ 0.85 for n≤1 cells). Downstream Monte-Carlo in Stage 4 must propagate this uncertainty (sample A[i][j] from posterior Beta distributions per run, not use point estimate).
3. **Single data point for (water|energy) and (transport|energy) is TEXAS_2021.** Robustness/LOO analysis in Stage 4 will show sensitivity to excluding Texas.
4. **INDIA_2012 primary is thin** (1 paragraph). Option to strengthen via CERC 2012 Post-Event Report was rejected by user (D1 route accepted on 2026-04-19).
5. **Diagonal a_ii=0** is a modelling convention; physically sectors can partially recover/degrade internally, but this is captured elsewhere (φ_j capacity function, recovery rate).

## Что нужно проверить перед Этапом 2

- [ ] Посмотреть `data/empirical_cascades/historical_dataset/cascade_events.yaml` — правильны ли все page-citations.
- [ ] Посмотреть `data/calibration/A_empirical_bayesian_v1.json` — согласиться на posterior means и CI.
- [ ] Решить: передавать ли в Stage 4 Monte Carlo sampled A (из Beta-posterior per run) или только point estimate A_empirical_bayesian_v1.matrix_posterior_mean_spectral_capped.
- [ ] Проверить WIOD sensitivity — тот ли snapshot.

## ⏸ Pause перед Этапом 2

Этап 2 — калибровка σ (стохастических параметров) из SCADA датасетов. 4 источника уже слинкованы в `data/scada/`:
- hai (HAI ICS, 2020-2023)
- kelmarsh (SCADA + PMU + Grid, 2016-2021)
- openwindscada
- road_safety (DfT, last 5 years)

Готов к запуску Этапа 2 по команде.
