# services/reporting/models.py

from datetime import datetime
from sqlalchemy import Integer, Float, String, DateTime, JSON, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, REPORTING_SCHEMA


# -------------------------------------------------------------------
# 1. Исторический срез состояния всех секторов (Energy, Water, Transport)
# -------------------------------------------------------------------

class SectorStatusSnapshot(Base):
    """
    Снимок состояния всех инфраструктурных секторов.
    Reporting собирает эти данные по запросу и сохраняет для истории.
    
    Пример структуры:
    {
        "energy": {"is_operational": true, "production": 1000},
        "water": {"is_operational": true, "load": 40},
        "transport": {"is_operational": false, "load": 90}
    }
    """
    __tablename__ = "sector_status_snapshots"
    __table_args__ = {"schema": REPORTING_SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
        index=True
    )

    experiment_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(f"{REPORTING_SCHEMA}.experiments.id"),
        nullable=True,
        index=True,
        comment="Опциональная привязка к эксперименту (если снимок собран в рамках Experiment Registry)"
    )

    scenario_id: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        index=True,
        comment="Идентификатор сценария (s) для удобного поиска/фильтрации"
    )

    run_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
        comment="Идентификатор прогона (r) внутри эксперимента"
    )

    # JSON со структурой состояний всех сервисов
    sectors: Mapped[dict] = mapped_column(JSON, nullable=False)



# -------------------------------------------------------------------
# 2. Кэш интегрального риска
# -------------------------------------------------------------------

class RiskOverviewSnapshot(Base):
    """
    Снимок агрегированного риска из risk_engine.
    Может использоваться для таймсерийного анализа и ускорения графиков.
    """
    __tablename__ = "risk_overview_snapshots"
    __table_args__ = {"schema": REPORTING_SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
        index=True
    )

    experiment_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(f"{REPORTING_SCHEMA}.experiments.id"),
        nullable=True,
        index=True,
        comment="Опциональная привязка к эксперименту (если снимок собран в рамках Experiment Registry)"
    )

    scenario_id: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        index=True,
        comment="Идентификатор сценария (s) для удобного поиска/фильтрации"
    )

    run_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
        comment="Идентификатор прогона (r) внутри эксперимента"
    )

    method: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        index=True,
        comment="Метод расчёта риска: classical | quantitative"
    )

    energy_risk: Mapped[float] = mapped_column(Float, nullable=False)
    water_risk: Mapped[float] = mapped_column(Float, nullable=False)
    transport_risk: Mapped[float] = mapped_column(Float, nullable=False)
    total_risk: Mapped[float] = mapped_column(Float, nullable=False)

    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)


# -------------------------------------------------------------------
# 3. Experiment Registry (единая сущность эксперимента для отчётности)
# -------------------------------------------------------------------

class Experiment(Base):
    """Реестр экспериментов (контролируемый вычислительный эксперимент).

    Сущность фиксирует конфигурацию запуска и обеспечивает воспроизводимость:
      - каталог сценариев S / конкретный scenario_id
      - параметры Monte Carlo
      - версии матрицы зависимостей A и весов w
      - версию кода (git_commit)

    На эту сущность могут ссылаться прогоны и любые снапшоты/результаты.
    """

    __tablename__ = "experiments"
    __table_args__ = {"schema": REPORTING_SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Идентификатор сценария (или имя набора сценариев), по которому запущен эксперимент
    scenario_id: Mapped[str] = mapped_column(String, nullable=False, index=True)

    # Метод расчёта/режим сравнения. Обычно: "both" (считаем K_cl и K_q в одном эксперименте)
    method: Mapped[str] = mapped_column(String, nullable=False, index=True, default="both")

    # Параметры Monte Carlo
    n_runs: Mapped[int] = mapped_column(Integer, nullable=False)
    delta_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.1)

    # Версионирование конфигураций
    matrix_A_version: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    weights_version: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    # Версия кода/сборки
    git_commit: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    # Произвольные параметры эксперимента (seed policy, описания, etc.)
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ExperimentRun(Base):
    """Единичный прогон (run) внутри эксперимента."""

    __tablename__ = "experiment_runs"
    __table_args__ = {"schema": REPORTING_SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    experiment_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(f"{REPORTING_SCHEMA}.experiments.id"),
        nullable=False,
        index=True,
    )

    scenario_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    run_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    seed: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    initiator: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    # Параметры шага/сценария (duration, amount, etc.)
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    # Технический статус прогона
    is_success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error: Mapped[str | None] = mapped_column(String, nullable=True)


class ExperimentResult(Base):
    """Агрегированные результаты эксперимента.

    Здесь храним итоговые метрики (K_cl, K_q, Delta%), а также статистику
    (p-value, доверительные интервалы) и распределения для построения графиков.
    """

    __tablename__ = "experiment_results"
    __table_args__ = {"schema": REPORTING_SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    experiment_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(f"{REPORTING_SCHEMA}.experiments.id"),
        nullable=False,
        index=True,
    )

    # Основные метрики методологии
    K_cl: Mapped[float | None] = mapped_column(Float, nullable=True)
    K_q: Mapped[float | None] = mapped_column(Float, nullable=True)
    Delta_percent: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Статистика для научной отчётности
    p_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    ci_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    ci_high: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Сырые распределения/выборки (например, список delta_R по прогонам)
    distributions: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Доп. метаданные: версия расчёта, метод теста, комментарии
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
