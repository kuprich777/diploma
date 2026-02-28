# Scenario Simulator: архитектура и поток обработки

## 1) Назначение сервиса
`scenario_simulator` — FastAPI-сервис, который оркестрирует сценарные воздействия на доменные микросервисы (`energy`, `water`, `transport`) и сравнивает изменение интегрального риска по двум методам (`classical` и `quantitative`) через `risk_engine`. Также сервис поддерживает серию прогонов Monte-Carlo и выгрузку итогов эксперимента в reporting-service.  
Если трактовать название документа как "payments", то это **Не подтверждено кодом**: в коде сервиса нет доменной логики платежей, только сценарная симуляция рисков.

## 2) Request flow (по шагам)

### A. Базовый контур запуска сервиса
1. Поднимается FastAPI-приложение, подключаются Prometheus-метрики и роутер `/api/v1/simulator`.
2. На старте пишется лог о запуске.
3. Доступны системные ручки `/health`, `/ready`, `/`.

### B. Поток `POST /api/v1/simulator/run_scenario`
1. Принимается `ScenarioRequest` (+ query-параметр `use_catalog`).
2. Определяется `run_id` (из запроса или генерируется из `timestamp`).
3. Определяются шаги сценария:
   - из встроенного `SCENARIO_CATALOG`, если `use_catalog=true` и шаги не переданы;
   - либо из `req.steps`.
4. Шаги сортируются по `step_index`; инициатором считается `sector` первого шага.
5. Best-effort запрашивается мета dependency matrix из `risk_engine`.
6. При `init_all_sectors=true` вызывается инициализация всех доменных сервисов (`_init_sector_state`).
7. Запрашивается базовый риск (до воздействия) для обоих методов: `classical` и `quantitative`.
8. Последовательно применяются шаги сценария через `_apply_step` (маршрутизация по `sector` + `action`, вызовы в соответствующие микросервисы).
9. Повторно запрашивается риск после воздействия (оба метода).
10. Считаются `delta_cl`, `delta_q`, а также индикаторы каскада `I_cl` и `I_q`.
11. Возвращается `ScenarioRunResult`.

### C. Поток `POST /api/v1/simulator/monte_carlo`
1. Принимается `MonteCarloRequest`.
2. Проверяются базовые ограничения (`duration_max >= duration_min`, `mode == real`).
3. Для каждого прогона:
   - рассчитывается `run_id` и случайный `duration`;
   - инициализируются все сектора;
   - снимаются базовые риски (`classical`, `quantitative`);
   - применяется инициирующее воздействие (`outage` или `load_increase`);
   - снимаются финальные риски;
   - считаются `I_cl`, `I_q`, `delta_R`, формируется `MonteCarloRun`.
4. После цикла считаются агрегаты: `K_cl`, `K_q`, `Delta_percent`, `mean/min/max/p95`.
5. Формируется payload и best-effort отправляется в reporting-service (`/experiments/register`).
6. Возвращается `MonteCarloResult`.

## 3) Где происходит валидация

### Валидация схемами (Pydantic)
- `ScenarioStep` ограничивает:
  - `step_index >= 1`;
  - `sector` только `energy|water|transport`;
  - `action` только из фиксированного списка.
- `ScenarioRequest.run_id >= 1` (если передан).
- `MonteCarloRequest` ограничивает:
  - `runs >= 1`, `duration_min >= 1`, `duration_max >= 1`, `start_run_id >= 1`;
  - `sector` и `initiator_action` — только разрешённые значения;
  - `mode` — только `real`;
  - пороги `delta_sector_threshold >= 0`, `non_initiator_threshold_classical` в диапазоне `[0,1]`.

### Явная валидация в обработчиках/хелперах
- `run_scenario`:
  - `404`, если неизвестный `scenario_id` в режиме каталога;
  - `400`, если нет шагов;
  - `400`, если инициатор вне ожидаемых секторов.
- `_apply_step`:
  - `400`, если для `adjust_*` не передан `params.value`;
  - `400`, если `action` не поддержан;
  - `502`, если доменный сервис недоступен/не принял ни один из candidate endpoint.
- `_service_base_for_sector`:
  - `400`, если неизвестный сектор.
- `run_monte_carlo`:
  - `400`, если `duration_max < duration_min`;
  - `400`, если `mode != real`;
  - `400`, если неизвестный `initiator_action`;
  - `500`, если не было ни одного прогона.

## 4) Основные сущности данных
- `ScenarioStep` — атомарное воздействие (номер шага, сектор, действие, параметры).
- `ScenarioRequest` — вход для одиночного запуска сценария.
- `ScenarioRunResult` — результат одного сценария с метриками до/после и индикаторами каскада.
- `MonteCarloRequest` — вход для серии прогонов.
- `MonteCarloRun` — результат одного прогона в серии.
- `MonteCarloResult` — агрегированный итог серии прогонов.
- `CatalogScenario`, `ScenarioCatalog` — DTO для выдачи встроенного каталога сценариев `S`.
- `SCENARIO_CATALOG` — зашитый в код словарь контролируемых сценариев.
- `Settings` — конфигурация URL-ов внешних сервисов и параметров симуляции.
- `RawEvent` в `models.py` — SQLAlchemy-модель сырых событий. Роль этой модели в runtime этого сервиса **Не подтверждено кодом** (в текущих маршрутах не используется).

## 5) Схема потока (Markdown)
```mermaid
flowchart TD
    C[Client] --> RS[POST /run_scenario или /monte_carlo]
    RS --> V[Валидация Pydantic + проверки в коде]
    V --> INIT[Init sector state (energy/water/transport)]
    INIT --> R0[GET risk_engine /risk/current?method=classical,quantitative]
    R0 --> ACT[Применение действий сценария в доменных сервисах]
    ACT --> R1[Повторный GET /risk/current]
    R1 --> CALC[Расчёт delta, I_cl, I_q, агрегатов]
    CALC --> REP[POST reporting /experiments/register (best-effort, MC)]
    CALC --> RESP[HTTP response ScenarioRunResult/MonteCarloResult]
```

## 6) Ключевые файлы и их роли
- `services/scenario_simulator/main.py` — инициализация приложения, health/readiness, подключение роутера и метрик.
- `services/scenario_simulator/routers/simulator.py` — основная бизнес-логика: каталог сценариев, запуск сценария, Monte-Carlo, вызовы внешних сервисов, расчёт метрик.
- `services/scenario_simulator/schemas.py` — Pydantic-модели входов/выходов и их ограничения.
- `services/scenario_simulator/config.py` — конфигурация URL-ов микросервисов, параметров моделирования и логирования.
- `services/scenario_simulator/utils/logging.py` — настройка логирования через loguru.
- `services/scenario_simulator/models.py` — SQLAlchemy-модель `RawEvent`; фактическое использование в этом сервисе **Не подтверждено кодом**.
- `services/scenario_simulator/requirements.txt` / `Dockerfile` — инфраструктурная упаковка окружения и зависимостей.

## 7) Risks / gotchas
1. **Множественные candidate endpoint-ы** в `_apply_step` и `_init_sector_state`: сервис «угадывает» путь среди нескольких вариантов. Это повышает совместимость, но усложняет диагностику интеграционных ошибок.
2. **Ошибки reporting-service не ломают Monte-Carlo** (`best-effort`): удобно для живучести, но можно тихо потерять факт регистрации эксперимента.
3. **`weights_version` всегда `None`** в `run_scenario`: версионирование весов не реализовано в risk_engine (по комментарию в коде).
4. **Пороги каскада захардкожены/параметризованы частично**:
   - в `run_scenario` фиксированные `1.0` и `0.1`;
   - в `monte_carlo` берутся из запроса.
5. **`models.py` ссылается на `database` модуль**, но его присутствие/подключение в этом контексте **Не подтверждено кодом**.
6. **В документации сервиса нет явного контракта по SLA/ретраям/идемпотентности** для внешних вызовов — **Не подтверждено кодом**.
