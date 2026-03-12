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
    action: Literal["outage", "load_increase", "adjust_production", "adjust_consumption", "resolve_outage", "dependency_check"] = Field(
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
    seed: Optional[int] = Field(
        default=None,
        ge=0,
        description="Явный seed для стохастических компонентов прогона. Если не задан, детерминированно вычисляется из (scenario_id, run_id)."
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
    auto_dependency_checks: bool = Field(
        default=False,
        description="[DEPRECATED] Автоматический dependency_check отключён; используйте явные шаги action=dependency_check"
    )

    stochastic_scale: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Опциональный уровень стохастики Monte-Carlo: относительный шум N(0, stochastic_scale) для параметров воздействия. 0.0 = полностью детерминированный прогон."
    )
    theta_classical: float = Field(
        default=0.3,
        ge=0.0,
        description="Порог θ для classical по правилу y_i,t = I(Δx_i,t ≥ θ)"
    )

    # --- realism extension parameters (all optional, off by default) ---
    enable_recovery: bool = Field(
        default=False,
        description="Enable optional post-shock recovery phase. Computes recovery_trajectory fields; does not alter existing 'after' metric."
    )
    recovery_rate: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description="Per-step exponential recovery fraction. 0.2 = 20% of remaining risk deficit recovered per step. Model: x_t = x_0 + (x_peak - x_0)*(1-rate)^t."
    )
    recovery_horizon: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Number of recovery steps to simulate (t=1..recovery_horizon)."
    )
    propagation_depth: int = Field(
        default=1,
        ge=1,
        le=3,
        description=(
            "Max cascade propagation depth in the interaction queue (default=1, preserves current behavior). "
            "Note: with matrix A v1.0 (only energy→water, energy→transport edges), depth>1 is a no-op "
            "since water and transport have no outgoing edges."
        )
    )
    heterogeneity_scale: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "Sector-level heterogeneity noise std. When >0, each sector receives an independent "
            "N(0, heterogeneity_scale) noise draw, modelling differential sector resilience. "
            "0.0 = homogeneous sectors (current behavior)."
        )
    )
    weather_factor: float = Field(
        default=1.0,
        ge=0.0,
        le=10.0,
        description=(
            "Exogenous weather severity multiplier applied to outage duration BEFORE stochastic noise. "
            "1.0 = nominal conditions (default, no effect). >1.0 amplifies outage severity (e.g. Winter Storm Uri context)."
        )
    )
    load_factor: float = Field(
        default=1.0,
        ge=0.0,
        le=10.0,
        description="Exogenous grid load multiplier on initial shock severity. 1.0 = nominal load (default)."
    )
    fuel_stress_factor: float = Field(
        default=1.0,
        ge=0.0,
        le=10.0,
        description="Exogenous fuel availability stress multiplier. 1.0 = no fuel stress (default)."
    )


class ScenarioRunResult(BaseModel):
    # --- идентификаторы экспериментальной единицы ---
    scenario_id: str = Field(description="Идентификатор сценария s ∈ S")
    run_id: int = Field(description="Номер прогона r")
    seed: Optional[int] = Field(default=None, description="Фактический seed, использованный в данном прогоне")
    cache_key: Optional[str] = Field(default=None, description="Диагностический ключ кэша результатов прогона")
    cache_hit: Optional[bool] = Field(default=None, description="Признак попадания в кэш результатов прогона")
    randomized_params: Optional[Dict[str, Any]] = Field(default=None, description="Фактические стохастические параметры, использованные в прогоне")
    x0_hash: Optional[str] = Field(default=None, description="Хеш baseline-вектора x0 для диагностики переинициализации")
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

    # --- векторные метрики x_i,0 и Δx_i,T ---
    baseline_x0: Optional[Dict[str, float]] = Field(
        default=None,
        description="Базовый вектор рисков x_i,0 по секторам для ключа (scenario_id, run_id)",
    )
    delta_x_q: Optional[Dict[str, float]] = Field(
        default=None,
        description="Вектор приращений Δx_i,T в количественном методе",
    )
    delta_x_cl: Optional[Dict[str, float]] = Field(
        default=None,
        description="Вектор приращений Δx_i,T в классическом методе",
    )

    before_vec_q: Optional[Dict[str, float]] = Field(default=None, description="Вектор рисков до сценария (quantitative)")
    after_vec_q: Optional[Dict[str, float]] = Field(default=None, description="Вектор рисков после сценария (quantitative)")
    delta_vec_q: Optional[Dict[str, float]] = Field(default=None, description="Приращение вектора рисков (quantitative)")
    before_vec_cl: Optional[Dict[str, float]] = Field(default=None, description="Вектор рисков до сценария (classical)")
    after_vec_cl: Optional[Dict[str, float]] = Field(default=None, description="Вектор рисков после сценария (classical)")
    delta_vec_cl: Optional[Dict[str, float]] = Field(default=None, description="Приращение вектора рисков (classical)")
    theta_classical: Optional[float] = Field(default=None)
    delta_sector_threshold: Optional[float] = Field(default=None)

    # --- совместимость со старым интерфейсом (используется в визуализациях) ---
    before: Optional[float] = Field(default=None, description="Интегральный риск до сценария (по умолчанию quantitative)")
    after: Optional[float] = Field(default=None, description="Интегральный риск после сценария (по умолчанию quantitative)")
    delta: Optional[float] = Field(default=None, description="Изменение риска (по умолчанию quantitative)")

    # --- realism extension: recovery dynamics ---
    peak_after_q: Optional[float] = Field(
        default=None,
        description="Peak total risk (quantitative) immediately post-shock. Equal to method_q_total_after."
    )
    peak_after_cl: Optional[float] = Field(
        default=None,
        description="Peak total risk (classical) immediately post-shock. Equal to method_cl_total_after."
    )
    final_after_recovery_q: Optional[float] = Field(
        default=None,
        description="Total risk (quantitative) at t=recovery_horizon after exponential recovery. Only set when enable_recovery=True."
    )
    final_after_recovery_cl: Optional[float] = Field(
        default=None,
        description="Total risk (classical) at t=recovery_horizon after exponential recovery. Only set when enable_recovery=True."
    )
    recovery_trajectory_q: Optional[List[float]] = Field(
        default=None,
        description="Total risk (quantitative) at each of t=1..recovery_horizon recovery steps. Only set when enable_recovery=True."
    )
    recovery_trajectory_cl: Optional[List[float]] = Field(
        default=None,
        description="Total risk (classical) at each of t=1..recovery_horizon recovery steps. Only set when enable_recovery=True."
    )

    # --- cl diagnostics ---
    cl_activated_sectors: Optional[List[str]] = Field(
        default=None,
        description="Non-initiating sectors that crossed θ_cascade in cl method at any step. Empty list when I_cl=0."
    )
    cl_first_activation_step: Optional[int] = Field(
        default=None,
        description="Step index (1-based) of first classical cascade activation. None when I_cl=0."
    )

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
    base_seed: Optional[int] = Field(
        default=None,
        ge=0,
        description="Базовый seed для серии Monte-Carlo. Если не задан, seed каждого прогона вычисляется из (scenario_id, run_id)."
    )
    sector: Literal["energy", "water", "transport"] = Field(
        description="Сектор, над которым проводится Monte-Carlo моделирование"
    )
    runs: int = Field(
        default=100,
        ge=100,
        le=2000,
        description="Количество прогонов Monte-Carlo (для статистической устойчивости K(N): минимум 100, рекомендовано 300+)"
    )
    duration_min: int = Field(
        default=5,
        ge=1,
        description="Минимальная длительность outage в минутах (используется напрямую как интенсивность воздействия без центрирования)"
    )
    duration_max: int = Field(
        default=60,
        ge=1,
        description="Максимальная длительность outage в минутах (монотонно усиливает воздействие)"
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
    theta_classical: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Порог θ для classical по правилу y_i,t = I(Δx_i,t ≥ θ)"
    )
    auto_dependency_checks: bool = Field(
        default=False,
        description="[DEPRECATED] Автоматический dependency_check отключён; используйте явные шаги action=dependency_check"
    )

    stochastic_scale: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Опциональный уровень стохастики Monte-Carlo: относительный шум N(0, stochastic_scale) для параметров воздействия. 0.0 = полностью детерминированный прогон."
    )

    # --- realism extension parameters (all optional, off by default) ---
    enable_recovery: bool = Field(
        default=False,
        description="Enable optional post-shock recovery phase across all MC runs."
    )
    recovery_rate: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description="Per-step exponential recovery fraction. 0.2 = 20% of remaining deficit recovered per step."
    )
    recovery_horizon: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Number of recovery steps to simulate per run."
    )
    propagation_depth: int = Field(
        default=1,
        ge=1,
        le=3,
        description=(
            "Max cascade propagation depth in the interaction queue (default=1, current behavior). "
            "With matrix A v1.0 (only energy→water, energy→transport edges), depth>1 is a no-op."
        )
    )
    heterogeneity_scale: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "Sector-level heterogeneity noise std. When >0, each sector receives an independent "
            "N(0, heterogeneity_scale) noise draw per run. 0.0 = homogeneous sectors (current behavior)."
        )
    )
    weather_factor: float = Field(
        default=1.0,
        ge=0.0,
        le=10.0,
        description="Exogenous weather severity multiplier applied to outage duration. 1.0 = no effect (default)."
    )
    load_factor: float = Field(
        default=1.0,
        ge=0.0,
        le=10.0,
        description="Exogenous grid load multiplier on initial shock severity. 1.0 = nominal (default)."
    )
    fuel_stress_factor: float = Field(
        default=1.0,
        ge=0.0,
        le=10.0,
        description="Exogenous fuel availability stress multiplier. 1.0 = no stress (default)."
    )


class MonteCarloRun(BaseModel):
    scenario_id: str = Field(description="Идентификатор сценария")
    run_id: int = Field(description="Номер прогона Monte-Carlo")
    run: int = Field(ge=1, description="Порядковый номер прогона внутри Monte-Carlo")
    seed: Optional[int] = Field(default=None, description="Фактический seed прогона")
    cache_key: Optional[str] = Field(default=None, description="Диагностический ключ кэша результатов прогона")
    cache_hit: Optional[bool] = Field(default=None, description="Признак попадания в кэш результатов прогона")
    randomized_params: Optional[Dict[str, Any]] = Field(default=None, description="Фактические стохастические параметры прогона")
    x0_hash: Optional[str] = Field(default=None, description="Хеш baseline-вектора x0")
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
    before_vec_q: Optional[Dict[str, float]] = Field(default=None)
    after_vec_q: Optional[Dict[str, float]] = Field(default=None)
    delta_vec_q: Optional[Dict[str, float]] = Field(default=None)
    before_vec_cl: Optional[Dict[str, float]] = Field(default=None)
    after_vec_cl: Optional[Dict[str, float]] = Field(default=None)
    delta_vec_cl: Optional[Dict[str, float]] = Field(default=None)
    theta_classical: Optional[float] = Field(default=None)
    delta_sector_threshold: Optional[float] = Field(default=None)

    # --- realism extension fields ---
    peak_after_q: Optional[float] = Field(
        default=None,
        description="Peak total risk (quantitative) post-shock = method_q_total_after."
    )
    final_after_recovery_q: Optional[float] = Field(
        default=None,
        description="Total risk (quantitative) after recovery_horizon steps. Set when enable_recovery=True."
    )
    recovery_trajectory_q: Optional[List[float]] = Field(
        default=None,
        description="Per-step recovery trajectory for total risk (quantitative). Set when enable_recovery=True."
    )
    cl_activated_sectors: Optional[List[str]] = Field(
        default=None,
        description="Non-initiating sectors that crossed θ_cascade in cl method at any step."
    )
    cl_first_activation_step: Optional[int] = Field(
        default=None,
        description="Step index (1-based) of first classical cascade activation. None when I_cl=0."
    )


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
    theta_classical: Optional[float] = Field(default=None)
    delta_sector_threshold: Optional[float] = Field(default=None)
    duration_correlation: Optional[float] = Field(default=None)


# --- DTOs for scenario catalog exposure ---

class CatalogScenario(BaseModel):
    scenario_id: str = Field(description="Идентификатор сценария s_i ∈ S")
    description: str = Field(description="Формализованное описание сценария (для каталога S)")
    steps: List[ScenarioStep] = Field(description="Упорядоченная последовательность шагов сценария s_i")


class ScenarioCatalog(BaseModel):
    scenarios: List[CatalogScenario] = Field(
        description="Каталог сценариев S = {s1, ..., sM}, используемый в вычислительном эксперименте"
    )
