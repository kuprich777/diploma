# services/scenario_simulator/routers/simulator.py

import httpx
import asyncio
from fastapi import APIRouter, HTTPException

from config import settings
from schemas import (
    OutageScenario,
    ScenarioResult,
    MonteCarloRequest,
    MonteCarloResult
)
from utils.logging import setup_logging

logger = setup_logging()

router = APIRouter(prefix="/api/v1/simulator", tags=["scenario_simulator"])


async def fetch_risk():
    """Считываем риск из risk_engine."""
    url = settings.RISK_ENGINE_URL + "/current"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"❌ Failed to fetch risk: {e}")
        raise HTTPException(status_code=500, detail="Risk engine unavailable")


@router.post("/simulate_outage", response_model=ScenarioResult)
async def simulate_outage(scn: OutageScenario):
    """
    Стимулирует сбой в одном из доменных сервисов и измеряет изменение риска.
    """

    logger.info(f"⚠️ Running outage scenario for {scn.sector}")
    sector_url = {
        "energy": settings.ENERGY_SERVICE_URL + "/api/v1/energy/simulate_outage",
        "water": settings.WATER_SERVICE_URL + "/api/v1/water/check_energy_dependency",
        "transport": settings.TRANSPORT_SERVICE_URL + "/api/v1/transport/check_energy_dependency",
    }.get(scn.sector)

    if not sector_url:
        raise HTTPException(status_code=400, detail="Unknown sector")

    # Step 1 — baseline risk
    before_risk = await fetch_risk()

    # Step 2 — apply outage
    try:
        async with httpx.AsyncClient() as client:
            await client.post(sector_url)
    except Exception as e:
        logger.error(f"❌ Outage simulation failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to apply outage")

    # Step 3 — risk after outage
    await asyncio.sleep(1)
    after_risk = await fetch_risk()

    return ScenarioResult(
        before=before_risk["total_risk"],
        after=after_risk["total_risk"],
        sector=scn.sector,
        delta=after_risk["total_risk"] - before_risk["total_risk"]
    )


@router.post("/monte_carlo", response_model=MonteCarloResult)
async def run_monte_carlo(req: MonteCarloRequest):
    """
    Моделирует множество сценариев отказов.
    """
    results = []
    for _ in range(req.runs):
        r = await simulate_outage(
            OutageScenario(sector=req.sector, duration=req.duration)
        )
        results.append(r.delta)

    return MonteCarloResult(
        average_delta=sum(results) / len(results),
        min_delta=min(results),
        max_delta=max(results),
        samples=len(results)
    )
