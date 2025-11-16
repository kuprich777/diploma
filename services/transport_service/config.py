import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Конфигурация транспортного сервиса (загружается из .env)."""

    # --- Основная информация ---
    SERVICE_NAME: str = "Transport Service"
    VERSION: str = "1.0.0"
    ENV: str = os.getenv("ENV", "dev")

    # --- Подключения ---
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@db:5432/diploma"
    )

    # --- URLs других микросервисов ---
    ENERGY_SERVICE_URL: str = os.getenv(
        "ENERGY_SERVICE_URL",
        "http://energy_service:8000"
    )

    # --- Начальные значения транспортной системы ---
    DEFAULT_LOAD: float = 0.0                 # начальная загруженность
    DEFAULT_OPERATIONAL: bool = True          # изначально система рабочая

    # --- Поведение ---
    ENERGY_CHECK_TIMEOUT: float = 5.0         # таймаут запроса в energy_service

    # --- Логирование ---
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# Экземпляр настроек, который можно импортировать
settings = Settings()
