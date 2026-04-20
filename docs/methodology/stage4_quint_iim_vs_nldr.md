# Этап 4-quint — IIM canonical (Haimes 2005) vs NLDR: методология и дизайн

**Дата:** 2026-04-19
**Ветка:** `methodology-overhaul`
**Артефакты результатов:** `results/mae_comparison.json`, `data/calibration/A_star_iim_canonical.json`, `data/calibration/wiod_sector_outputs.json`

---

## 1. Цель этапа

Сравнить две конкурирующие модели каскадного распространения нарушений между секторами `{energy, water, transport}` на одном и том же наборе задокументированных исторических событий.

- **IIM canonical** — каноническая Inoperability Input-Output Model по Haimes-Santos 2005 (Part I, eq. 11). Детерминированная, статическая.
- **NLDR** — нелинейный каскадный оператор (Barucca NEVA / Battiston DebtRank generalisation), стохастический Monte Carlo в режиме stage-4-ter.

**Гипотеза H₁:** NLDR точнее IIM на ≥ 25 % по MAE intensity,
$$\Delta = \frac{\text{MAE}_\text{IIM} - \text{MAE}_\text{NLDR}}{\text{MAE}_\text{IIM}} \geq 0.25.$$

---

## 2. Данные

### 2.1. Матрица Леонтьева `A` (общая для обеих моделей в части топологии)

- **Источник:** WIOD 2016 release, National Input-Output Tables.
- **Страны:** RUS + DEU + USA.
- **Год:** 2014.
- **Секторы (ISIC Rev.4):**
  - `energy`    = `D35` (Electricity, gas, steam and air conditioning supply)
  - `water`     = `E36` (Water collection, treatment and supply)
  - `transport` = `H49 + H50 + H51 + H52 + H53` (агрегированно: land, water, air, warehousing, postal)
- **Метод построения:** Leontief direct-requirements $a_{ij} = X_{ij} / \text{GO}_j$, усреднение по странам с доступными данными, масштабирование off-diagonal max = 0.5, диагональ = 0.
- **Особенность:** для RUS `water` GO = 0 в WIOD 2014, столбец/строка water усредняется только по DEU+USA.
- **Файл:** `data/calibration/A_wiod_sensitivity.json` (role = SENSITIVITY_ONLY baseline, version v3.0, ρ(A) = 0.3955, Spearman ρ vs OLS v2 = 0.962).

```
A (raw):              energy    water   transport
    energy           0.000    0.350     0.304
    water            0.006    0.000     0.001
    transport        0.500    0.332     0.000
```

### 2.2. Gross Output `x_j` для A*-преобразования

- **Скрипт:** `scripts/matrix_calibration/extract_sector_outputs.py`
- **Метод:** чтение строки `GO / Origin=TOT` со второго листа WIOD NIOT Excel (`National IO-tables`), суммирование по колонкам sector-кодов, усреднение по странам с GO > 0 (правило RUS-water совпадает с правилом усреднения `A`).
- **Файл исходников:** `matrix_doc/sources/NIOTS/{RUS,DEU,USA}_NIOT_nov16.xlsx`
- **Результат** (`data/calibration/wiod_sector_outputs.json`, млн USD):

| Сектор | x_j (mean) | Страны-слагаемые |
|---|---:|---|
| energy    | 246 777.20 | RUS + DEU + USA |
| water     |  12 949.94 | DEU + USA (RUS исключён) |
| transport | 564 730.37 | RUS + DEU + USA |

Отношения: `x_energy/x_water = 19.06`, `x_energy/x_transport = 0.44`, `x_transport/x_water = 43.61`.

### 2.3. Ground truth интенсивностей каскада

Приоритет **primary → secondary**:

1. **Primary** — `data/empirical_cascades/historical_dataset/cascade_events.yaml`. Исходные расследовательские отчёты (UCTE Final Report 2006, FERC/NERC Cold Weather Report 2021, MoP India Annual Report 2012-13, NTSB MIR-25-40). Документируют только 2 из 12 off-diagonal ячеек (TEXAS_2021: water 0.75, transport 0.25); остальные — `NOT_DOCUMENTED_IN_SOURCE`.
2. **Secondary** — `results/validation_real_events.json::events[*].reality.delta_approx`. Восстановленные из academic/post-event surveys оценки (Hobby UH Texas Survey, Dulin et al. 2025 Nature Comm., City of Waco AAR, Maryland DEP), покрывают все 12 ячеек.

Комбинация: primary перекрывает secondary везде, где первичный отчёт документирует ячейку.

### 2.4. Сценарии (4 исторических события)

| event_id | initiator | amplitude | amplitude_source |
|---|---|---:|---|
| EUROPE_2006    | energy    | 0.15 | secondary (reality) |
| TEXAS_2021     | energy    | 0.71 | primary (FERC Hobby survey p.12) |
| INDIA_2012     | energy    | 0.70 | secondary (reality) |
| BALTIMORE_2024 | transport | 0.30 | secondary (reality) |

---

## 3. Матрицы-операторы

### 3.1. IIM canonical — A*

Каноническое преобразование **Haimes 2005 Part I eq. (11)**:
$$A^*_{ij} = A_{ij} \cdot \frac{x_j}{x_i}, \quad A^*_{ii} = 0.$$

- **Скрипт:** `scripts/matrix_calibration/apply_haimes_transformation.py`
- **Входы:** `A_wiod_sensitivity.json` + `wiod_sector_outputs.json`
- **Свойства:** `ρ(A*) = ρ(A_raw) = 0.3955` (spectral radius инвариантен при diagonal similarity $D^{-1} A D$ с $D = \mathrm{diag}(x)$). Нормализация до 0.95 не потребовалась.
- **Артефакт:** `data/calibration/A_star_iim_canonical.json`

```
A*:                   energy     water   transport
    energy           0.0000    0.0184     0.6957
    water            0.1143    0.0000     0.0436
    transport        0.2185    0.0076     0.0000
```

**Оператор** (`services/risk_engine/iim_canonical.py::IIMCanonical`):
$$q = (I - A^*)^{-1} c^*, \quad q \leftarrow \mathrm{clip}(q, 0, 1).$$

Одна линейная операция на сценарий. Без стохастики, без временной динамики.

### 3.2. NLDR — A (без преобразования)

- **Оператор:** `services/risk_engine/cascade_operators.py::NevaOperator` с параметром `β = 2` (нелинейный DebtRank/NEVA).
  $$x_i(t+1) = \mathrm{clip}\bigl( x_i(0) + \sum_j A_{ij} \cdot (1 - (1 - x_j(t))^\beta),\ 0, 1 \bigr).$$
- **Матрица:** та же `A` из `A_wiod_sensitivity.json` (без Haimes-преобразования). NLDR работает непосредственно в пространстве intensity, а не inoperability.
- **Режим запуска:** Monte Carlo N = 5000 (для EUROPE/TEXAS/INDIA) или N = 1000 (BALTIMORE), seed-reproducible, с калибровкой рекавери/шума из Этапа 4-ter.
- **Прогноз по событию:** `median_final_delta` из `results/validation_real_events.json::events[*].model.median_final_delta` — покомпонентное медианное приращение за MC.

### 3.3. Ключевое методологическое различие

| | IIM canonical (Haimes) | NLDR (NEVA) |
|---|---|---|
| Семантика единиц | inoperability q ∈ [0,1] (доля утраченной функции) | intensity x ∈ [0,1] (quantile-based шкала) |
| Преобразование A | $A^* = A \cdot x_j/x_i$ — канонически масштабирует на размеры секторов | A используется как есть |
| Вид уравнения | статическое $(I{-}A^*)^{-1} c^*$ | итеративное $x(t{+}1) = x_0 + A \cdot (1 - (1-x)^\beta)$ |
| Нелинейность | нет | $β = 2$ (концентрация стресса) |
| Стохастика | нет | σ-шум + recovery, MC |

Сравнение не двух разных калибровок одной матрицы, а **двух разных семантик распространения**. Haimes-преобразование вводится именно чтобы переместить A из экономического пространства в inoperability, как требует оригинальная постановка IIM.

---

## 4. Протокол сравнения

### 4.1. Расчёт прогнозов

Для каждого из 4 событий (`yaml_id`):

1. Читаем `initiator.sector` и `amplitude` (primary > secondary).
2. **IIM**: $c^*_\text{initiator} = \text{amplitude}$, остальные 0; вычисляем $q = (I - A^*)^{-1} c^*$; кладём в `iim_pred`.
3. **NLDR**: берём предсказание напрямую из `validation_real_events.json::events[yaml_id].model.median_final_delta`.
4. **Ground truth**: per-sector intensity из YAML (primary) с дополнением reality (secondary).

### 4.2. Метрика

$$\text{MAE}_\text{метод}(\text{event}) = \frac{1}{|\mathcal{S}_\text{non-init}|} \sum_{s \in \mathcal{S}_\text{non-init}} \bigl| \hat{y}^\text{метод}_s - y^\text{GT}_s \bigr|$$

где $\mathcal{S}_\text{non-init}$ — секторы, не являющиеся инициатором (диагональ по соглашению исключается).

Агрегация — простое среднее по 4 событиям (Leave-One-Out эквивалент, т.к. ни одна модель не калибруется per-event).

### 4.3. Решающее правило

| Δ = (MAE_IIM − MAE_NLDR) / MAE_IIM | Статус H₁ |
|---|---|
| ≥ 0.25 | CONFIRMED |
| 0.10 ≤ Δ < 0.25 | PARTIAL |
| < 0.10 | NOT_CONFIRMED |

Отрицательный Δ означает обратный знак гипотезы (IIM точнее NLDR).

---

## 5. Результаты (воспроизведено в `results/mae_comparison.json`)

| event | MAE_IIM | MAE_NLDR |
|---|---:|---:|
| EUROPE_2006    | 0.0515 | 0.1200 |
| TEXAS_2021     | 0.3558 | 0.5899 |
| INDIA_2012     | 0.1828 | 0.2622 |
| BALTIMORE_2024 | 0.1205 | 0.0950 |
| **mean (oos)** | **0.1777** | **0.2668** |

**Δ = −50.2 %** → **H₁ NOT_CONFIRMED** (обратный знак).

Bias (средняя знаковая ошибка, не-инициатор):

| сектор | IIM | NLDR |
|---|---:|---:|
| energy    | +0.1973 | +0.1877 |
| water     | −0.1819 | −0.1466 |
| transport | −0.1216 | +0.3323 |

---

## 6. Интерпретация

1. **IIM canonical систематически недооценивает** (bias по non-initiator водному и транспортному секторам отрицательный), но остаётся вблизи модератных истинных значений.
2. **NLDR с β = 2 систематически переоценивает transport** (+0.33), что выбивает его из GT на TEXAS (pred 0.667 vs GT 0.25) и EUROPE (pred 0.357 vs GT 0.12).
3. Выигрыш NLDR остаётся только на BALTIMORE_2024, где истинная интенсивность transport совпадает с насыщенной NEVA-оценкой (GT 0.3 ≈ pred 0.632 ближе, чем IIM 0.354 к 0.3 — hence малый NLDR-bias на одном событии).
4. Это каноническое ожидание: **линейный статический IIM консервативен**, **нелинейный NEVA раздувается до насыщения**. При малой выборке документированных событий (N=4) консерватизм выигрывает по MAE.

---

## 7. Созданные артефакты

```
scripts/matrix_calibration/extract_sector_outputs.py       — x_j из WIOD NIOT
scripts/matrix_calibration/apply_haimes_transformation.py  — A → A*
services/risk_engine/iim_canonical.py                      — IIMCanonical класс
scripts/validation/mae_comparison.py                       — пайплайн сравнения
data/calibration/wiod_sector_outputs.json                  — x_j artifact
data/calibration/A_star_iim_canonical.json                 — A* artifact
results/mae_comparison.json                                — per-event MAE + summary
```

---

## 8. Цитирование

- **Haimes, Y. Y., Horowitz, B. M., Lambert, J. H., Santos, J. R., Crowther, K., Lian, C.** (2005). Inoperability Input-Output Model for Interdependent Infrastructure Sectors. I: Theory and Methodology. *Journal of Infrastructure Systems*, 11(2), 67–79.
- **Timmer, M. P., Dietzenbacher, E., Los, B., Stehrer, R., de Vries, G. J.** (2015). An Illustrated User Guide to the World Input-Output Database. *Review of International Economics*, 23.
- **Barucca, P., Bardoscia, M., Caccioli, F., D'Errico, M., Visentin, G., Caldarelli, G., Battiston, S.** (2020). Network Valuation in Financial Systems. *Mathematical Finance*, 30(4).
- UCTE (2007). *Final Report: System Disturbance on 4 November 2006.*
- FERC–NERC (2021). *The February 2021 Cold Weather Outages in Texas and the South Central United States.*
- NTSB (2025). *Marine Investigation Report MIR-25-40: Contact of Containership Dali with Francis Scott Key Bridge.*
