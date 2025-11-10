# energy_service/models.py
from sqlalchemy import String, Float, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from database import Base, ENERGY_SCHEMA


class EnergyRecord(Base):
    """
    Модель записи состояния энергетического сектора.
    Каждая запись отражает текущее состояние (производство, потребление, сбой и т.д.)
    """
    __tablename__ = "records"
    __table_args__ = {"schema": ENERGY_SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    production: Mapped[float] = mapped_column(Float, nullable=False)
    consumption: Mapped[float] = mapped_column(Float, nullable=False)
    is_operational: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
