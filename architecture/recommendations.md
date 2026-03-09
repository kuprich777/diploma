# Рекомендации по улучшению архитектуры

## 1) Приоритет P0 (критично перед дальнейшим развитием)

1. **Устранить merge-конфликты и стабилизировать `scenario_simulator`.**
   - Сейчас в коде есть conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`), это риск некорректной логики и деградации CI.
   - Нужен быстрый hardening: почистить конфликт, покрыть ключевые ветки e2e и unit-тестами.

2. **Зафиксировать контракт API между оркестратором и доменными сервисами.**
   - Сейчас симулятор использует «кандидаты URL» и fallback-стратегии.
   - Рекомендуется единый versioned-contract (`/api/v1/...`) + OpenAPI contract tests.

3. **Ввести timeout/retry/circuit breaker policy в едином виде.**
   - Вызовы HTTP уже имеют timeout, но политика поведения не централизована.
   - Нужна библиотека/модуль клиентских адаптеров: retry (idempotent только), backoff, лимиты, error taxonomy.

---

## 2) Приоритет P1 (существенно улучшит устойчивость)

## 2.1. Избавиться от tight coupling через event backbone
- Добавить брокер событий (Kafka/NATS/RabbitMQ) для межсервисных доменных событий:
  - `EnergyOutageDetected`
  - `WaterDegraded`
  - `TransportLoadChanged`
  - `RiskRecalculated`
- Тогда `reporting` и downstream аналитика смогут работать event-driven, а не только pull-on-demand.
- `scenario_simulator` может публиковать «commands/events», а доменные сервисы подтверждать обработку.

## 2.2. Сделать идемпотентность и дедупликацию запросов
- Ввести `idempotency_key` для мутаций состояния.
- Хранить correlation_id / causation_id для всей цепочки шагов сценария.
- Это важно для повторных прогонов, retriable-операций и надёжного аудита.

## 2.3. Формализовать модель данных по состояниям
- Сейчас модель фактически append-only журнал, но без явной декларации.
- Рекомендация:
  - либо полноценный event sourcing (events + projections),
  - либо явный current-state table + history table.
- Это упростит запросы, ускорит чтение текущего состояния и повысит объяснимость.

## 2.4. Матрицу зависимостей и веса вынести из in-memory
- Перенести `weights` и `dependency_matrix` в персистентное хранилище (БД + version table).
- Дать endpoint для чтения активной версии/истории изменений.
- Добавить «pin версии» в run metadata для строгой воспроизводимости экспериментов.

---

## 3) Приоритет P2 (качество и масштабируемость)

## 3.1. Data pipeline: довести `normalizer` до production-ready
- Реализовать реальный проход:
  - чтение batch из `ingestor`,
  - валидация/преобразование,
  - запись normalized events,
  - дедуп/контроль качества данных.
- Добавить DQ-метрики (missing fields, schema drift, outliers).

## 3.2. Ввести API Gateway / BFF слой
- Сейчас внешние клиенты потенциально ходят в разные сервисы.
- Рекомендуется единая точка входа с:
  - authn/authz,
  - rate limiting,
  - request tracing,
  - маршрутизацией по версиям API.

## 3.3. Наблюдаемость уровня production
- Помимо Prometheus метрик добавить:
  - distributed tracing (OpenTelemetry),
  - structured logging с trace_id,
  - SLO/SLI (доступность API, latency p95, error rate).

## 3.4. Тестовая стратегия «контракт + интеграция + сценарии»
- Contract tests между `scenario_simulator`, `risk_engine`, доменными сервисами.
- Интеграционные тесты на docker-compose стенде.
- Golden scenarios для сравнения динамики риска между версиями модели.

---

## 4) Предложенная целевая эволюция по этапам

### Этап 1 (1–2 спринта)
- Починка конфликтов и стабилизация текущих API.
- Контрактные тесты и централизация http-клиентов.
- Персистентное версионирование матрицы/весов.

### Этап 2 (2–4 спринта)
- Введение event broker и событийного контура.
- Расширение normalizer/ingestor до полноценного data pipeline.
- Улучшение reporting на event-driven snapshots.

### Этап 3 (дальше)
- Gateway, безопасность, multi-tenant readiness.
- Оптимизация хранилищ (partitioning, retention policy).
- MLOps/ModelOps контур для риска (валидация модели, drift detection, эксперимент-трекинг).

---

## 5) Практический чек-лист «с чего начать завтра»
1. Убрать conflict markers в `scenario_simulator`, прогнать тесты.
2. Зафиксировать и задокументировать единый API-контракт действий сценария.
3. Добавить correlation_id/idempotency_key во все мутации.
4. Вынести dependency matrix/weights в БД с версиями.
5. Реализовать первый end-to-end поток `ingestor -> normalizer -> reporting`.
