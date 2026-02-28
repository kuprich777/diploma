# services/reporting/Dockerfile

FROM python:3.11-slim

# Рабочая директория внутри контейнера
WORKDIR /app

# Базовые настройки Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

# Системные зависимости (для psycopg2 и т.п.)
RUN apt-get update && apt-get install -y gcc libpq-dev && rm -rf /var/lib/apt/lists/*

# Устанавливаем зависимости
COPY requirements.txt .
RUN set -eux; \
    for attempt in 1 2 3; do \
      pip install --no-cache-dir --retries 10 --timeout 120 -r requirements.txt && break; \
      if [ "$attempt" -eq 3 ]; then \
        echo "pip install failed after ${attempt} attempts"; \
        exit 1; \
      fi; \
      echo "pip install failed on attempt ${attempt}, retrying..."; \
      sleep 5; \
    done

# Копируем исходники сервиса
COPY . .

# Переменные окружения по умолчанию
ENV SERVICE_NAME=reporting_service
ENV PORT=8000

# Сначала применяем миграции Alembic, потом стартуем FastAPI через uvicorn
CMD python -m alembic upgrade head && \
    uvicorn main:app --host 0.0.0.0 --port ${PORT}
