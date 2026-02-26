from sqlalchemy import String, Float, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, WATER_SCHEMA


class WaterStatus(Base):
    """
    Снимок состояния водного сектора.
    Хранит текущее производство, потребление воды и флаги доступности.
    """
    __tablename__ = "status"
    __table_args__ = {"schema": WATER_SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # --- ключ эксперимента (изоляция сценариев и прогонов) ---
    scenario_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    run_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # Производство воды (скважины, станции очистки)
    supply: Mapped[float] = mapped_column(Float, nullable=False)

    # Потребление воды (жилищно-коммунальные нужды, промышленность)
    demand: Mapped[float] = mapped_column(Float, nullable=False)

    # Флаг работоспособности сектора
    operational: Mapped[bool] = mapped_column(Boolean, default=True)

    # Флаг зависимости от energy_service (водные станции требуют энергию)
    energy_dependent: Mapped[bool] = mapped_column(Boolean, default=True)

    # Причина деградации или аварии, если есть
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
