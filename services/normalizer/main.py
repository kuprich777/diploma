# services/normalizer/main.py

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from utils.logging import setup_logging
from database import engine, ensure_schema
from models import Base
from config import settings
from routers import normalizer as normalizer_router


# --- Логирование ---
logger = setup_logging()

# --- Приложение FastAPI ---
app = FastAPI(
    title=settings.SERVICE_NAME,
    version=settings.VERSION,
    description=(
        "Normalizer Service — нормализация сырых данных из ingestor "
        "для последующей аналитики и расчёта рисков."
    ),
)

# --- Метрики Prometheus ---
Instrumentator().instrument(app).expose(app, include_in_schema=False)


# --- События приложения ---
@app.on_event("startup")
def startup_event():
    """
    Создаёт схему и таблицы normalizer при запуске.
    В дальнейшем здесь можно добавить планировщик периодической нормализации.
    """
    ensure_schema()
    Base.metadata.create_all(bind=engine)
    logger.info("🧹 normalizer_service started and schema ensured.")


# --- Health & readiness ---
@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok", "service": "normalizer"}


@app.get("/ready", tags=["system"])
async def ready():
    return {"status": "ready"}


@app.get("/", include_in_schema=False)
async def root():
    return {"message": "Normalizer Service is operational"}


# --- Маршруты доменной логики (нормализация) ---
app.include_router(normalizer_router.router)
