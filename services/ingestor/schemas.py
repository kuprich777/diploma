from datetime import datetime
from pydantic import BaseModel, Field
from typing import Any, Dict


class RawEventIn(BaseModel):
    """DTO для приёма сырого события от внешних источников или других сервисов."""
    source: str = Field(description="Идентификатор источника данных (service, file, etc.)")
    payload: Dict[str, Any] = Field(description="Произвольный JSON-пейлоад")


class RawEventOut(BaseModel):
    """DTO для отдачи сохранённого события наружу (например, для отладки/репортинга)."""
    id: int
    source: str
    payload: Dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True  # Pydantic v2: аналог orm_mode=True
