# services/water_service/main.py

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from utils.logging import setup_logging
from database import engine, ensure_schema
from models import Base
from config import settings
from routers import water as water_router


# --- Логирование ---
logger = setup_logging()

# --- Приложение FastAPI ---
app = FastAPI(
    title=settings.SERVICE_NAME,
    version=settings.VERSION,
    description="Water sector microservice",
)

# --- Метрики Prometheus ---
Instrumentator().instrument(app).expose(app, include_in_schema=False)


# --- События приложения ---
@app.on_event("startup")
def startup_event():
    """Создаёт схему и таблицы при запуске сервиса."""
    ensure_schema()
    Base.metadata.create_all(bind=engine)
    logger.info("💧 water_service started and schema ensured.")


# --- Health & readiness ---
@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok", "service": "water_service"}


@app.get("/ready", tags=["system"])
async def ready():
    return {"status": "ready"}


@app.get("/", include_in_schema=False)
async def root():
    return {"message": "Water Service is operational"}


# --- Подключаем роутер доменной логики ---
app.include_router(water_router.router)
