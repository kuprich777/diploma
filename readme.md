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
