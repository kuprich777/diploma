# services/water_service/database.py

import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# URL базы берём из переменных окружения (подставится из docker-compose или .env)
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/diploma")

# Отдельная схема для водного сервиса
WATER_SCHEMA = "water"

# Движок SQLAlchemy
engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)

# Фабрика сессий
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """Базовый класс моделей SQLAlchemy для water_service."""
    pass


def ensure_schema() -> None:
    """Создаёт схему water, если она ещё не существует."""
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{WATER_SCHEMA}"'))
        # при желании можно установить search_path, но это не обязательно
        # conn.execute(text(f'SET search_path TO "{WATER_SCHEMA}", public'))


def get_db():
    """Зависимость FastAPI для получения сессии БД."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
