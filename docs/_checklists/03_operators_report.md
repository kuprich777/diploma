# Этап 3 — NEVA + IIM операторы: итоговый отчёт

**Дата:** 2026-04-19
**Ветка:** `methodology-overhaul`
**Статус:** ✅ Этап 3 завершён, готов к Этапу 4

## Сводка артефактов

| Файл | Назначение |
|---|---|
| `services/risk_engine/cascade_operators.py` | 3 оператора: Classical, IIM, NEVA |
| `tests/test_cascade_operators.py` | 10 unit-тестов, все проходят (+ 18 существующих SDE = 28 total) |
| `scripts/run_operator_comparison.py` | Сравнительный эксперимент на 5 синтетических шоках |
| `results/stage3_operator_comparison.json` | Табличные результаты эксперимента |

## Реализованные операторы

### 1. ClassicalOperator
```
x(t+1) = clip_{[0,1]}( x(t) + A · x(t) )
```
Base-case чистого aggregation; совпадает с текущим риск-энджином при σ=0, ρ=0, dt=1.

### 2. IIMOperator — Haimes-Santos 2005
```
q(t+1) = clip_{[0,1]}( A* · q(t) + c*(t) )
fixed_point q* = (I - A*)^-1 · c*   (если ρ(A*) < 1)
```
Exogenous perturbation c*(t) задаётся callable. Замкнутая форма для fixed-point реализована.
Ссылка: Haimes Y.Y., Santos J.R. (2005). Systems Engineering 8(4), 273-291.

### 3. NevaOperator — Barucca et al. 2020 (адаптация)
```
x_i(t+1) = clip( x_i(0) + Σ_j A[i][j] · stress_j(h_j(t)) )
stress_j(h) = 1 - h^β        # h ∈ [0,1]; h = 1-x
```
β=1 → линейный DebtRank (Battiston 2012). β>1 → non-linear NEVA с концентрацией потерь у дефолта.

Ссылка: Barucca P., Bardoscia M., Caccioli F., D'Errico M., Visentin G., Caldarelli G., Battiston S. (2020). Network valuation in financial systems. Mathematical Finance 30(4), 1181-1204.

## Тесты

```
tests/test_cascade_operators.py:
  TestClassicalOperator        2 passed
  TestIIMOperator              3 passed
  TestNevaOperator             4 passed
  TestOperatorComparison       1 passed
------------------------------------------
Total: 10 passed + 18 existing SDE = 28 passed
```

## Сравнительный эксперимент

Matrix: `A_empirical_bayesian_v1` (spectral capped, ρ=0.95).
Capacity C=[0.75, 0.75, 0.75], δ=0.10, n_steps=50.

5 сценариев (mild/severe shocks в energy, transport, water):

```
Scenario                  Op            I_cl   I_q    maxΔ   water transport  energy conv@
------------------------------------------------------------------------------------------
S_energy_mild             classical        1     1   0.900   1.000     1.000   1.000     4
S_energy_mild             iim              0     1   0.214   0.014     0.013   0.013    50
S_energy_mild             neva_beta1       1     1   0.900   1.000     0.971   1.000     8
S_energy_mild             neva_beta2       1     1   0.900   1.000     0.971   1.000     5
...
S_transport_severe        iim              0     1   0.388   0.026     0.023   0.024    50
...
```

## Ключевые наблюдения

1. **Classical** и **NEVA** предсказывают полный каскад (saturation к [1,1,1]) во всех сценариях. Причина: ρ(A) = 0.95 близко к единице, и без recovery term (ρ_j) чистая propagation divergent.

2. **IIM** консервативный — при импульсном возмущении c(0)=shock, c(t>0)=0 решение затухает со скоростью ρ(A)^t ≈ 0.95^t. I_cl=0 во всех сценариях (q(t) не достигает C=0.75).

3. **NEVA β=2 vs β=1**: почти одинаковый результат в данных сценариях — матрица A настолько активная, что stress функция на любом уровне h<1 быстро выталкивает в сатурацию. Различия заметны при малых shocks и слабо-связанных матрицах.

4. **I_q = 1 везде** — quantitative (Δ≥δ=0.10) срабатывает даже для IIM, подтверждая что quantitative более чувствителен классического порога.

## Интерпретация для диплома

- **IIM = нижняя граница**: чистый линейный оператор с импульсным шоком → conservative estimate каскадного риска.
- **Classical/NEVA = верхняя граница**: aggressive propagation без damping.
- **SDE (существующая модель)** = реалистичная середина с stochastic noise + recovery rate + dynamic A.

Полное Monte Carlo сравнение SDE vs IIM vs NEVA на реалистичных шоках будет в Этапе 4.

## Ограничения

1. **NEVA β как гиперпараметр**: в Barucca 2020 β связан с специфической природой финансового risk valuation. Для инфраструктурной адаптации оптимальный β не известен и должен подбираться через калибровку LOO (Этап 4).
2. **IIM c(t) функция**: в данном сравнении используется импульс. Для реалистичного моделирования это должна быть time-dependent функция (например, spike в момент атаки, затухание согласно restoration curve).
3. **Отсутствие diffusion/stochastic в операторах**: текущие операторы детерминированные. В Этапе 4 IIM и NEVA будут обёрнуты в Monte Carlo с эквивалентной σ-шум компонентой для fair comparison с SDE.

## Связь с pre-reform кодом

Существующий `services/risk_engine/sde_integrator.py` (Euler-Maruyama с reflecting [0,1]) остаётся primary method. Новые операторы `cascade_operators.py` — **не replacement**, а альтернативные baseline для cross-method valid comparison.

## ⏸ Pause перед Этапом 4

Этап 4 — LOO cross-validation + полный Monte Carlo на 15 сценариях. План:
1. Реализация LOO: обучить A на 3 из 4 событий, валидировать на 4-м.
2. Интеграция 3 операторов (SDE, IIM, NEVA) в единый Monte Carlo harness.
3. N=1000 на каждый из 15 сценариев × 3 операторов.
4. Метрики: K_cl, K_q, K_iim, K_neva, mean_delta, p95_delta, coverage.
5. Таблица 15×4 операторов + bootstrap CI.

Готов к запуску Этапа 4 по команде.
