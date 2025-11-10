#env.py
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, text
from alembic import context

# --- Импортируем наши объекты ---
from database import Base, ENERGY_SCHEMA, ensure_schema
from models import *  # noqa: F403, импорт моделей чтобы Alembic видел metadata
from config import settings

# --- Alembic Config объект ---
config = context.config

# Если URL не прописан в alembic.ini — подставляем из окружения
db_url = os.getenv("DATABASE_URL", settings.DATABASE_URL)
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)

# Логирование Alembic
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Указываем метаданные моделей (нужно для autogenerate)
target_metadata = Base.metadata


# --- Миграции offline ---
def run_migrations_offline() -> None:
    """Запуск миграций без подключения к БД (генерация SQL)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        include_schemas=True,
        version_table_schema=ENERGY_SCHEMA,
        render_as_batch=True,
        literal_binds=True,
    )

    with context.begin_transaction():
        context.execute(f'CREATE SCHEMA IF NOT EXISTS "{ENERGY_SCHEMA}"')
        context.run_migrations()


# --- Миграции online ---
def run_migrations_online() -> None:
    """Запуск миграций с подключением к БД."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # Убеждаемся, что схема существует
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{ENERGY_SCHEMA}"'))

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            version_table_schema=ENERGY_SCHEMA,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


# --- Точка входа ---
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
