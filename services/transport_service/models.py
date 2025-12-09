from sqlalchemy import String, Float, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, TRANSPORT_SCHEMA


class TransportStatus(Base):
    """
    Снимок состояния транспортной системы.
    Каждая запись фиксирует загрузку, состояние и зависимость от энергетического сектора.
    """
    __tablename__ = "status"
    __table_args__ = {"schema": TRANSPORT_SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    load: Mapped[float] = mapped_column(Float, nullable=False)               # загруженность
    operational: Mapped[bool] = mapped_column(Boolean, default=True)        # система доступна
    energy_dependent: Mapped[bool] = mapped_column(Boolean, default=True)   # зависит от EnergyService
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)  # причина сбоя
