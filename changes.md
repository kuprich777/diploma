# changes.md — Реестр изменений: переход на ветку newresearch

> Дата аудита: 2026-04-13  
> Ветка: newresearch  
> Автор аудита: Claude Code  

---

## 1. Обзор перехода

### 1.1. Математическая модель

| Аспект | Старая модель | Новая модель |
|--------|--------------|-------------|
| Динамика состояния | x_{t+1} = clip(x_t + u_t + A·x_t) | СДУ: dx_j = (Σa_{ij}x_i − ρ_j x_j)dt + σ_j x_j dW_j |
| Метод интегрирования | Алгебраический (одношаговый) | Эйлер—Маруяма (многошаговый) |
| Каскадный отказ | y_i = I(x_i ≥ θ), топология A[i][j]>0 | S_j = I(x_j < C_j), импульс при отказе |
| Стохастика | stochastic_scale на duration | Винеровский процесс σ_j x_j dW_j |
| Оптимизация | Нет | min_{ΔA} E[Σ w_j(1−S_j)] s.t. budget |
| Baselines | Нет | DebtRank, ICM |
| Калибровка σ | σ=0.03 (литература) | HAI Dataset + Kelmarsh Farm SCADA |
| Калибровка C | θ=0.70–0.75 (экспертная/sweep) | quantile(0.95) из HAI + DfT HGV |
| Калибровка A | Леонтьев WIOD (сохраняется) | Леонтьев WIOD (сохраняется) |
| MC-оркестрация | HTTP между сервисами через httpx | multiprocessing.Pool (TODO) |
| Размерность | 3×3 | 3×3 → перспектива N×N |

### 1.2. Архитектура стенда

| Аспект | Было | Стало |
|--------|------|-------|
| Сервисы | 9 (energy, water, transport, risk_engine, scenario_simulator, reporting, ingestor, normalizer, db) | 7 (energy, water, transport, risk_engine, scenario_simulator, optimizer, db) |
| RabbitMQ | НЕ был объявлен в docker-compose (только упомянут в docs) | Не применимо |
| Новый сервис | — | optimizer (:8006) — skeleton, TODO |
| Документация | 10+ файлов в docs/ (старая) + корневые .md | 6 файлов в docs/ (новая) |

---

## 2. Удалённые файлы и каталоги

### 2.1. Удалённые сервисы

| Путь | Причина удаления | Проверка зависимостей |
|------|-----------------|----------------------|
| services/ingestor/ | Skeleton-сервис, не вызывается из других сервисов в расчётах | grep: нет imports из других сервисов кроме своего main.py |
| services/normalizer/ | Skeleton-сервис, не вызывается напрямую из расчётных сервисов | grep: нет imports; в docker-compose только URL env var |
| services/reporting/ | Вызывается из simulator.py как fire-and-forget (_post_experiment_registry), но сам ничего не считает. Удаление не влияет на MC-расчёты (failures logged as warnings) | simulator.py строка 1170: REPORTING_SERVICE_URL only, non-critical |

### 2.2. Удалённые документы в docs/ (заменены новыми)

| Файл | Причина | Замена |
|------|---------|--------|
| docs/00_index.md | Индекс старой документации | docs/ (новая структура) |
| docs/01_stand_configuration.md | Конфигурация старых 9 сервисов | docs/ARCHITECTURE.md |
| docs/02_dependency_matrix.md | Матрица A v1.0/v2.0/OLS | docs/MATH_MODEL.md |
| docs/03_scenario_catalog.md | Каталог сценариев старой модели | docs/EXPERIMENT_CATALOG.md (TODO) |
| docs/04_experiment_results.md | Результаты старых MC-прогонов | docs/RESULTS.md (TODO) |
| docs/05_how_experiments_were_run.md | Методология HTTP-MC | docs/MATH_MODEL.md |
| docs/06_data_sources.md | Источники данных старой модели | docs/DATA_SOURCES.md |
| docs/ARCHITECTURE.md | Архитектура 9 сервисов (старая) | docs/ARCHITECTURE.md (перезаписан) |
| docs/STAND_ARCHITECTURE.md | Дубль ARCHITECTURE.md | docs/ARCHITECTURE.md |

### 2.3. Удалённые корневые .md файлы

| Файл | Причина |
|------|---------|
| readme.md | Flowchart-диаграмма без содержания; заменён README.md |
| ttreadme.md | Черновик; устаревшее описание старой архитектуры |
| REVIEW_TASKS.md | Список задач старого sprint-а; устарел |

### 2.4. Удалённые директории с артефактами реальных сценариев (корень)

| Директория | Причина |
|-----------|---------|
| Baltimore 2024/ | Результаты MC старой модели (HTTP-MC, discrete operator); будут пересчитаны с СДУ |
| UCTE 2007 / | Результаты MC старой модели; будут пересчитаны |

### 2.5. Удалённые артефакты results/

| Паттерн | Причина |
|---------|---------|
| results/*.json | Результаты HTTP-MC старой модели; будут пересчитаны |
| results/*.csv | Sweep-таблицы старой модели |
| results/figures/*.png | Графики старой модели; будут перегенерированы |
| results/theta_sweep/ | 45 файлов sweep по θ старой модели |

### 2.6. Удалённые скрипты (HTTP-MC, old operator)

| Файл | Причина | Замена |
|------|---------|--------|
| scripts/run_mc_experiment.py | Вызывает POST /monte_carlo через httpx; старая MC-оркестрация | scripts/run_monte_carlo.py (TODO, multiprocessing.Pool) |
| scripts/run_theta_sweep.py | Sweep θ по старому дискретному оператору | — |
| scripts/run_theta_node_sweep.py | Sweep θ_node; привязан к set_classical_threshold HTTP API | — |
| scripts/run_load_sweep.py | Load sweep через HTTP-MC | — |
| scripts/run_factorial_experiment.py | 2×2 factorial через HTTP | — |
| scripts/run_severity_sweep.py | Severity sweep через HTTP | — |
| scripts/run_calib_check.py | N=100 quick check через HTTP | — |
| scripts/compute_roc_analysis.py | ROC по старым K_cl/K_q данным | — |
| scripts/generate_theta_sweep_figures.py | Графики sweep θ (старые данные) | scripts/generate_plots.py (TODO) |
| scripts/generate_results_figures.py | Графики старых результатов | scripts/generate_plots.py (TODO) |
| experiments/run_bayesian_mc.py | Bayesian MC через HTTP | — |

### 2.7. Удалённые прочие директории

| Путь | Причина |
|------|---------|
| docs/c4/ | C4-диаграммы старой архитектуры (9 сервисов) |
| docs/regression/ | OLS-регрессия старой калибровки A; superseded by Leontief |
| real_scenarios_testbed/ | Testbed-сравнения старой модели |
| real_data_validation/ | Валидация старой модели; данные перейдут в validation/ |
| real_scenarios/ | run_experiment.py использует x_{t+1}=clip(x+u+Ax) (старый оператор) |
| validation/ | Устаревшие валидационные таблицы (historical_vs_model_comparison.csv ссылается на старый оператор) |
| experiments/ | Только run_bayesian_mc.py (HTTP-based); удалён |
| test/ | curl.env + run_scenarios.sh для старых HTTP-эндпоинтов |
| reporting/ | Построен из старых results/ данных (HTTP-MC); удалён вместе с данными |
| notes/ | scenario_analysis_colab.md ссылается на старый reporting-сервис |

---

## 3. Сохранённые файлы

### 3.1. Сохранены без изменений

| Файл | Причина сохранения |
|------|-------------------|
| services/risk_engine/sde_integrator.py | Ключевой модуль новой модели |
| services/risk_engine/routers/risk.py | Работающие эндпоинты; нужна проверка совместимости с СДУ |
| services/risk_engine/main.py, config.py, models.py, schemas.py | Активные |
| services/scenario_simulator/routers/simulator.py | Активный (MC через HTTP — переходный период) |
| services/scenario_simulator/schemas.py, models.py | Активные |
| services/energy_service/, water_service/, transport_service/ | Доменные модели, работают |
| scripts/calibrate_A.py | Новая калибровка по Леонтьеву (WIOD) |
| scripts/calibrate_sigma.py | Новая калибровка σ (HAI + Kelmarsh) |
| scripts/calibrate_capacity.py | Новая калибровка C (HAI + DfT HGV) |
| data/calibration/ | Результаты калибровки σ, C, A |
| data/baltimore_2024_proxy.csv, europe_2006_proxy.csv | Данные для валидации |
| matrix_doc/ | Калибровщик WIOD + Байесовская калибровка |
| tests/test_sde_integrator.py | Тесты СДУ (11 тестов, все PASS) |
| .env, .env.example, .gitignore | Конфигурация |
| Makefile | Targets: calibrate-*, test, up/down |
| Energy Outage Dataset/ | Данные EAGLE-I для валидации Texas 2021 |
| docker-compose.energy.yml | Конфигурация только для energy-сервиса |

### 3.2. Сохранены с модификацией

| Файл | Что изменено |
|------|-------------|
| docker-compose.yml | Удалены блоки ingestor, normalizer, reporting; добавлен optimizer (TODO) |
| docs/ARCHITECTURE.md | Перезаписан: новая архитектура 6 сервисов + СДУ |
| README.md | Перезаписан: быстрый старт, новая структура |

---

## 4. Новые файлы и каталоги

### 4.1. Новые сервисы

| Путь | Назначение | Статус |
|------|-----------|--------|
| services/optimizer/ | Стохастическая оптимизация min_{ΔA} E[Σ w_j(1−S_j)] | Skeleton (__init__.py only) — TODO |

### 4.2. Новая документация

| Файл | Содержание | Статус |
|------|-----------|--------|
| docs/ARCHITECTURE.md | Архитектура стенда v2.0, API-эндпоинты, Mermaid-диаграмма | Создан |
| docs/MATH_MODEL.md | Полная математическая модель СДУ + оптимизация + baselines | Создан |
| docs/DATA_SOURCES.md | Датасеты, калибровка, протокол нехватки данных | Создан |
| docs/EXPERIMENT_CATALOG.md | Каталог экспериментов новой модели | TODO |
| docs/RESULTS.md | Результаты (заполняется после прогонов) | TODO |
| docs/VISUALIZATION_GUIDE.md | Гайд по графикам | TODO |
| changes.md | Этот файл | Создан |

### 4.3. Новые скрипты (TODO)

| Путь | Назначение |
|------|-----------|
| scripts/run_monte_carlo.py | MC с СДУ через multiprocessing.Pool |
| scripts/run_optimization.py | Задача оптимизации |
| scripts/compare_methods.py | Сравнение: наш vs DebtRank vs ICM |
| scripts/generate_plots.py | Графики для ВКР |
| scripts/validate_historical.py | Валидация Texas 2021 / India 2012 |

### 4.4. Новые модули (TODO)

| Путь | Назначение |
|------|-----------|
| services/risk_engine/baselines.py | DebtRank (Battiston 2012) + ICM |

### 4.5. Новые данные/конфигурация

| Путь | Содержание | Статус |
|------|-----------|--------|
| data/calibration/sigma_calibrated.json | σ из HAI + Kelmarsh (36 файлов) | Есть |
| data/calibration/capacity_thresholds.json | C_energy=0.8832, C_water=0.6463, C_transport=0.9280 | Есть |
| data/calibration/A_leontief.json | A по Леонтьеву (RUS+DEU+USA, WIOD 2014) | Есть |
| config.env | Пути к внешним датасетам, параметры СДУ | Создан/обновлён |
| config.env.example | Шаблон для воспроизводимости | Создан |

---

## 5. Маппинг: формула → файл → метод

| Формула | Файл | Метод/класс |
|---------|------|-------------|
| dx_j = (Σa_{ij}x_i − ρ_j x_j)dt + σ_j x_j dW_j | services/risk_engine/sde_integrator.py | SDEIntegrator.step() |
| Эйлер—Маруяма clip[0,1] | services/risk_engine/sde_integrator.py | SDEIntegrator.run() |
| I_cl, I_q (cascade indicators) | services/risk_engine/sde_integrator.py | SDEIntegrator.detect_cascade() |
| a[i][j] = X[i][j] / q[j] (Leontief) | scripts/calibrate_A.py | extract_leontief() |
| σ = std(Δlog x) / sqrt(dt) | scripts/calibrate_sigma.py | calibrate_hai_sigma(), calibrate_kelmarsh_sigma() |
| C_j = quantile(x_j, 0.95) / nominal | scripts/calibrate_capacity.py | calibrate_threshold() |
| C_transport = q95(HGV monthly counts) | scripts/calibrate_capacity.py | calibrate_transport_C_hgv() |
| Bayesian update τ_post, μ_post | matrix_doc/bayesian_calibrator.py | BayesianMatrixCalibrator |
| DebtRank | services/risk_engine/baselines.py | TODO |
| ICM | services/risk_engine/baselines.py | TODO |
| min_{ΔA} E[Σ w_j(1−S_j)] | services/optimizer/ | TODO |

---

## 6. Внешние зависимости (датасеты)

| Датасет | Путь | Статус |
|---------|------|--------|
| HAI ICS Security Dataset | /Users/kuprich/Documents/diploma_repo/datasets/dataset hai /hai/ | ✅ Есть (hai-21.03: 8 файлов .csv.gz, 1.3M строк) |
| Kelmarsh Farm SCADA | /Users/kuprich/Documents/diploma_repo/datasets/kelmarsh/ | ✅ Есть (36 файлов, Senvion MM92, 2016–2021) |
| UK DfT Road Safety Open Data | /Users/kuprich/Documents/diploma_repo/datasets/Road safety open data/ | ✅ Есть (3 CSV, 2020–2024, ~500K строк) |
| OpenWindSCADA | /Users/kuprich/Documents/diploma_repo/datasets/OpenWindSCADA/ | ⚠️ Meta-repo only (ссылки на Zenodo) |
| WIOD 2016 NIOT | ./matrix_doc/sources/NIOTS/ | ✅ Есть (43 страны, *.xlsx) |
| EAGLE-I Energy Outage Dataset | ./Energy Outage Dataset/ | ✅ Есть (2014–2023, US counties) |
