from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import httpx

from database import get_db
from models import TransportStatus as TransportStatusModel
from schemas import TransportStatus, LoadUpdate
from utils.logging import setup_logging
from config import settings

logger = setup_logging()

router = APIRouter(prefix="/api/v1/transport", tags=["transport"])


#   Вспомогательные функции 

async def fetch_energy_operational() -> bool:
    """
    Запрашивает статус энергосервиса.
    Ожидает endpoint /api/v1/energy/status от energy_service.
    """
    energy_status_url = settings.ENERGY_SERVICE_URL.rstrip("/") + "/status"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(energy_status_url)
        resp.raise_for_status()
        data = resp.json()
        is_op = bool(data.get("is_operational", False))
        logger.debug(f"🔌 Energy service operational: {is_op}")
        return is_op
    except httpx.RequestError as e:
        logger.error(f"❌ Error connecting to Energy Service: {e}")
        return False
    except httpx.HTTPStatusError as e:
        logger.warning(f"⚠️ Energy Service returned HTTP {e.response.status_code}")
        return False



@router.post("/init")
async def init_transport_state(db: Session = Depends(get_db)):
    """
    Инициализирует базовую запись состояния транспортной системы.
    Использует дефолтные значения из config.py.
    """
    record = (
        db.query(TransportStatusModel)
        .order_by(TransportStatusModel.id.desc())
        .first()
    )
    if record:
        return {"message": "Transport state already initialized"}

    new_record = TransportStatusModel(
        load=settings.DEFAULT_LOAD,
        operational=settings.DEFAULT_OPERATIONAL,
        energy_dependent=True,
        reason=None,
    )
    db.add(new_record)
    db.commit()
    db.refresh(new_record)

    logger.info(
        f"🚚 Transport initialized: load={new_record.load}, "
        f"operational={new_record.operational}"
    )

    return {
        "message": "Transport state initialized",
        "load": new_record.load,
        "operational": new_record.operational,
    }


@router.get("/status", response_model=TransportStatus)
async def get_transport_status(db: Session = Depends(get_db)):
    """
    Возвращает текущее состояние транспортной сети.
    """
    record = (
        db.query(TransportStatusModel)
        .order_by(TransportStatusModel.id.desc())
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="No transport status found")

    return TransportStatus(
        load=record.load,
        operational=record.operational,
        energy_dependent=record.energy_dependent,
        reason=record.reason,
    )


@router.post("/update_load")
async def update_load(update: LoadUpdate, db: Session = Depends(get_db)):
    """
    Обновляет загруженность транспортной сети (без изменений зависимости от энергетики).
    """
    record = (
        db.query(TransportStatusModel)
        .order_by(TransportStatusModel.id.desc())
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="No transport status found")

    new_record = TransportStatusModel(
        load=update.load,
        operational=record.operational,
        energy_dependent=record.energy_dependent,
        reason=record.reason,
    )
    db.add(new_record)
    db.commit()
    db.refresh(new_record)

    logger.info(f"🚦 Transport load updated: {new_record.load}")
    return {"message": "Transport load updated", "load": new_record.load}


@router.post("/increase_load")
async def increase_load(amount: float, db: Session = Depends(get_db)):
    """
    Увеличивает загруженность транспортной системы на указанное значение.
    amount — величина, на которую нужно увеличить текущую загрузку.
    """
    record = (
        db.query(TransportStatusModel)
        .order_by(TransportStatusModel.id.desc())
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="No transport status found")

    new_load = max(0.0, record.load + amount)

    new_record = TransportStatusModel(
        load=new_load,
        operational=record.operational,
        energy_dependent=record.energy_dependent,
        reason=record.reason,
    )

    db.add(new_record)
    db.commit()
    db.refresh(new_record)

    logger.info(f"📈 Transport load increased by {amount}, new load={new_load}")
    return {
        "message": "Transport load increased",
        "previous_load": record.load,
        "new_load": new_load
    }


@router.post("/check_energy_dependency")
async def check_energy_dependency(db: Session = Depends(get_db)):
    """
    Проверяет зависимость транспортной системы от энергетического сервиса.
    Если Energy Service не работает — помечает транспорт как неоперационный.
    """
    record = (
        db.query(TransportStatusModel)
        .order_by(TransportStatusModel.id.desc())
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="No transport status found")

    is_energy_ok = await fetch_energy_operational()

    if not is_energy_ok:
        new_record = TransportStatusModel(
            load=record.load,
            operational=False,
            energy_dependent=True,
            reason="Energy service outage",
        )
        db.add(new_record)
        db.commit()
        db.refresh(new_record)

        logger.warning("🚨 Transport impacted by energy outage")
        return {
            "message": "Transport system impacted by energy outage",
            "operational": False,
            "reason": new_record.reason,
        }

    logger.info("✅ Energy service operational, transport not impacted")
    return {
        "message": "Energy service is operational, no impact on transport",
        "operational": record.operational,
        "reason": record.reason,
    }

@router.post("/resolve_outage")
async def resolve_outage(db: Session = Depends(get_db)):
    """
    Восстанавливает работу транспортного сектора после сбоя.
    Создаёт новую запись с operational=True и сбрасывает reason.
    """
    record = (
        db.query(TransportStatusModel)
        .order_by(TransportStatusModel.id.desc())
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="No transport status found")

    new_record = TransportStatusModel(
        load=record.load,
        operational=True,
        energy_dependent=record.energy_dependent,
        reason=None,
    )
    db.add(new_record)
    db.commit()
    db.refresh(new_record)

    logger.info("✅ Transport outage resolved, transport sector is operational again.")
    return {
        "message": "Transport outage resolved, transport sector is operational",
        "operational": new_record.operational,
    }