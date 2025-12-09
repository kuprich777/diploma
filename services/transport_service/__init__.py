"""
transport_service — микросервис транспортного сектора.
Содержит API, модели, миграции, настройки и логику взаимодействия с Energy Service.
"""

from .config import settings
from .database import engine, Base, get_db, ensure_schema

__all__ = [
    "settings",
    "engine",
    "Base",
    "get_db",
    "ensure_schema",
]
