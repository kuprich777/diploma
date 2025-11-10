import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# Читаем URL из переменных окружения
DATABASE_URL = os.getenv("DATABASE_URL")
ENERGY_SCHEMA = "energy"

# Создаём движок с пингом (устойчивость к сбоям соединений)
engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)

# Сессия
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

# Базовый класс моделей
class Base(DeclarativeBase):
    """Базовый класс для моделей SQLAlchemy"""
    pass


def ensure_schema():
    """Создаёт схему energy, если её нет"""
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{ENERGY_SCHEMA}"'))
        conn.execute(text(f'SET search_path TO "{ENERGY_SCHEMA}", public'))


def get_db():
    """Зависимость FastAPI для работы с БД"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
