# Верификация: SDE = non-linear DebtRank?

**Дата проверки:** 2026-04-19
**Режим:** read-only диагностика, без правок кода.
**Итог:** **SDE реализует non-linear DebtRank (NEVA-рамка, Bardoscia et al. 2016)** — с двумя
некритичными расхождениями в том, _откуда_ канонические скрипты берут параметры C_j и α
(не в математике самого оператора).

---

## 1. Точка входа интегратора

- **Файл:** `services/risk_engine/sde_integrator.py`
- **Размер:** 14 351 байт, 398 строк
- **Последняя модификация:** 2026-04-15 01:51
- **Публичные классы:** `SDEConfig`, `SDEIntegrator`, `CascadeResult`

Harness, вызывающий интегратор с правильными параметрами:
`services/risk_engine/mc_harness.py` → `scripts/run_stage4_mc.py`.

---

## 2. Drift term (реальная цитата кода)

Из `sde_integrator.py:154–186` (вычисление динамической A) и `:222–223` (drift):

```python
# _compute_dynamic_A(x): применяет φ_j к столбцу j
phi[j] = np.exp(-self.alpha * excess / denom)   # excess = x_j − C_j (если > 0)
# ...
return self.A_static * phi[np.newaxis, :]       # (N,N) * (1,N) → columnwise scaling

# step():
A_current = self._compute_dynamic_A(x)
drift = A_current @ x - cfg.rho * x             # Σ_i A_static[j,i]·φ_i(x_i)·x_i − ρ_j·x_j
```

**Ключевое наблюдение.** Поскольку A_current = A_static · diag(φ), то

$$
\mathrm{drift}_j \;=\; \sum_i A_{ji}^{\mathrm{static}} \cdot \varphi_i(x_i) \cdot x_i \;-\; \rho_j x_j
\;=\; \sum_i A_{ji}^{\mathrm{static}} \cdot V_i(x_i) \;-\; \rho_j x_j
$$

c **valuation function**

$$
V_i(x) \;=\; x \cdot \varphi_i(x) \;=\; x \cdot \exp\!\Bigl(-\alpha \cdot \frac{\max(0,\, x - C_i)}{1 - C_i}\Bigr).
$$

Это **ровно** нелинейная DebtRank-оценка по Bardoscia et al. 2016. Реализация факторизована:
вместо явного вычисления `V_i` формула превращает столбцовое масштабирование `A[:, i]·φ_i` в
`(A·diag(φ))·x` — результат математически идентичен.

---

## 3. Численная проверка нелинейности (ШАГ 4)

Тест (встроенный прогон):
- A = A_empirical_bayesian_v1 (ρ=0.50), σ = SCADA-вектор, C = 0.85 (однородно для чистоты теста), α = 3.
- Вход 1: x = (0.5, 0.5, 0.5) — все ниже capacity.
- Вход 2: x = (0.95, 0.5, 0.5) — энергетика выше capacity.

**Результат:**

| α | V(x=0.5) | V(x=0.95) | V(0.95)/V(0.5) | Интерпретация |
|---|---|---|---|---|
| 0.0 | 0.5000 | 0.9500 | **1.90** | линейный предел — совпадает с DebtRank-1 |
| 3.0 | 0.5000 | 0.1286 | **0.257** | нелинейное saturation — φ(0.95)=0.1353 |

Соотношение V(0.95)/V(0.5) падает с 1.90 до 0.257 при α=3 → saturating non-linearity сработала.
**Заключение:** non-linear DebtRank.

---

## 4. Откуда берутся параметры (в канонической MC-цепочке)

Источник истины — `scripts/run_stage4_mc.py`:

| Параметр | Источник | Значение | OK? |
|---|---|---|---|
| A | `data/calibration/A_empirical_bayesian_v1.json` → `matrix_posterior_mean_spectral_capped` | ρ(A) = 0.500 | ✓ |
| σ | `data/calibration/sigma_empirical_v1.json` (SCADA калибровка, Этап 2) | (0.101, 0.122, 0.023) /hr | ✓ |
| α | жёстко `ALPHA = 3.0` в `run_stage4_mc.py:51` | 3.0 | ✓ (но hardcoded) |
| C | жёстко `C_DEFAULT = [0.75, 0.75, 0.75]` в `run_stage4_mc.py:46` | [0.75, 0.75, 0.75] | **✗** |
| ρ_rec | жёстко `RHO_RECOVERY = [0.30, 0.30, 0.30]` в `run_stage4_mc.py:50` | 0.30 | ✓ |
| dt, T_steps | константы: 0.1, 30 | — | — |

**Расхождение по C_j.** Файл `data/calibration/capacity_thresholds.json` существует и содержит
калиброванные значения:
- C_energy = 0.883 (HAI 21.03 P2+P4, q95)
- C_water = 0.646 (HAI 21.03 P3, q95)
- C_transport = 0.928 (DfT monthly HGV q95)

Но `run_stage4_mc.py` **не загружает этот файл** — он использует унифицированное C=0.75
(оставшееся с θ-recalibration эксперимента Этапа 3). Grep по репо: чтение
`capacity_thresholds.json` встречается в `scripts/sweep_alpha.py` и
`scripts/calibrate_capacity.py`, но не в каноническом MC-раннере Этапа 4.

**Это не влияет на заключение о том, что SDE = non-linear DebtRank** — математика оператора
корректна. Это вопрос конфигурационной чистоты: Этап 4 использует «круглое» C=0.75,
а не SCADA-калибровку Этапа 2.

---

## 5. Skorokhod reflection

`sde_integrator.py:234`:
```python
x_new = np.clip(x_raw, 0.0, 1.0)
```

Проекция на [0,1] после каждого EM-шага — это и есть отражение Скорохода
для компактного ящика. Учёт clip-диагностики (upper/lower) присутствует
(строки 241–243).

---

## 6. Итоговая таблица соответствия

| Компонент | Ожидаемое | Фактическое | Статус |
|---|---|---|---|
| Drift term | `Σ A_ji · V_i(x_i) − ρ_j · x_j` | `A(t)@x − ρ·x`, где `A(t)=A_static·diag(φ)` → эквивалентно | **✓** |
| Valuation V_j | `x · exp(−α · max(0, x−C) / (1−C))` | `x · φ_j(x)` с тем же φ | **✓** |
| α параметр | `3.0` из конфига/скрипта | `ALPHA = 3.0` hardcoded в `run_stage4_mc.py:51` | **✓** (hardcoded, но корректно) |
| C_j | из `capacity_thresholds.json` (0.883/0.646/0.928) | `C_DEFAULT = [0.75, 0.75, 0.75]` hardcoded | **✗** (конфиг-расхождение, не математическое) |
| σ_j | SCADA-калибровка Этапа 2 | `sigma_empirical_v1.json` → `load_sigma()` | **✓** |
| Матрица A | `A_empirical_bayesian_v1.json` | тот же путь, ключ `matrix_posterior_mean_spectral_capped` | **✓** |
| ρ(A) | 0.50 | 0.49999999999999994 | **✓** |
| ρ_rec | 0.30 | 0.30 hardcoded | **✓** |
| Skorokhod reflection | применяется | `np.clip(x_raw, 0.0, 1.0)` на каждом шаге | **✓** |

---

## 7. Заключение

**SDE-интегратор реализует non-linear DebtRank valuation из NEVA-рамки.**
Математика drift term, valuation function V_j, α-saturation и граничное отражение —
всё соответствует Bardoscia et al. 2016.

**Переименование в NLDR безопасно** с точки зрения семантики оператора.

**Единственное предупреждение:** перед переименованием стоит решить — возвращать ли
канонический MC-скрипт Этапа 4 к калиброванным capacity thresholds
(0.883/0.646/0.928 из `capacity_thresholds.json`) или задокументировать отдельно,
что для MC Этапа 4 намеренно взято унифицированное C=0.75 из θ-recalibration.
Это отдельный вопрос (конфигурация, не математика) — решать вместе, **не** автоматической правкой.
