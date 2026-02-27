# Анализ кода: схемы данных, API и опасные места

## 1) Контекст и границы анализа

Репозиторий содержит 3 реализованных микросервиса:
- `energy_service`
- `transport_service`
- `water_service`

На уровне `docker-compose.yml` также задекларированы `ingestor`, `normalizer`, `risk_engine`, `scenario_simulator`, `reporting`, но соответствующих директорий в текущем дереве репозитория нет.

---

## 2) Схемы данных

### 2.1. PostgreSQL / SQLAlchemy-модели

### Energy Service (`schema = energy`, table = `records`)

| Поле | Тип | Nullable | Назначение |
|---|---|---:|---|
| `id` | `Integer` (PK) | нет | Идентификатор записи состояния |
| `production` | `Float` | нет | Текущее производство энергии (MW) |
| `consumption` | `Float` | нет | Текущее потребление энергии (MW) |
| `is_operational` | `Boolean` | нет | Флаг работоспособности энергосистемы |
| `reason` | `String(255)` | да | Причина сбоя (если есть) |
| `duration` | `Integer` | да | Длительность сбоя (минуты) |

Особенность: используется отдельная схема `energy`; при старте сервиса она создаётся через `ensure_schema()`.

### Transport Service (`table = transport_status`)

| Поле | Тип | Nullable | Назначение |
|---|---|---:|---|
| `id` | `Integer` (PK) | нет | Идентификатор записи |
| `load` | `Float` | нет | Загруженность транспорта |
| `operational` | `Boolean` | по умолчанию `True` | Работоспособность транспортной системы |
| `energy_dependent` | `Boolean` | по умолчанию `True` | Флаг зависимости от энергии |
| `reason` | `String` | да | Причина деградации/сбоя |

### Water Service (`table = water_status`)

| Поле | Тип | Nullable | Назначение |
|---|---|---:|---|
| `id` | `Integer` (PK) | нет | Идентификатор записи |
| `water_level` | `Float` | нет | Уровень воды |
| `operational` | `Boolean` | по умолчанию `True` | Работоспособность водной системы |
| `energy_dependent` | `Boolean` | по умолчанию `True` | Флаг зависимости от энергии |
| `reason` | `String` | да | Причина деградации/сбоя |

> Важно: для `water_service` модель существует, но `main.py` и `database.py` сейчас копируют код `transport_service` (см. раздел «Опасные места»).

### 2.2. Pydantic-схемы (DTO)

#### Energy Service

`services/energy_service/schemas.py`:
- `EnergyStatus`: `production >= 0`, `consumption >= 0`, `is_operational`
- `Outage`: `reason` (1..255), `duration >= 0`
- `EnergyRecordBase/Create/Out`: заготовка CRUD-DTO, включая `id` и `from_attributes=True` для ORM-объектов

В `main.py` дублируются отдельные `BaseModel`-классы `EnergyStatus`/`Outage` без валидационных ограничений (`Field`).

---

## 3) API-контракты

## 3.1. Energy Service

### Технические endpoints
- `GET /health` → `{"status":"ok","service":"energy_service"}`
- `GET /ready` → `{"status":"ready"}`
- `GET /` → служебное сообщение
- `GET /metrics` → Prometheus-метрики

### Версионированные endpoints (`/api/v1/energy`)
- `POST /api/v1/energy/init`
  - Создаёт начальную запись с `DEFAULT_PRODUCTION`/`DEFAULT_CONSUMPTION`, если таблица пуста.
- `GET /api/v1/energy/status`
  - Возвращает последнее состояние.
- `POST /api/v1/energy/adjust_production?amount=<float>`
  - Создаёт новую запись с изменённым производством.
- `POST /api/v1/energy/adjust_consumption?amount=<float>`
  - Создаёт новую запись с изменённым потреблением.
- `POST /api/v1/energy/simulate_outage`
  - Body: `{ "reason": "...", "duration": <int> }`.
- `POST /api/v1/energy/resolve_outage`
  - Снимает аварийный статус.

### Дублирующиеся root-endpoints (без префикса)
В `main.py` присутствует почти тот же набор:
- `GET /status`
- `POST /adjust_production`
- `POST /adjust_consumption`
- `POST /simulate_outage`
- `POST /resolve_outage`

Это функциональный дубль роутера `/api/v1/energy`.

## 3.2. Transport Service

- `GET /` → состояние сервиса
- `GET /status` → последнее состояние транспорта
- `POST /update_load` (body: `{ "load": float }`) → добавляет новую запись состояния
- `POST /check_energy_dependency` → ходит во внешний `ENERGY_SERVICE_URL + /status`, при неуспехе переводит транспорт в `operational=False`

## 3.3. Water Service

Фактическое API сейчас совпадает с `transport_service`, потому что `main.py` содержит копию транспортного кода (модели запроса `TransportStatus`, `LoadUpdate`, методы `/update_load`, `/check_energy_dependency`).

Это означает расхождение между моделью `WaterStatus` и реальным API/логикой сервиса.

---

## 4) Опасные места (risk hotspots)

Ниже — приоритетный список проблем с потенциальным влиянием на прод.

### [Критично] 1. `water_service` реализован как копия `transport_service`

Симптомы:
- `services/water_service/main.py` содержит комментарии/классы/эндпоинты транспорта.
- Код читает/пишет `models.TransportStatus`, которого нет в `water_service/models.py`.
- `services/water_service/database.py` использует дефолт `transport_db` и комментарии `transport_service`.

Риск:
- при первом запросе к `/status` в water-сервисе будет ошибка атрибута/несоответствие модели;
- возможна запись не в ту БД/схему при дефолтном `DATABASE_URL`.

Что делать:
- переписать `water_service/main.py` под `WaterStatus`/`water_level`;
- привести `database.py` к корректному имени БД или унифицировать на общий `DATABASE_URL`;
- добавить smoke-тесты на запуск и базовые endpoint-ы каждого сервиса.

### [Критично] 2. Дублирование бизнес-эндпоинтов в `energy_service`

Симптомы:
- одинаковая бизнес-логика определена и в `routers/energy.py` (`/api/v1/energy/...`), и в `main.py` (`/...`).

Риск:
- двойная поверхность API и потенциальное рассинхронизированное поведение при будущих изменениях;
- запутанная клиентская интеграция (какой endpoint «канонический»).

Что делать:
- оставить единственный слой роутинга (лучше `routers/energy.py` + префикс версии);
- в `main.py` оставить только технические endpoint-ы и `include_router`.

### [Высокий] 3. Рассинхрон DTO: `schemas.py` vs `main.py`

Симптомы:
- в `schemas.py` есть ограничения (`ge`, `min_length`, `max_length`), но `main.py` использует собственные модели без ограничений.

Риск:
- на root-endpoint-ах можно принять данные, которые не проходят через ожидаемую валидацию;
- разные гарантии данных для разных URL одного и того же сервиса.

Что делать:
- импортировать DTO только из `schemas.py`, удалить дубли классов из `main.py`.

### [Высокий] 4. Отсутствие timeout/retry/circuit-breaker при межсервисных вызовах

Симптом:
- `requests.get()` в `transport_service.check_energy_status()` без явного `timeout`.

Риск:
- подвисание воркеров и каскадная деградация при недоступности energy-service.

Что делать:
- добавить `timeout=(connect, read)`;
- добавить retry с backoff (или через gateway/service mesh);
- логировать причины деградации.

### [Средний] 5. Нет транзакционной защиты от гонок при записи «последнего состояния»

Симптом:
- паттерн read-latest → derive → insert-latest выполняется без блокировок, во всех сервисах.

Риск:
- race condition при конкурентных запросах: потеря/перезапись промежуточных состояний.

Что делать:
- использовать `SELECT ... FOR UPDATE` + транзакции или event-sourcing с версионированием;
- как минимум ввести `created_at` и optimistic lock/version.

### [Средний] 6. Потенциальный crash при пустом `DATABASE_URL` в energy_service

Симптом:
- `create_engine(os.getenv("DATABASE_URL"))` без fallback.

Риск:
- сервис упадёт при старте, если переменная не задана.

Что делать:
- использовать fallback из `settings.DATABASE_URL` (или fail-fast с понятной ошибкой).

### [Средний] 7. `docker-compose.yml` ссылается на сервисы, которых нет в репозитории

Симптом:
- объявлены `./services/ingestor`, `normalizer`, `risk_engine`, `scenario_simulator`, `reporting`, но такие директории отсутствуют.

Риск:
- `docker compose up` для полного стека падает на этапе build.

Что делать:
- либо добавить сервисы, либо вынести их в отдельный compose-профиль/файл и документировать текущий минимальный набор.

---

## 5) Рекомендованный минимальный план стабилизации

1. Исправить `water_service` (главный блокер).
2. Убрать дубли endpoint-ов и DTO в `energy_service`.
3. Ввести timeout/retry на межсервисные HTTP-вызовы.
4. Добавить базовые интеграционные smoke-тесты:
   - запуск сервиса;
   - init/status;
   - один сценарий деградации и восстановления.
5. Согласовать `docker-compose` с фактическим составом репозитория.
