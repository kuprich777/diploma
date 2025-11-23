# services/reporting/alembic/env.py

import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, text
from alembic import context

# --- Добавляем путь к корню сервиса (/app), чтобы работали импорты ---
BASE_DIR = os.path.dirname(os.path.dirname(__file__))  # -> /app
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# --- Импортируем внутренние модули reporting-сервиса ---
from database import Base, REPORTING_SCHEMA  # noqa
from models import *  # noqa: F403
from config import settings  # noqa


# --- Конфигурация Alembic ---
config = context.config

# URL БД — из окружения или из config.py
db_url = os.getenv("DATABASE_URL", settings.DATABASE_URL)
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)

# Логирование Alembic
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Метаданные моделей — по ним Alembic строит миграции
target_metadata = Base.metadata


# --- OFFLINE режим (генерация SQL без подключения к БД) ---
def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        include_schemas=True,
        version_table_schema=REPORTING_SCHEMA,
        render_as_batch=True,
        literal_binds=True,
    )

    with context.begin_transaction():
        context.execute(f'CREATE SCHEMA IF NOT EXISTS "{REPORTING_SCHEMA}"')
        context.run_migrations()


# --- ONLINE режим (с реальным подключением к БД) ---
def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{REPORTING_SCHEMA}"'))

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            version_table_schema=REPORTING_SCHEMA,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


# --- Точка входа ---
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
