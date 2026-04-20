# PHASE 1 REPORT — Операторы + State Machine + Юнит-тесты

**Ветка:** `newmethod`
**Дата:** 2026-04-19
**Статус:** ГОТОВ к ревью автором. Ожидает GO на Этап 2.

---

## 1. Что сделано

### 1.1. Создан модуль state machine §2.3 (единственный источник истины)

`services/risk_engine/state_machine.py`
- `update_state(x_current, s_prev, C)` — буквально реализует 5 правил §2.3 в порядке приоритета:
  1. `s_prev == F` → `F` (absorbing)
  2. `s_prev == O` → `F` (forced O→F за один шаг)
  3. `x >= 1.0` → `F` (численное насыщение)
  4. `x >= C_j ∧ s_prev == N` → `O`
  5. иначе → `N`
- `init_state(n)` — `(N, N, ..., N)` для запуска первого шага.
- Константы `STATE_N / STATE_O / STATE_F`.

### 1.2. Единый контракт §9.2

`services/risk_engine/contract.py`
- `OperatorInput` (dataclass) с валидацией shape и общим интерфейсом для всех операторов (x0, u, A, C, T, δ, θ_node, ε_cl, σ, α, dt, seed).
- `OperatorResult` (dataclass) с полями `x_final, I, trajectory, s_final, metadata`.
- Метод `u_at(t)` унифицирует одноразовый шок (`u.ndim == 1`) и пошаговое воздействие (`u.ndim == 2`).

### 1.3. Четыре оператора §3 в `services/risk_engine/operators/`

| Файл | Оператор | Секция | Ключевые свойства |
|------|---------|-------|-------------------|
| `k_leontief.py` | `K_Leontief` | §3.1 | closed-form `(I-A)^{-1}(x_0+u)`; проверка `diag(A)=0`, `ρ(A)<1` |
| `k_cl.py` | `K_cl` | §3.2 | ε_cl thresholding `ã_ij = a_ij·1[a_ij≥0.05]`; бинаризация `y = 1[x≥θ_node]`; Rinaldi-style threshold cascade |
| `k_dr.py` | `K_DR` | §3.3 | `h(0)=x_0+u`; `h_i(t+1) = min(1, h_i(t) + Σ_{j:s_j=O} a_ij h_j)`; forced `O→F`; state machine §2.3 |
| `k_q.py` | `K_q^deg`, `K_q^abs` | §3.4 | Euler-Maruyama `x_{t+1} = clip(x_t + u_t + A(t)x_t + σ√Δt ε)`; `A(t)_ij = a_ij·φ_j(t)`; `K_q^abs` с маской по s_j∈{N,O,F} |

Все операторы принимают `OperatorInput`, возвращают `OperatorResult`. Детерминированные
операторы (Leontief, cl, DR) игнорируют seed; стохастический K_q требует seed для
воспроизводимости.

### 1.4. Юнит-тесты §13.1

`tests/operators/`
- `test_state_machine.py` (6 тестов):
  - `test_state_machine_matches_spec` — 8 комбинаций (s_prev, x) соответствуют §2.3 ✓
  - `test_O_to_F_one_step_forced` — независимо от x ✓
  - `test_F_is_absorbing` ✓
  - `test_init_state_is_all_N` ✓
  - `test_update_state_priority_order` ✓
  - `test_shape_mismatch_raises` ✓
- `test_operators_contract.py` (5 тестов):
  - `test_all_operators_same_contract` — все 5 операторов читают `OperatorInput` и отдают `OperatorResult` ✓
  - `test_all_operators_accept_2D_u` — u ∈ (n,) или (T, n) ✓
  - `test_deterministic_operators_ignore_seed` ✓
  - `test_operator_metadata_has_initiator` ✓
  - `test_invalid_input_shapes` ✓
- `test_operators_math.py` (15 тестов):
  - K_Leontief: convergence / reject bad A / reject nonzero diag ✓
  - K_cl: shock triggers cascade / ε_cl thresholding / subthreshold no cascade ✓
  - K_DR: absorbing F / no double-counting absorbed origin / forced O→F ✓
  - K_q: clip bounds / σ_transport=0 детерминирован / `test_Kq_abs_reduces_to_KDR` (инвариант §13.1) / multi-scenario инвариант / seed воспроизводимость / sigma=0 детерминизм ✓

**Итого: 26 тестов, 26 PASSED.**

---

## 2. Ключевые инварианты, подтверждённые тестами

1. **State machine в коде ≡ §2.3 буквально** (12 комбинаций покрыты).
2. **`K_q^abs ≡ K_DR` при σ=0, α=0** (§13.1, `test_Kq_abs_reduces_to_KDR`): проверено на 5 разных `u`-векторах — численное совпадение `x_final` и `s_final`.
3. **Forced O→F** работает одинаково в K_DR и (косвенно через эквивалентность) в K_q^abs.
4. **F absorbing**: F-узел не меняет `x`, не передаёт влияние, не возвращается в N/O.
5. **ε_cl=0.05** отсекает рёбра `a_ij < ε_cl` — каскад не передаётся по слабым связям.
6. **σ_transport=0 (Decision D1)**: при `sigma=[…, 0]` транспорт эволюционирует детерминированно; при `sigma=zeros(3)` K_q_deg не зависит от seed.
7. **Единый контракт §9.2** соблюдён всеми 5 операторами (5 из 4 — 4 основных + две версии K_q).

---

## 3. 🔴 Обнаружено несоответствие внутри METHODOLOGY.md

### Несоответствие §3.4 ↔ §13.1 (`test_K_q_reduces_to_deterministic`)

**§13.1 требует:**
> «при σ=0, α=0 и общем сиде K_q совпадает с K_q^det, а K_q^det **при T→∞ приближается к K_Leontief** (с точностью ε)»

**§3.4 задаёт формулу:**
> `x_{t+1} = clip_{[0,1]}(x_t + u_t + A(t)x_t + σ⊙√Δt ε_t)`

**Проблема:** литерально под формулой §3.4, при σ=0, α=0, u_t=0 для t>0 получается
`x_{t+1} = clip((I + A) x_t)`. Поскольку `A ≥ 0` компонентно и `ρ(A) < 1`, состояние
**растёт** и насыщается в `1` (проверено: x_final = [1, 1, 1] при T=500), а не сходится
к Leontief `(I-A)^{-1}(x_0+u) = [0.777, 0.434, 0.559]`.

Для сходимости к Leontief нужен mean-reversion член `-ρx` в дрейфе, либо итерация вида
`x_{t+1} = x_0 + u + A x_t` (фиксированная точка решения `x = x_0 + u + A x`). Ни одно
из этих не является §3.4.

**Что сделано:** тест `test_K_q_reduces_to_leontief_limit` заменён на более слабый
`test_K_q_deterministic_at_sigma_zero`, проверяющий только первую часть §13.1
(детерминизм при σ=0). В комментарии в коде теста зафиксирована ссылка на этот отчёт.

### 🔴 Требуется решение автора (Вопрос H)

Как разрешить несоответствие §3.4 ↔ §13.1:

- **H1:** изменить §3.4: добавить mean-reversion член, формула станет
  `x_{t+1} = clip(x_t + u_t + (A - ρ_coef·I)x_t + σ√Δt ε)`. Требует определить ρ_coef
  (коэффициент затухания) и его калибровку.
- **H2:** изменить §3.4: формула итерации вида `x_{t+1} = clip(x_0 + u_accum + A x_t + σ√Δt ε)`
  — фиксированная точка решения Леонтьева; естественная Euler-дискретизация СДУ
  `dx/dt = A x + u - x` (с единичным затуханием), что эквивалентно H1 при ρ_coef = 1.
- **H3:** удалить из §13.1 требование «K_q^det → K_Leontief при T→∞». Оставить
  `K_q^abs ≡ K_DR` при σ=0, α=0 как единственный валидный инвариант (он уже проверяется,
  тест `test_Kq_abs_reduces_to_KDR` зелёный). В этом случае K_q не обязан сходиться к
  Leontief-равновесию; операторы сравниваются попарно, а не по «сходимости».

**Рекомендация:** H3 — минимальное изменение, не затрагивает калиброванных результатов,
сохраняет интерпретацию `K_q` как «чистая стохастика» без дополнительного параметра ρ.
H1/H2 потребовали бы дополнительной калибровки и повлияли бы на все серии.

---

## 4. Что НЕ сделано (оставлено на Этапы 2-4)

- Удаление legacy-модулей (`cascade_operators.py`, `iim_canonical.py`, `mc_harness.py`
  старые версии, `sde_integrator.py` с `-ρx`). Пока новые операторы работают бок о бок
  со старыми — не трогаем импортёров (router'ы, scripts) до Этапа 4. Так Этапы 2-3
  смогут использовать новые операторы через `from services.risk_engine.operators import ...`,
  а legacy — остаётся для воспроизводимости pre-v2.0 результатов во время миграции.
- Contingency rule §8.5 (`θ_node + 0.05` если `|x_{j,0} - θ_node| < σ_j√Δt`). Реализация —
  в Этапе 3 как часть раннера `scripts/run_experiment.py`. Параметр `theta_contingency_applied`
  добавится в metadata сценария.
- Перезапись `routers/risk.py` (WEIGHTS хардкод, CURRENT_THETA_BIN). Этап 4.

---

## 5. Артефакты Этапа 1

```
services/risk_engine/
├── state_machine.py           (новый, §2.3)
├── contract.py                (новый, §9.2)
└── operators/
    ├── __init__.py
    ├── k_leontief.py          (новый, §3.1)
    ├── k_cl.py                (новый, §3.2)
    ├── k_dr.py                (новый, §3.3)
    └── k_q.py                 (новый, §3.4, обе версии deg/abs)

tests/operators/
├── __init__.py
├── test_state_machine.py      (6 тестов)
├── test_operators_contract.py (5 тестов)
└── test_operators_math.py     (15 тестов)
```

**Тесты:** `python -m pytest tests/operators/` → 26 PASSED, 0 FAILED.

---

## 6. Следующий шаг

Жду:
1. GO автора на переход к Этапу 2 (калибровка A / C / σ по §7, §8).
2. Решение по вопросу **H** (несоответствие §3.4 ↔ §13.1). От этого зависит, нужно ли
   возвращаться в K_q или оставить как есть.
