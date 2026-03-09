from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class WaterStatus(BaseModel):
    """
    DTO для ответа /api/v1/water/status.
    Показывает текущее состояние водного сектора.
    """
    supply: float = Field(
        ge=0,
        description="Текущий объём производства воды (например, м³/ч)"
    )
    demand: float = Field(
        ge=0,
        description="Текущий объём потребления воды (например, м³/ч)"
    )
    operational: bool = Field(
        description="Флаг работоспособности водного сектора"
    )
    energy_dependent: bool = Field(
        description="Флаг зависимости водного сектора от энергетики"
    )
    reason: Optional[str] = Field(
        default=None,
        description="Причина деградации/аварии, если есть"
    )
    degradation: float = Field(
        ge=0.0,
        le=1.0,
        default=0.0,
        description="Нормированная деградация сектора [0..1]"
    )


class WaterRisk(BaseModel):
    sector: str = Field(default="water", description="Идентификатор сектора")
    risk: float = Field(ge=0.0, le=1.0, description="Нормированный уровень риска")
    degradation: float = Field(ge=0.0, le=1.0, description="Нормированная деградация")


class SupplyUpdate(BaseModel):
    """
    Тело запроса для обновления объёма производства воды (/adjust_supply).
    """
    supply: float = Field(
        ge=0,
        description="Новый объём производства воды"
    )


class DemandUpdate(BaseModel):
    """
    Тело запроса для обновления объёма потребления воды (/adjust_demand).
    """
    demand: float = Field(
        ge=0,
        description="Новый объём потребления воды"
    )


# На будущее — если будешь отдавать ORM-модели напрямую:
class WaterStatusOut(WaterStatus):
    id: int

    # Pydantic v2: аналог orm_mode=True
    model_config = ConfigDict(from_attributes=True)
