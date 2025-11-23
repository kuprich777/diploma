import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Конфигурация ingestor-сервиса."""

    SERVICE_NAME: str = "Ingestor Service"
    VERSION: str = "1.0.0"
    ENV: str = os.getenv("ENV", "dev")

    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@db:5432/diploma",
    )

    # Можно будет использовать для внешних источников данных
    EXTERNAL_SOURCE_URL: str = os.getenv(
        "EXTERNAL_SOURCE_URL",
        "https://example.com/data",
    )

    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
