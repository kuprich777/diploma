from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict


class NormalizedEventIn(BaseModel):
    """
    DTO для явной передачи нормализованного события извне (если понадобится).
    Чаще normalizer будет сам формировать такие события из ingestor.raw_events.
    """
    raw_event_id: int = Field(description="ID исходного сырого события из ingestor.raw_events")
    source: str = Field(description="Источник данных (например, 'energy', 'water', 'transport')")
    normalized_payload: Dict[str, Any] = Field(
        description="Нормализованный JSON-пейлоад (унифицированная структура данных)"
    )


class NormalizedEventOut(BaseModel):
    """
    DTO для отдачи нормализованного события наружу (например, в reporting или для отладки).
    """
    id: int
    raw_event_id: int
    source: str
    normalized_payload: Dict[str, Any]
    normalized_at: datetime

    # Pydantic v2: включить работу напрямую с ORM-моделями
    model_config = ConfigDict(from_attributes=True)


class NormalizeBatchRequest(BaseModel):
    """
    Параметры пакетной нормализации.
    Можно указать лимит, источник или фильтры по типу событий.
    """
    limit: int = Field(
        default=100,
        gt=0,
        description="Максимальное количество сырьевых событий для обработки за один запуск",
    )
    source: Optional[str] = Field(
        default=None,
        description="Если указано — нормализуем только события с этим source",
    )


class NormalizeBatchResult(BaseModel):
    """
    Результат пакетной нормализации.
    """
    processed: int = Field(description="Сколько сырых событий было обработано")
    created: int = Field(description="Сколько нормализованных событий создано")
    skipped: int = Field(description="Сколько событий пропущено (ошибка/дубликат/фильтр)")
    details: Optional[List[str]] = Field(
        default=None,
        description="Опциональные текстовые детали (ошибки, предупреждения и т.п.)",
    )


class NormalizerStatus(BaseModel):
    """
    Сводная информация о состоянии normalizer-сервиса.
    Можно расширять по мере необходимости.
    """
    total_normalized: int = Field(description="Всего нормализованных событий в системе")
    last_normalized_at: Optional[datetime] = Field(
        default=None,
        description="Время последней успешной нормализации (если была)",
    )
