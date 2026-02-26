from sqlalchemy import Integer, String, JSON, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime

from database import Base, INGESTOR_SCHEMA


class RawEvent(Base):
    """
    Сырой загруженный объект/событие.
    Его потом будет забирать normalizer.
    """
    __tablename__ = "raw_events"
    scenario_id: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True,
        doc="Идентификатор сценария вычислительного эксперимента"
    )

    run_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True,
        doc="Номер прогона Monte-Carlo"
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    __table_args__ = (
        Index(
            "ix_raw_events_scenario_run",
            "scenario_id",
            "run_id",
            "created_at",
        ),
        {"schema": INGESTOR_SCHEMA},
    )
