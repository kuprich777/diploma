# services/scenario_simulator/config.py

import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Конфигурация Scenario Simulator — сервиса для моделирования аварий,
    сценарного анализа и Монте-Карло прогнозирования.
    """

    # --- Основная информация ---
    SERVICE_NAME: str = "Scenario Simulator Service"
    VERSION: str = "1.0.0"
    ENV: str = os.getenv("ENV", "dev")

    # URL микросервисов задаются на уровне /api/v1,
    # чтобы сценарный симулятор мог единообразно вызывать
    # доменные эндпойнты (init, simulate_outage, risk/current)
    # независимо от внутренней маршрутизации сервисов.

    # --- URL остальных микросервисов ---
    RISK_ENGINE_URL: str = os.getenv(
        "RISK_ENGINE_URL",
        "http://risk_engine:8000/api/v1"
    )

    ENERGY_SERVICE_URL: str = os.getenv(
        "ENERGY_SERVICE_URL",
        "http://energy_service:8000/api/v1"
    )

    WATER_SERVICE_URL: str = os.getenv(
        "WATER_SERVICE_URL",
        "http://water_service:8000/api/v1"
    )

    TRANSPORT_SERVICE_URL: str = os.getenv(
        "TRANSPORT_SERVICE_URL",
        "http://transport_service:8000/api/v1"
    )

    REPORTING_SERVICE_URL: str = os.getenv(
        "REPORTING_SERVICE_URL",
        "http://reporting:8000/api/v1/reporting"
    )

    # --- Параметры моделирования ---
    DEFAULT_OUTAGE_DURATION: int = 10             # минут
    SIMULATION_RUNS: int = 20                     # количество прогонов Монте-Карло
    DEFAULT_SCENARIO_ID: str = "default"
    DEFAULT_MODE: str = "real"   # real | analytic
    OUTAGE_PAUSE_SEC: float = 1.0                 # задержка перед измерением риска
    MEASUREMENT_DELAY_SEC: float = 0.5  # задержка между шагами сценария

    # --- Логирование ---
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # --- Подгрузка из .env ---
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
