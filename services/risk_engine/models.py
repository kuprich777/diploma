# services/risk_engine/models.py

from datetime import datetime

from sqlalchemy import Integer, Float, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, RISK_SCHEMA


class RiskSnapshot(Base):
    """
    Снимок оценок рисков по секторам инфраструктуры и интегрального риска.
    Используется для хранения истории, анализа динамики и сценарного моделирования.
    """
    __tablename__ = "risk_snapshots"
    __table_args__ = {"schema": RISK_SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Временная метка расчёта
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        index=True,
    )

    # Оценки рисков по секторам (0..1)
    energy_risk: Mapped[float] = mapped_column(Float, nullable=False)
    water_risk: Mapped[float] = mapped_column(Float, nullable=False)
    transport_risk: Mapped[float] = mapped_column(Float, nullable=False)

    # Интегральный риск (с учётом весов)
    total_risk: Mapped[float] = mapped_column(Float, nullable=False)

    # Доп. информация: веса, флаги работоспособности, параметры расчёта
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
