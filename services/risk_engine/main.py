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

    # Оценки рисков по секторам (0..1 или 0..100 — выбираешь в исследовании)
    energy_risk: Mapped[float] = mapped_column(Float, nullable=False)
    water_risk: Mapped[float] = mapped_column(Float, nullable=False)
    transport_risk: Mapped[float] = mapped_column(Float, nullable=False)

    # Интегральный риск (с учётом весов ENERGY_WEIGHT, WATER_WEIGHT, TRANSPORT_WEIGHT)
    total_risk: Mapped[float] = mapped_column(Float, nullable=False)

    # Дополнительные данные — параметры расчёта, конфигурация весов, исходные статусы
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
