from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


# ------------------------------------------------------------
#  СХЕМЫ ВХОДА ОТ ДОМЕННЫХ СЕРВИСОВ
# ------------------------------------------------------------

class SectorStatus(BaseModel):
    """
    Унифицированная модель статуса сектора.
    Ожидаем, что energy/water/transport сервисы вернут объекты этой структуры.
    """
    is_operational: bool = Field(description="Флаг работоспособности сектора")
    # Дополнительные поля могут добавляться позже (production, demand, load, etc.)
    # но для risk_engine важен только operational — базовый триггер риска.


# ------------------------------------------------------------
#  РИСКИ ПО СЕКТОРАМ
# ------------------------------------------------------------

class SectorRisk(BaseModel):
    """
    Риск одного сектора в нормализованном виде.
    Risk ∈ [0;1], где:
      0  = всё идеально
      1  = полный отказ сектора
    """
    name: str = Field(description="Название сектора (energy/water/transport)")
    risk: float = Field(ge=0, le=1, description="Нормализованный риск сектора")


class AggregatedRisk(BaseModel):
    """
    Интегральный риск всей инфраструктуры.
    """
    energy_risk: float = Field(ge=0, le=1)
    water_risk: float = Field(ge=0, le=1)
    transport_risk: float = Field(ge=0, le=1)
    total_risk: float = Field(ge=0, le=1, description="Итоговый агрегированный риск")

    calculated_at: datetime = Field(
        description="Время расчёта интегрального риска",
        default_factory=datetime.utcnow
    )


# ------------------------------------------------------------
#  СХЕМЫ ДЛЯ ORM-МОДЕЛИ RiskSnapshot
# ------------------------------------------------------------

class RiskSnapshotOut(BaseModel):
    """
    DTO для отдачи истории рисков.
    """
    id: int
    calculated_at: datetime

    energy_risk: float
    water_risk: float
    transport_risk: float

    total_risk: float

    meta: Optional[dict] = None

    model_config = ConfigDict(from_attributes=True)  # Pydantic v2: ORM mode


class RiskHistory(BaseModel):
    """
    Коллекция исторических оценок риска.
    """
    items: list[RiskSnapshotOut]
    count: int = Field(description="Количество элементов в истории")


# ------------------------------------------------------------
#  DTO ДЛЯ РУЧНОГО ПЕРЕСЧЁТА
# ------------------------------------------------------------

class RiskRecalcRequest(BaseModel):
    """
    Тело запроса для ручного пересчёта риска.
    Можно добавить в будущем поля типа:
        - override weights
        - simulate outages
    """
    save: bool
