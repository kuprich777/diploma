import sys
from loguru import logger
from config import settings


def setup_logging():
    """
    Настраивает loguru-логгер для микросервиса.

    Логи выводятся в stdout (для Docker), формат короткий и читаемый.
    Уровень логирования задаётся через settings.LOG_LEVEL.
    """
    # Удаляем дефолтные хендлеры loguru
    logger.remove()

    # Добавляем кастомный форматтер
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )

    # Добавляем stdout-вывод
    logger.add(
        sys.stdout,
        colorize=True,
        format=log_format,
        level=settings.LOG_LEVEL.upper(),
        enqueue=True,       # потокобезопасность в Docker
        backtrace=False,    # можно включить при отладке
        diagnose=False      # не показывает внутренние стеки loguru
    )

    # Пример структурного формата для интеграции с Loki/ELK (при желании)
    # logger.add(
    #     "logs/energy_service.json",
    #     serialize=True,
    #     level=settings.LOG_LEVEL.upper(),
    #     rotation="10 MB",
    #     retention="7 days"
    # )

    logger.info(f"📜 Logging initialized with level: {settings.LOG_LEVEL.upper()}")
    return logger
