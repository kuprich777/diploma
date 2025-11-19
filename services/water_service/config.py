import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Конфигурация water_service (водный сектор)."""

    # --- Общая информация ---
    SERVICE_NAME: str = "Water Service"
    VERSION: str = "1.0.0"
    ENV: str = os.getenv("ENV", "dev")

    # --- Подключение к базе ---
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@db:5432/diploma"
    )

    # --- Зависимости от других сервисов ---
    ENERGY_SERVICE_URL: str = os.getenv(
        "ENERGY_SERVICE_URL",
        "http://energy_service:8000"
    )

    # --- Начальные параметры водной системы ---
    DEFAULT_SUPPLY: float = 1000.0     # произв. воды (м³/ч)
    DEFAULT_DEMAND: float = 800.0      # потребление (м³/ч)
    DEFAULT_OPERATIONAL: bool = True   # система работает по умолчанию

    # --- Поведение сервиса ---
    ENERGY_CHECK_TIMEOUT: float = 5.0  # таймаут обращения к energy_service

    # --- Логирование ---
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# Экземпляр настроек (используется по всему сервису)
settings = Settings()
