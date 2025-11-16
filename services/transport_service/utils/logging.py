import sys
from loguru import logger
from config import settings


def setup_logging():
    """
    Настраивает loguru-логгер для транспортного сервиса.

    Выводится в stdout (поддержка Docker).
    Уровень логирования регулируется через settings.LOG_LEVEL.
    """
    # Удаляем стандартные обработчики
    logger.remove()

    # Формат логов
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )

    # Добавляем stdout
    logger.add(
        sys.stdout,
        colorize=True,
        format=log_format,
        level=settings.LOG_LEVEL.upper(),
        enqueue=True,        # потокобезопасность
        backtrace=False,
        diagnose=False
    )

    logger.info(f"📜 Logging initialized with level: {settings.LOG_LEVEL.upper()}")
    return logger
