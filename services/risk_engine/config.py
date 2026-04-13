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
        [0.0,   0.350, 0.304],  # energy зависит от water(0.350), transport(0.304)
        [0.006, 0.0,   0.001],  # water зависит от energy(0.006), transport(0.001)
        [0.500, 0.332, 0.0  ],  # transport зависит от energy(0.500), water(0.332)
    ]
    # A_wiod_v3: WIOD 2016 NIOT (Leontief direct requirements, нулевая диагональ,
    # rescale max off-diagonal = 0.5). Страны: RUS+DEU+USA, год 2014.
    # Секторы: Energy=D35, Water=E36, Transport=H49-H53 (агрегат).
    # Spearman ρ(A_wiod_v3, A_calibrated_v2.0) = 1.000 — одинаковый ранговый порядок.
    # Источник: matrix_doc/A_calibrated_wiod.json, скрипт matrix_doc/calibrate_wiod.py.

    # Версия матрицы (для воспроизводимости экспериментов)
    DEPENDENCY_MATRIX_VERSION: str = os.getenv(
        "DEPENDENCY_MATRIX_VERSION",
        "v3.0"
    )

    # Разрешить ли динамическое обновление матрицы через API
    ENABLE_DYNAMIC_MATRIX: bool = True

    # --- Классический оператор: порог бинаризации узла (theta_node) ---
    # THETA_BIN is used ONLY for node binarization: y_i = I(x_i >= theta_node).
    # Classical cascade propagation uses matrix TOPOLOGY only (A[i][j] > 0),
    # NOT threshold-based edge filtering. This separates the two mechanisms.
    #
    # Rationale for 0.75 (A_calibrated v2.0 recalibration, 2026-04-09):
    #   Baseline pre-shock sector risks (A_calibrated v2.0):
    #     energy ≈ 0.667, water ≈ 0.000, transport ≈ 0.333.
    #   theta_node = 0.75 is the empirically calibrated optimal:
    #   - Minimum θ where K_cl > 0 (classical is non-degenerate) AND
    #     K_q > K_cl (H₁ satisfied) for BOTH S3 (transport) and S4 (water).
    #   - theta_sweep N=500: at θ=0.70 → S3 K_cl=0.478 > K_q=0.390 (H₁ violated);
    #     at θ=0.75 → S3 K_cl=0.344 < K_q=0.390 ✓, S4 K_cl=0.344 < K_q=0.796 ✓.
    #   - For θ∈[0.50..0.65]: K_cl=0 (classical always below baseline, degenerate).
    #
    # Previous value: 0.70 (set for A_expert v1.0, transport risk 1−e^(−3×0.40)=0.699
    # is right at threshold → stochastic oscillation causes K_cl >> K_q for S3).
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
