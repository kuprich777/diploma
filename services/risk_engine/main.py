# services/risk_engine/main.py

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from utils.logging import setup_logging
from database import engine, ensure_schema
from models import Base
from config import settings
from routers import risk as risk_router  # <-- вот ЭТО важно

logger = setup_logging()

app = FastAPI(
    title=settings.SERVICE_NAME,
    version=settings.VERSION,
    description="Risk Engine — микросервис для расчёта рисков по секторам и интегрального риска",
)

Instrumentator().instrument(app).expose(app, include_in_schema=False)

@app.on_event("startup")
async def startup_event():
    ensure_schema()
    Base.metadata.create_all(bind=engine)
    logger.info("⚙️ risk_engine started and schema ensured.")

    if settings.ASYNC_MESSAGING_ENABLED:
        try:
            from messaging import RabbitMQConnection, subscribe
            from routers.risk import set_mq, handle_sector_event
            mq = RabbitMQConnection(settings.RABBITMQ_URL)
            await mq.connect()
            set_mq(mq)
            app.state.mq = mq
            # Subscribe to all three sector state-change topics
            await subscribe(
                mq.channel,
                settings.RABBITMQ_EXCHANGE,
                "energy.state_changed",
                "risk_engine.energy_events",
                handle_sector_event,
            )
            await subscribe(
                mq.channel,
                settings.RABBITMQ_EXCHANGE,
                "water.state_changed",
                "risk_engine.water_events",
                handle_sector_event,
            )
            await subscribe(
                mq.channel,
                settings.RABBITMQ_EXCHANGE,
                "transport.state_changed",
                "risk_engine.transport_events",
                handle_sector_event,
            )
            logger.info(
                "🐇 risk_engine: async messaging connected, "
                "subscribed to energy/water/transport.state_changed"
            )
        except Exception as exc:
            logger.warning(
                "⚠️  RabbitMQ unavailable — risk_engine running in sync-only mode: %s", exc
            )
            app.state.mq = None


@app.on_event("shutdown")
async def shutdown_event():
    mq = getattr(app.state, "mq", None)
    if mq:
        await mq.close()

@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok", "service": "risk_engine"}

@app.get("/ready", tags=["system"])
async def ready():
    return {"status": "ready"}

@app.get("/", include_in_schema=False)
async def root():
    return {"message": "Risk Engine is operational"}

# Подключаем КАК РОУТЕР именно тот файл, который ты показала
app.include_router(risk_router.router)