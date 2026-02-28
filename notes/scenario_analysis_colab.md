# Colab notebook template: анализ результатов сценариев в CSV

Ниже — готовый **текст ячеек** для Google Colab.

> Важно: в вашем текущем `test/run_scenarios.sh` данные **печатаются в stdout** и в CSV не сохраняются автоматически. Для CSV мы будем забирать JSON-ответы API во время прогона и сохранять их в DataFrame/CSV прямо в ноутбуке.

---

## Ячейка 1 — зависимости

```python
!pip -q install pandas requests matplotlib seaborn sqlalchemy psycopg2-binary
```

---

## Ячейка 2 — импорты и конфиг

```python
import json
import requests
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime

sns.set(style="whitegrid")

BASE = "http://localhost"
PORTS = {
    "energy": 8001,
    "water": 8002,
    "transport": 8003,
    "risk": 8004,
    "sim": 8005,
}

SCENARIO_ID = "S1_energy_outage"
RUN_ID = 1001


def u(service, path):
    return f"{BASE}:{PORTS[service]}{path}"


def get_json(url, **kwargs):
    r = requests.get(url, timeout=20, **kwargs)
    r.raise_for_status()
    return r.json()


def post_json(url, json_body=None, **kwargs):
    r = requests.post(url, json=json_body, timeout=20, **kwargs)
    r.raise_for_status()
    return r.json()
```

---

## Ячейка 3 — инициализация и базовые срезы

```python
records = []

# init
records.append({"event": "init_energy", **post_json(
    u("energy", f"/api/v1/energy/init?scenario_id={SCENARIO_ID}&run_id={RUN_ID}&force=true")
)})
records.append({"event": "init_water", **post_json(
    u("water", f"/api/v1/water/init?scenario_id={SCENARIO_ID}&run_id={RUN_ID}&force=true")
)})
records.append({"event": "init_transport", **post_json(
    u("transport", f"/api/v1/transport/init?scenario_id={SCENARIO_ID}&run_id={RUN_ID}&force=true")
)})

# baseline statuses
energy_status = get_json(u("energy", f"/api/v1/energy/status?scenario_id={SCENARIO_ID}&run_id={RUN_ID}"))
water_status = get_json(u("water", f"/api/v1/water/status?scenario_id={SCENARIO_ID}&run_id={RUN_ID}"))
transport_status = get_json(u("transport", f"/api/v1/transport/status?scenario_id={SCENARIO_ID}&run_id={RUN_ID}"))

risk_before = get_json(u("risk", f"/api/v1/risk/current?scenario_id={SCENARIO_ID}&run_id={RUN_ID}&method=quantitative"))

print("energy_status:", energy_status)
print("water_status:", water_status)
print("transport_status:", transport_status)
print("risk_before:", risk_before)
```

---

## Ячейка 4 — прогон сценария и сбор данных

```python
scenario_steps = []

# инициирующее воздействие
outage_result = post_json(
    u("energy", f"/api/v1/energy/simulate_outage?scenario_id={SCENARIO_ID}&run_id={RUN_ID}&step_index=1&action=outage"),
    {"reason": "colab_test", "duration": 30}
)
scenario_steps.append({"step": "energy_outage", **outage_result})

# зависимости
water_dep = post_json(
    u("water", f"/api/v1/water/check_energy_dependency?scenario_id={SCENARIO_ID}&run_id={RUN_ID}&step_index=2&action=dependency_check")
)
transport_dep = post_json(
    u("transport", f"/api/v1/transport/check_energy_dependency?scenario_id={SCENARIO_ID}&run_id={RUN_ID}&step_index=2&action=dependency_check")
)
scenario_steps.append({"step": "water_dependency", **water_dep})
scenario_steps.append({"step": "transport_dependency", **transport_dep})

risk_after = get_json(u("risk", f"/api/v1/risk/current?scenario_id={SCENARIO_ID}&run_id={RUN_ID}&method=quantitative"))

print("outage_result:", outage_result)
print("risk_after:", risk_after)
```

---

## Ячейка 5 — Monte Carlo (главный источник табличных данных)

```python
mc = post_json(
    u("sim", "/api/v1/simulator/monte_carlo"),
    {
        "scenario_id": SCENARIO_ID,
        "sector": "energy",
        "mode": "real",
        "runs": 20,
        "start_run_id": 5000,
        "duration_min": 5,
        "duration_max": 30,
        "initiator_action": "outage"
    }
)

print("Monte Carlo summary:")
for k in ["mean_delta", "min_delta", "max_delta", "p95_delta", "K_cl", "K_q", "Delta_percent"]:
    print(k, mc.get(k))

mc_runs_df = pd.DataFrame(mc["runs_data"])
mc_runs_df.head()
```

---

## Ячейка 6 — формирование CSV

```python
# 1) шаги сценария
scenario_steps_df = pd.DataFrame(scenario_steps)

# 2) срез риска до/после
risk_df = pd.DataFrame([
    {"moment": "before", **risk_before},
    {"moment": "after", **risk_after},
])

# 3) агрегаты Monte Carlo
mc_summary_df = pd.DataFrame([{
    "scenario_id": mc["scenario_id"],
    "sector": mc["sector"],
    "runs": mc["runs"],
    "mean_delta": mc["mean_delta"],
    "min_delta": mc["min_delta"],
    "max_delta": mc["max_delta"],
    "p95_delta": mc["p95_delta"],
    "K_cl": mc["K_cl"],
    "K_q": mc["K_q"],
    "Delta_percent": mc["Delta_percent"],
}])

scenario_steps_df.to_csv("scenario_steps.csv", index=False)
risk_df.to_csv("risk_before_after.csv", index=False)
mc_runs_df.to_csv("monte_carlo_runs.csv", index=False)
mc_summary_df.to_csv("monte_carlo_summary.csv", index=False)

print("CSV created:")
print("- scenario_steps.csv")
print("- risk_before_after.csv")
print("- monte_carlo_runs.csv")
print("- monte_carlo_summary.csv")
```

---

## Ячейка 7 — простая визуализация

```python
fig, axes = plt.subplots(1, 2, figsize=(12, 4))

sns.histplot(mc_runs_df["delta"], kde=True, ax=axes[0])
axes[0].set_title("Distribution of delta")

sns.scatterplot(data=mc_runs_df, x="duration", y="delta", ax=axes[1])
axes[1].set_title("delta vs outage duration")

plt.tight_layout()
plt.show()
```

---

## Ячейка 8 (опционально) — чтение из PostgreSQL reporting schema

Если в стенде включён `reporting_service` и `scenario_simulator` успешно отправляет registry payload, то данные уже пишутся в БД в таблицы:
- `reporting.experiments`
- `reporting.experiment_runs`
- `reporting.experiment_results`

```python
from sqlalchemy import create_engine

# подставьте свой DSN
DATABASE_URL = "postgresql+psycopg2://postgres:postgres@localhost:5432/diploma"
engine = create_engine(DATABASE_URL)

query_runs = """
SELECT scenario_id, run_id, initiator, params, started_at, finished_at, is_success, error
FROM reporting.experiment_runs
ORDER BY id DESC
LIMIT 200;
"""

runs_db_df = pd.read_sql(query_runs, engine)
runs_db_df.to_csv("reporting_experiment_runs.csv", index=False)
runs_db_df.head()
```

---

## Что уже есть в вашей системе прямо сейчас

1. **CSV-файлы из коробки не формируются** при `bash test/run_scenarios.sh` — скрипт только печатает ответы `curl`.
2. **Данные для CSV уже присутствуют в JSON-ответах**, особенно `runs_data` из `/api/v1/simulator/monte_carlo`.
3. **При активном reporting-сервисе** результаты Monte Carlo экспортируются в БД (таблицы реестра экспериментов), откуда их можно выгружать в CSV SQL-запросом.
