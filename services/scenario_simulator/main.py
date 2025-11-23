from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from utils.logging import setup_logging
from database import engine, ensure_schema
from models import Base
from config import settings
from routers import ingestor as ingestor_router

logger = setup_logging()

app = FastAPI(
    title=settings.SERVICE_NAME,
    version=settings.VERSION,
    description="Raw data ingestor microservice",
)

Instrumentator().instrument(app).expose(app, include_in_schema=False)


@app.on_event("startup")
def startup_event():
    ensure_schema()
    Base.metadata.create_all(bind=engine)
    logger.info("📥 ingestor_service started and schema ensured.")


@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok", "service": "ingestor"}


@app.get("/ready", tags=["system"])
async def ready():
    return {"status": "ready"}


@app.get("/", include_in_schema=False)
async def root():
    return {"message": "Ingestor Service is operational"}


app.include_router(ingestor_router.router)
