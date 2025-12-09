import sys
from loguru import logger
from config import settings


def setup_logging():
    """
    Настраивает loguru-логгер для water_service.

    Пишет в stdout (чтобы Docker/Kubernetes собирали логи).
    Уровень логирования регулируется переменной окружения LOG_LEVEL.
    """

    # Удаляем все предыдущие обработчики (по умолчанию loguru пишет в stderr)
    logger.remove()

    # Формат логов
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )

    # Добавляем хендлер вывода в stdout
    logger.add(
        sys.stdout,
        colorize=True,
        format=log_format,
        level=settings.LOG_LEVEL.upper(),
        enqueue=True,        # безопасно для многопоточности/мультипроцесса
        backtrace=False,
        diagnose=False
    )

    logger.info(f"📜 Logging initialized for water_service (level={settings.LOG_LEVEL.upper()})")
    return logger
