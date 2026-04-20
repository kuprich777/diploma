# Этап 1.2 — Аудит первичных источников перед извлечением интенсивностей

**Дата:** 2026-04-19
**Ветка:** `methodology-overhaul`
**Статус:** ⏸ PAUSE — требуется решение пользователя перед извлечением

## Проблема

Принцип 1 («никакой фабрикации») требует, чтобы каждая интенсивность воздействия в `cascade_events.yaml` трассировалась до страницы первичного источника. Сканирование 4 primary PDF показало, что **три из четырёх отчётов не документируют кросс-секторальные последствия систематически** — это секторально-специфические (электроэнергетика / морской транспорт) расследования.

## Сводка по событиям

| Событие | Primary PDF | Energy | Water | Transport |
|---|---|---|---|---|
| EUROPE_2006 | UCTE Final Report | ✓ «>15 млн домохозяйств» (p. 10) | ✗ NOT_DOCUMENTED (0 упоминаний rail/metro/municipal water) | ✗ NOT_DOCUMENTED |
| TEXAS_2021 | FERC/NERC Cold Weather | ✓ «4.5 млн человек без электроэнергии» (p. ~23) | ~ «boil-water orders» упомянут только в сноске 5 (ссылка на WSJ), без количественных данных; generation feedwater — это **в пределах energy** | ✗ NOT_DOCUMENTED |
| INDIA_2012 | MoP Annual Report 2012-13 | ✓ «two disturbances 30-31 July, essential loads restored 2-3 hours» (p. 112) — 1 абзац, без count | ✗ NOT_DOCUMENTED | ✗ NOT_DOCUMENTED |
| BALTIMORE_2024 | NTSB MIR-25-40 | ✗ NOT_DOCUMENTED | ✗ NOT_DOCUMENTED | ✓ Обрушение моста, закрытие порта (весь отчёт об этом) |

**Диагональ по соглашению a_ii=0** (строки Level 1 prior) — самосектор инициатора не считается.

## Честное извлечение при строгом соблюдении Принципа 1

Из 4 событий × 3 сектора = 12 внедиагональных ячеек-наблюдений:
- Только 1 ячейка имеет документированную интенсивность в primary: Baltimore → transport (но transport и есть инициатор, т.е. диагональ).
- Кросс-секторальных (off-diagonal) ячеек с документированными данными: **0**.
- Europe 2006 energy→? : primary документирует energy-последствия (households), но energy — это инициатор; строка energy в матрице должна иметь пропагацию на transport/water, не на energy.
- Texas 2021 energy→? : аналогично — events внутри energy, включая generation feedwater, не являются cross-sector.

**Под строгим primary-only режимом Level 2 даёт 0 информативных ячеек** — Bayesian posterior будет полностью prior-dominated.

## Варианты для пользователя

### Вариант A. Строго primary-only, задокументировать отсутствие данных
- `cascade_events.yaml` фиксирует: для каждого события — только *инициатор* и его *амплитуда* из primary (с page). Off-diagonal intensities = `NOT_DOCUMENTED_IN_SOURCE`.
- Beta-Binomial posterior в Этапе 1.4 вырождается в Level 1 prior (renormalised initiator marginals).
- Плюс: полная прозрачность, никакой фабрикации.
- Минус: теряется ценность авторского датасета — он ничего не добавляет к Pescaroli.

### Вариант B. Добавить secondary-источники для документированных фактов
Для каждого события найти один вторичный peer-reviewed / official источник, документирующий cross-sector последствия:
- EUROPE_2006 → e.g. Pescaroli & Alexander 2016 сами обсуждают этот кейс; ENTSO-E follow-up reports; академические статьи.
- TEXAS_2021 → TWDB (Texas Water Development Board) post-event report о boil-water advisories (14.9 млн подвергнуто, по открытым данным); GAO-22-105312.
- INDIA_2012 → CERC «Report on the Grid Disturbance on 30th and 31st July 2012» (официальный отчёт Central Electricity Regulatory Commission, публично доступен) — документирует 670 млн затронутых, транспорт (метро Delhi, пригородные поезда).
- BALTIMORE_2024 → GAO / MDTA отчёты, экономические исследования о закрытии порта.

Маркировка `source_level: "secondary"` для каждой такой ячейки, отдельное поле `primary_confirms: true/false/partial`.
- Плюс: датасет становится информативным; Bayesian posterior реально двигает prior.
- Минус: требует дополнительных PDF (у нас их пока нет), либо web-цитирование с указанием точного URL/DOI.

### Вариант C. Сократить таксономию событий или заменить часть из них
Заменить INDIA_2012 (беден в документации) на событие с лучше документированным primary. Кандидаты:
- US-Canada 2003 (отчёт у нас есть, `USCanadaNEBlackoutReportch1-32003.pdf`) — хорошо документирует transport (NYC subway, airports) и water.
- Iberia 2025 (отчёт у нас есть, `Final Report ... Spain and Portugal 28 April 2025.pdf`) — свежий, возможно документирует больше.

## Рекомендация

**Вариант B** с 1–2 secondary-источниками на событие, явно маркированными. Это даст:
- ~6–8 информативных ячеек (из 12 возможных).
- Datset, который действительно обновляет prior.
- Полную прозрачность: каждая ячейка с `source_level` и `citation_url_or_page`.

Для этого пользователю нужно либо:
- (B1) Скачать CERC India 2012 отчёт + TWDB/GAO Texas 2021 отчёт + положить в `data/empirical_cascades/reports/`;
- (B2) Разрешить цитирование открытых secondary-источников по URL/DOI без локального PDF (менее строго, но реалистично).

## Что сделано на этом шаге

- Извлечён полный текст UCTE 2006 (4372 строки), Texas 2021 (12042), India 2012 (12331), Baltimore 2024 (10932) в `/tmp/*.txt`.
- Выполнен keyword-scan по `rail|train|metro|water|pump|traffic|highway|tunnel|port|commut|boil`.
- Идентифицирована секция India 2012 blackout (lines 5704–5718 MoP Annual Report): 1 абзац, без count затронутых.
- Идентифицирована секция Texas water в примечании 5 (p. ~XV): ссылка на WSJ, без количественных данных в самом FERC/NERC отчёте.
- Baltimore — transport-события описаны подробно, energy/water — нет.

## Остановка

Остановка до решения пользователя по Варианту A / B / C.
