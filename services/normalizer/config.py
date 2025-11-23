import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Конфигурация normalizer — сервиса нормализации сырых данных.
    """

    # --- Общая информация ---
    SERVICE_NAME: str = "Normalizer Service"
    VERSION: str = "1.0.0"
    ENV: str = os.getenv("ENV", "dev")

    # --- Подключение к базе ---
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@db:5432/diploma"
    )

    # --- URLs зависимостей ---
    INGESTOR_URL: str = os.getenv(
        "INGESTOR_URL",
        "http://ingestor:8000/api/v1/ingestor"
    )

    # --- Параметры обработки ---
    BATCH_SIZE: int = 100           # сколько raw_events обрабатывать за один проход
    RUN_INTERVAL_SEC: int = 10      # интервал периодической нормализации
    SKIP_IF_EMPTY: bool = True      # если нет данных — пропускаем проход

    # --- Логирование ---
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# Глобальный объект конфигурации
settings = Settings()
