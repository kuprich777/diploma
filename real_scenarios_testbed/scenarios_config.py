"""
Конфигурация 5 реальных сценариев для прогона через микросервисный стенд.

Маппинг на API стенда:
  - Для energy/water-инициаторов с dep_check → MonteCarloRequest(sector=..., initiator_action="outage")
  - Для transport load_increase → MonteCarloRequest(sector="transport", initiator_action="load_increase")
  - Для Christchurch (multi-initiator) → ручной цикл по ScenarioRequest с кастомными шагами

Ключевые различия:
  MonteCarloRequest строит шаги АВТОМАТИЧЕСКИ по sector + initiator_action.
  Для dep_check шаги добавляются самим стендом при sector="energy" + initiator_action="outage".
  Кастомные шаги (multi-sector) возможны только через ScenarioRequest.
"""

# ---------------------------------------------------------------------------
# Формат MonteCarloRequest (sector-based, для 4 из 5 сценариев)
# ---------------------------------------------------------------------------
# Обязательные поля:
#   scenario_id: str
#   sector: "energy" | "water" | "transport"
#   runs: int (min 100)
#   initiator_action: "outage" | "load_increase"
#   duration_min / duration_max: int
#   stochastic_scale: float
#   weather_factor, load_factor, fuel_stress_factor: float
#   delta_sector_threshold: float (= δ)
#   theta_classical: float (= θ_cascade)

REAL_SCENARIOS: dict = {
    "REAL_texas_2021": {
        "name": "Texas 2021 (Winter Storm Uri)",
        "source": "FERC/NERC (2021), Texas Comptroller (2021)",
        "mc_mode": "api",          # использовать MonteCarloRequest
        "initiator": "energy",
        "ground_truth": {
            "severity": {"energy": 0.90, "water": 0.49, "transport": 0.75},
            "damage_usd": "80-195 billion",
            "source_detail": (
                "28,345 MW deficit / 77,000 MW installed capacity = 36.8%; "
                "demand spike factor → effective shock 68%. "
                "water: 49% boil-water systems (Texas TCEQ). "
                "transport: TxDOT mobility index −75%."
            ),
        },
        # MonteCarloRequest fields
        "mc_params": {
            "sector": "energy",
            "initiator_action": "outage",
            "runs": 200,
            "stochastic_scale": 0.3,
            "weather_factor": 2.5,       # экстремальный холод (−20°F)
            "load_factor": 1.4,          # пиковый спрос +40% выше нормы
            "fuel_stress_factor": 1.8,   # замерзание газопроводов
            "duration_min": 20,
            "duration_max": 30,
            "propagation_depth": 1,
            "delta_sector_threshold": 0.1,
            "theta_classical": 0.3,
        },
        # ScenarioRequest steps (для одиночного детального прогона)
        "single_steps": [
            {"step_index": 1, "sector": "energy", "action": "outage",
             "params": {"duration": 30, "reason": "winter_storm_uri"}},
            {"step_index": 2, "sector": "water", "action": "dependency_check",
             "params": {"source_sector": "energy", "source_duration": 30}},
            {"step_index": 3, "sector": "transport", "action": "dependency_check",
             "params": {"source_sector": "energy", "source_duration": 30}},
        ],
        "single_params": {
            "weather_factor": 2.5,
            "load_factor": 1.4,
            "fuel_stress_factor": 1.8,
            "stochastic_scale": 0.0,    # детерминированный прогон
            "propagation_depth": 1,
        },
    },

    "REAL_india_2012": {
        "name": "India 2012 (Northern Grid Collapse)",
        "source": "Central Electricity Authority, Grid Disturbance Report 2012",
        "mc_mode": "api",
        "initiator": "energy",
        "ground_truth": {
            "severity": {"energy": 0.58, "water": 0.30, "transport": 0.40},
            "damage_usd": "~0.1B direct; 620M people affected",
            "source_detail": (
                "48 GW / 82 GW Northern Region installed capacity = 0.585. "
                "water: UN-Habitat survey Aug 2012 ~30% urban piped systems. "
                "transport: 300/900 trains halted + Delhi Metro = 0.40."
            ),
        },
        "mc_params": {
            "sector": "energy",
            "initiator_action": "outage",
            "runs": 200,
            "stochastic_scale": 0.3,
            "weather_factor": 1.5,       # жара, перегрузка (42°C)
            "load_factor": 1.3,          # пиковое потребление
            "fuel_stress_factor": 1.0,
            "duration_min": 15,
            "duration_max": 25,
            "propagation_depth": 1,
            "delta_sector_threshold": 0.1,
            "theta_classical": 0.3,
        },
        "single_steps": [
            {"step_index": 1, "sector": "energy", "action": "outage",
             "params": {"duration": 25, "reason": "northern_grid_collapse"}},
            {"step_index": 2, "sector": "water", "action": "dependency_check",
             "params": {"source_sector": "energy", "source_duration": 25}},
            {"step_index": 3, "sector": "transport", "action": "dependency_check",
             "params": {"source_sector": "energy", "source_duration": 25}},
        ],
        "single_params": {
            "weather_factor": 1.5,
            "load_factor": 1.3,
            "fuel_stress_factor": 1.0,
            "stochastic_scale": 0.0,
            "propagation_depth": 1,
        },
    },

    "REAL_europe_2006": {
        "name": "Europe 2006 (UCTE Split)",
        "source": "UCTE Final Report 2007; ERGEG 2007",
        "mc_mode": "api",
        "initiator": "energy",
        "ground_truth": {
            "severity": {"energy": 0.25, "water": 0.15, "transport": 0.10},
            "damage_usd": "~1.5 billion",
            "source_detail": (
                "10 GW imbalance / 40 GW western zone load = 0.25 (UCTE p.19). "
                "water: localised pump-station trips ~15% (ERGEG 2007). "
                "transport: Eurocontrol + DB/SNCF/FS electric trains ~15 min = 0.10."
            ),
        },
        "mc_params": {
            "sector": "energy",
            "initiator_action": "outage",
            "runs": 200,
            "stochastic_scale": 0.2,
            "weather_factor": 1.0,
            "load_factor": 1.0,
            "fuel_stress_factor": 1.0,
            "duration_min": 5,
            "duration_max": 15,
            "propagation_depth": 1,
            "delta_sector_threshold": 0.1,
            "theta_classical": 0.3,
        },
        "single_steps": [
            {"step_index": 1, "sector": "energy", "action": "outage",
             "params": {"duration": 10, "reason": "ucte_split"}},
            {"step_index": 2, "sector": "water", "action": "dependency_check",
             "params": {"source_sector": "energy", "source_duration": 10}},
            {"step_index": 3, "sector": "transport", "action": "dependency_check",
             "params": {"source_sector": "energy", "source_duration": 10}},
        ],
        "single_params": {
            "weather_factor": 1.0,
            "load_factor": 1.0,
            "fuel_stress_factor": 1.0,
            "stochastic_scale": 0.0,
            "propagation_depth": 1,
        },
    },

    "REAL_baltimore_2024": {
        "name": "Baltimore Key Bridge 2024",
        "source": "Dulin et al. (2025), Nature Communications",
        "mc_mode": "api",
        "initiator": "transport",    # НЕ энергетика — транспорт
        "ground_truth": {
            "severity": {"energy": 0.05, "water": 0.02, "transport": 0.30},
            "cascade_multiplier": 1.30,
            "damage_usd": "2.2B total (direct 1.7B + cascade 0.5B)",
            "source_detail": (
                "Port of Baltimore = 30% of Baltimore MSA freight GDP → shock_transport=0.30. "
                "Dulin et al. (2025) Table 2. energy: fuel delivery disruption ~5% (Suppl. S3). "
                "water: ~2% (MDEQ press release Mar 27 2024)."
            ),
        },
        "mc_params": {
            "sector": "transport",
            "initiator_action": "load_increase",
            "load_amount": 0.30,
            "runs": 200,
            "stochastic_scale": 0.15,
            "weather_factor": 1.0,
            "load_factor": 1.0,
            "fuel_stress_factor": 1.0,
            "duration_min": 10,
            "duration_max": 20,
            "propagation_depth": 1,
            "delta_sector_threshold": 0.1,
            "theta_classical": 0.3,
        },
        "single_steps": [
            {"step_index": 1, "sector": "transport", "action": "load_increase",
             "params": {"amount": 0.30}},
            {"step_index": 2, "sector": "energy", "action": "dependency_check",
             "params": {"source_sector": "transport", "source_duration": 15}},
            {"step_index": 3, "sector": "water", "action": "dependency_check",
             "params": {"source_sector": "transport", "source_duration": 15}},
        ],
        "single_params": {
            "weather_factor": 1.0,
            "load_factor": 1.0,
            "fuel_stress_factor": 1.0,
            "stochastic_scale": 0.0,
            "propagation_depth": 1,
        },
    },

    "REAL_christchurch_2011": {
        "name": "Christchurch 2011 (M6.3 Earthquake)",
        "source": "Zollner et al. (2023), Reliability Engineering & System Safety",
        "mc_mode": "manual",   # MonteCarloRequest не поддерживает multi-sector — ручной цикл
        "initiator": "multi",
        "ground_truth": {
            "severity": {"energy": 0.40, "water": 0.80, "transport": 0.50},
            "cascade_multiplier": 2.0,
            "damage_usd": "~40 billion NZD",
            "source_detail": (
                "Orion Networks: 40% supply loss at t=0 (Section 4.2). "
                "Canterbury RC: 80% pipe network damaged (Table 3). "
                "NZTA: 50% road network closed (Table 3). "
                "Zollner (2023) cascade range 1.71–2.31 → midpoint 2.0."
            ),
        },
        # Для ручного MC: N прогонов через ScenarioRequest с кастомными шагами
        "mc_manual_runs": 200,
        "mc_stochastic_scale": 0.3,
        "mc_start_run_id": 5001,  # изоляция по run_id
        # Шаги с параметрами (stochastic_scale применяется в ScenarioRequest)
        # ПРИМЕЧАНИЕ: water service не поддерживает action="outage" (нет /simulate_outage).
        # Используем load_increase с высоким amount=0.70 для имитации 80% потери
        # водоснабжения — аппроксимация прямого удара через повышенную нагрузку.
        "single_steps": [
            {"step_index": 1, "sector": "energy", "action": "outage",
             "params": {"duration": 25, "reason": "earthquake_m63"}},
            {"step_index": 2, "sector": "water", "action": "load_increase",
             "params": {"amount": 0.70}},
            {"step_index": 3, "sector": "transport", "action": "load_increase",
             "params": {"amount": 0.40}},
        ],
        "single_params": {
            "weather_factor": 1.0,
            "load_factor": 1.5,
            "fuel_stress_factor": 1.2,
            "stochastic_scale": 0.0,
            "propagation_depth": 1,
        },
        # Параметры для ручного MC (stochastic добавляется в ScenarioRequest)
        "mc_step_params": {
            "weather_factor": 1.0,
            "load_factor": 1.5,
            "fuel_stress_factor": 1.2,
            "propagation_depth": 1,
        },
        "mc_params": {
            # Для единообразия интерфейса — параметры delta/theta для post-processing
            "delta_sector_threshold": 0.1,
            "theta_classical": 0.3,
        },
    },
}

# Порядок прогона (воспроизводимый)
SCENARIO_ORDER = [
    "REAL_texas_2021",
    "REAL_india_2012",
    "REAL_europe_2006",
    "REAL_baltimore_2024",
    "REAL_christchurch_2011",
]

# Базовый run_id для одиночных прогонов (безопасно избегает переполнения time_ns())
SINGLE_RUN_BASE_ID = 9001
