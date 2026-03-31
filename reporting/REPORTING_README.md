# Reporting Datasets — DIPLOMA Stand

Generated from `/results/` artifacts. All datasets are ready for pandas / Excel / plotting without manual cleaning.

---

## Созданные файлы

### 1. `reporting_runs_master.csv` — Основной flat dataset (4 000 строк)

**Назначение:** Все прогоны по четырём главным экспериментам в едином формате.

**Сценарии:**
| Сценарий | Роль | Прогонов | K_cl | K_q |
|---|---|---|---|---|
| S1_energy_outage | extreme / saturated | 1 000 | 1.000 | 1.000 |
| S3_transport_load | marginal / primary | 1 000 | 0.534 | 0.956 |
| S1b_energy_partial | partial degradation | 1 000 | 0.423 | 0.631 |
| S4_water_partial | partial degradation | 1 000 | 0.416 | 0.876 |

**Схема (обязательный порядок колонок):**
```
run, run_id, seed, before, after, delta, duration,
I_q, I_cl, theta_classical, delta_sector_threshold,
method_q_total_before, method_q_total_after,
method_cl_total_before, method_cl_total_after,
delta_R, stochastic_scale,
risk_trajectory_q, risk_trajectory_cl,  ← JSON-строка: {sector: [before, after]}
before_vec_q, after_vec_q, delta_vec_q,  ← JSON-строки: {sector: float}
before_vec_cl, after_vec_cl, delta_vec_cl,
scenario_name, cl_activated_sectors, cl_first_activation_step,
step_1_amount, theta_node
```

**Примечание:** `risk_trajectory_q` и `risk_trajectory_cl` — сконструированные 2-шаговые "траектории" (before → after) по секторам, сериализованные в JSON. Полные временны́е ряды в raw данных отсутствуют.

**Графики:**
- Bar charts K_cl vs K_q по сценариям
- Scatter: delta_R vs duration (по методу и сценарию)
- Histogram: распределение delta_R по case_label

---

### 2. `reporting_runs_showcase.csv` — Showcase прогоны (15 строк)

**Назначение:** Отобранные демонстрационные прогоны для стенда. Один-два примера каждого типового случая.

**Отобранные кейсы:**

| Сценарий | case_label | I_q | I_cl | delta_R | Обоснование выбора |
|---|---|---|---|---|---|
| S1_energy_outage | max_delta | 1 | 1 | 0.5533 | Сильнейший каскад в экстремальном сценарии |
| S1_energy_outage | both_detect | 1 | 1 | 0.5063 | Медиана — типичный прогон при outage |
| S1_energy_outage | both_detect | 1 | 1 | 0.1095 | Минимальный delta_R при 100% каскаде |
| S1_energy_outage | both_detect | 1 | 1 | 0.4751 | Кратчайший outage (5 мин) — мгновенный каскад |
| S1_energy_outage | both_detect | 1 | 1 | 0.4626 | Длиннейший outage (30 мин) |
| S3_transport_load | q_only | 1 | 0 | 0.3839 | **Ключевой**: quantitative видит, classical — нет; max delta среди q_only |
| S3_transport_load | q_only | 1 | 0 | 0.2806 | Медианный q_only — типичный зазор |
| S3_transport_load | near_threshold | 1 | 0 | 0.0697 | Пограничный q_only: минимальный шаг, едва детектируется |
| S3_transport_load | both_detect | 1 | 1 | 0.4329 | Оба метода срабатывают при высокой нагрузке |
| S3_transport_load | both_detect | 1 | 1 | 0.3621 | Медианный both_detect |
| S3_transport_load | max_delta | 1 | 1 | 0.4329 | Максимальный delta_R в маргинальном сценарии |
| S3_transport_load | both_miss | 0 | 0 | 0.1540 | Оба пропускают: нагрузка ниже порога |
| S3_transport_load | near_threshold | 0 | 0 | 0.1593 | Ближайший к порогу промах |
| S4_water_partial | q_only | 1 | 0 | 0.5533 | Вода: quantitative видит крупный каскад, classical — нет |
| S4_water_partial | max_delta | 1 | 1 | 0.5533 | Вода: максимальный каскад, оба детектируют |

**Дополнительные поля:**
- `scenario_label` — читаемое название сценария
- `scenario_type` — `extreme` / `marginal` / `partial_degradation`
- `case_label` — `q_only` / `both_detect` / `both_miss` / `max_delta` / `near_threshold`
- `selection_reason` — текстовое обоснование выбора

**Графики:**
- Иллюстративные диаграммы per-sector до/после по секторам
- Сравнение individual runs: energy/water/transport bars
- "Стрелочные" диаграммы: before → after по методам

---

### 3. `reporting_scenarios_summary.csv` — Сводная таблица по сценариям (8 строк)

**Назначение:** Агрегированное сравнение всех экспериментов — основа для bar charts и сводных таблиц.

**Ключевые колонки:** `scenario_name`, `scenario_role`, `K_cl`, `K_q`, `K_qi`, `gap_abs`, `gap_rel_percent`, `mean_delta_R`, `p95_delta_R`, `recommended_for_stand`

**Рекомендованные для стенда:** S1_energy_outage, S3_transport_load, S4_water_partial, S3_transport_load_factorial

**Графики:**
- Grouped bar chart: K_cl vs K_q (по сценариям)
- Gap bar chart: gap_abs / gap_rel_percent
- Summary table (comparison table в докладе)

---

### 4. `reporting_trajectories_long.csv` — Long-format траектории (180 строк)

**Назначение:** Tidy-формат для line plots и "шарфиков" по секторам.

**Структура:** одна строка = один сектор × один шаг × один метод.

**Колонки:** `scenario_name`, `run`, `run_id`, `method`, `step_index`, `sector`, `risk_value`, `I_q`, `I_cl`, `case_label`, `scenario_type`

**Источник:** `before_vec_q` / `after_vec_q` (step 0/1 для quantitative), `before_vec_cl` / `after_vec_cl` (step 0/1 для classical). Содержит все 15 showcase runs × 3 сектора × 2 шага × 2 метода = 180 строк.

**Графики:**
- Line/bar: risk per sector до и после по методу
- Faceted plot по case_label (q_only vs both_detect vs both_miss)
- Spaghetti plot: overlay нескольких прогонов по одному сектору

---

### 5. `reporting_threshold_analysis.csv` — Scatter / threshold diagnostics (4 000 строк)

**Назначение:** Scatter plots и пороговый анализ. Все прогоны всех 4 экспериментов + per-sector after-risk.

**Ключевые поля:**
- `duration`, `delta_R` — для scatter duration × delta_R
- `I_q`, `I_cl`, `case_label` — для coloring
- `step_1_amount` — фактический шаг нагрузки (стохастически отклонён от номинала)
- `energy_after_q`, `water_after_q`, `transport_after_q` — сектора после удара (quantitative)
- `energy_after_cl`, `water_after_cl`, `transport_after_cl` — сектора после удара (classical)
- `method_q_total_after`, `method_cl_total_after` — суммарный риск после

**Графики:**
- Scatter: duration × delta_R (colorby case_label / scenario)
- Scatter: step_1_amount × delta_R → детектируемость
- Scatter: energy_after_q × transport_after_q → пространство рисков
- Comparison: method_q_total_after vs method_cl_total_after (diagonal plot)
- Threshold line: theta_node=0.70, theta_classical=0.30

---

### 6. `reporting_theta_sweep.csv` — Theta sweep (15 точек)

S3_transport_load при load=0.40, theta_node ∈ [0.20, 0.90], N=500/точка.

| theta_node | K_cl | K_q | gap_abs |
|---|---|---|---|
| 0.20–0.65 | 0.0 | ≈0.944 | ≈0.944 |
| **0.70** | **0.526** | **0.944** | **0.418** |
| 0.75–0.90 | 0.102–0.392 | 0.944 | уменьш. |

**Ключевой вывод:** K_q стабильно ≈0.944 при всех theta; K_cl зависит от theta и падает до 0 при низком пороге. FPR=0 везде.

**Графики:**
- Line plot: K_cl(theta) и K_q(theta) — демонстрация фундаментального зазора
- Gap plot: gap_abs(theta)

---

### 7. `reporting_load_sweep.csv` — Load sweep (13 точек)

S3_transport_load, theta_node=0.70, load ∈ [0.10, 0.60], N=500/точка.

| load_amount | K_cl | K_q |
|---|---|---|
| 0.10 | 0.106 | 0.364 |
| **0.40** | **0.526** | **0.944** |
| 0.60 | 0.762 | 0.978 |

**Графики:**
- Line plot: K_cl(load) и K_q(load) — кривые отклика
- Gap plot: gap_abs(load) — где зазор максимален

---

### 8. `reporting_severity_sweep.csv` — Severity sweep (12 точек)

S4_water_partial, severity ∈ [0.10, 0.80], N=500/точка.

**Максимальный зазор:** ≈0.55 при severity≈0.45–0.50.

**Графики:**
- Line plot: K_cl(severity) и K_q(severity)

---

### 9. `reporting_roc_analysis.csv` — ROC-анализ (15 точек)

I_q как ground truth, I_cl как параметризованный классификатор (по theta_node).

**Ключевой вывод:** FPR=0 для всех theta → AUC=0 на ROC (классический метод — идеальная специфичность, переменная чувствительность). Классические обнаружения ⊆ количественных.

**Колонки:** `theta_node`, `TP`, `FP`, `FN`, `TN`, `sensitivity`, `specificity`, `FPR`, `precision`, `F1`, `K_cl`, `K_q`

**Графики:**
- ROC curve (FPR vs sensitivity) — вырожденная: все точки на FPR=0 оси
- Precision-Recall curve
- Sensitivity(theta) line plot

---

## Главные сценарии для стенда

### 🔴 Extreme Reference: S1_energy_outage

- **Артефакт:** `mc_baseline_theta070_1000_*`
- **Параметры:** outage energy, N=1000, theta_node=0.70, stochastic_scale=0.3
- **Результат:** K_cl=K_q=1.0 — 100% обнаружение обоими методами
- **Назначение на стенде:** Демонстрация насыщенного режима. Полный выход из строя энергетики → каскад на все сектора гарантирован. Методы неразличимы (оба равно "хороши" при катастрофе).
- **Риск:** Не использовать для сравнения методов — результат тривиален.

### 🟡 Marginal Reference: S3_transport_load

- **Артефакт:** `mc_marginal_s3_load040_1000_*`
- **Параметры:** load_increase transport +40%, N=1000, theta_node=0.70, stochastic_scale=0.3
- **Результат:** K_cl=0.534, K_q=0.956, Δ=42.2pp
- **Назначение на стенде:** **Главный демонстрационный кейс.** 42.2% прогонов, которые quantitative обнаруживает, classical пропускает. FPR=0 подтверждён — classical никогда не ложно срабатывает. Зазор фундаментален: при любом theta_node K_q >> K_cl.

### 🟠 Partial Degradation: S4_water_partial

- **Артефакт:** `mc_s4_1000_*`
- **Параметры:** load_increase water +70%, N=1000, theta_node=0.70, stochastic_scale=0.3
- **Результат:** K_cl=0.416, K_q=0.876, Δ=46.0pp — крупнейший абсолютный зазор
- **Назначение на стенде:** Демонстрация зазора в сценарии с водой как источником каскада. Интересен тем, что цепочка water→energy→transport ранее обнаруживается quantitative методом через непрерывную пропагацию.

---

## Ограничения и замечания

### Аномалия S1b: cl_only случаи (146 из 1000)
В S1b_energy_partial обнаружено 146 прогонов, где I_cl=1, I_q=0 — формально нарушает утверждение "classical ⊆ quantitative".

**Объяснение:** I_q определяется как `delta_R >= delta_sector_threshold=0.1` (количественный прирост риска), а I_cl — как факт пересечения binary threshold в топологии. При минимальной нагрузке (+1%) energy иногда лишь чуть превышает theta_bin=0.70 (classical cascade fires), но суммарный delta_R < 0.1 (I_q=0). Это различие в определениях индикаторов, не нарушение теоремы.

**Для стенда:** S1b не рекомендован как основной демонстрационный сценарий (recommended_for_stand=0).

### Отсутствие временны́х рядов
`risk_trajectory_q` / `risk_trajectory_cl` в master/showcase CSV — это 2-шаговые before→after "траектории", не полные временны́е ряды. Полные временны́е серии в raw данных не сохранялись.

### run_id в S1 baseline
В `mc_baseline_theta070_1000_*` у S1 run_id начинается с 1 и совпадает с S3 run_id. При объединении датасетов используй `(scenario_name, run)` как составной ключ, не `run_id` один.

### Стохастический step_1_amount
`step_1_amount` — фактический шаг нагрузки после стохастической рандомизации (`max(0, N(load_amount, stochastic_scale*load_amount))`). Для S1_energy_outage это поле пустое (outage, не load_increase).

---

## Рекомендуемые графики для стенда

| График | Датасет | Ключевые поля |
|---|---|---|
| K_cl vs K_q bar chart | `scenarios_summary` | K_cl, K_q, scenario_name |
| Gap bar chart | `scenarios_summary` | gap_abs, gap_rel_percent |
| K_cl(theta), K_q(theta) line | `theta_sweep` | theta_node, K_cl, K_q |
| K_cl(load), K_q(load) line | `load_sweep` | load_amount, K_cl, K_q |
| K_cl(severity) vs K_q | `severity_sweep` | severity, K_cl, K_q |
| Scatter: delta_R vs step_1_amount | `threshold_analysis` (S3) | step_1_amount, delta_R, case_label |
| Before/After sector bars | `trajectories_long` | sector, step_index, risk_value, method |
| ROC: FPR vs sensitivity | `roc_analysis` | FPR, sensitivity, theta_node |
| Scatter: q_total vs cl_total | `threshold_analysis` | method_q_total_after, method_cl_total_after, I_q, I_cl |
| Case label distribution | `threshold_analysis` | scenario_name, case_label |
