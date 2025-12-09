from sqlalchemy import Integer, String, JSON, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime

from database import Base, INGESTOR_SCHEMA


class RawEvent(Base):
    """
    Сырой загруженный объект/событие.
    Его потом будет забирать normalizer.
    """
    __tablename__ = "raw_events"
    __table_args__ = {"schema": INGESTOR_SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
