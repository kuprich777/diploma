# transport_service/models.py
from sqlalchemy import Column, Integer, String, Float, Boolean
from .database import Base

class TransportStatus(Base):
    __tablename__ = "transport_status"

    id = Column(Integer, primary_key=True, index=True)
    load = Column(Float, nullable=False)  # Загруженность транспорта
    operational = Column(Boolean, default=True)  # Работоспособность системы
    energy_dependent = Column(Boolean, default=True)  # Зависимость от энергетики
    reason = Column(String, nullable=True)  # Причина сбоя, если есть
