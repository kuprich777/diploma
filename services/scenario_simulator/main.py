from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from utils.logging import setup_logging
from config import settings
from routers import simulator as simulator_router


logger = setup_logging()

app = FastAPI(
    title=settings.SERVICE_NAME,
    version=settings.VERSION,
    description="Scenario Simulator — сервис для моделирования аварий и сценариев риска",
)

# Метрики Prometheus
Instrumentator().instrument(app).expose(app, include_in_schema=False)


@app.on_event("startup")
def startup_event():
    logger.info("🎮 scenario_simulator started.")


@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok", "service": "scenario_simulator"}


@app.get("/ready", tags=["system"])
async def ready():
    return {"status": "ready"}


@app.get("/", include_in_schema=False)
async def root():
    return {"message": "Scenario Simulator is operational"}


# Подключаем роутер с бизнес-логикой (run_scenario, monte_carlo и т.п.)
app.include_router(simulator_router.router)
