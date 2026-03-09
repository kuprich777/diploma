# Текущая архитектура проекта DIPLOMA

## 1) Общая картина
Проект реализован как набор FastAPI-микросервисов, которые поднимаются через Docker Compose и используют один PostgreSQL-инстанс (`db`).

Ключевые доменные сервисы:
- `energy_service`
- `water_service`
- `transport_service`
- `risk_engine`
- `scenario_simulator`
- `reporting`

Сервисы данных:
- `ingestor`
- `normalizer`

Все сервисы (кроме симулятора) в текущем состоянии ориентированы на схему «событийная история состояний в БД + чтение последнего состояния». Т.е. на каждое изменение создаётся новая запись, а «текущее состояние» вычисляется как `ORDER BY id DESC LIMIT 1` в рамках ключа эксперимента (`scenario_id`, `run_id`).

---

## 2) Контейнерная топология и зависимости
По `docker-compose.yml`:
- Общая БД: `postgres:16`.
- Внешние порты:
  - `energy_service`: `8001`
  - `water_service`: `8002`
  - `transport_service`: `8003`
  - `risk_engine`: `8004`
  - `scenario_simulator`: `8005`
  - `reporting`: `8010`
- Межсервисные URL передаются через переменные окружения.

Явные цепочки зависимостей:
1. `water_service` зависит от `energy_service` (проверка энергозависимости воды).
2. `transport_service` зависит от `energy_service` и `water_service` (по env; фактическая доменная проверка в основном по energy).
3. `risk_engine` агрегирует состояния/риски из `energy/water/transport`.
4. `scenario_simulator` оркестрирует доменные сервисы и запрашивает расчёт из `risk_engine`.
5. `reporting` читает онлайн-состояния из доменных сервисов + риск из `risk_engine` и сохраняет snapshots.
6. `normalizer` и `ingestor` выделены как отдельный data-контур, но интеграция пока скелетная.

---

## 3) Зоны ответственности сервисов

## 3.1. `energy_service`
**Отвечает за:**
- состояние энергетики (production/consumption/operational);
- операции `init`, `adjust_production`, `adjust_consumption`, `simulate_outage`, `resolve_outage`;
- расчёт собственного риска `x_energy` через `/risk/current`.

**Особенности:**
- использует нормализованную шкалу деградации [0..1];
- outage-ветка даёт высокий базовый риск, усиливающийся длительностью.

## 3.2. `water_service`
**Отвечает за:**
- состояние водоснабжения (supply/demand/operational);
- операции изменения спроса/предложения;
- endpoint `check_energy_dependency` для учёта влияния энергии;
- собственный риск через `/risk/current`.

**Особенности:**
- требует `scenario_id`/`run_id` почти во всех endpoint'ах (строгая изоляция экспериментов);
- при сбое energy применяется деградация по дефициту и флагам зависимостей.

## 3.3. `transport_service`
**Отвечает за:**
- транспортное состояние (`load`, `operational`);
- операции `update_load`, `increase_load`, `check_energy_dependency`, `resolve_outage`;
- собственный риск через `/risk/current`.

**Особенности:**
- риск в первую очередь производен от загрузки и операционности;
- dependency-check реализует «мягкий» impact при энергетических сбоях.

## 3.4. `risk_engine`
**Отвечает за:**
- сбор рисков из 3 доменных сервисов;
- расчёт интегрального риска;
- два метода:
  - `classical` (пороговая/бинарная логика),
  - `quantitative` (`x' = clip(x + A x)`);
- поддержку runtime-настроек:
  - веса отраслей,
  - матрица межотраслевых зависимостей `A` (in-memory);
- хранение истории risk snapshots.

**Особенности:**
- сначала пытается взять `/risk/current` у сектора, затем fallback на `/status`;
- при недоступности сектора возвращает риск по fail-safe модели (высокий риск).

## 3.5. `scenario_simulator`
**Отвечает за:**
- каталог сценариев (S1/S2/S3);
- выполнение последовательности шагов сценария по секторам;
- Monte Carlo прогоны, сидирование и стохастическую вариацию параметров;
- сбор before/after risk-метрик и индикаторов каскадности.

**Особенности:**
- оркестрация идёт через HTTP вызовы в доменные сервисы;
- есть асинхронная очередь взаимодействий, запускающая дополнительные dependency-check шаги на основе матрицы `A`;
- поддерживается экспериментальный ключ (`scenario_id`, `run_id`) и трассировка шага (`step_index`, `action`).

## 3.6. `reporting`
**Отвечает за:**
- «живой» summary (состояния отраслей + риск);
- сохранение snapshot'ов состояния/риска в БД reporting;
- выдачу risk history.

**Особенности:**
- агрегирует данные в pull-режиме (на запрос), не по push/event model.

## 3.7. `ingestor` и `normalizer`
- `ingestor`: приём raw events.
- `normalizer`: каркас нормализации + статус/листинг нормализованных событий.

Текущая реализация normalizer — в основном scaffold (реальная ETL-логика помечена TODO).

---

## 4) Типы взаимодействий между сервисами

1. **Синхронные HTTP (основной тип):**
   - `risk_engine -> energy/water/transport`
   - `water/transport -> energy` (dependency checks)
   - `scenario_simulator -> domain services`
   - `scenario_simulator -> risk_engine`
   - `reporting -> domain services + risk_engine`

2. **Общая БД PostgreSQL (инфраструктурный слой):**
   - каждый сервис пишет в свои таблицы/схемы;
   - «текущее состояние» обычно вычисляется как последняя запись.

3. **In-memory runtime state:**
   - веса и dependency matrix в `risk_engine`;
   - baseline/cache структуры в `scenario_simulator`.

4. **Наблюдаемость и техэндпойнты:**
   - `/health`, `/ready`;
   - метрики Prometheus (`prometheus_fastapi_instrumentator`).

---

## 5) Как проходит типовой сценарный прогон
1. Инициализация отраслевых состояний по ключу `(scenario_id, run_id)`.
2. `scenario_simulator` берёт baseline risk у `risk_engine`.
3. По шагам вызывает доменные actions (`simulate_outage`, `increase_load`, `check_*_dependency` и т.д.).
4. После каждого шага (или блока шагов) запрашивает обновлённый риск.
5. Возвращает агрегированный результат прогона: до/после, дельты, индикаторы каскадности, трассировку шагов.

---

## 6) Текущее состояние зрелости

### Сильные стороны
- Ясное разбиение по доменам и оркестрации.
- Единый подход к API и health/readiness.
- Поддержка воспроизводимости через `(scenario_id, run_id)`.
- Наличие встроенной метрик/наблюдаемости.

### Ограничения
- Сильная связность через синхронный HTTP (много точек отказа).
- Данные по состояниям хранятся как append-only без явной CQRS/event-store дисциплины.
- `normalizer` и data-пайплайн пока не доведены до production-уровня.
- В `scenario_simulator` есть признаки незавершённого merge (conflict markers), что указывает на технический риск целостности кода.
