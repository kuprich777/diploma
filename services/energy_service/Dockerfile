# --- Базовый образ ---
FROM python:3.11-slim

# --- Рабочая директория ---
WORKDIR /app

# --- Настройки среды ---
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# --- Системные зависимости ---
RUN apt-get update && apt-get install -y gcc libpq-dev && rm -rf /var/lib/apt/lists/*

# --- Копируем зависимости и устанавливаем их отдельно (кэшируется) ---
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# --- Копируем весь проект ---
COPY . .

# --- Переменные окружения ---
ENV SERVICE_NAME=energy_service
ENV PORT=8000

# --- Команда запуска ---
# Выполняем миграции перед стартом сервиса
CMD alembic upgrade head && \
    uvicorn main:app --host 0.0.0.0 --port ${PORT}
