import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Конфигурация микросервиса energy_service.
    Загружается из переменных окружения (.env) или docker-compose.
    """

    # --- Общая информация ---
    SERVICE_NAME: str = "energy_service"
    VERSION: str = "1.0.0"
    ENV: str = os.getenv("ENV", "dev")

    # --- Подключения ---
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@db:5432/diploma"
    )

    # --- Начальные параметры модели ---
    DEFAULT_PRODUCTION: float = 1000.0
    DEFAULT_CONSUMPTION: float = 900.0

    # --- Вероятность и параметры сбоя ---
    OUTAGE_PROBABILITY: float = 0.1       # Вероятность сбоя (10%)
    OUTAGE_DURATION_MIN: int = 5          # мин. длительность сбоя (мин)
    OUTAGE_DURATION_MAX: int = 60         # макс. длительность сбоя (мин)

    # --- Параметры нормализации риска (используются в routers/energy.py) ---
    MAX_OUTAGE_DURATION: int = 60
    OUTAGE_BASE_RISK: float = 0.5
    OUTAGE_DURATION_WEIGHT: float = 0.5
    UTILIZATION_LOW: float = 0.7
    UTILIZATION_HIGH: float = 1.0

    # --- Логирование ---
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # --- Метрики / API ---
    METRICS_ENABLED: bool = True
    METRICS_PATH: str = "/metrics"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# Единый экземпляр конфигурации для импорта
settings = Settings()
