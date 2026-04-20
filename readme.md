# DIPLOMA — Стенд стохастического моделирования рисков критической инфраструктуры

Микросервисный вычислительный стенд для анализа каскадных отказов в системах
критической инфраструктуры (энергетика, водоснабжение, транспорт). Методология —
**синтез трёх интеллектуальных линий**: анализ Леонтьева (1936, структура матрицы
межотраслевых зависимостей), концепция взаимозависимости КИ (Rinaldi 2001,
бинарный threshold cascade как baseline) и непрерывная мера дистресса
(Battiston 2012; Bardoscia 2015, $x_i \in [0, 1]$) — в единый стохастический
оператор на ограниченной области, применимый на стадии проектирования без
истории аварий.

**Ветка:** `newmain` | **Источник истины:** [`docs/methodology/METHODOLOGY_FINAL.md`](docs/methodology/METHODOLOGY_FINAL.md) | **Модель:** СДУ Эйлера–Маруямы с проекцией Скорохода + threshold-cascade baseline $K^{(\text{cl})}$ + канонический DebtRank $K^{(DR)}$ (TODO, Серия 4) + Recovery Dynamics $\kappa$ (TODO, Серия 5)

---

## Быстрый старт

```bash
# 1. Клонировать репозиторий
git clone <repo-url> diploma
cd diploma
git checkout newmain

# 2. Настроить пути к датасетам
cp config.env.example config.env
# Отредактировать DATASETS_ROOT в config.env

# 3. Запустить стенд
docker compose up -d

# 4. Проверить работоспособность
curl http://localhost:8004/api/v1/risk/current
curl http://localhost:8005/api/v1/simulator/catalog

# 5. Запустить калибровку (требуются внешние датасеты)
make calibrate-sigma
make calibrate-capacity
make calibrate-A

# 6. Запустить тесты
make test
```

---

## Структура каталогов

```
diploma/
├── README.md                        # этот файл
├── changes.md                       # реестр изменений (audit trail)
├── config.env                       # локальные пути (не в git)
├── config.env.example               # шаблон config.env
├── docker-compose.yml               # 6 сервисов: energy, water, transport,
│                                    #   risk_engine, scenario_simulator, optimizer(TODO)
├── Makefile                         # targets: up, down, test, calibrate-*
│
├── services/
│   ├── energy_service/              # :8001 — доменная модель энергетики
│   ├── water_service/               # :8002 — доменная модель водоснабжения
│   ├── transport_service/           # :8003 — доменная модель транспорта
│   ├── risk_engine/                 # :8004 — СДУ-интегратор, matrix A, cascade
│   │   ├── sde_integrator.py        # SDEIntegrator (Euler-Maruyama)
│   │   ├── cascade_operators.py     # Classical / IIM iterative / NEVA NLDR β=2
│   │   ├── iim_canonical.py         # IIM canonical, q=(I-A*)^-1 c* (Haimes eq.11)
│   │   └── mc_harness.py            # Унифицированный MC (SDE+IIM+NEVA на 1 шуме)
│   ├── scenario_simulator/          # :8005 — Monte Carlo оркестрация
│   └── optimizer/                   # :8006 — стохастическая оптимизация (TODO)
│
├── scripts/
│   ├── calibrate_sigma.py           # σ из HAI + Kelmarsh Farm SCADA
│   ├── calibrate_capacity.py        # C из HAI + DfT Road Safety (HGV)
│   ├── calibrate_A.py               # A по Леонтьеву (WIOD 2016)
│   ├── matrix_calibration/          # x_j (NIOT GO/TOT), A* (Haimes eq.11)
│   ├── sigma_calibration/           # диагностика σ
│   ├── diagnostics/                 # ρ-sweep, Этап 4-ter
│   ├── validation/                  # mae_comparison (IIM canonical vs NLDR)
│   ├── run_operator_comparison.py   # Этап 3: сравнение трёх операторов
│   ├── run_stage4_mc.py             # Этап 4: 15 сценариев × 3 оператора
│   ├── run_optimization.py          # оптимизация (TODO)
│   ├── generate_plots.py            # графики для ВКР (TODO)
│   └── validate_historical.py       # валидация Texas 2021 / India 2012 (TODO)
│
├── data/
│   ├── calibration/                 # результаты калибровки
│   │   ├── sigma_calibrated.json    # σ_energy=6.54/0.79, σ_water=18.08 ч⁻¹/²
│   │   ├── capacity_thresholds.json # C: 0.883/0.646/0.928
│   │   ├── A_leontief.json          # A 3×3 (Leontief, WIOD)
│   │   ├── wiod_sector_outputs.json # x_j (GO): 246777/12950/564730
│   │   └── A_star_iim_canonical.json# A* = A·x_j/x_i, ρ=0.3955
│   ├── scenarios/                   # JSON-конфиги сценариев
│   └── wiod/                        # WIOD таблицы (вне git, symlink или copy)
│
├── matrix_doc/
│   ├── bayesian_calibrator.py       # байесовская калибровка A
│   ├── sources/NIOTS/               # 43 WIOD NIOT xlsx файла
│   └── figures/                     # графики матрицы A
│
├── docs/
│   ├── ARCHITECTURE.md              # архитектура стенда v2.1 (resolve)
│   ├── MATH_MODEL.md                # СДУ + cascade операторы + IIM canonical
│   ├── DATA_SOURCES.md              # датасеты и протокол калибровки
│   ├── EXPERIMENT_CATALOG.md        # каталог экспериментов (SDE + этапы 3/4/4-ter/4-quint)
│   ├── RESULTS.md                   # результаты (SDE + MAE IIM vs NLDR)
│   ├── VISUALIZATION_GUIDE.md       # гайд по графикам (TODO)
│   ├── methodology/                 # calibration_rationale, stage4_quint_iim_vs_nldr
│   └── _checklists/                 # аудиты этапов 00–04_ter + verification
│
├── tests/
│   ├── test_sde_integrator.py       # 11 тестов SDEIntegrator (все PASS)
│   └── test_cascade_operators.py    # unit-тесты Classical/IIM/NEVA
│
├── results/
│   ├── mc_runs/                     # результаты MC-прогонов
│   ├── optimization/                # результаты оптимизации
│   ├── plots/                       # графики
│   └── comparison/                  # сравнение методов
│
└── Energy Outage Dataset/           # EAGLE-I (2014–2023, US counties)
```

---

## Математическая модель

Динамика сектора $j$ ($x_j \in [0,1]$ — относительная нагрузка):

$$dx_j = \left(\sum_i a_{ij} x_i - \rho_j x_j\right)dt + \sigma_j x_j\,dW_j$$

Каскадный отказ: $x_j(t) \geq C_j$ (классический) или $\Delta x_j \geq \delta$ (квантитативный).

Подробнее: [docs/MATH_MODEL.md](docs/MATH_MODEL.md)

---

## Документация

| Файл | Содержание |
|------|-----------|
| [docs/methodology/METHODOLOGY_FINAL.md](docs/methodology/METHODOLOGY_FINAL.md) | **Источник истины.** Финальная редакция методологической части ВКР (v4) |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Архитектура стенда, API, диаграммы |
| [docs/MATH_MODEL.md](docs/MATH_MODEL.md) | Математическая модель (формулы, параметры) |
| [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md) | Датасеты, калибровка, no-fabrication protocol |
| [changes.md](changes.md) | Полный реестр изменений (аудит) |

---

## Требования

- **Python** 3.11+
- **Docker** + Docker Compose v2
- **Датасеты** (вне репозитория):
  - HAI ICS Security Dataset (Kaggle)
  - Kelmarsh Farm SCADA (Zenodo 5841834)
  - DfT Road Safety Open Data (UK gov)
  - WIOD 2016 NIOT (встроен в репо: `matrix_doc/sources/NIOTS/`)
- **Python-пакеты** (для скриптов вне Docker): `numpy scipy pandas openpyxl`

---

## Статус реализации

| Компонент | Статус |
|-----------|--------|
| СДУ-интегратор (Euler-Maruyama) | ✅ Реализован + 11 тестов |
| Калибровка σ (HAI + Kelmarsh) | ✅ Готово |
| Калибровка C (HAI + DfT HGV) | ✅ Готово |
| Калибровка A (Leontief/WIOD) | ✅ Готово |
| Байесовская калибровка A | ✅ Готово |
| x_j (Gross Output, WIOD NIOT) | ✅ Готово |
| A* Haimes eq.11 (A*_ij = A_ij·x_j/x_i) | ✅ Готово |
| Cascade операторы (Classical/IIM/NEVA β=2) | ✅ Готово + тесты |
| IIM canonical (closed-form q=(I-A*)⁻¹c*) | ✅ Готово |
| Унифицированный MC harness | ✅ Готово |
| MC-оркестрация (HTTP, переходный) | ✅ Работает |
| Этап 3 (operator comparison) | ✅ Готово |
| Этап 4 (MC 15×3) | ✅ Готово + LOO robustness |
| Этап 4-ter (ρ recalibration) | ✅ Готово |
| Этап 4-quint (MAE IIM canonical vs NLDR) | ✅ Готово (H₁ NOT_CONFIRMED, Δ=−50.2%) |
| MC через multiprocessing.Pool | TODO |
| Оптимизатор (optimizer:8006) | TODO |
| Графики для ВКР | TODO |
