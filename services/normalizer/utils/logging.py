import sys
from loguru import logger
from config import settings


def setup_logging():
    """
    Настраивает loguru-логгер для normalizer.

    Логи идут в stdout (Docker-friendly),
    уровень берём из settings.LOG_LEVEL.
    """
    logger.remove()

    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )

    logger.add(
        sys.stdout,
        colorize=True,
        format=log_format,
        level=settings.LOG_LEVEL.upper(),
        enqueue=True,
        backtrace=False,
        diagnose=False,
    )

    logger.info(
        f"📜 Logging initialized for normalizer (level={settings.LOG_LEVEL.upper()})"
    )
    return logger
