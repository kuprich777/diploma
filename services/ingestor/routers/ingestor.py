from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models import RawEvent
from schemas import RawEventIn, RawEventOut
from utils.logging import setup_logging

logger = setup_logging()

router = APIRouter(prefix="/api/v1/ingestor", tags=["ingestor"])


@router.post("/ingest", response_model=RawEventOut)
async def ingest_event(event: RawEventIn, db: Session = Depends(get_db)):
    """
    Приём сырого события и сохранение его в БД.
    Этим эндпойнтом могут пользоваться:
      - внешние источники,
      - internal сервисы (например, scenario_simulator),
      - скрипты загрузки исторических данных.
    """
    obj = RawEvent(
        source=event.source,
        payload=event.payload,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)

    logger.info(f"📥 Ingested raw event from source={event.source}, id={obj.id}")
    return obj


@router.get("/ping")
async def ping():
    """Простой ping для проверки доступности ingestor."""
    return {"status": "ok", "service": "ingestor"}
