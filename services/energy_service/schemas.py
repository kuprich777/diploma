# services/energy_service/schemas.py
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


# ----- Базовые DTO для внешнего API -----

class EnergyStatus(BaseModel):
    """Сводное состояние энергосистемы (для /status)."""
    production: float = Field(ge=0, description="Текущее производство, MW")
    consumption: float = Field(ge=0, description="Текущее потребление, MW")
    is_operational: bool = Field(description="Флаг работоспособности")


class Outage(BaseModel):
    """Параметры моделируемого сбоя (для /simulate_outage)."""
    reason: str = Field(min_length=1, max_length=255, description="Причина сбоя")
    duration: int = Field(ge=0, description="Длительность сбоя в минутах")


# ----- CRUD DTO для EnergyRecord -----

class EnergyRecordBase(BaseModel):
    production: float = Field(ge=0)
    consumption: float = Field(ge=0)
    is_operational: bool = True
    reason: Optional[str] = Field(default=None, max_length=255)
    duration: Optional[int] = Field(default=None, ge=0)


class EnergyRecordCreate(EnergyRecordBase):
    """Создание записи состояния (на будущее, если потребуется явный POST)."""
    pass


class EnergyRecordOut(EnergyRecordBase):
    """Выдача записи наружу (response_model)."""
    id: int

    # В Pydantic v2 заменяет Config.orm_mode = True
    model_config = ConfigDict(from_attributes=True)
