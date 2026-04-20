# MIGRATION_PLAN — синхронизация репозитория с METHODOLOGY.md

**Ветка:** `newmethod`
**Источник истины:** `docs/methodology/METHODOLOGY.md` (v2.0-draft, 986 строк, от 2026-04-19)
**Дата плана:** 2026-04-19
**Статус:** УТВЕРЖДЁН автором 2026-04-19. Решения A-G зафиксированы в конце документа. Приступаем к Этапу 1.

Принцип: METHODOLOGY.md — нормативный документ. Весь код, скрипты, документация должны буквально
соответствовать её формулировкам. При расхождении: либо править код/документ, либо править
METHODOLOGY.md (по решению автора), но держать согласованность в ОДНОМ месте.

Этот план разделён на четыре категории: **сохранить**, **править**, **удалить**, **создать** —
плюс блок вопросов к автору (требуется решение перед исполнением).

---

## 1. СОХРАНИТЬ (соответствует METHODOLOGY.md как есть)

| Путь | Почему соответствует |
|------|---------------------|
| `docs/methodology/METHODOLOGY.md` | нормативный источник истины |
| `services/risk_engine/` (FastAPI шасси, `main.py`, `settings.py`) | инфраструктура без методологии |
| `services/{energy,water,transport}_service/` (HTTP-каркас) | доменные сервисы без методологии; параметры рефакторятся по §8 |
| `services/scenario_simulator/` (HTTP-каркас, БД, pydantic модели) | оркестратор без привязки к конкретным операторам; будет переиспользоваться |
| `docker-compose.yml`, `Makefile` (up/down/test/logs) | инфраструктура |
| `tests/test_sde_integrator.py` | 11 unit-тестов интегратора Эйлера-Маруямы — базовые числовые свойства сохраняются для K_q^abs (§3.4) |
| `matrix_doc/sources/NIOTS/` (43 WIOD NIOT xlsx) | сырой датасет WIOD 2016 NIOT, используется в §7 (расширяется на 6 стран) |
| `Energy Outage Dataset/` (EAGLE-I) | источник для Series 7 Texas 2021 (§9.3) |
| `data/wiod/` (если есть artefact) | первичные таблицы |

---

## 2. ПРАВИТЬ (код/документ есть, но не матчит методологию)

### 2.1. services/risk_engine/

| Файл | Что менять | Секция METHODOLOGY |
|------|-----------|-------------------|
| `cascade_operators.py` | Полностью переписать под §3.1–§3.4. Удалить текущие `ClassicalOperator` (x+Ax без бинаризации), `IIMOperator` (итеративный c_star), `NevaOperator` (β-экспоненциальный). Внедрить 4 новых оператора: `KLeontiefOperator` (§3.1, closed-form), `KClOperator` (§3.2, бинаризация + ε_cl + правило §8.5), `KDROperator` (§3.3, state machine + direct a_ij·h_j + forced O→F), `KqDegOperator` и `KqAbsOperator` (§3.4). Единый контракт §9.2. | §3.1–§3.4, §9.2 |
| `sde_integrator.py` | Переписать drift по §3.4: `x_{t+1} = x_t + u_t + A(t)x_t + σ√Δt ε_t` (без `-ρ·x`); shock u_t применяется на шаге шока (а не только t=0), σ_transport=0 детерминированно. | §3.4 |
| `mc_harness.py` | Переписать под 4 новых оператора (унифицированный контракт §9.2); общий pred-correc шум; убрать IIM/NEVA из имён. | §9.2 |
| `iim_canonical.py` | Удалить либо перенести в `legacy/`. Операторы §3 не используют Haimes A*-transform. | §3 (отсутствует) |
| `routers/risk.py` | `WEIGHTS={e:0.7,w:0.2,t:0.1}` → `w_j = GO_j / Σ GO_k` (§5.2). Перепроверить `CURRENT_THETA_BIN` — должно быть 0.75 по §0.4. Endpoints адаптируются под новые операторы. | §5.2, §0.4 |

### 2.2. scripts/calibrate_*

| Файл | Что менять | Секция |
|------|-----------|-------|
| `scripts/calibrate_sigma.py` | Полностью переписать под §8.2: (1) ARIMA pre-filtering AR(p), BIC по p∈{1,2,3}; (2) Newey-West HAC с L=⌊4(n/100)^(2/9)⌋; (3) /(1-C_j) безразмерная нормировка; (4) SNR-gate SNR_j=δ/(σ_j^dim √Δt)≥1 — блокирующий. σ_transport=0 фиксируется. ACF(1)<0.1 — критерий приёмки. | §8.2 |
| `scripts/sigma_calibration/extract_sigma_hourly.py` | Проверить; переписать под ту же §8.2 или удалить (дубль функционала). | §8.2 |
| `scripts/calibrate_capacity.py` | Оставить логику HAI+DfT (§8.1), но перепроверить выборки/отчёт. Контракт `C_energy≈0.88, C_water≈0.65, C_transport≈0.93` зафиксирован §0.4. | §8.1, §0.4 |
| `scripts/calibrate_A.py` | Переписать под §7: 6 кандидатов (DEU, USA, GBR, FRA, JPN, CAN), **без RUS**, Spearman≥0.85 pairwise, отбор подмножества C* с \|C*\|≥3, нормировка a_ij^ols = a_ij^raw/a_jj^raw, zero diagonal, spectral radius ≤0.95 в конце. Artefact `A_WIOD_v4`. | §7 |
| `matrix_doc/calibrate_wiod.py` | Привести к §7 или удалить (дубль `scripts/calibrate_A.py`). | §7 |
| `scripts/matrix_calibration/apply_haimes_transformation.py` | Удалить или перенести в `legacy/` — §3 не использует A*-transform. | §3 |
| `scripts/matrix_calibration/bayesian_posterior*.py` | Привести под Appendix Б: LOOCV, σ_ε=0.25 prior std. | Appendix Б |
| `scripts/matrix_calibration/extract_sector_outputs.py` | Переориентировать на 6-страновый набор и GO по §7/§5.2 (для w_j). | §7, §5.2 |
| `scripts/matrix_calibration/loo_calibration.py` | Пересобрать под A_WIOD^v4. | §7 |

### 2.3. scripts/run_* (эксперименты)

| Файл | Что менять | Секция |
|------|-----------|-------|
| `scripts/run_operator_comparison.py` | Заменить на единый `scripts/run_experiment.py` (§9.2). | §9 |
| `scripts/run_stage4_mc.py` | То же. | §9 |
| `scripts/run_full_experiment.py` | То же. Удалить хардкод A_wiod_v3, σ=[0.259,...], dt=0.1. | §9 |
| `scripts/run_theta_sweep.py`, `scripts/run_load_sweep.py` | Переписать как подпрограммы `run_experiment.py` или удалить. | §9 |
| `scripts/validation/mae_comparison.py` | Переосмыслить в контексте §5–§6 (сравнение 4 операторов, не IIM-vs-NLDR). | §5, §6 |
| `scripts/diagnostics/` | Проверить на совместимость с новой матрицей/σ; обновить. | §7, §8 |

### 2.4. services/scenario_simulator/

| Файл | Что менять | Секция |
|------|-----------|-------|
| `routers/simulator.py` | Каталог сценариев проверить на покрытие 8 сценариев §9.1 (4 синтетических + 4 исторических). Добавить недостающие. | §9.1 |
| `schemas.py` | Поля `theta_node`, `theta_cascade` → зафиксировать 0.75, 0.05 как default по §0.4; добавить поля для K^abs (τ, u_t, σ). | §0.4, §3.4 |

### 2.5. docs/ (верхний уровень)

| Файл | Что менять |
|------|-----------|
| `docs/ARCHITECTURE.md` | Актуализировать: 4 оператора §3, единый harness, state_machine.py. Убрать упоминания IIM canonical / NLDR β=2 как основных методов. |
| `docs/DATA_SOURCES.md` | Обновить §4 (WIOD → 6 стран, без RUS), §1-2 (σ через §8.2). Добавить выборочный период, ACF(1) отчёт. |
| `docs/MATH_MODEL.md` | Привести к §3 METHODOLOGY (4 оператора, state machine) **или** удалить — по решению автора (см. вопрос A ниже). |
| `docs/EXPERIMENT_CATALOG.md` | Полностью переписать под §9.3 (8 серий: Series 1 S1, Series 2 S1', Series 3 S3, Series 4 S4, Series 5 Baltimore, Series 6 UCTE, Series 7 Texas, Series 8 India). |
| `docs/RESULTS.md` | Очистить/пересчитать: после выполнения Этапов 1-3 заполнить матрицами K|M, K_sat, D, R, CDF; при текущем статусе — отметить как «pending Phase 3». |
| `readme.md` | Актуализировать список этапов, ссылки, структуру. |
| `changes.md` | Добавить раздел `## [newmethod] METHODOLOGY v2.0 migration`. |
| `docs/_checklists/` | Добавить чеклисты по Phase 1–5 и §13.3 приёмка. |

---

## 3. УДАЛИТЬ (устарело / противоречит новой методологии)

> **Политика:** не удалять в Этапе 0; только пометить в плане. Физическое удаление — после утверждения.
> Рекомендуется перенос в `legacy/` (на случай аудита), не физический `rm`.

| Путь | Причина |
|------|---------|
| `services/risk_engine/iim_canonical.py` | §3 не использует Haimes A*-transform; IIM canonical не входит в 4 оператора. |
| `scripts/matrix_calibration/apply_haimes_transformation.py` | См. выше. |
| `data/calibration/A_star_iim_canonical.json` | Артефакт устаревшего A*-transform. |
| `data/calibration/A_wiod_sensitivity*` (если содержат RUS) | §7 явно запрещает RUS. |
| `results/stage4_*` (если полагались на IIM canonical / NLDR β=2) | Методологически устарели; оставить как `results/legacy/etap_4_pre_methodology/`. |
| `results/etap_4_original/` | То же. |
| `docs/methodology/stage4_quint_iim_vs_nldr.md` | IIM vs NLDR — не входит в §3/§9.3. Либо удалить, либо пометить «pre-v2.0 archive». |
| `docs/methodology/calibration_rationale.md` | Проверить: если описывает §8 некорректно — переписать; если историческое обоснование — пометить архивным. |

---

## 4. СОЗДАТЬ (нет в репо, требуется по METHODOLOGY)

### 4.1. Код

| Путь | Назначение | Секция |
|------|-----------|-------|
| `services/risk_engine/state_machine.py` | Single source of truth: s_j∈{N,O,F}, 5 priority rules, F absorbing, forced O→F одношаговый. Используется K_DR (§3.3) и K_q^deg (§3.4). | §2.3 |
| `services/risk_engine/operators/k_leontief.py` | Closed-form q=(I-A)⁻¹ c (impulse). | §3.1 |
| `services/risk_engine/operators/k_cl.py` | Бинаризация y_i=I(x_i≥θ_node), правило ε_cl=0.05, contingency §8.5. | §3.2 |
| `services/risk_engine/operators/k_dr.py` | State machine + direct a_ij·h_j + forced O→F. | §3.3 |
| `services/risk_engine/operators/k_q.py` | K_q^deg (дискретный через state machine) и K_q^abs (SDE через sde_integrator). | §3.4 |
| `services/risk_engine/contract.py` | Единый контракт операторов (§9.2): вход {x₀, A, u_t, σ, params}, выход {x_T, events, K_mask}. | §9.2 |
| `scripts/run_experiment.py` | Единый раннер: принимает series_id, сценарий, оператор, N_runs; делает MC на общем шуме; пишет в `results/<series>_<operator>_<params>.json`. | §9.2 |
| `scripts/bootstrap_paired.py` | Paired bootstrap B=10⁴ на парах (r_Kq, r_Km); Bonferroni 98.33% CI (3 сравнения); baseline_zero_detect handling. | §6 |
| `scripts/calibrate_A_v4.py` | Реализация §7 (6 стран, Spearman отбор, a_jj нормировка, spectral≤0.95) → `data/calibration/A_WIOD_v4.json`. (Или рефактор `calibrate_A.py`.) | §7 |
| `scripts/calibrate_sigma_v2.py` | ARIMA + Newey-West + /(1-C_j) + SNR-gate. (Или рефактор `calibrate_sigma.py`.) | §8.2 |

### 4.2. Тесты (§13.1)

| Тест | Проверяет |
|------|----------|
| `tests/test_state_machine.py::test_state_machine_matches_spec` | 5 правил §2.3; F absorbing; forced O→F. |
| `tests/test_operators.py::test_Kq_abs_reduces_to_KDR` | K_q^abs при σ=0, τ=ε_cl=0.05 сходится к K_DR в пределе Δt→0. |
| `tests/test_operators.py::test_all_operators_same_contract` | Все 4 оператора принимают общий вход §9.2 и дают общий выход. |
| `tests/test_operators.py::test_Kcl_contingency_rule` | §8.5 (θ_node adjustment). |
| `tests/test_calibration.py::test_A_spectral_radius` | ρ(A^v4) ≤ 0.95. |
| `tests/test_calibration.py::test_sigma_snr_gate` | Блокирующий SNR≥1 для energy+water. |
| `tests/test_bootstrap.py::test_paired_bootstrap_ci` | Bonferroni 98.33% CI ширина. |
| `tests/test_weights.py::test_go_weights_sum_to_one` | §5.2. |

### 4.3. Документация

| Путь | Назначение |
|------|-----------|
| `docs/methodology/PHASE_1_REPORT.md` | По окончании Этапа 1. |
| `docs/methodology/PHASE_2_REPORT.md` | По окончании Этапа 2. |
| `docs/methodology/PHASE_3_REPORT.md` | По окончании Этапа 3. |
| `docs/methodology/PHASE_4_REPORT.md` | По окончании Этапа 4. |
| `docs/methodology/MIGRATION_COMPLETE.md` | По окончании Этапа 5. |
| `docs/00_index.md` … `docs/06_data_sources.md` | **Требуется решение автора (см. вопрос B).** |
| `docs/WEIGHTS_NOTE.md` | Обоснование w_j=GO_j/Σ, §5.2. **Требуется решение автора (B).** |

### 4.4. Данные

| Путь | Что будет |
|------|----------|
| `data/calibration/A_WIOD_v4.json` | Матрица 3×3 по 6 странам, §7. |
| `data/calibration/A_WIOD_v4_meta.json` | Список стран C*, pairwise Spearman, a_jj^raw, ρ(A). |
| `data/calibration/sigma_calibrated_v2.json` | σ по §8.2 с SNR-отчётом, ACF(1). |
| `data/calibration/sector_weights_v1.json` | w_j=GO_j/Σ GO_k по §5.2. |

---

## 🔴 ТРЕБУЕТСЯ РЕШЕНИЕ АВТОРА

Перед переходом к Этапу 1 нужны однозначные решения по 7 пунктам. Не могу продолжать, не
придумав ответы — нарушит принцип no-fabrication.

### A. Судьба `docs/MATH_MODEL.md`
METHODOLOGY.md §3 полностью заменяет прежние формулы. Два варианта:
- **A1:** удалить `docs/MATH_MODEL.md`, оставить только `docs/methodology/METHODOLOGY.md` как единый math-source.
- **A2:** сохранить `docs/MATH_MODEL.md` как короткий stub с заголовком и ссылкой `→ см. METHODOLOGY.md §3`.

**Рекомендация:** A2 (stub) для совместимости с существующими ссылками в `readme.md` и PR-ах.

### B. Восстанавливать ли `docs/00_index.md` … `06_data_sources.md` и `WEIGHTS_NOTE.md`
Эти файлы упомянуты в изначальном промте, но на ветке `newmethod` их нет (были в baseline
commit `f8497b6` на другой ветке). Варианты:
- **B1:** восстановить из `f8497b6` и переписать под METHODOLOGY v2.0.
- **B2:** НЕ восстанавливать — использовать монолитную `METHODOLOGY.md` + узкий `ARCHITECTURE.md`/`DATA_SOURCES.md`.
- **B3:** заново написать 7 коротких файлов с нуля под v2.0.

**Рекомендация:** B2 (одна нормативная METHODOLOGY + минимум верхнеуровневых docs) — меньше мест для расхождений.

### C. Удалять или архивировать legacy-артефакты
- `services/risk_engine/iim_canonical.py`, `apply_haimes_transformation.py`, `A_star_iim_canonical.json`, `stage4_*` результаты, `stage4_quint_iim_vs_nldr.md`.
- **C1:** физическое удаление (чистый репо).
- **C2:** перенос в `legacy/` (аудиторский след).

**Рекомендация:** C2 на время миграции (Этапы 1-3), физическое удаление — на Этапе 4 после подтверждения, что новые операторы отработали все 8 серий.

### D. σ_transport=0 — источник «нулевой σ» в §8.2 СДЕ
§8.2 требует σ_transport=0 детерминированно. Нужно подтвердить:
- **D1:** σ=0 подставляется прямо в SDE (drift-only траектория transport) — K_q^abs для transport≡детерминистский;
- **D2:** σ=0 означает «нет стохастической компоненты», но остаётся шум в шоках u_t;
- **D3:** σ_transport=0 только в Series 7/8 исторических, а в синтетических S3/S4 берётся non-zero из альтернативного источника.

**Цитата METHODOLOGY.md:** «σ_transport = 0 детерминированно (нет подходящего источника)».
**Моё прочтение:** D1 — буквально. Подтверди, что D1 корректно.

### E. Источник временного ряда для σ_transport (если D≠D1)
Если σ_transport ≠ 0, нужен источник высокочастотного временного ряда. В репо нет такого
датасета для transport (DfT — количество аварий в месяц, не часовое). Если D=D1 — вопрос снимается.

### F. Порядок и стратегия удаления RUS из матричной калибровки
В памяти зафиксирована A_wiod_v3 (RUS+DEU+USA, ρ=0.3955). После миграции на A_WIOD^v4
(без RUS, +GBR/FRA/JPN/CAN):
- **F1:** все ранее зафиксированные результаты (baseline MC, marginal S3, Sprint 1/2, θ recalibration, REAL_baltimore_2024, REAL_europe_2006 — см. auto-memory) становятся методологически несовместимыми. Они помечаются «PRE-v2.0 ARCHIVE» и полностью перезапускаются.
- **F2:** оставить A_wiod_v3 как «historical baseline», сравнивать новые результаты с ним.

**Рекомендация:** F1. F2 создаст противоречие «RUS-included baseline vs RUS-excluded run» — смешение несравнимых методологий.

### G. θ_node — 0.70 или 0.75
В auto-memory записано, что актуальное значение 0.70 (откат 2026-04-12 для REAL_europe_2006).
В METHODOLOGY.md §0.4 пре-зарегистрированное значение **θ_node = 0.75**.
- **G1:** θ=0.75 — единственное значение, используется во всех 8 сериях (METHODOLOGY нормативна).
- **G2:** держать в коде оба, по умолчанию 0.75; 0.70 — только в legacy воспроизведении.

**Рекомендация:** G1. G2 вернёт двойственность, которая и привела к необходимости этой миграции.

---

## План Этапов 1-5 (после утверждения)

- **Этап 1:** `state_machine.py` + 4 оператора + unit-тесты §13.1 → `PHASE_1_REPORT.md`.
- **Этап 2:** `A_WIOD_v4` + σ по §8.2 + SNR-gate + `w_j` → `PHASE_2_REPORT.md`.
- **Этап 3:** 8 серий (MC с общим шумом), paired bootstrap, Bonferroni → `PHASE_3_REPORT.md`.
- **Этап 4:** синхронизация всей документации, `changes.md` → `PHASE_4_REPORT.md`.
- **Этап 5:** pytest green, §13.3 приёмка, dry-run Series 1 N=50 → `MIGRATION_COMPLETE.md`.

Между этапами — явные gate: следующий этап не начинается, пока автор не утвердил отчёт предыдущего.

---

**Жду решений по пунктам A-G и общего GO на переход к Этапу 1.**

---

## Решения автора (2026-04-19)

- **A → A1** (удаление): `docs/MATH_MODEL.md` удаляется. Единый math-source — `docs/methodology/METHODOLOGY.md`.
- **B → условно B1**: `docs/00_index..06_data_sources.md` и `WEIGHTS_NOTE.md` восстанавливать только если анализ на Этапе 4 покажет их необходимость. По умолчанию — **не восстанавливаем**.
- **C → C1** (физическое удаление): `iim_canonical.py`, `apply_haimes_transformation.py`, `A_star_iim_canonical.json`, `stage4_*` результаты, `stage4_quint_iim_vs_nldr.md` — удалить на соответствующих этапах.
- **D → D1** (строго буквальное): `σ_transport = 0` во всех операторах, во всех сценариях, без исключений. В K_q транспорт эволюционирует детерминированно: `x_transport(t+1) = clip(x_transport(t) + u_transport(t) + Σ_j A(t)_{t,j} x_j(t))`, без броуновской компоненты. Шум energy/water опосредованно влияет на transport через A.
- **E**: источник ряда не ищем. Назначение σ_transport экспертно или через proxy нарушило бы no-fabrication protocol. Направление будущих исследований — **Belgium OBU (Kaggle) + Caltrans PeMS**: агрегация нагрузки узла и калибровка через ARIMA + Newey-West. Зафиксировать в `DATA_SOURCES.md` как «будущие источники».
- **F → F1**: все предыдущие MC-результаты (A_wiod_v3 baseline, marginal S3, Sprint 1/2, θ-recalibration, REAL_baltimore_2024, REAL_europe_2006) помечаются PRE-v2.0 ARCHIVE и полностью перезапускаются на A_WIOD^v4.
- **G → G1**: θ_node = 0.75 — единственное значение, во всех 8 сериях. METHODOLOGY.md §0.4 нормативна. Старое 0.70 — удаляется из кода/конфигов (не сохраняется как legacy-константа).

GO на Этап 1: 2026-04-19.
