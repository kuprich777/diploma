# services/reporting/main.py

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from utils.logging import setup_logging
from config import settings
from database import engine, ensure_schema
from models import Base
from routers import reporting as reporting_router


# --- Логирование ---
logger = setup_logging()

# --- Приложение FastAPI ---
app = FastAPI(
    title=settings.SERVICE_NAME,
    version=settings.VERSION,
    description=(
        "Reporting Service — агрегированный API для визуализации результатов: "
        "состояние секторов, интегральный риск, сценарии и история."
    ),
)

# --- Метрики Prometheus ---
Instrumentator().instrument(app).expose(app, include_in_schema=False)


# --- События приложения ---
@app.on_event("startup")
def startup_event():
    """
    Если reporting будет иметь свои таблицы (кэш, агрегаты) —
    создаём схему и таблицы при старте сервиса.
    Сейчас это скелет, но он готов к расширению.
    """
    ensure_schema()
    Base.metadata.create_all(bind=engine)
    logger.info("📊 reporting_service started and schema ensured.")


# --- Health & readiness ---
@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok", "service": "reporting"}


@app.get("/ready", tags=["system"])
async def ready():
    return {"status": "ready"}


@app.get("/", include_in_schema=False)
async def root():
    return {"message": "Reporting Service is operational"}


# --- Основной роутер отчётности ---
app.include_router(reporting_router.router)
