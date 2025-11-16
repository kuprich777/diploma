#services/transport_service/main.py

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from utils.logging import setup_logging
from database import engine, ensure_schema
from models import Base
from config import settings
from routers import transport as transport_router


# Логирование
logger = setup_logging()

# Приложение FastAPI
app = FastAPI(
    title=settings.SERVICE_NAME,
    version=settings.VERSION,
    description="Transport sector microservice"
)

# Метрики Prometheus
Instrumentator().instrument(app).expose(app, include_in_schema=False)


@app.on_event("startup")
def startup_event():
    """Создаёт схему, таблицы и запускает сервис."""
    ensure_schema()
    Base.metadata.create_all(bind=engine)
    logger.info("🚚 transport_service started and schema ensured.")


# Health-check endpoints
@app.get("/health", tags=["system"])
def health():
    return {"status": "ok", "service": "transport_service"}


@app.get("/ready", tags=["system"])
def ready():
    return {"status": "ready"}


@app.get("/", include_in_schema=False)
def root():
    return {"message": "Transport Service is operational"}


# Подключаем маршруты транспортного сервиса
app.include_router(transport_router.router)
