from typing import Literal, List
from pydantic import BaseModel, Field


class OutageScenario(BaseModel):
    sector: Literal["energy", "water", "transport"] = Field(
        description="Сектор, в котором моделируется сбой"
    )
    duration: int = Field(
        default=10,
        ge=1,
        description="Длительность сбоя в минутах"
    )


class ScenarioResult(BaseModel):
    before: float = Field(description="Интегральный риск до события")
    after: float = Field(description="Интегральный риск после события")
    delta: float = Field(description="Изменение риска после события")
    sector: str = Field(description="Сектор, в котором произошёл сбой")


class MonteCarloRequest(BaseModel):
    sector: Literal["energy", "water", "transport"] = Field(
        description="Сектор, над которым проводится Монте-Карло моделирование"
    )
    runs: int = Field(
        default=20,
        ge=1,
        le=1000,
        description="Количество прогонов Monte-Carlo"
    )
    duration_min: int = Field(
        default=5,
        ge=1,
        description="Минимальная длительность outage в минутах"
    )
    duration_max: int = Field(
        default=60,
        ge=1,
        description="Максимальная длительность outage в минутах"
    )


class MonteCarloRun(BaseModel):
    run: int = Field(description="Номер прогона")
    before: float = Field(description="Риск до события")
    after: float = Field(description="Риск после события")
    delta: float = Field(description="Изменение риска Δ")
    duration: int = Field(description="Длительность outage в данном прогоне")


class MonteCarloResult(BaseModel):
    sector: str = Field(description="Сектор моделирования")
    runs: int = Field(description="Количество прогонов")

    mean_delta: float = Field(description="Среднее изменение риска")
    min_delta: float = Field(description="Минимальное значение Δ")
    max_delta: float = Field(description="Максимальное значение Δ")
    p95_delta: float = Field(description="95-й перцентиль распределения Δ")

    runs_data: List[MonteCarloRun] = Field(
        description="Подробные результаты каждого прогона Monte-Carlo"
    )
