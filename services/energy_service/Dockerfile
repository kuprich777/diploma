FROM python:3.11-slim
WORKDIR /app

# корректный многострочный ENV (без комментариев на этой строке)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

RUN apt-get update && apt-get install -y gcc libpq-dev && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir --retries 10 --timeout 120 -r requirements.txt
COPY . .

ENV SERVICE_NAME=energy_service
ENV PORT=8000

# ВАЖНО: запускаем alembic как модуль python
CMD python -m alembic upgrade head && \
    uvicorn main:app --host 0.0.0.0 --port ${PORT}
