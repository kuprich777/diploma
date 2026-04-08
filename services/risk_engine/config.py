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
        [0.0,    0.3246, 0.1357],  # energy зависит от water(0.3246), transport(0.1357)
        [0.0824, 0.0,    0.0199],  # water зависит от energy(0.0824), transport(0.0199)
        [0.5,    0.1998, 0.0   ],  # transport зависит от energy(0.5), water(0.1998)
    ]
    # A_calibrated_v2.0: OLS по ТЗВ-2019 (Россия), Eurostat (Германия), BEA (США)
    # Все 3 страны: знаки совпадают 6/6, Spearman ρ=0.962

    # Версия матрицы (для воспроизводимости экспериментов)
    DEPENDENCY_MATRIX_VERSION: str = os.getenv(
        "DEPENDENCY_MATRIX_VERSION",
        "v2.0"
    )

    # Разрешить ли динамическое обновление матрицы через API
    ENABLE_DYNAMIC_MATRIX: bool = True

    # --- Классический оператор: порог бинаризации узла (theta_node) ---
    # THETA_BIN is used ONLY for node binarization: y_i = I(x_i >= theta_node).
    # Classical cascade propagation uses matrix TOPOLOGY only (A[i][j] > 0),
    # NOT threshold-based edge filtering. This separates the two mechanisms.
    #
    # Rationale for 0.70:
    #   Baseline pre-shock sector risks in S1_energy_outage are approximately:
    #     energy ≈ 0.667, water ≈ 0.267, transport ≈ 0.333.
    #   theta_node = 0.70 lies just above the maximum steady-state risk (0.667),
    #   ensuring pre-shock classical state is {0,0,0} (not saturated).
    #   After an energy outage, energy risk rises to ~1.0 >> 0.70, triggering
    #   the classical cascade through all topology-connected sectors.
    #
    # Previous value was 0.25 (committed 2026-03-12), which caused pre-shock
    # saturation: all three sector risks exceeded 0.25 before any shock,
    # making classical cascade detection degenerate (K_cl=0.0).
    #
    # Override via env var THETA_BIN or POST /api/v1/risk/set_classical_threshold.
    THETA_BIN: float = float(os.getenv("THETA_BIN", "0.70"))

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
