import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Конфигурация risk_engine — ядра расчёта инфраструктурных рисков.
    """

    # --- Основная информация ---
    SERVICE_NAME: str = "Risk Engine Service"
    VERSION: str = "1.0.0"
    ENV: str = os.getenv("ENV", "dev")

    # --- Подключение к БД ---
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@db:5432/diploma"
    )

    # --- URLs доменных сервисов ---
    ENERGY_SERVICE_URL: str = os.getenv(
        "ENERGY_SERVICE_URL",
        "http://energy_service:8000/api/v1/energy/status"
    )

    WATER_SERVICE_URL: str = os.getenv(
        "WATER_SERVICE_URL",
        "http://water_service:8000/api/v1/water/status"
    )

    TRANSPORT_SERVICE_URL: str = os.getenv(
        "TRANSPORT_SERVICE_URL",
        "http://transport_service:8000/api/v1/transport/status"
    )

    # --- Веса секторов в интегральном риске ---
    # эти параметры важны для твоего диплома
    ENERGY_WEIGHT: float = 0.4
    WATER_WEIGHT: float = 0.3
    TRANSPORT_WEIGHT: float = 0.3

    # --- Настройки поведения ---
    REQUEST_TIMEOUT: float = 5.0     # таймаут запросов к сервисам
    RETRIES: int = 2                 # количество ретраев при ошибках

    # --- Логирование ---
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # --- Файл .env ---
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
