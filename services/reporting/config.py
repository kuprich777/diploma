# services/reporting/config.py

import os
from pathlib import Path
from pydantic_settings import BaseSettings


def _default_reports_dir() -> str:
    """Возвращает безопасный путь для каталога отчётов.

    В dev-окружении репозитория можно подняться до корня проекта и использовать
    `<repo>/reporting`. В контейнере файл часто лежит как `/app/config.py`, где
    `parents[2]` недоступен — тогда используем `/app/reporting`.
    """
    config_path = Path(__file__).resolve()
    project_root = config_path.parents[2] if len(config_path.parents) > 2 else config_path.parent
    return str(project_root / "reporting")


class Settings(BaseSettings):
    """
    Конфигурация Reporting Service — сервис агрегированной аналитики.
    Собирает информацию из energy/water/transport, risk_engine, normalizer
    и scenario_simulator.
    """

    # --- Основная информация ---
    SERVICE_NAME: str = "Reporting Service"
    VERSION: str = "1.0.0"
    ENV: str = os.getenv("ENV", "dev")

    # --- Подключение к БД ---
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@db:5432/diploma"
    )

    # --- URL микросервисов ---
    ENERGY_SERVICE_URL: str = os.getenv(
        "ENERGY_SERVICE_URL",
        "http://energy_service:8000/api/v1/energy"
    )
    WATER_SERVICE_URL: str = os.getenv(
        "WATER_SERVICE_URL",
        "http://water_service:8000/api/v1/water"
    )
    TRANSPORT_SERVICE_URL: str = os.getenv(
        "TRANSPORT_SERVICE_URL",
        "http://transport_service:8000/api/v1/transport"
    )

    RISK_ENGINE_URL: str = os.getenv(
        "RISK_ENGINE_URL",
        "http://risk_engine:8000/api/v1/risk"
    )

    NORMALIZER_URL: str = os.getenv(
        "NORMALIZER_URL",
        "http://normalizer:8000/api/v1/normalizer"
    )

    SIMULATOR_URL: str = os.getenv(
        "SIMULATOR_URL",
        "http://scenario_simulator:8000/api/v1/simulator"
    )

    # --- Настройки запросов ---
    REQUEST_TIMEOUT: float = 5.0
    RETRIES: int = 2

    # --- Файловое хранилище отчётов (в корне проекта /reporting) ---
    REPORTS_DIR: str = os.getenv(
        "REPORTS_DIR",
        _default_reports_dir(),
    )

    # --- Логирование ---
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
