# transport_service/database.py
# services/transport_service/database.py

import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# URL базы берём из переменных окружения
DATABASE_URL = os.getenv("DATABASE_URL")

# Отдельная схема для транспортного сервиса
TRANSPORT_SCHEMA = "transport"

# Движок SQLAlchemy
engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)

# Фабрика сессий
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


# Базовый класс для моделей
class Base(DeclarativeBase):
    """Базовый класс моделей SQLAlchemy."""
    pass


def ensure_schema() -> None:
    """Создаёт схему transport, если она ещё не существует."""
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{TRANSPORT_SCHEMA}"'))
        # опционально: установить search_path на время сессии
        conn.execute(text(f'SET search_path TO "{TRANSPORT_SCHEMA}", public'))


def get_db():
    """Зависимость FastAPI для работы с БД."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
