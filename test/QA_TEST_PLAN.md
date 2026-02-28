# QA test plan + parameterized cURL scenarios

## 1) Краткий анализ кода

Платформа состоит из доменных сервисов (`energy`, `water`, `transport`), риск-агрегатора (`risk_engine`) и оркестратора сценариев (`scenario_simulator`).

Ключевые точки для QA:
- Изоляция состояния по `(scenario_id, run_id)` во всех доменных сервисах.
- Корректная инициализация базового состояния `/init` и воспроизводимость прогона.
- Корректное применение шагов сценария через `scenario_simulator` (`outage`, `load_increase`, `resolve_outage`).
- Корректный пересчёт риска в `risk_engine` для `method=classical|quantitative`.
- Валидация ошибок (невалидные параметры, неизвестный `scenario_id`, некорректный диапазон Monte-Carlo).

## 2) Что добавлено в директорию `test`

- `test/curl.env.example` — параметризованные переменные окружения.
- `test/run_scenarios.sh` — набор curl-сценариев для smoke/integration/negative.

## 3) Набор тестов для QA

### Smoke
1. Инициализация всех доменных сервисов (`/init?force=true`).
2. Проверка статусов (`/status`) после init.
3. Получение базового риска (`/risk/current`).

### Integration (каскад)
4. Инициировать outage в energy.
5. Прогнать `check_energy_dependency` в water/transport.
6. Проверить изменение риска после outage.
7. Запустить сценарий из каталога через simulator (`/run_scenario?use_catalog=true`).
8. Запустить кастомный сценарий (`load_increase` в transport).

### Monte-Carlo
9. Выполнить `/monte_carlo` в `mode=real`.
10. Проверить метрики: `mean_delta`, `p95_delta`, `K_cl`, `K_q`, `runs_data`.

### Negative
11. Неизвестный `scenario_id` для `run_scenario` (ожидаем 404).
12. `duration_max < duration_min` для `monte_carlo` (ожидаем 400).

## 4) Как запускать

```bash
cp test/curl.env.example test/curl.env
# отредактировать параметры при необходимости
bash test/run_scenarios.sh
```

или с явным env-файлом:

```bash
ENV_FILE=test/curl.env bash test/run_scenarios.sh
```

## 5) Параметры, которые чаще всего меняют

- `HOST`, `*_PORT` — адреса сервисов в тестовом окружении.
- `SCENARIO_ID`, `RUN_ID` — идентификатор и номер прогона.
- `OUTAGE_DURATION`, `TRANSPORT_LOAD_AMOUNT` — интенсивность воздействия.
- `MONTE_CARLO_*` — параметры серии прогонов.
