from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List

import httpx
import random
import statistics

from config import settings
from utils.logging import setup_logging

logger = setup_logging()
router = APIRouter(prefix="/api/v1/simulator", tags=["simulator"])


class MonteCarloRequest(BaseModel):
    sector: str = "energy"
    runs: int = 50
    duration_min: int = 5
    duration_max: int = 30


class MonteCarloRun(BaseModel):
    run: int
    before: float
    after: float
    delta: float
    duration: int


class MonteCarloResult(BaseModel):
    sector: str
    runs: int
    mean_delta: float
    min_delta: float
    max_delta: float
    p95_delta: float
    runs_data: List[MonteCarloRun]


async def fetch_risk() -> dict:
    """
    Забирает текущий интегральный риск из risk_engine.
    """

    base = settings.RISK_ENGINE_URL.rstrip("/")
    if base.endswith("/api/v1/risk"):
        url = f"{base}/current"
    else:
        url = f"{base}/api/v1/risk/current"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as e:
        logger.error(f"❌ Failed to fetch risk from {url}: {e}")
        raise HTTPException(status_code=502, detail="Risk engine is unavailable")


@router.post("/monte_carlo", response_model=MonteCarloResult)
async def run_monte_carlo(req: MonteCarloRequest):
    """\
    Моделирует множество сценариев отказов методом Монте-Карло.

    Обновлённая логика (аналитическая, без реальных вызовов outage):

    - один раз считывается текущий интегральный риск (base_risk) из risk_engine,
    - для каждого прогона случайно выбираются:
        * длительность outage в диапазоне [duration_min, duration_max],
        * тяжесть шока severity в диапазоне [0.1, 0.5] (внутренний параметр),
    - прирост риска считается по простой модели:
        delta = alpha * severity + beta * duration_norm,
      где duration_norm — нормированная длительность в [0, 1],
    - итоговый риск ограничивается в [0.0, 1.0].

    На выходе:
    - агрегированные метрики по Δ риска (mean, min, max, p95),
    - подробные результаты каждого прогона.
    """

    if req.duration_max < req.duration_min:
        raise HTTPException(status_code=400, detail="duration_max must be >= duration_min")

    logger.info(
        f"🎲 Monte-Carlo start (analytic): sector={req.sector}, runs={req.runs}, "
        f"duration=[{req.duration_min}, {req.duration_max}]"
    )

    # 1) Берём базовый интегральный риск один раз
    try:
        base_risk_json = await fetch_risk()
        base_total = float(base_risk_json.get("total_risk", 0.0))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to fetch base risk for Monte-Carlo: {e}")
        raise HTTPException(status_code=500, detail="Risk engine unavailable")

    runs_data: list[MonteCarloRun] = []
    deltas: list[float] = []

    # Параметры модели — можно вынести в config, если понадобится
    severity_min = 0.1
    severity_max = 0.5
    alpha = 0.6  # вклад тяжести шока
    beta = 0.2   # вклад длительности

    for i in range(1, req.runs + 1):
        # Случайная тяжесть шока и длительность
        severity = random.uniform(severity_min, severity_max)
        duration = random.randint(req.duration_min, req.duration_max)

        # Нормируем длительность в [0, 1]
        if req.duration_max > req.duration_min:
            duration_norm = (duration - req.duration_min) / (req.duration_max - req.duration_min)
        else:
            duration_norm = 0.0

        # Простейшая модель прироста риска
        delta = alpha * severity + beta * duration_norm

        after = base_total + delta
        # Ограничиваем риск разумными пределами
        after = max(0.0, min(1.0, after))

        effective_delta = after - base_total
        deltas.append(effective_delta)

        runs_data.append(
            MonteCarloRun(
                run=i,
                before=base_total,
                after=after,
                delta=effective_delta,
                duration=duration,
            )
        )

        logger.debug(
            f"🎲 Monte-Carlo run={i}: severity={severity:.3f}, duration={duration}, "
            f"before={base_total:.3f}, after={after:.3f}, Δ={effective_delta:.3f}"
        )

    if not deltas:
        raise HTTPException(status_code=500, detail="No Monte-Carlo runs executed")

    mean_delta = float(statistics.fmean(deltas))
    min_delta = float(min(deltas))
    max_delta = float(max(deltas))

    sorted_deltas = sorted(deltas)
    idx_95 = max(0, int(0.95 * (len(sorted_deltas) - 1)))
    p95_delta = float(sorted_deltas[idx_95])

    logger.info(
        f"🎲 Monte-Carlo done: meanΔ={mean_delta:.4f}, minΔ={min_delta:.4f}, "
        f"maxΔ={max_delta:.4f}, p95Δ={p95_delta:.4f}"
    )

    return MonteCarloResult(
        sector=req.sector,
        runs=req.runs,
        mean_delta=mean_delta,
        min_delta=min_delta,
        max_delta=max_delta,
        p95_delta=p95_delta,
        runs_data=runs_data,
    )
