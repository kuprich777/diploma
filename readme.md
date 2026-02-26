flowchart TB

%% =========================
%% UI & Gateway Layer
%% =========================
UI["UI / Dashboard\n(Streamlit / React)"]
GATEWAY["API Gateway / Auth\n(FastAPI / Traefik)"]
UI --> GATEWAY

%% =========================
%% Domain Services
%% =========================
subgraph DOMAIN["Доменные сервисы"]
    ENERGY["energy_service\n- производство\n- сбои"]
    WATER["water_service\n- давление\n- утечки"]
    TRANSPORT["transport_service\n- загрузка\n- пропускная способность"]
end

GATEWAY --> ENERGY
GATEWAY --> WATER
GATEWAY --> TRANSPORT

%% =========================
%% Data & Processing
%% =========================
subgraph DATA["Данные и обработка"]
    INGESTOR["ingestor\n(raw events)"]
    NORMALIZER["normalizer\nочистка/унификация"]
end

INGESTOR --> NORMALIZER

%% =========================
%% Risk, Scenarios, Reporting
%% =========================
RISK["risk_engine\n- classical / quantitative\n- интегральный риск"]
SIM["scenario_simulator\n- run_scenario\n- monte_carlo"]
REPORT["reporting\n- агрегаты\n- история\n- KPI"]

ENERGY --> RISK
WATER --> RISK
TRANSPORT --> RISK
NORMALIZER --> RISK

SIM --> ENERGY
SIM --> WATER
SIM --> TRANSPORT
SIM --> RISK

RISK --> REPORT
SIM --> REPORT
REPORT --> GATEWAY

%% =========================
%% Infrastructure
%% =========================
DB[("PostgreSQL")]
ENERGY --- DB
WATER --- DB
TRANSPORT --- DB
INGESTOR --- DB
NORMALIZER --- DB
RISK --- DB
REPORT --- DB
