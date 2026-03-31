# real_scenarios — верификация модели на реальных инцидентах

Эксперимент проверяет стохастическую модель системных рисков
на 5 задокументированных каскадных инцидентах.

## Модель

```
x_{t+1} = clip[0,1](x_t + u_t + A·x_t)
```

- **x_t** — вектор риска ∈ [0,1]³ (энергетика, водоснабжение, транспорт)
- **A** — матрица межсекторального влияния (экспертная, v1.0)
- **u_t** — вектор шока (из исторических данных)
- **δ = 0.10**, **θ = 0.70**, **σ = 0.03**, **N = 1000**, **seed = 42**

## Сценарии

| № | Сценарий | Дата | Инициатор |
|---|---|---|---|
| 1 | Texas 2021 (Winter Storm Uri) | 2021-02-10 | Энергетика |
| 2 | India 2012 (Northern Grid Collapse) | 2012-07-30 | Энергетика |
| 3 | Europe 2006 (UCTE Split) | 2006-11-04 | Энергетика |
| 4 | Baltimore 2024 (Key Bridge) | 2024-03-26 | Транспорт |
| 5 | Christchurch 2011 (M6.3 earthquake) | 2011-02-22 | Множественные |

## Структура

```
real_scenarios/
├── data/
│   └── scenarios.json          # параметры и ground truth по 5 сценариям
├── results/
│   ├── experiment_results.json # результаты MC, сравнение с реальностью
│   ├── A_sensitivity.json      # чувствительность к матрице A (India 2012)
│   ├── REAL_SCENARIOS_REPORT.md
│   └── figures/
│       ├── fig1_model_vs_reality.png
│       ├── fig2_cascade_multipliers.png
│       ├── fig3_Kcl_vs_Kq_real.png
│       ├── fig4_risk_distribution.png
│       └── fig5_delta_sensitivity.png
├── run_experiment.py           # MC-прогон, сравнение, δ-sweep, A-sensitivity
├── generate_report.py          # Markdown-отчёт
├── generate_charts.py          # 5 графиков
├── requirements.txt
└── README.md
```

## Запуск

```bash
cd real_scenarios
pip install -r requirements.txt
python run_experiment.py && python generate_report.py && python generate_charts.py
```

## Источники данных (ground truth)

Все значения severity_i взяты из открытых первоисточников.
Нормировка в [0,1] задокументирована в `data/scenarios.json` (поле `source_notes`).

| Сценарий | Источник |
|---|---|
| Texas 2021 | FERC/NERC Final Report (Nov 2021); UT Austin (Jul 2021); Texas Comptroller (Oct 2021) |
| India 2012 | Central Electricity Authority, Grid Disturbance Report (Aug 2012) |
| Europe 2006 | UCTE Final Report (Jan 2007); ERGEG Report (2007) |
| Baltimore 2024 | Dulin et al. (2025), Nature Communications, doi:10.1038/s41467-025-64683-6 |
| Christchurch 2011 | Zollner et al. (2023), Reliability Engineering & System Safety |
