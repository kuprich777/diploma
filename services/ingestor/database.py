import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/diploma")

INGESTOR_SCHEMA = "ingestor"

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """Базовый класс моделей SQLAlchemy для ingestor."""
    pass


def ensure_schema() -> None:
    """Создаёт схему ingestor, если она ещё не существует."""
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{INGESTOR_SCHEMA}"'))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
