# transport_service/main.py
from fastapi import FastAPI, HTTPException, Depends
from sqlalchemy.orm import Session
from . import models, database
from .database import get_db
from pydantic import BaseModel
import os
import requests

app = FastAPI()

models.Base.metadata.create_all(bind=database.engine)  # Создание таблиц

ENERGY_SERVICE_URL = os.getenv("ENERGY_SERVICE_URL", "http://energy_service:8000")

# Модели для запросов и ответов
class TransportStatus(BaseModel):
    load: float
    operational: bool
    energy_dependent: bool

class LoadUpdate(BaseModel):
    load: float

# Функции для взаимодействия с energy_service
def check_energy_status():
    try:
        response = requests.get(f"{ENERGY_SERVICE_URL}/status")
        response.raise_for_status()
        data = response.json()
        return data.get("is_operational", False)
    except requests.RequestException:
        return False

# Эндпоинты
@app.get("/")
async def root():
    return {"message": "Transport Service is operational"}

@app.get("/status", response_model=TransportStatus)
async def get_transport_status(db: Session = Depends(get_db)):
    """Возвращает текущее состояние транспортной сети"""
    record = db.query(models.TransportStatus).order_by(models.TransportStatus.id.desc()).first()
    if record:
        return TransportStatus(
            load=record.load,
            operational=record.operational,
            energy_dependent=record.energy_dependent
        )
    raise HTTPException(status_code=404, detail="No transport status found")

@app.post("/update_load")
async def update_load(update: LoadUpdate, db: Session = Depends(get_db)):
    """Обновляет загруженность транспортной сети"""
    record = db.query(models.TransportStatus).order_by(models.TransportStatus.id.desc()).first()
    if record:
        new_record = models.TransportStatus(
            load=update.load,
            operational=record.operational,
            energy_dependent=record.energy_dependent
        )
        db.add(new_record)
        db.commit()
        return {"message": "Transport load updated"}
    raise HTTPException(status_code=404, detail="No transport status found")

@app.post("/check_energy_dependency")
async def check_energy_dependency(db: Session = Depends(get_db)):
    """Проверяет зависимость транспортной системы от энергетического сервиса"""
    is_energy_operational = check_energy_status()
    record = db.query(models.TransportStatus).order_by(models.TransportStatus.id.desc()).first()
    if record:
        if not is_energy_operational:
            new_record = models.TransportStatus(
                load=record.load,
                operational=False,
                energy_dependent=True,
                reason="Energy service outage"
            )
            db.add(new_record)
            db.commit()
            return {"message": "Transport system impacted by energy outage"}
        else:
            return {"message": "Energy service is operational, no impact on transport"}
    raise HTTPException(status_code=404, detail="No transport status found")