import sys
from loguru import logger
from config import settings


def setup_logging():
    logger.remove()

    fmt = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level}</level> | "
        "<cyan>{function}:{line}</cyan> - "
        "<level>{message}</level>"
    )

    logger.add(
        sys.stdout,
        colorize=True,
        format=fmt,
        level=settings.LOG_LEVEL.upper(),
        enqueue=True,
    )

    logger.info(f"📜 Logging initialized for scenario_simulator (level={settings.LOG_LEVEL.upper()})")
    return logger
