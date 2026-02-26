from typing import Literal, List, Dict, Any, Optional
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


# --- DTOs for scenario execution ---

class ScenarioStep(BaseModel):
    step_index: int = Field(
        ge=1,
        description="Порядковый номер шага сценария (t = 1..T)"
    )
    sector: Literal["energy", "water", "transport"] = Field(
        description="Сектор, над которым выполняется воздействие"
    )
    action: Literal["outage", "load_increase", "adjust_production", "adjust_consumption", "resolve_outage"] = Field(
        description="Тип воздействия (действие сценария)"
    )
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Параметры воздействия (например, duration, amount, reason и т.п.)"
    )


class ScenarioRequest(BaseModel):
    scenario_id: str = Field(
        description="Идентификатор сценария s ∈ S (каталог сценариев используется для воспроизводимости эксперимента)"
    )
    run_id: Optional[int] = Field(
        default=None,
        ge=1,
        description="Номер прогона r. Если не указан, генерируется автоматически в контуре Monte-Carlo или run_scenario"
    )
    method: Optional[Literal["classical", "quantitative", "both"]] = Field(
        default="both",
        description="Метод расчёта риска: classical, quantitative или оба (для сравнительного эксперимента)"
    )
    steps: Optional[List[ScenarioStep]] = Field(
        default=None,
        description="Последовательность шагов сценария. Если не задана (null) или пустая, используется каталог сценариев S по scenario_id."
    )
    init_all_sectors: bool = Field(
        default=True,
        description="Инициализировать базовое состояние всех доменных микросервисов перед сценарием"
    )


class ScenarioRunResult(BaseModel):
    # --- идентификаторы экспериментальной единицы ---
    scenario_id: str = Field(description="Идентификатор сценария s ∈ S")
    run_id: int = Field(description="Номер прогона r")
    initiator: Literal["energy", "water", "transport"] = Field(
        description="Инициирующий сектор i0 (источник сценарного воздействия)"
    )

    # --- версии параметров модели (воспроизводимость) ---
    matrix_A_version: Optional[str] = Field(default=None, description="Версия матрицы межотраслевых зависимостей A")
    weights_version: Optional[str] = Field(default=None, description="Версия весов агрегирования (если используется)")

    # --- агрегированные значения интегрального риска (x0 -> xT) ---
    method_cl_total_before: Optional[float] = Field(default=None, description="total_risk (classical) до сценария")
    method_cl_total_after: Optional[float] = Field(default=None, description="total_risk (classical) после сценария")
    method_q_total_before: Optional[float] = Field(default=None, description="total_risk (quantitative) до сценария")
    method_q_total_after: Optional[float] = Field(default=None, description="total_risk (quantitative) после сценария")

    # --- приращения интегрального риска ---
    delta_cl: Optional[float] = Field(default=None, description="ΔR (classical) = after - before")
    delta_q: Optional[float] = Field(default=None, description="ΔR (quantitative) = after - before")

    # --- бинарные индикаторы каскада (для K^(cl), K^(q)) ---
    I_cl: Optional[int] = Field(default=None, description="Индикатор каскада по классическому подходу (0/1)")
    I_q: Optional[int] = Field(default=None, description="Индикатор каскада по количественному подходу (0/1)")

    # --- совместимость со старым интерфейсом (используется в визуализациях) ---
    before: Optional[float] = Field(default=None, description="Интегральный риск до сценария (по умолчанию quantitative)")
    after: Optional[float] = Field(default=None, description="Интегральный риск после сценария (по умолчанию quantitative)")
    delta: Optional[float] = Field(default=None, description="Изменение риска (по умолчанию quantitative)")

    # --- трассировка выполнения сценария ---
    steps: List[Dict[str, Any]] = Field(description="Логи шагов сценария (ответы доменных микросервисов)")


class MonteCarloRequest(BaseModel):
    scenario_id: str = Field(
        default="default",
        description="Идентификатор сценария s ∈ S (ключ эксперимента; используется для изоляции прогонов)"
    )
    start_run_id: int = Field(
        default=1,
        ge=1,
        description="Начальный номер прогона r0. В Monte-Carlo будут использованы run_id = r0..r0+runs-1"
    )
    sector: Literal["energy", "water", "transport"] = Field(
        description="Сектор, над которым проводится Monte-Carlo моделирование"
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
    initiator_action: Literal["outage", "load_increase"] = Field(
        default="outage",
        description="Инициирующее действие для Monte Carlo: outage (сбой) или load_increase (рост нагрузки)."
    )

    load_amount: float = Field(
        default=0.25,
        ge=0.0,
        description="Величина роста нагрузки (используется только при initiator_action=load_increase)."
    )
    mode: Literal["real"] = Field(
        default="real",
        description="Режим моделирования: real — вычислительный эксперимент через микросервисы (analytic временно отключён в публичном API)"
    )
    delta_sector_threshold: float = Field(
        default=0.1,
        ge=0.0,
        description="Порог δ для фиксации каскада в количественном подходе: прирост риска сектора-неинициатора ≥ δ"
    )
    non_initiator_threshold_classical: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Порог для фиксации каскада в классическом подходе по бинарным рискам (обычно 1.0)"
    )


class MonteCarloRun(BaseModel):
    scenario_id: str = Field(description="Идентификатор сценария")
    run_id: int = Field(description="Номер прогона Monte-Carlo")
    run: int = Field(ge=1, description="Порядковый номер прогона внутри Monte-Carlo")
    before: float = Field(description="Интегральный риск до события")
    after: float = Field(description="Интегральный риск после события")
    delta: float = Field(description="Изменение риска Δ")
    duration: int = Field(description="Длительность outage в данном прогоне")

    method_cl_total_before: Optional[float] = Field(default=None, description="total_risk (classical) до воздействия")
    method_cl_total_after: Optional[float] = Field(default=None, description="total_risk (classical) после воздействия")
    method_q_total_before: Optional[float] = Field(default=None, description="total_risk (quantitative) до воздействия")
    method_q_total_after: Optional[float] = Field(default=None, description="total_risk (quantitative) после воздействия")

    I_cl: Optional[int] = Field(default=None, description="Индикатор каскада по классическому подходу (0/1)")
    I_q: Optional[int] = Field(default=None, description="Индикатор каскада по количественному подходу (0/1)")

    delta_R: Optional[float] = Field(default=None, description="ΔR = total_risk(q)_after - total_risk(q)_before")


class MonteCarloResult(BaseModel):
    scenario_id: str = Field(description="Идентификатор сценария")
    sector: str = Field(description="Сектор моделирования")
    runs: int = Field(description="Количество прогонов")
    mode: str = Field(description="Режим моделирования")

    mean_delta: float = Field(description="Среднее изменение риска")
    min_delta: float = Field(description="Минимальное значение Δ")
    max_delta: float = Field(description="Максимальное значение Δ")
    p95_delta: float = Field(description="95-й перцентиль распределения Δ")

    K_cl: Optional[float] = Field(default=None, description="Полнота выявления каскадов K^(cl) по Monte-Carlo")
    K_q: Optional[float] = Field(default=None, description="Полнота выявления каскадов K^(q) по Monte-Carlo")
    Delta_percent: Optional[float] = Field(default=None, description="Относительный прирост (K_q - K_cl)/K_cl * 100%")

    runs_data: List[MonteCarloRun] = Field(
        description="Подробные результаты каждого прогона Monte-Carlo"
    )


# --- DTOs for scenario catalog exposure ---

class CatalogScenario(BaseModel):
    scenario_id: str = Field(description="Идентификатор сценария s_i ∈ S")
    description: str = Field(description="Формализованное описание сценария (для каталога S)")
    steps: List[ScenarioStep] = Field(description="Упорядоченная последовательность шагов сценария s_i")


class ScenarioCatalog(BaseModel):
    scenarios: List[CatalogScenario] = Field(
        description="Каталог сценариев S = {s1, ..., sM}, используемый в вычислительном эксперименте"
    )
