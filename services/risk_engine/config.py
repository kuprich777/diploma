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

    # --- Матрица межотраслевых зависимостей A ---
    # Базовая матрица (по умолчанию) используется как оператор A в количественной модели
    # Структура: A[i][j] — влияние сектора j на сектор i
    # Порядок секторов: [energy, water, transport]
    DEPENDENCY_MATRIX: list[list[float]] = [
        [0.0, 0.2, 0.3],   # energy зависит от water, transport
        [0.4, 0.0, 0.2],   # water зависит от energy, transport
        [0.5, 0.3, 0.0],   # transport зависит от energy, water
    ]

    # Версия матрицы (для воспроизводимости экспериментов)
    DEPENDENCY_MATRIX_VERSION: str = os.getenv(
        "DEPENDENCY_MATRIX_VERSION",
        "v1.0"
    )

    # Разрешить ли динамическое обновление матрицы через API
    ENABLE_DYNAMIC_MATRIX: bool = True

    # --- Возможность динамически обновлять веса через API ---
    # Эти параметры используются в /api/v1/risk/update_weights
    ENABLE_DYNAMIC_WEIGHTS: bool = True

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
