from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


# ---------- DTO для бизнес-эндпойнтов ----------

class TransportStatus(BaseModel):
    """Сводное состояние транспортной системы (ответ для /status)."""
    load: float = Field(ge=0, description="Текущая загруженность транспортной сети, % или условные единицы")
    operational: bool = Field(description="Флаг работоспособности транспортной системы")
    energy_dependent: bool = Field(description="Флаг зависимости от энергетического сектора")
    reason: Optional[str] = Field(default=None, description="Причина деградации, если есть")


class LoadUpdate(BaseModel):
    """Тело запроса для обновления загруженности транспорта (/update_load)."""
    load: float = Field(ge=0, description="Новая загруженность транспортной сети")


# ---------- DTO для работы с ORM (на будущее, если понадобится CRUD) ----------

class TransportStatusBase(BaseModel):
    load: float = Field(ge=0)
    operational: bool = True
    energy_dependent: bool = True
    reason: Optional[str] = Field(default=None, max_length=255)


class TransportStatusCreate(TransportStatusBase):
    """Модель для явного создания записи (если добавим POST /create)."""
    pass


class TransportStatusOut(TransportStatusBase):
    """Модель для отдачи ORM-объекта наружу."""
    id: int

    # Pydantic v2: аналог orm_mode = True
    model_config = ConfigDict(from_attributes=True)
