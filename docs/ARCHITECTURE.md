# Архитектура стенда DIPLOMA v2.1 (newmain)

> Описывает **реально существующее** состояние кода на ветке `newmain`.
> Охватывает этапы 3 (operator comparison), 4 (MC 15×3), 4-ter (rho-recalibration),
> 4-quint (IIM canonical Haimes vs NLDR MAE).
> Планируемые компоненты помечены `TODO`.
> Источник истины по методологии: [`docs/methodology/METHODOLOGY_FINAL.md`](methodology/METHODOLOGY_FINAL.md).
> Полный реестр изменений: [changes.md](../changes.md)

---

## 0. Методологический базис

Настоящая работа позиционируется как **синтез трёх интеллектуальных линий** в единый
стохастический оператор на ограниченной области (METHODOLOGY_FINAL.md §1.1):

1. **Анализ Леонтьева (1936)** — источник структуры матрицы межотраслевых зависимостей
   $A$ с калибровкой методом прямых затрат $a_{ij} = X_{ij}/\mathrm{GO}_j$.
2. **Взаимозависимость КИ (Rinaldi et al. 2001)** — источник понятийной рамки
   каскадов и классического бинарного оператора threshold cascade, выступающего
   здесь как baseline $K^{(\mathrm{cl})}$.
3. **Непрерывная мера дистресса (Battiston et al. 2012; Bardoscia et al. 2015)** —
   источник **одного** принципа: непрерывного описания $x_i \in [0, 1]$. Это
   единственный элемент, буквально наследуемый из DebtRank-литературы; остальные
   элементы работы (стохастика, проекция Скорохода, метрика $K$) формулируются
   независимо.

Канонический DebtRank $K^{(DR)}$ со state machine $\{N, O, F\}$ (Battiston 2012 /
Li 2021) предусмотрен как дополнительный baseline в расширенной серии 4
(METHODOLOGY_FINAL.md §10.1). Механизм Recovery Dynamics с параметром $\kappa$
(формула 23) — как опциональное расширение (§10.2), при $\kappa=0$
эквивалентное основному оператору.

---

## 1. Таблица сервисов

| Сервис | Порт | Контейнер | Роль | Математика |
|--------|------|-----------|------|-----------|
| energy_service | 8001 | energy_service | Доменная модель энергосектора | risk = clip₀₁((cons/prod − 0.7) / 0.3) |
| water_service | 8002 | water_service | Доменная модель водоснабжения | risk = clip₀₁(max(0, demand − supply) / demand) |
| transport_service | 8003 | transport_service | Доменная модель транспорта | risk = 1 − e^(−k · load) |
| risk_engine | 8004 | risk_engine | СДУ-интегратор, matrix A, cascade operators, MC harness | Euler–Maruyama (SDE), IIM (Haimes 2005), IIM canonical, NEVA/NLDR (Barucca 2020, β=2) |
| scenario_simulator | 8005 | scenario_simulator | MC-оркестрация сценариев | N ≥ 10³, HTTP-вызовы (переходный период) |
| optimizer | 8006 | optimizer | Стохастическая оптимизация | min_{ΔA} E[Σ w_j(1−S_j)] s.t. budget | **TODO** |
| db | 5433→5432 | diploma-db | PostgreSQL 16 | — |

**Удалены** (относительно предыдущей ветки): ingestor, normalizer, reporting.

---

## 2. API-эндпоинты (реально существующие)

### 2.1. risk_engine (:8004) — `/api/v1/risk/`

| Метод | Путь | Назначение |
|-------|------|-----------|
| GET | `/current` | Текущий агрегированный риск (AggregatedRisk) |
| GET | `/current_iterative` | Риск через итеративный квантитативный оператор |
| POST | `/recalculate` | Пересчитать риск (RiskSnapshotOut) |
| POST | `/update_weights` | Обновить веса секторов |
| GET | `/classical_threshold` | Текущее значение θ |
| POST | `/set_classical_threshold` | Установить θ |
| GET | `/dependency_matrix` | Текущая матрица A (3×3) |
| POST | `/dependency_matrix` | Обновить матрицу A |
| GET | `/history` | История снимков риска |

**Планируемые эндпоинты расширенных серий (METHODOLOGY_FINAL.md §9.4, §9.5, §10.3):**

| Метод | Путь | Назначение |
|-------|------|-----------|
| POST | `/compute_K_DR` | Канонический DebtRank со state machine {N, O, F} — Серия 4. **TODO** |
| POST | `/compute_K_q_recovery` | Количественный оператор с Recovery Dynamics (κ) — Серия 5. **TODO** |
| GET | `/benchmark_centralities` | Меры центральности (eigenvector / Katz / PageRank / column-sum) + Kendall τ_K. **TODO** |

### 2.2. scenario_simulator (:8005) — `/api/v1/simulator/`

| Метод | Путь | Назначение |
|-------|------|-----------|
| GET | `/catalog` | Каталог сценариев |
| POST | `/run_scenario` | Запустить один сценарий |
| POST | `/monte_carlo` | Monte Carlo (N прогонов) |

### 2.3. energy_service (:8001), water_service (:8002), transport_service (:8003)

Каждый сервис предоставляет стандартный набор эндпоинтов (см. `routers/`):
- GET `/status` — текущее состояние (x_j, risk)
- POST `/update` — обновить параметры (production, consumption, load)
- POST `/outage` — симулировать отказ
- GET `/history` — история состояний

---

## 3. Диаграмма потоков данных

```mermaid
graph TD
    subgraph Калибровка["Калибровка (offline)"]
        HAI[HAI Dataset<br/>hai-21.03, 1.3M строк] -->|σ_energy, σ_water<br/>C_energy, C_water| CAL[data/calibration/]
        KELM[Kelmarsh Farm SCADA<br/>36 файлов, Senvion MM92] -->|σ_wind| CAL
        HGV[DfT Road Safety<br/>HGV collisions 2020–2024] -->|C_transport| CAL
        WIOD[WIOD 2016 NIOT<br/>43 страны, .xlsx] -->|A_leontief 3×3<br/>x_j (GO)| CAL
        CAL -->|A + x_j| AS[A* = A·x_j/x_i<br/>Haimes transform]
    end

    subgraph Стенд["Вычислительный стенд (online)"]
        CAL --> RE[risk_engine :8004<br/>SDEIntegrator + cascade_operators + mc_harness]
        AS --> RE
        ES[energy :8001] -->|x_energy| RE
        WS[water :8002] -->|x_water| RE
        TS[transport :8003] -->|x_transport| RE

        subgraph Операторы["Операторы (METHODOLOGY_FINAL.md §3, §10)"]
            KCL[K_cl — Rinaldi threshold cascade<br/>бинаризация θ_node + топология A]
            KDR[K_DR — Battiston / Li state machine<br/>N, O, F; absorbing F<br/>TODO: placeholder, Серия 4]
            KQ[K_q — SDE + проекция Скорохода<br/>Эйлер–Маруяма, δ=0.10]
        end

        RE --> KCL
        RE --> KDR
        RE --> KQ
        KCL -->|I_cl| SS[scenario_simulator :8005<br/>Monte Carlo N≥10³]
        KDR -->|I_DR| SS
        KQ -->|I_q| SS
        SS -->|ΔA recommendations| OPT[optimizer :8006<br/>TODO]
    end

    subgraph Результаты["Результаты"]
        SS --> MC[results/mc_runs/]
        RE --> S3[stage3_operator_comparison.json]
        RE --> S4[stage4_mc_15x3.json<br/>stage4_loo_robustness.json]
        RE --> S4Q[mae_comparison.json<br/>IIM canonical vs NLDR]
        OPT --> OPTRES[results/optimization/]
        MC --> PLOTS[results/plots/]
    end
```

---

## 4. Маппинг: формула → файл → метод

| Формула | Файл | Метод |
|---------|------|-------|
| dx_j = (Σa_{ij}x_i − ρ_j x_j)dt + σ_j x_j dW_j | `services/risk_engine/sde_integrator.py` | `SDEIntegrator.step()` |
| Euler–Maruyama, clip[0,1] | `services/risk_engine/sde_integrator.py` | `SDEIntegrator.run()` |
| I_cl, I_q (каскадные индикаторы) | `services/risk_engine/sde_integrator.py` | `SDEIntegrator.detect_cascade()` |
| x(t+1)=clip(x+A·x) — Classical baseline | `services/risk_engine/cascade_operators.py` | `ClassicalOperator` |
| q(t+1)=clip(A*·q+c*) — IIM iterative | `services/risk_engine/cascade_operators.py` | `IIMOperator` |
| x(t+1)=clip(x₀+A·(1−(1−x)^β)) — NLDR β=2 | `services/risk_engine/cascade_operators.py` | `NevaOperator` |
| q=(I−A*)⁻¹c* — IIM canonical Haimes eq.(11) | `services/risk_engine/iim_canonical.py` | `IIMCanonical.predict()` |
| Unified MC harness: SDE + IIM + NEVA одним σ-шумом | `services/risk_engine/mc_harness.py` | `run_sde_once`, `run_iim_once`, `run_neva_once` |
| A*_ij = A_ij · x_j/x_i (Haimes transform) | `scripts/matrix_calibration/apply_haimes_transformation.py` | `main()` |
| x_j из WIOD NIOT (GO/TOT row) | `scripts/matrix_calibration/extract_sector_outputs.py` | `extract_outputs()` |
| MAE intensity (IIM canonical vs NLDR) | `scripts/validation/mae_comparison.py` | `main()` |
| a[i][j] = X[i][j] / q[j] | `scripts/calibrate_A.py` | `extract_leontief()` |
| σ = std(Δlog x) / sqrt(dt) | `scripts/calibrate_sigma.py` | `calibrate_hai_sigma()`, `calibrate_kelmarsh_sigma()` |
| C_j = q95(x_j/nominal) | `scripts/calibrate_capacity.py` | `calibrate_threshold()` |
| C_transport = q95(HGV monthly) | `scripts/calibrate_capacity.py` | `calibrate_transport_C_hgv()` |
| φ_j = exp(−α·max(0,x_j−C_j)/(1−C_j)) | `services/risk_engine/sde_integrator.py` | `SDEIntegrator._compute_dynamic_A()` |
| A(t) = A_static · diag(φ) | `services/risk_engine/sde_integrator.py` | `SDEIntegrator._compute_dynamic_A()` |
| Bayesian update (τ_post, μ_post) | `matrix_doc/bayesian_calibrator.py` | `BayesianMatrixCalibrator` |
| min_{ΔA} E[Σ w_j(1−S_j)] | `services/optimizer/` | **TODO** |

---

## 5. Внешние зависимости

```
/Users/kuprich/Documents/diploma_repo/
├── diploma/                         ← этот репозиторий (ветка newmain)
└── datasets/                        ← внешние данные (не в git)
    ├── dataset hai /hai/            ← HAI ICS Security Dataset (hai-21.03)
    ├── kelmarsh/                    ← Kelmarsh Farm SCADA (Zenodo 5841834)
    ├── Road safety open data/       ← DfT Road Safety (UK, 2020–2024)
    ├── OpenWindSCADA/               ← meta-repo (ссылки; данные из Kelmarsh)
    └── (wiod/)                      ← WIOD 2016 NIOT внутри репо: matrix_doc/sources/NIOTS/
```

Конфигурация путей: `config.env` (не в git) / `config.env.example` (шаблон).

---

## 6. Что удалено

Полный реестр: [changes.md](../changes.md). Краткая сводка:

- **Удалены сервисы**: ingestor, normalizer, reporting — skeleton-сервисы без расчётных функций
- **Удалена документация**: docs/00–06_*.md, docs/STAND_ARCHITECTURE.md, docs/c4/, docs/regression/
- **Удалены артефакты**: results/*.json (старые MC), results/theta_sweep/, Baltimore 2024/, UCTE 2007 /
- **Удалены скрипты**: все HTTP-MC скрипты (run_theta_sweep.py, run_load_sweep.py и др.)
- **Удалены директории**: real_scenarios_testbed/, real_data_validation/, validation/, experiments/, test/

---

## 7. Что добавлено на `newmain` (relative to `newresearch`)

**Новые файлы:**

- `services/risk_engine/cascade_operators.py` — три оператора одной семьёй (Classical, IIM iterative, NEVA/NLDR с β=2).
- `services/risk_engine/iim_canonical.py` — `IIMCanonical` класс, детерминированный `q=(I-A*)⁻¹c*`.
- `services/risk_engine/mc_harness.py` — единый MC harness: SDE + IIM + NEVA на одном σ-шуме, seed-reproducible.
- `scripts/matrix_calibration/extract_sector_outputs.py` — x_j (Gross Output) из WIOD NIOT (RUS+DEU+USA 2014).
- `scripts/matrix_calibration/apply_haimes_transformation.py` — A → A* per Haimes 2005 eq.(11).
- `scripts/validation/mae_comparison.py` — MAE сравнение IIM canonical vs NLDR на 4 исторических событиях.
- `scripts/run_operator_comparison.py`, `scripts/run_stage4_mc.py` — драйверы Этапа 3/4.
- `scripts/diagnostics/`, `scripts/sigma_calibration/` — диагностика, ρ-sweep.
- `tests/test_cascade_operators.py` — unit-тесты трёх операторов.
- `data/calibration/A_star_iim_canonical.json` — матрица A* Haimes.
- `data/calibration/wiod_sector_outputs.json` — x_j по секторам.
- `docs/methodology/calibration_rationale.md` — обоснование ρ_A=0.5, ρ_rec=0.3, T_steps=50.
- `docs/methodology/stage4_quint_iim_vs_nldr.md` — методология этапа 4-quint.
- `docs/_checklists/` — аудиты этапов 00–04_ter + verification.
- `results/stage3_operator_comparison.json`, `results/stage4_mc_15x3.json`, `results/stage4_loo_robustness.json`, `results/mae_comparison.json`.
- `results/etap_4_original/`, `results/diagnostics/rho_sweep.md`.
