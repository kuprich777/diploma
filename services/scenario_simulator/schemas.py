from pydantic import BaseModel, Field


class OutageScenario(BaseModel):
    sector: str = Field(description="energy | water | transport")
    duration: int = Field(default=10, description="Длительность сбоя в минутах")


class ScenarioResult(BaseModel):
    before: float
    after: float
    delta: float
    sector: str


class MonteCarloRequest(BaseModel):
    sector: str
    duration: int = 10
    runs: int = 20


class MonteCarloResult(BaseModel):
    average_delta: float
    min_delta: float
    max_delta: float
    samples: int
