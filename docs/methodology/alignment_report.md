# Отчёт о приведении репозитория в соответствие с METHODOLOGY_FINAL.md

**Дата:** 2026-04-20
**Ветка:** `newmain`
**Базовая версия METHODOLOGY_FINAL.md:** v4 (2026-04-20)
**Режим работы:** вариант C по инструкции пользователя — только документация
и конфиги; код (Этапы 3, 4 инструкции) отложен.

---

## Изменённые файлы

### docs

- `docs/ARCHITECTURE.md` — заголовок ветки `resolve` → `newmain`; добавлен раздел 0
  «Методологический базис» (синтез трёх линий); планируемые эндпоинты
  `/compute_K_DR`, `/compute_K_q_recovery`, `/benchmark_centralities`;
  в Mermaid-диаграмме секция «Операторы» с тремя блоками K_cl / K_DR / K_q;
  исправлено `ветка newresearch` → `newmain` во внешних зависимостях и §7.
- `docs/MATH_MODEL.md` — добавлен раздел §2.0 с канонической формой основного
  оператора (формула 5); §4a «Extended operator with recovery» (формула 23 + метрики
  Bruneau 24 и τ^rec 25); §4b «Канонический DebtRank K^(DR)» (§10.1);
  §5a «Калибровка σ по §5.2» — двухшаговая схема ARIMA + Newey—West,
  безразмерная нормировка (16), SNR-check (18), таблица raw/dim/SNR с TODO-маркерами;
  pre-registered θ_node по формуле (9), NERC EOP-011 демонетизирован до исторического
  референса; рефразировано положение о DebtRank-литературе (наследуется только
  принцип непрерывной меры).
- `docs/DATA_SOURCES.md` — баннер источника истины; секция 6 расширена
  ссылкой на §5.1 / §12 METHODOLOGY_FINAL.md (no-fabrication protocol).
- `docs/EXPERIMENT_CATALOG.md` — баннер источника истины; флаг расхождения
  значений матрицы `A_wiod_v3` между каталогом и Таблицей 2 METHODOLOGY_FINAL.md
  (см. «Открытые вопросы»); REAL_christchurch_2011 помечен как расширенная
  валидация (в Таблице 6 финального документа — четыре основных события).
- `docs/RESULTS.md` — баннер «основная серия / Серии 4, 5 в разработке»;
  ветка `newresearch` → `newmain`; ссылка на источник истины.

### readme

- `readme.md` — переформулировано как «синтез трёх линий»
  (Леонтьев / Ринальди / Баттистон); ветка `resolve` → `newmain` в быстром старте;
  METHODOLOGY_FINAL.md добавлен в индекс документации как источник истины.

### changes

- `changes.md` — добавлена запись `[unreleased — v4 alignment, 2026-04-20]`
  в самый верх со списком документационных изменений и явной пометкой, что
  код-часть в этой записи не отражена.

### configs

- `config.env` — заголовок `newresearch branch` → `newmain branch` + ссылка
  на источник истины; новые блоки «Параметры методологии», «Recovery Dynamics»,
  «K_DR baseline», «SNR acceptance check» с §-ссылками. Существующие
  SDE/MC/optimizer переменные не меняются.
- `config.env.example` — те же добавления, формат-комментарии «per
  METHODOLOGY_FINAL.md §...».

## Новые файлы

- `docs/methodology/alignment_report.md` — этот отчёт.

Новых файлов в `services/`, `scripts/`, `tests/` по варианту C не создавалось.

## Placeholder'ы и TODO

Маркеры, оставленные в документации:

- `docs/MATH_MODEL.md` §5a, таблица калибровки — `<!-- TODO: value from
  calibrate_sigma.py (two-step ARIMA + NW) -->` для $\sigma_j^{\text{raw}}$,
  $\sigma_j^{\text{dim}}$, $\mathrm{SNR}_j$ по секторам energy и water. Причина: per
  METHODOLOGY_FINAL.md §5.2 это «к заполнению»; текущие значения в
  `sigma_calibrated.json` получены иной процедурой.
- `docs/EXPERIMENT_CATALOG.md`, баннер — TODO с расхождением значений
  матрицы `A_wiod_v3` между каталогом экспериментов
  (`[[0, 0.350, 0.304], [0.006, 0, 0.001], [0.500, 0.332, 0]]`) и Таблицей 2
  METHODOLOGY_FINAL.md §2.2
  (`[[0, 0.350, 0.087], [0.082, 0, 0.020], [0.500, 0.332, 0]]`). Решение
  отложено — требуется либо перепрогон экспериментов на финальной матрице, либо
  обновление Таблицы 2 по фактическому пути калибровки.
- `docs/ARCHITECTURE.md` §2.1, блок планируемых эндпоинтов — `/compute_K_DR`,
  `/compute_K_q_recovery`, `/benchmark_centralities` помечены **TODO**, требуют
  placeholder-реализаций в `services/risk_engine/operators/` (Этапы 3–4
  исходной инструкции, отложены по варианту C).

## Тесты

Тесты не модифицировались и не добавлялись. Список новых тестов из инструкции
(раздел 4.6) — `tests/operators/test_k_dr.py`, `tests/operators/test_recovery.py`,
`tests/calibration/test_sigma_dim.py`, `tests/benchmarks/test_centrality.py` —
отложен вместе с код-частью.

## Открытые вопросы

1. **Расхождение значений матрицы.** `A_wiod_v3` в `EXPERIMENT_CATALOG.md` и в
   памяти проекта (`energy=[0, 0.350, 0.304]`, `water=[0.006, 0, 0.001]`)
   **не совпадает** с Таблицей 2 METHODOLOGY_FINAL.md
   (`energy=[0, 0.350, 0.087]`, `water=[0.082, 0, 0.020]`). Численные результаты
   таблиц RESULTS.md и EXPERIMENT_CATALOG.md сохранены как есть; какой из двух
   вариантов считать «финальным» — решение пользователя.
2. **Существующая калибровка σ.** `data/calibration/sigma_calibrated.json`
   содержит $\sigma_e = 6{,}54\, \text{ч}^{-1/2}$, $\sigma_w = 18{,}08\, \text{ч}^{-1/2}$ по v1
   (subsampled RV / Zhang 2005). METHODOLOGY_FINAL.md §5.2 требует двухшаговой
   схемы ARIMA + NW и помечает эти же ячейки «к заполнению». Требуется перезапуск
   `calibrate_sigma.py` в новой схеме и последующая сверка безразмерных значений
   с SNR ≥ 1.
3. **Код-часть пропущена.** По варианту C не создавались: `services/risk_engine/
   operators/k_dr.py`, `services/risk_engine/operators/recovery.py`, расширение
   `SDEIntegrator.step` на опциональный $\kappa$, двухшаговая переработка
   `scripts/calibrate_sigma.py`, `scripts/benchmark_centrality.py`, тесты.
   Причина — untracked/modified файлы в рабочем дереве на момент запуска
   (включая `services/risk_engine/operators/`, `state_machine.py`,
   `cascade_operators.py`, `scripts/sigma_calibration/`), которые могут
   представлять частичную реализацию указанных компонентов.
4. **Untracked docs в `docs/_checklists/`** содержат ссылки `Ветка: resolve`.
   Эти файлы — аудит-трейлы прошлых этапов; обновление ветки на `newmain`
   в их заголовках может исказить исторический контекст. Решение — либо
   оставить как есть, либо явно приписать `(историческое значение)` при первой
   возможности.

## Рекомендуемые коммиты

Предлагаемая разбивка (по логическим группам, вариант C-scope):

1. `docs: align top-level methodology docs with METHODOLOGY_FINAL.md` —
   `docs/ARCHITECTURE.md`, `docs/MATH_MODEL.md`, `docs/DATA_SOURCES.md`,
   `docs/EXPERIMENT_CATALOG.md`, `docs/RESULTS.md`, `readme.md`.
2. `config: add methodology and extended-series env vars with
   METHODOLOGY_FINAL.md refs` — `config.env`, `config.env.example`.
3. `chore: update changes.md with v4 alignment entry (docs scope)` —
   `changes.md`.
4. `docs(methodology): add alignment report for v4 source-of-truth migration` —
   `docs/methodology/alignment_report.md`.

После коммитов документации — отдельная серия для код-части:

5. `feat(operators): add K_DR canonical DebtRank placeholder` — новый файл
   `services/risk_engine/operators/k_dr.py` (после ревизии текущих untracked
   файлов в `services/risk_engine/operators/`).
6. `feat(operators): add recovery dynamics with backward-compatible κ` —
   новый файл `services/risk_engine/operators/recovery.py` + изменения в
   `sde_integrator.py`.
7. `feat(calibration): two-step ARIMA + NW σ calibration with dimensionless
   SNR check` — правки `scripts/calibrate_sigma.py` (после уточнения, что
   делать с `calibrate_sigma_v2.py` и `scripts/sigma_calibration/`).
8. `feat(benchmark): add centrality comparison script` —
   `scripts/benchmark_centrality.py`.
9. `test: add placeholder tests for new operators and metrics` —
   `tests/operators/`, `tests/calibration/`, `tests/benchmarks/`.

---

**Git-коммитов и push-ей в рамках этой работы не сделано.** Коммиты оставлены
пользователю, чтобы он мог их выполнить вручную и при необходимости
перераспределить изменения между коммитами.
