# water_service/models.py
from sqlalchemy import Column, Integer, String, Float, Boolean
from .database import Base

class WaterStatus(Base):
    __tablename__ = "water_status"

    id = Column(Integer, primary_key=True, index=True)
    water_level = Column(Float, nullable=False)  # Уровень воды
    operational = Column(Boolean, default=True)  # Работоспособность системы
    energy_dependent = Column(Boolean, default=True)  # Зависимость от энергетики
    reason = Column(String, nullable=True)  # Причина сбоя, если есть
