# Математическая модель DIPLOMA v2.0

> Этот файл описывает **целевую** математическую модель (СДУ + оптимизация).  
> Реализация: `services/risk_engine/sde_integrator.py`, `scripts/calibrate_*.py`.

---

## 1. СДУ-модель состояния инфраструктуры

### 1.1. Непрерывная формулировка

Состояние сектора $j \in \{1, \ldots, N\}$ (здесь $N=3$: энергетика, водоснабжение, транспорт) описывается относительной нагрузкой $x_j(t) \in [0, 1]$.

Динамика:

$$dx_j(t) = \underbrace{\left(\sum_{i=1}^N a_{ij}\,x_i(t) - \rho_j\,x_j(t)\right)}_{\text{дрейф}}\,dt + \underbrace{\sigma_j\,x_j(t)\,dW_j(t)}_{\text{диффузия}} \tag{1}$$

**Параметры:**

| Символ | Размерность | Единицы | Диапазон | Метод калибровки |
|--------|-------------|---------|----------|-----------------|
| $x_j(t)$ | скаляр | б/р, $[0,1]$ | $[0,1]$ | состояние модели |
| $a_{ij}$ | матрица $N \times N$ | б/р | $[0, 0.5]$ | Леонтьев, WIOD 2016 |
| $\rho_j$ | скаляр | $\text{ч}^{-1}$ | $[0, \infty)$ | экспертно / TODO |
| $\sigma_j$ | скаляр | $\text{ч}^{-1/2}$ | $[0, \infty)$ | HAI + Kelmarsh SCADA |
| $W_j(t)$ | стандартный ВП | — | — | i.i.d. |
| $C_j$ | скаляр | б/р, $[0,1]$ | $(0,1]$ | quantile(0.95) / HAI, DfT |

**Граничные условия:** отражающие границы на $[0, 1]$ — реализованы через clip.

### 1.2. Интерпретация параметров

- $x_j = 0$: сектор $j$ полностью неработоспособен
- $x_j = 1$: сектор $j$ работает на полной мощности / номинальной нагрузке
- $a_{ij} > 0$: сектор $j$ зависит от сектора $i$ (рост $x_i$ повышает нагрузку на $j$)
- $\rho_j > 0$: естественное восстановление сектора $j$
- $\sigma_j$: волатильность (из SCADA / HAI данных)
- $C_j$: порог перегрузки (95-й перцентиль нормального режима)

---

## 2. Схема Эйлера–Маруямы

Дискретизация уравнения (1) с шагом $\Delta t$:

$$x_j^{k+1} = \mathrm{clip}_{[0,1]}\!\left(x_j^k + \left(\sum_i a_{ij}\,x_i^k - \rho_j\,x_j^k\right)\Delta t + \sigma_j\,x_j^k\,\sqrt{\Delta t}\,Z_j^k\right) \tag{2}$$

где $Z_j^k \sim \mathcal{N}(0,1)$ — i.i.d., генерируются из PRNG с детерминированным seed.

**Шок** (внешнее воздействие в момент $t=0$):

$$x^1 = \mathrm{clip}_{[0,1]}\!\left(\text{правая часть (2)}\big|_{k=0} + u\right) \tag{3}$$

где $u \in \mathbb{R}^N$ — вектор начального шока (только на шаге $k=0$).

**Реализация:** `SDEIntegrator.step()`, `SDEIntegrator.run()` — файл `services/risk_engine/sde_integrator.py`.

**Совместимость:** при $\sigma=0$, $\rho=0$, $\Delta t=1$ схема (2) совпадает со старым дискретным оператором $x_{t+1} = \mathrm{clip}(x_t + A \cdot x_t)$ (тест `test_compatible_with_old_operator`).

---

## 3. Пороговый каскадный механизм

### 3.1. Классический каскад (I_cl)

Сектор $j$ считается **отказавшим** (перегруженным), если:

$$x_j(t) \geq C_j \tag{4}$$

Индикатор классического каскада (за горизонт $T$):

$$I_\text{cl}(s, r) = \mathbf{1}\!\left[\exists\, j \neq j_0,\; \exists\, t \leq T:\; x_j(t) \geq C_j\right] \tag{5}$$

### 3.2. Квантитативный каскад (I_q)

$$I_q(s, r) = \mathbf{1}\!\left[\exists\, j \neq j_0:\; \max_{t \leq T}\!\left(x_j(t) - x_j(0)\right) \geq \delta\right] \tag{6}$$

где $\delta = 0.10$ (по умолчанию) — порог количественного роста нагрузки.

### 3.3. Эмпирические вероятности каскада (MC)

По $R$ прогонам:

$$K_\text{cl}(s) = \frac{1}{R}\sum_{r=1}^R I_\text{cl}(s, r), \qquad K_q(s) = \frac{1}{R}\sum_{r=1}^R I_q(s, r) \tag{7}$$

**Гипотеза H₁:** $K_q(s) > K_\text{cl}(s)$ — квантитативный детектор чувствительнее классического.

**Реализация:** `SDEIntegrator.detect_cascade()`.

---

## 4. Задача стохастической оптимизации

Задача: найти изменение матрицы зависимостей $\Delta A$, минимизирующее ожидаемые потери:

$$\min_{\Delta A} \; \mathbb{E}\!\left[\sum_{j=1}^N w_j\bigl(1 - S_j(T)\bigr)\right] \tag{8}$$

где $S_j(t) = \mathbf{1}[x_j(t) < C_j]$ — бинарный статус «работоспособен».

**Ограничения:**

$$\sum_{i,j} c_{ij}\,|\Delta A_{ij}| \leq B, \quad A + \Delta A \geq 0, \quad \rho(A + \Delta A) < 1 \tag{9}$$

($B$ — бюджет вмешательства, $c_{ij}$ — стоимость укрепления связи, $\rho$ — спектральный радиус).

**Метод:** Sample Average Approximation (SAA) + проекция на допустимое множество.

**Реализация:** `services/optimizer/` — **TODO**.

---

## 5. Калибровка параметров

| Параметр | Метод | Источник данных | Результат | Файл |
|----------|-------|-----------------|-----------|------|
| $\sigma_\text{energy}$ (ICS) | $\text{std}(\Delta\log x) / \sqrt{\Delta t}$ | HAI 21.03, P4_ST_PO/P4_HT_PO | 6.54 ч⁻¹/² | `data/calibration/sigma_calibrated.json` |
| $\sigma_\text{energy}$ (ветер) | $\text{std}(\Delta\log P) / \sqrt{\Delta t}$ | Kelmarsh Farm SCADA, 36 файлов | 0.790 ч⁻¹/² | `data/calibration/sigma_calibrated.json` |
| $\sigma_\text{water}$ | $\text{std}(\Delta\log x) / \sqrt{\Delta t}$ | HAI 21.03, P3_LIT01/PIT01/FIT01 | 18.08 ч⁻¹/² | `data/calibration/sigma_calibrated.json` |
| $C_\text{energy}$ | $q_{0.95}(x/x_\text{nom})$ | HAI 21.03, нормальный режим | 0.883 | `data/calibration/capacity_thresholds.json` |
| $C_\text{water}$ | $q_{0.95}(x/x_\text{nom})$ | HAI 21.03, нормальный режим | 0.646 | `data/calibration/capacity_thresholds.json` |
| $C_\text{transport}$ | $q_{0.95}(\text{ежемесячные HGV})$ | DfT Road Safety 2020–2024 | 0.928 | `data/calibration/capacity_thresholds.json` |
| $a_{ij}$ | Леонтьев: $a_{ij} = X_{ij}/q_j$ | WIOD 2016 NIOT, RUS+DEU+USA, 2014 | 3×3 матрица | `data/calibration/A_leontief.json` |
| $\rho_j$ | — | Не калиброван | $\rho = 0$ | hardcode (TODO) |

**Примечание по $\sigma$:** калиброванные значения — в единицах $\text{ч}^{-1/2}$. При использовании в СДУ с безразмерным $\Delta t$ необходим перевод: $\sigma_\text{model} = \sigma_\text{calibrated} \cdot \sqrt{\Delta t_\text{hours}}$.

---

## 6. Базовые методы (Baselines)

### 6.1. DebtRank (Battiston et al., 2012)

Итеративное распространение «дистресса»:

$$h_i(t+1) = \min\!\left(1,\; h_i(t) + \sum_{j:\, h_j(t)<1} a_{ji}\,h_j(t)\right) \tag{10}$$

$$R = \sum_i h_i(\infty) \cdot v_i \tag{11}$$

где $v_i$ — экономический вес сектора $i$, $h_i(0) = \mathbf{1}[i = j_0]$.

**Реализация:** `services/risk_engine/baselines.py` — **TODO**.

### 6.2. Independent Cascade Model (ICM)

Шок инициатора $j_0$: $j_0$ становится «активным» с вероятностью 1.  
Каждый сосед $i$ активируется с вероятностью $p_{ij_0} = f(a_{ij_0})$ независимо.  
Итоговый ущерб: доля активированных узлов.

$$K_\text{ICM}(j_0) = \mathbb{E}\!\left[\frac{|\text{activated}|}{N}\right] \tag{12}$$

**Реализация:** `services/risk_engine/baselines.py` — **TODO**.

---

## 7. Связь с предыдущей моделью

При $\sigma_j = 0$, $\rho_j = 0$, $\Delta t = 1$, $T=1$, $u = $ шок:

$$x^1 = \mathrm{clip}_{[0,1]}(x^0 + A \cdot x^0 + u) \tag{13}$$

что совпадает со старым одношаговым оператором. Тест: `tests/test_sde_integrator.py::test_compatible_with_old_operator`.

---

## 8. Нотация и сокращения

| Символ | Значение |
|--------|---------|
| $N$ | Число секторов (= 3: energy, water, transport) |
| $j_0$ | Инициатор каскада |
| $T$ | Горизонт симуляции (шагов) |
| $R$ | Число MC-прогонов |
| $s$ | Сценарий |
| $r$ | Номер прогона |
| $B$ | Бюджет оптимизации |
| $\rho(\cdot)$ | Спектральный радиус матрицы |
| i.i.d. | Независимые одинаково распределённые |
| СДУ | Стохастическое дифференциальное уравнение |
| ВП | Винеровский процесс (стандартное броуновское движение) |
| SAA | Sample Average Approximation |
