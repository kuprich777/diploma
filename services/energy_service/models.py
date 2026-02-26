# energy_service/models.py
from sqlalchemy import String, Float, Integer, Boolean, DateTime
from sqlalchemy.sql import func
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

    # --- Experiment traceability fields ---
    scenario_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    step_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # --- Timestamps for reproducibility/auditing ---
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Operational variables (used to compute normalized sector risk x_energy(t) in the service layer)
    production: Mapped[float] = mapped_column(Float, nullable=False)
    consumption: Mapped[float] = mapped_column(Float, nullable=False)
    is_operational: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Outage metadata (when applicable)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
