from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict


# ------------------------------------------------------------
#  БАЗОВЫЕ DTO ДЛЯ СНАПШОТОВ
# ------------------------------------------------------------

class SectorStatusSnapshotOut(BaseModel):
    """
    DTO для отдачи снимка состояния всех секторов.
    Обёртка над моделью SectorStatusSnapshot.
    """
    id: int
    snapshot_at: datetime
    sectors: Dict[str, Any]

    model_config = ConfigDict(from_attributes=True)


class RiskOverviewSnapshotOut(BaseModel):
    """
    DTO для отдачи кэшированного снимка агрегированного риска.
    Обёртка над моделью RiskOverviewSnapshot.
    """
    id: int
    snapshot_at: datetime

    energy_risk: float
    water_risk: float
    transport_risk: float
    total_risk: float

    meta: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------
#  СВОДНЫЕ ОТЧЁТЫ
# ------------------------------------------------------------

class SectorState(BaseModel):
    """
    Унифицированное представление состояния одного сектора.
    Используется в summary-ответах.
    """
    name: str = Field(description="Название сектора: energy | water | transport")
    is_operational: bool = Field(description="Флаг работоспособности сектора")
    details: Dict[str, Any] = Field(
        default_factory=dict,
        description="Произвольные доменные детали (production, load, demand, etc.)"
    )


class RiskSummary(BaseModel):
    """
    Сводная оценка рисков по секторам + интегральный риск.
    """
    energy_risk: float = Field(ge=0, le=1)
    water_risk: float = Field(ge=0, le=1)
    transport_risk: float = Field(ge=0, le=1)
    total_risk: float = Field(ge=0, le=1)

    calculated_at: datetime = Field(
        description="Время, соответствующее snapshot_at RiskOverviewSnapshot или расчёту risk_engine"
    )


class ReportingSummary(BaseModel):
    """
    Главный DTO для endpoint-а типа /api/v1/reporting/summary:
    - текущее состояние секторов,
    - текущий риск,
    - вспомогательная мета-информация.
    """
    sectors: List[SectorState]
    risk: RiskSummary

    source: str = Field(
        default="live",
        description="Источник данных: live (онлайн-запрос к сервисам) или cached (из БД reporting)"
    )


# ------------------------------------------------------------
#  ИСТОРИЯ РИСКОВ ДЛЯ ГРАФИКОВ
# ------------------------------------------------------------

class RiskHistoryItem(BaseModel):
    """
    Один элемент временного ряда риска.
    Удобен для построения графиков.
    """
    snapshot_at: datetime
    energy_risk: float
    water_risk: float
    transport_risk: float
    total_risk: float


class RiskHistoryResponse(BaseModel):
    """
    DTO для endpoint-а типа /api/v1/reporting/risk/history.
    """
    items: List[RiskHistoryItem]
    count: int = Field(description="Количество точек в выборке")


# ------------------------------------------------------------
#  СНАПШОТЫ ДЛЯ ОТЛАДКИ / RAW-ВЫГРУЗОК
# ------------------------------------------------------------

class SnapshotListResponse(BaseModel):
    """
    Обёртка для отдачи коллекций снапшотов (секторов или риска).
    """
    items: List[dict]
    count: int
