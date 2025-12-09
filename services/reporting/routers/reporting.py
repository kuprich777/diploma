# services/reporting/routers/reporting.py

import httpx
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import desc

from config import settings
from database import get_db
from models import SectorStatusSnapshot, RiskOverviewSnapshot
from schemas import (
    ReportingSummary,
    SectorState,
    RiskSummary,
    RiskHistoryResponse,
    RiskHistoryItem,
    SectorStatusSnapshotOut,
    RiskOverviewSnapshotOut,
    SnapshotListResponse,
)
from utils.logging import setup_logging

logger = setup_logging()

router = APIRouter(prefix="/api/v1/reporting", tags=["reporting"])

async def fetch_json(url: str, name: str):
    """Унифицированный запрос к сервисам с обработкой ошибок."""
    try:
        async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT) as client:
            resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"❌ Failed to fetch {name}: {e}")
        raise HTTPException(status_code=503, detail=f"{name} service unavailable")

@router.get("/summary", response_model=ReportingSummary)
async def summary(db: Session = Depends(get_db)):
    """
    Отдаёт:
      - текущее состояние energy/water/transport (онлайн)
      - текущий риск (онлайн)
    и сохраняет снапшоты в БД reporting.
    """

    logger.info("📊 Generating LIVE summary report")

    # 1. Получаем состояния всех секторов
    energy = await fetch_json(f"{settings.ENERGY_SERVICE_URL}/status", "energy")
    water = await fetch_json(f"{settings.WATER_SERVICE_URL}/status", "water")
    transport = await fetch_json(f"{settings.TRANSPORT_SERVICE_URL}/status", "transport")

    # 2. Получаем текущий риск
    risk = await fetch_json(f"{settings.RISK_ENGINE_URL}/current", "risk_engine")

    # 3. Формируем DTO
    sectors = [
        SectorState(name="energy", is_operational=energy["is_operational"], details=energy),
        SectorState(name="water", is_operational=water["is_operational"], details=water),
        SectorState(name="transport", is_operational=transport["is_operational"], details=transport),
    ]

    risk_summary = RiskSummary(
        energy_risk=risk["energy_risk"],
        water_risk=risk["water_risk"],
        transport_risk=risk["transport_risk"],
        total_risk=risk["total_risk"],
        calculated_at=risk["calculated_at"],
    )

    # 4. Сохраняем снапшоты в БД (кэш)
    sector_snapshot = SectorStatusSnapshot(sectors={
        "energy": energy,
        "water": water,
        "transport": transport,
    })
    risk_snapshot = RiskOverviewSnapshot(
        energy_risk=risk["energy_risk"],
        water_risk=risk["water_risk"],
        transport_risk=risk["transport_risk"],
        total_risk=risk["total_risk"],
        meta={"source": "live"}
    )

    db.add(sector_snapshot)
    db.add(risk_snapshot)
    db.commit()

    logger.info("💾 LIVE summary saved into reporting schema")

    return ReportingSummary(
        sectors=sectors,
        risk=risk_summary,
        source="live",
    )

@router.get("/risk/history", response_model=RiskHistoryResponse)
async def risk_history(limit: int = 100, db: Session = Depends(get_db)):
    """
    Возвращает историю сохранённых оценок риска.
    Отлично подходит для построения графиков.
    """
    logger.info(f"📈 Fetching risk history, limit={limit}")

    if limit <= 0:
        raise HTTPException(status_code=400, detail="limit must be positive")

    rows = (
        db.query(RiskOverviewSnapshot)
        .order_by(desc(RiskOverviewSnapshot.snapshot_at))
        .limit(limit)
        .all()
    )

    items = [
        RiskHistoryItem(
            snapshot_at=r.snapshot_at,
            energy_risk=r.energy_risk,
            water_risk=r.water_risk,
            transport_risk=r.transport_risk,
            total_risk=r.total_risk,
        )
        for r in rows
    ]

    return RiskHistoryResponse(items=items, count=len(items))

@router.get("/snapshots/sectors", response_model=SnapshotListResponse)
async def list_sector_snapshots(limit: int = 50, db: Session = Depends(get_db)):
    rows = (
        db.query(SectorStatusSnapshot)
        .order_by(desc(SectorStatusSnapshot.snapshot_at))
        .limit(limit)
        .all()
    )

    return SnapshotListResponse(
        items=[SectorStatusSnapshotOut.model_validate(r).dict() for r in rows],
        count=len(rows),
    )

@router.get("/snapshots/risk", response_model=SnapshotListResponse)
async def list_risk_snapshots(limit: int = 50, db: Session = Depends(get_db)):
    rows = (
        db.query(RiskOverviewSnapshot)
        .order_by(desc(RiskOverviewSnapshot.snapshot_at))
        .limit(limit)
        .all()
    )

    return SnapshotListResponse(
        items=[RiskOverviewSnapshotOut.model_validate(r).dict() for r in rows],
        count=len(rows),
    )
