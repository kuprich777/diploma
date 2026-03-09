flowchart TB

%% =========================
%% UI & Gateway Layer
%% =========================
UI["UI / Dashboard
(Streamlit / React)"]

GATEWAY["API Gateway / Auth
(FastAPI / Traefik)"]

UI --> GATEWAY

%% =========================
%% Sector Services (Energy/Water/Transport)
%% =========================
subgraph SECTOR["Отраслевой слой"]
    ENERGY["energy_service
    - производство
    - сбои"]

    WATER["water_service
    - давление
    - утечки"]

    TRANSPORT["transport_service
    - загрузка
    - пропускная способность"]
end

GATEWAY --> ENERGY
GATEWAY --> WATER
GATEWAY --> TRANSPORT

%% =========================
%% Event Stream Joiner
%% =========================
JOINER["stream-joiner
(Kafka consumer)"]

ENERGY --> JOINER
WATER --> JOINER
TRANSPORT --> JOINER

%% =========================
%% Data Layer
%% =========================
subgraph DATA["Данные и обработка"]
    INGESTOR["ingestor
    (raw events)"]
    NORMALIZER["normalizer
    очистка/унификация"]
    EXTERNAL["external_data
    PPI / OECD / OPSD"]
    DATALAKE["data lake (MinIO/S3)
    raw / clean / features"]
    META["metadata_service
    catalog / lineage"]
end

JOINER --> INGESTOR
INGESTOR --> NORMALIZER
EXTERNAL --> NORMALIZER
NORMALIZER --> DATALAKE
DATALAKE --> META

%% =========================
%% ML Layer
%% =========================
subgraph ML["ML и риск-моделирование"]
    FEAST["feature-store (Feast)
    офлайн/онлайн фичи"]
    TRAIN["training_service
    MLflow training / registry"]
    RISK["risk_engine
    - правила
    - ML риск"]
end

DATALAKE --> FEAST
FEAST --> TRAIN
TRAIN --> RISK
RISK --> GATEWAY

%% =========================
%% Cross-Sector Engine
%% =========================
subgraph CROSS["Кросс-отраслевые эффекты"]
    GRAPH["dependency-graph-service
    граф зависимостей"]
    IMPACT["impact-propagation-service
    диффузия / Monte Carlo"]
    LOSS["loss-aggregator
    денежный и интегральный риск"]
    SCENARIO["scenario_simulator /
    scenario-orchestrator"]
end

RISK --> GRAPH
GRAPH --> IMPACT
IMPACT --> LOSS
LOSS --> SCENARIO
SCENARIO --> GATEWAY

JOINER --> IMPACT

%% =========================
%% Reporting & Monitoring
%% =========================
subgraph REPORT["Отчётность и контроль"]
    REPORTING["reporting
    агрегаты / история / KPI"]
    MONITOR["monitoring-service
    Prometheus / Grafana / Evidently"]
end

RISK --> REPORTING
LOSS --> REPORTING
SCENARIO --> REPORTING
REPORTING --> MONITOR
MONITOR --> GATEWAY


---

## Async Messaging Architecture

Inter-service communication for cross-sector dependency checks and risk
aggregation is handled asynchronously via **RabbitMQ** (AMQP 0-9-1).
The shared library lives in `shared/messaging.py` and is volume-mounted
read-only into each participating container at `/app/messaging.py`.

### Routing key map

| Routing key               | Publisher          | Subscribers                          |
|---------------------------|--------------------|--------------------------------------|
| `energy.state_changed`    | energy_service     | water_service, transport_service, risk_engine |
| `water.state_changed`     | water_service      | risk_engine                          |
| `transport.state_changed` | transport_service  | risk_engine                          |
| `risk.updated`            | risk_engine        | (reporting / future consumers)       |

### Exchange topology

```
Exchange : infrastructure_events   (topic, durable)
   energy.state_changed  ──►  water_service.energy_events   (durable queue)
                         ──►  transport_service.energy_events
                         ──►  risk_engine.energy_events
   water.state_changed   ──►  risk_engine.water_events
   transport.state_changed ──► risk_engine.transport_events

Exchange : infrastructure_events.dlx  (fanout, durable)
   all service queues declare x-dead-letter-exchange → dlx
   dead letters land in: infrastructure_events.dead_letters
```

### Message envelope

Every message published by any service carries:

```json
{
  "scenario_id":    "S1_energy_outage",
  "run_id":         "42",
  "version_A":      "v1.0",
  "version_w":      "v1.0",
  "sector":         "energy",
  "timestamp_step": 1712345678,
  "payload": { ... domain-specific fields ... }
}
```

### Graceful degradation

Set `ASYNC_MESSAGING_ENABLED=false` (per service) to disable the broker
path.  Water and transport services then fall back to synchronous HTTP
calls to energy_service.  Risk engine falls back to its original
parallel HTTP polling of all three sector services.

### Inspecting dead letters

```
GET http://localhost:8004/api/v1/risk/admin/dead-letters?count=20
```

Or via the RabbitMQ management UI:

```
make rabbit   # opens http://localhost:15672  (guest / guest)
```
