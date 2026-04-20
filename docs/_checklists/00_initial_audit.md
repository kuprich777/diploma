# Этап 0 — Инвентаризация инфраструктуры

**Дата:** 2026-04-19
**Ветка:** `methodology-overhaul` (создана от `resolve`, baseline-коммит `f8497b6`)

## Сводный статус

`[✓]` — в наличии, пригодно | `[~]` — частично / требует уточнения | `[✗]` — отсутствует

### Инфраструктура кода

- `[✓]` SDE-интегратор — `services/risk_engine/sde_integrator.py` (Euler-Maruyama, reflecting `[0,1]`)
- `[✓]` Функция φ_j — описана в докстринге и реализована в `_compute_dynamic_A()` (строка 154)
- `[✓]` Рефлектированная граница Скорохода — реализована через `clip_{[0,1]}` (строки 13, 199, 272)
- `[✓]` 18/18 существующих тестов проходят (`pytest tests/ -q` → `18 passed in 0.16s`)

### Библиотеки Python

- `[✓]` `pandas 2.0.3`, `numpy 1.24.3`, `scipy 1.11.1`, `matplotlib 3.7.2`, `seaborn 0.12.2`, `pyyaml 6.0` — уже установлены
- `[~]` `pymc 5.28.4`, `arviz 0.23.4` — установлены, **но импорт сопровождается предупреждениями о несовместимости NumPy 1.x / 2.x в связанных библиотеках (pyarrow, bottleneck, numexpr)**. Финальный import возвращает объект модуля, но возможны runtime-сбои в сложных операциях. Для Этапа 1 предусмотрена closed-form Beta-Binomial калибровка без MCMC, поэтому pymc может не потребоваться в критическом пути.
- `[✓]` `neva` (Bardoscia) — установлен из git, импортируется. Версия `__version__` не выставлена пакетом.

### Матрицы и данные

- `[~]` Матрица WIOD — **не найдена в `data/calibration/A_WIOD_v3.json`** (там лежит старая `A_leontief.json` от 15 апреля). Однако snapshot присутствует в `results/A_wiod_v3_snapshot.json` (закоммичено в `f8497b6`). Для sensitivity-анализа Этапа 1.5 источник есть.
- `[✓]` **SCADA-данные — все 4 источника найдены и слинкованы.**
  - `data/scada/hai` → `/Users/kuprich/Documents/diploma_repo/datasets/dataset hai /hai` (подмножества hai-20.07, hai-21.03, hai-22.04, hai-23.05)
  - `data/scada/kelmarsh` → Kelmarsh SCADA 2016–2021 + PMU + Grid + static (данные 6 лет)
  - `data/scada/openwindscada` → OpenWindSCADA (data/, notebooks/, community_annotations/)
  - `data/scada/road_safety` → DfT Road Safety (casualty/collision/vehicle CSV, last 5 years)
- `[✓]` **Primary PDF для всех 4 исторических событий найдены и слинкованы.**
  - EUROPE_2006 → `blackout-nov-06-UCTE-report.pdf` (UCTE Final Report: System Disturbance on 4 November 2006)
  - TEXAS_2021 → `Cold Weather Report_ 2021_120821.pdf` (FERC-NERC-Regional Entity Staff Report: The February 2021 Cold Weather Outages in Texas and the South Central United States)
  - INDIA_2012 → `Annual_Report_2012-13_English.pdf` (Ministry of Power, Government of India, Annual Report 2012-13)
  - BALTIMORE_2024 → `MIR2540.pdf` (NTSB MIR-25-40, 18 ноября 2025, Contact of Containership Dali with Francis Scott Key Bridge)
- `[✓]` Методологические и вспомогательные PDF:
  - `barucca2020NEVA.pdf` — Barucca et al. 2020 (для Этапа 3)
  - `FR2016_Pescaroli_Nones.pdf` — Pescaroli & Nones 2016 (Level 1 prior; соавтор Nones, не Alexander — требует сверки с каноническим Pescaroli & Alexander 2016 в Natural Hazards)
  - `USCanadaNEBlackoutReportch1-32003.pdf` — US-Canada 2003 Task Force Report (дополнительное historical, если понадобится)
  - `Final Report ... Spain and Portugal 28 April 2025.pdf` — Iberia 2025 (дополнительное historical)
  - `MIR2510.pdf` — NTSB MIR-25-10 контекст Baltimore
  - `Statistical_Yearbook_2007_4.pdf` — UCTE 2007 годовая статистика (supplementary для Europe 2006)
  - `02-0417.pdf` — Milwaukee Cryptosporidium 1993 (water→health, вне 3-секторной модели; не используется)
- `[—]` Не связаны с методологией (не линкуются): `FERC-NERC-...-Presentation-38-RM.pdf` (McCullough Research memo, вторичный — перекрыт FERC/NERC Cold Weather Report), `epjconf_MINOS2012_04002.pdf` (семинар по ядерным материалам CEA France, не связан с India 2012 blackout).

### Структура директорий (0.2)

Созданы:
- `data/empirical_cascades/{reports,papers,historical_dataset,matrix_calibration}/`
- `data/scenarios/` (уже была, содержит `REAL_europe_2006.json`, `REAL_india_2012.json`)
- `docs/{_checklists,methodology,legacy}/`

`data/scada/` — **не создана**, поскольку исходные датасеты отсутствуют; создавать пустую пока нет смысла.

## Блокеры

1. ~~SCADA-датасеты (Этап 2)~~ — **снято** (2026-04-19): все 4 источника слинкованы из `/Users/kuprich/Documents/diploma_repo/datasets/`.
2. ~~PDF источников для Level 2~~ — **снято** (2026-04-19): primary-отчёты по всем 4 запланированным событиям присутствуют в `datasets/reports/` и слинкованы. Pescaroli-prior также есть (требуется сверка FR2016_Pescaroli_Nones vs канонической Pescaroli & Alexander 2016 при первом использовании).
3. **NumPy 1.x / 2.x** (остаётся) — предупреждения при импорте pymc/arviz из-за несовместимости с pyarrow/bottleneck/numexpr. Для closed-form Beta-Binomial в Этапе 1.4 не критично (pymc не нужен в критическом пути). Проявится только при попытке `pymc.sample()` или при активном использовании pandas.ArrowExtensionArray. Решается при необходимости созданием изолированного окружения `conda create -n diploma python=3.11 "numpy<2"`.

## Что сделано на Этапе 0

- Ветка `methodology-overhaul` создана от `resolve`, baseline-коммит `f8497b6` с артефактами прошлой методологии зафиксирован.
- Рабочие директории созданы (кроме `data/scada/` — см. блокер 1).
- Библиотеки установлены; runtime-предупреждения задокументированы.
- Инвентаризация проведена, три блокера выявлены явно.

## Переход к Этапу 1

Все блокеры сняты, все primary-источники на месте. Готово к запуску Этапа 1. **Остановка для подтверждения.**
