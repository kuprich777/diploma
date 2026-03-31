# real_scenarios_testbed — прогон реальных сценариев через микросервисный стенд

Верификация стохастической модели системных рисков на 5 реальных инцидентах
через действующий Docker-стенд (10 микросервисов).

## Быстрый старт

```bash
# 1. Запустить стенд
cd diploma
docker-compose up -d
sleep 30

# 2. Проверить готовность
cd real_scenarios_testbed
python check_testbed.py

# 3. Прогон (≈ 10–20 мин на 5 × 200 прогонов)
python run_on_testbed.py

# 4. Сравнение с автономным скриптом
python compare_testbed_vs_standalone.py

# 5. Графики
python generate_testbed_charts.py
```

## Структура

```
real_scenarios_testbed/
├── scenarios_config.py              # конфигурация 5 сценариев (параметры API)
├── check_testbed.py                 # шаг 0: проверка доступности стенда
├── run_on_testbed.py                # шаг 2: прогон через стенд
├── compare_testbed_vs_standalone.py # шаг 3: сравнение с numpy-скриптом
├── generate_testbed_charts.py       # шаг 4: 3 графика
├── README.md
└── results/
    ├── testbed_results.json
    ├── testbed_run.log
    ├── COMPARISON_REPORT.md
    └── figures/
        ├── fig_testbed_Kcl_Kq.png
        ├── fig_testbed_vs_standalone.png
        └── fig_testbed_model_vs_reality.png
```

## 5 сценариев

| # | ID | Инициатор | MC-режим |
|---|---|---|---|
| 1 | REAL_texas_2021 | energy (outage) | MonteCarloRequest API |
| 2 | REAL_india_2012 | energy (outage) | MonteCarloRequest API |
| 3 | REAL_europe_2006 | energy (outage) | MonteCarloRequest API |
| 4 | REAL_baltimore_2024 | transport (load_increase) | MonteCarloRequest API |
| 5 | REAL_christchurch_2011 | multi (energy + water + transport) | ручной цикл ScenarioRequest |

## Особенности API стенда

### MonteCarloRequest (для 4 из 5 сценариев)
```python
POST http://localhost:8005/api/v1/scenarios/monte_carlo
{
    "scenario_id": "REAL_texas_2021",
    "sector": "energy",           # инициирующий сектор
    "runs": 200,                  # min 100
    "initiator_action": "outage",
    "duration_min": 20,
    "duration_max": 30,
    "stochastic_scale": 0.3,
    "weather_factor": 2.5,
    "load_factor": 1.4,
    "fuel_stress_factor": 1.8,
    "delta_sector_threshold": 0.1,
    "theta_classical": 0.3,
    "mode": "real"
}
```
Стенд автоматически строит шаги (outage + dep_check для всех соседей).

### ScenarioRequest (одиночный прогон / Christchurch)
```python
POST http://localhost:8005/api/v1/scenarios/run
{
    "scenario_id": "REAL_christchurch_2011",
    "run_id": 5001,
    "steps": [
        {"step_index": 1, "sector": "energy",    "action": "outage",        "params": {"duration": 25}},
        {"step_index": 2, "sector": "water",     "action": "outage",        "params": {"duration": 25}},
        {"step_index": 3, "sector": "transport", "action": "load_increase", "params": {"amount": 0.40}}
    ],
    "stochastic_scale": 0.3,
    "propagation_depth": 1
}
```
- `step_index` обязателен (ge=1)
- `action` = `"dependency_check"` (не `"dep_check"`)
- `run_id` = маленькое число (9001+), не time_ns() во избежание переполнения INT

## Ожидаемые расхождения стенд vs скрипт

| Аспект | Скрипт | Стенд |
|---|---|---|
| Оператор | clip(x + shock + A·x) | risk_engine (HTTP) |
| Веса energy→water | A=0.4 | domain=0.55 |
| Веса energy→transport | A=0.5 | domain=0.70 |
| Шум | Gaussian σ=0.03 | stochastic_scale × N(1,σ) на duration |
| Скорость | 2 с / 1000 прогонов | 10 мин / 200 прогонов |

**Критерий согласованности**: |K_q(стенд) − K_q(скрипт)| ≤ 0.05.
