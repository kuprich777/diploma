from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models import NormalizedEvent
from schemas import (
    NormalizedEventOut,
    NormalizeBatchRequest,
    NormalizeBatchResult,
    NormalizerStatus,
)
from utils.logging import setup_logging

logger = setup_logging()

router = APIRouter(prefix="/api/v1/normalizer", tags=["normalizer"])


# ---------- Служебные эндпойнты ----------


@router.get("/status", response_model=NormalizerStatus)
async def get_status(db: Session = Depends(get_db)):
    """
    Сводная информация о состоянии normalizer-сервиса:
      - сколько событий уже нормализовано
      - когда была последняя нормализация
    """
    total: int = db.query(func.count(NormalizedEvent.id)).scalar() or 0
    last_ts = db.query(func.max(NormalizedEvent.normalized_at)).scalar()

    return NormalizerStatus(
        total_normalized=total,
        last_normalized_at=last_ts,
    )


@router.get("/events", response_model=List[NormalizedEventOut])
async def list_normalized_events(
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """
    Возвращает последние N нормализованных событий.
    Полезно для отладки и для reporting-сервиса.
    """
    if limit <= 0:
        raise HTTPException(status_code=400, detail="limit must be positive")

    items = (
        db.query(NormalizedEvent)
        .order_by(NormalizedEvent.normalized_at.desc())
        .limit(limit)
        .all()
    )

    return [NormalizedEventOut.model_validate(obj) for obj in items]


# ---------- Основной бизнес-эндпоинт ----------


@router.post("/run", response_model=NormalizeBatchResult)
async def run_normalization(
    req: NormalizeBatchRequest,
    db: Session = Depends(get_db),
):
    """
    Запускает один проход нормализации.

    В будущем здесь можно:
      - забирать пачку сырых событий из сервиса ingestor (по API или напрямую из БД),
      - трансформировать их в NormalizedEvent,
      - сохранять в схему normalized.

    Сейчас реализован скелет, который просто возвращает 0 обработанных событий.
    Это валидный каркас, который можно развивать в рамках диплома.
    """
    logger.info(
        "🧹 Normalization run requested: limit=%s, source=%s",
        req.limit,
        req.source,
    )

    # TODO: реальная логика:
    # 1. забрать сырые события из ingestor (по API / БД)
    # 2. для каждого построить normalized_payload
    # 3. создать NormalizedEvent(...) и сохранить в БД
    # 4. обновить processed/created/skipped + details

    result = NormalizeBatchResult(
        processed=0,
        created=0,
        skipped=0,
        details=["Normalization logic is not implemented yet (skeleton)."],
    )

    logger.info(
        "🧹 Normalization finished: processed=%s, created=%s, skipped=%s",
        result.processed,
        result.created,
        result.skipped,
    )

    return result
