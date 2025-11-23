# services/normalizer/database.py

import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# URL базы берём из окружения (docker-compose / .env)
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@db:5432/diploma",
)

# Отдельная схема для нормализованных данных
NORMALIZER_SCHEMA = "normalized"

# Движок SQLAlchemy
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    future=True,
)

# Фабрика сессий
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    """Базовый класс моделей SQLAlchemy для normalizer."""
    pass


def ensure_schema() -> None:
    """Создаёт схему normalized, если она ещё не существует."""
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{NORMALIZER_SCHEMA}"'))
        # опционально можно выставить search_path:
        # conn.execute(text(f'SET search_path TO "{NORMALIZER_SCHEMA}", public'))


def get_db():
    """Зависимость FastAPI для получения сессии БД."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
