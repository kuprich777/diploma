# services/energy_service/schemas.py
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


# ----- Базовые DTO для внешнего API -----

class EnergyStatus(BaseModel):
    """Сводное состояние энергосистемы (для /status)."""
    production: float = Field(ge=0, description="Текущее производство, MW")
    consumption: float = Field(ge=0, description="Текущее потребление, MW")
    is_operational: bool = Field(description="Флаг работоспособности")
    degradation: float = Field(ge=0.0, le=1.0, default=0.0, description="Нормированная деградация [0..1]")


class EnergyRisk(BaseModel):
    """Нормированный риск энергосистемы (x_E,t ∈ [0,1])."""
    sector: str = Field(default="energy", description="Идентификатор сектора")
    risk: float = Field(ge=0.0, le=1.0, description="Нормированный уровень риска")
    calculated_at: str = Field(description="Время расчёта риска")


class Outage(BaseModel):
    """Параметры моделируемого сбоя (для /simulate_outage)."""
    reason: str = Field(min_length=1, max_length=255, description="Причина сбоя")
    duration: int = Field(ge=0, description="Длительность сбоя в минутах")


class ScenarioStepResult(BaseModel):
    """Результат одного шага сценария (для экспериментов и Monte Carlo)."""
    scenario_id: str = Field(description="Идентификатор сценария")
    run_id: int = Field(description="Номер прогона Monte Carlo")
    step_index: int = Field(description="Номер шага сценария")
    sector: str = Field(description="Сектор-исполнитель действия")
    action: str = Field(description="Тип воздействия")
    risk_before: float = Field(ge=0.0, le=1.0)
    risk_after: float = Field(ge=0.0, le=1.0)
    delta: float = Field(description="Изменение риска")


# ----- CRUD DTO для EnergyRecord -----

class EnergyRecordBase(BaseModel):
    # Операционные параметры, из которых в сервисном слое вычисляется риск x_E,t
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
    scenario_id: Optional[str] = None
    run_id: Optional[int] = None
    step_index: Optional[int] = None
    action: Optional[str] = None

    # В Pydantic v2 заменяет Config.orm_mode = True
    model_config = ConfigDict(from_attributes=True)
