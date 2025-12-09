# services/reporting/models.py

from datetime import datetime
from sqlalchemy import Integer, Float, String, DateTime, JSON
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

    energy_risk: Mapped[float] = mapped_column(Float, nullable=False)
    water_risk: Mapped[float] = mapped_column(Float, nullable=False)
    transport_risk: Mapped[float] = mapped_column(Float, nullable=False)
    total_risk: Mapped[float] = mapped_column(Float, nullable=False)

    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
