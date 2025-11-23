# services/normalizer/models.py

from datetime import datetime
from sqlalchemy import Integer, String, JSON, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, NORMALIZER_SCHEMA


class NormalizedEvent(Base):
    """
    Нормализованное событие.
    Это результат обработки raw_events из ingestor.
    Может служить входом для risk_engine или reporting.
    """
    __tablename__ = "normalized_events"
    __table_args__ = {"schema": NORMALIZER_SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # ID сырого события из ingestor.raw_events
    raw_event_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)

    # Источник данных (тот же, что в raw_event.source)
    source: Mapped[str] = mapped_column(String(100), nullable=False)

    # Нормализованный JSON — структурированные данные
    normalized_payload: Mapped[dict] = mapped_column(JSON, nullable=False)

    # Когда событие было нормализовано
    normalized_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
        index=True,
    )
