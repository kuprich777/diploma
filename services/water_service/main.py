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
async def startup_event():
    """Создаёт схему и таблицы; подключает async messaging если включено."""
    ensure_schema()
    Base.metadata.create_all(bind=engine)
    logger.info("💧 water_service started and schema ensured.")

    if settings.ASYNC_MESSAGING_ENABLED:
        try:
            from messaging import RabbitMQConnection, subscribe
            from routers.water import set_mq, handle_energy_event
            mq = RabbitMQConnection(settings.RABBITMQ_URL)
            await mq.connect()
            set_mq(mq)
            app.state.mq = mq
            await subscribe(
                mq.channel,
                settings.RABBITMQ_EXCHANGE,
                "energy.state_changed",
                "water_service.energy_events",
                handle_energy_event,
            )
            logger.info("🐇 water_service: async messaging connected, subscribed to energy.state_changed")
        except Exception as exc:
            logger.warning(
                "⚠️  RabbitMQ unavailable — water_service running in sync-only mode: %s", exc
            )
            app.state.mq = None


@app.on_event("shutdown")
async def shutdown_event():
    mq = getattr(app.state, "mq", None)
    if mq:
        await mq.close()


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
