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
def startup_event():
    ensure_schema()
    Base.metadata.create_all(bind=engine)
    logger.info("⚙️ risk_engine started and schema ensured.")

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