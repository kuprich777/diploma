# Обоснование калибровки ρ(A), ρ_rec и T_steps

## ρ(A) — спектральный радиус матрицы зависимостей

### Численное значение и источник
После применения Beta-Binomial posterior (prior Beta(1,1), 2/12 ячеек с документированными наблюдениями) сырая матрица A_raw имеет ρ = 1.0000 (на грани неустойчивости из-за почти-равномерных posterior-средних 0.50). Применяется спектральная нормировка:

```
A_capped = A_raw · (ρ_target / ρ(A_raw))  при  ρ(A_raw) > ρ_target
```

### Финальный выбор: ρ_target = 0.50 (Этап 4-ter)

Выбран после параметрического sweep 5×5 (см. `results/diagnostics/rho_sweep.md` и `docs/_checklists/04_ter_recalibration_report.md`).

Sweep идентифицировал 5 пар (ρ_A, ρ_rec) с discriminating SDE-откликом на маржинальном сценарии. Все они характеризуются **λ_growth = ρ_A − ρ_rec = +0.20** — режим слабой supercriticality, где SDE разрешает амплитуду и не уходит в clip=1.

Выбор `(ρ_A, ρ_rec) = (0.50, 0.30)` — по трём критериям:

1. **Recovery time 1/ρ_rec = 3.33 time units ≈ 3.3 часа** (при dt=0.1 ч, что соответствует калибровке σ per-hour):
   - UCTE 2006: «normal in less than 2 hours»;
   - India 2012: «essential loads restored within 2–3 hours»;
   - 3.3 часа покрывает обе оценки консервативно.
2. **Cross-sector coupling ρ_A=0.50** → off-diagonals ≈ [0.21, 0.29]: strong enough for cascade propagation but well below instability threshold.
3. **Запас по условию Банаха**: ρ_A < 1 с зазором 0.50.

### История выбора

| Этап | ρ_target | ρ_rec | Status |
|---|---|---|---|
| Stage 4 original | 0.95 | 0.02 | ❌ SDE saturates (K_cl=1 all scenarios) |
| Stage 4-bis | 0.70 | 0.02 | ❌ λ_growth=+0.68 → still saturates |
| **Stage 4-ter** | **0.50** | **0.30** | ✅ discriminating, K_cl ∈ [0.004, 0.589] |

### Теоретическая ссылка
Bardoscia M., Battiston S., Caccioli F., Caldarelli G. (2017). **«Pathways towards instability in financial networks»**. *Nature Communications 8, 14416.* Показана монотонная зависимость скорости каскада от ρ(L): при ρ близком к 1 — экспоненциальное разрастание, при ρ<0.5 — convergent fixed-point. Наш выбор ρ=0.50 на границе этих режимов, что балансирует «достаточное распространение» и «контролируемый темп».

### Обсолетный раздел (исторический) — Stage 4-bis выбор ρ=0.70

Выбор обоснован эмпирическим соответствием наблюдаемой длительности реальных каскадов критической инфраструктуры. При ρ=0.95 (Этап 4 исходный) модель предсказывает полное распространение шока за ~5 часов, что не соответствует реальным темпам:

- **Europe 2006** (UCTE Final Report, p. 5, 10): ~100 минут до стабилизации в 15 млн домохозяйств; resynchronisation за 38 минут.
- **Texas 2021** (FERC-NERC Staff Report, Exec. Summary): развёртывание за ~24 часа до пиковой деградации; восстановление — дни.
- **India 2012** (MoP Annual Report 2012-13, p. 112): ~15 минут до полного отключения Northern + Eastern + North-Eastern, восстановление за 2-3 часа.
- **Baltimore 2024** (NTSB MIR-25-40): часы до полного прекращения судоходства.

Таким образом, «скорость каскада» варьирует от ~15 минут до нескольких часов в зависимости от инициатора. Нормировка ρ=0.70 соответствует медианному режиму (часы).

### Теоретическая ссылка
Bardoscia M., Battiston S., Caccioli F., Caldarelli G. (2017). **«Pathways towards instability in financial networks»**. *Nature Communications 8, 14416.* Показана монотонная зависимость скорости каскада от ρ(L) (эквивалентная нашему ρ(A)): при ρ близком к 1 — exponentially fast propagation, при ρ<0.5 — convergent fixed-point с ограниченным радиусом влияния.

### Условие Банаха
Для IIM fixed-point solution `q* = (I − A)^(−1) c*` требуется ρ(A) < 1 (строго). ρ_target=0.70 выполняет это с запасом 0.30.

### Альтернативы (для sensitivity)
- ρ_target=0.95 (Этап 4 исходный): worst-case saturation.
- ρ_target=0.50: conservative scenario.
- ρ_target=0.30: «слабокаскадная» матрица; близко к отсутствию cross-sector эффектов.

---

## T_steps — горизонт интегрирования

### Численное значение
T_steps=30, dt=0.1 → физическое время T = 3.0 (interpretable as 3 часа при σ, калиброванном per-hour).

### Обоснование
Инвестиционный due diligence интересуется **early-warning horizon** — первыми часами развития каскада, когда сигнал детектируется до активации emergency response. 3 часа покрывают:

- фазу primary propagation (начальный перенос шока по A),
- проявление first-threshold crossings у non-initiator секторов,
- detection-window до emergency recovery.

3 часа **не** покрывают:

- асимптотический equilibrium (нерелевантно для risk signal),
- full cascade unfolding (часы-сутки, за пределами early-warning),
- восстановление и resilience mechanisms (отдельная задача).

### Референс
UCTE (2007). **Final Report System Disturbance on 4 November 2006**. Timeline: первые 60 минут определили географический масштаб каскада (п. 2 Executive Summary). После этого система уже разделена — качественных изменений уровня загрузки не происходит.

### Альтернативы
- T_steps=50 (Этап 4 исходный): 5 часов, слишком длинный для early-warning, приводит к saturation SDE.
- T_steps=10: 1 час — слишком короткий, не охватывает primary propagation.

---

## Связанные параметры, которые **не** калибровались в 4-bis

| Параметр | Значение | Источник | Статус |
|---|---|---|---|
| σ | [0.1012, 0.1218, 0.0232] | SCADA (Этап 2) | fixed |
| C (capacity) | [0.75, 0.75, 0.75] | θ=0.75 из pre-reform sweep | fixed |
| ρ_rec (recovery rate) | [0.02, 0.02, 0.02]/step | «mild mean-reversion», не калибровался | **потенциальная проблема** — см. `04_bis_recalibration_report.md` |
| x0_base | [0.3, 0.3, 0.3] | «generic operational baseline» | **потенциальная проблема** — см. отчёт |
| α (dynamic degradation) | 3.0 | pre-reform default | fixed |
| β_NEVA | 2.0 | Barucca 2020 conventional | fixed |

Sanity check Этапа 4-bis показал, что ρ_rec=0.02 «mild mean-reversion» оказывается слишком слабой при ρ(A)=0.70 — λ_growth=0.68 даёт экспоненциальный рост даже без σ. Это **отдельный методологический вопрос**, не решаемый перекалибровкой ρ_cap и T_steps.

См. `docs/_checklists/04_bis_recalibration_report.md` для полной диагностики.
