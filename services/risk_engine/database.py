# services/risk_engine/database.py

import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# URL базы: берём из окружения (docker-compose / .env)
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@db:5432/diploma"
)

# Отдельная схема для risk_engine
RISK_SCHEMA = "risk"

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
    """Базовый класс моделей SQLAlchemy для risk_engine."""
    pass


def ensure_schema() -> None:
    """Создаёт схему risk, если она ещё не существует."""
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{RISK_SCHEMA}"'))
        # при желании можно выставить search_path:
        # conn.execute(text(f'SET search_path TO "{RISK_SCHEMA}", public'))


def get_db():
    """Зависимость FastAPI для получения сессии БД."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
