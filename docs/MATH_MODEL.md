# Математическая модель DIPLOMA v2.1 (newmain)

> Источник истины по методологии — [`docs/methodology/METHODOLOGY_FINAL.md`](methodology/METHODOLOGY_FINAL.md).
> В случае расхождения приоритет у финального документа (формулы 5, 9, 23, 16–18).
>
> Этот файл описывает **реально реализованную** математическую модель на ветке `newmain`.
> Охватывает: СДУ (Эйлер–Маруяма), три каскадных оператора (Classical, IIM iterative, NEVA/NLDR β=2),
> канонический IIM (Haimes 2005 eq.(11) через A*-преобразование), унифицированный MC harness.
> Реализация: `services/risk_engine/{sde_integrator.py, cascade_operators.py, iim_canonical.py, mc_harness.py}`,
> `scripts/calibrate_*.py`, `scripts/matrix_calibration/`, `scripts/validation/`.

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

### 1.3. Динамическая матрица зависимостей A(t)

В базовой СДУ-модели (1) матрица $A$ постоянна. Однако при каскадном отказе
узла-поставщика $j$ ($x_j \geq C_j$) его способность передавать нагрузку
снижается: происходит разрыв цепочек поставок. Для учёта этого вводится
**множитель деградации**:

$$\varphi_j(t) = \exp\!\left(-\alpha \cdot \frac{\max(0,\, x_j(t) - C_j)}{1 - C_j}\right) \in (0,\, 1] \tag{1a}$$

**Динамическая матрица** (умножение по столбцам — поставщик $j$):

$$A(t)_{ij} = A^\text{static}_{ij} \cdot \varphi_j(t) \tag{1b}$$

Если поставщик $j$ перегружен, **все** зависящие от него сектора $i$ получают
ослабленный вклад — это моделирует разрыв цепочки поставок.

**Параметр** $\alpha \geq 0$ управляет скоростью затухания:

| $\alpha$ | $\varphi_j$ при $x_j = 1$ | Интерпретация |
|----------|--------------------------|---------------|
| 0 | 1.0 | Статическая матрица (без деградации) |
| 1 | $e^{-1} \approx 0.368$ | Умеренное затухание |
| 5 | $e^{-5} \approx 0.007$ | Сильный разрыв цепочки |
| 10 | $e^{-10} \approx 0.000045$ | Практически полный разрыв |

**Реализация:** `SDEIntegrator._compute_dynamic_A()` — `services/risk_engine/sde_integrator.py`

**При $\alpha = 0$:** $\varphi_j = 1$ для всех $j$ → $A(t) = A^\text{static}$, без вычислений (fast path).

### 1.4. Эмпирические результаты sweep по $\alpha$ (Глава 3)

Скрипт `scripts/sweep_alpha.py` запускает $N=1000$ MC-прогонов для каждого $\alpha \in \{0,1,2,3,5,8,10,15,20\}$ в **маржинальном режиме** ($T=7$ шагов, шоки выбраны так, что $K_\text{cl}(\alpha=0)\approx 0.57$):

| Сценарий | Шок | $K_\text{cl}(\alpha{=}0)$ | $K_\text{cl}(\alpha{=}15)$ | $\Delta K_\text{cl}$ | mean\_$\Delta x$: $\alpha$=0→15 |
|----------|-----|:---:|:---:|:---:|:---:|
| S3: transport, $u_T=+0.25$ | инициатор — транспорт | 0.594 | 0.604 | +0.010 | 0.233→0.235 |
| S4: water, $u_W=+0.20$ | инициатор — водоснабжение | 0.592 | 0.528 | **−0.064** | 0.406→0.357 |

**Выводы:**

- **S4 (инициатор — водоснабжение):** $\alpha > 0$ достоверно *затухает* каскад. $K_\text{cl}$ снижается на 6.4 п.п. ($\approx 4$ стандартных ошибки), mean\_$\Delta x$ снижается монотонно (−12%). Механизм: при перегрузке водоснабжения ($x_\text{water} > C_\text{water}$) коэффициент $\varphi_\text{water} < 1$ ослабляет передачу нагрузки на энергетику ($a_{01}=0.350$) и транспорт ($a_{21}=0.332$).

- **S3 (инициатор — транспорт):** $\alpha > 0$ не оказывает статистически значимого эффекта на $K_\text{cl}$ или $K_q$ (флуктуации в пределах $\pm 1.5$ SE). Причина: шок $u_T=0.25$ не выводит транспортный узел выше порога ($x_T^\text{post-shock}=0.583 \ll C_T=0.928$), поэтому $\varphi_T\equiv 1$ и деградация не активируется. Каскад в энергетику ($x_E$) определяется стохастикой, и обратная связь через $\varphi_E$ мала из-за малости избытка.

- **Общий вывод:** деградационный механизм ($\alpha > 0$) работает как *демпфер* — снижает интенсивность каскадов, когда инициатор или промежуточный узел явно превышает порог $C_j$. При шоках, не приводящих к превышению порога, $\alpha$ не влияет (fast path $\varphi_j = 1$).

**Артефакты:** `results/alpha_sweep.json`, `results/alpha_sweep.csv`, `results/figures/alpha_sweep_combined.png`.

---

## 2. Схема Эйлера–Маруямы

### 2.0. Основной оператор (METHODOLOGY_FINAL.md §3.1, формула 5)

Финальная редакция методологии фиксирует основной оператор в компактной
безразмерной форме с аддитивным сценарным воздействием $u_t$ и аддитивной
стохастикой $\boldsymbol\sigma \odot \sqrt{\Delta t}\,\boldsymbol\varepsilon_t$:

$$\boxed{\;x_{t+1} \;=\; \mathrm{clip}_{[0,1]}\!\bigl(\,x_t + u_t + A\,x_t + \boldsymbol\sigma \odot \sqrt{\Delta t}\,\boldsymbol\varepsilon_t\,\bigr),
\qquad \boldsymbol\varepsilon_t \sim \mathcal N(0, I_n)\;} \tag{5}$$

Проекция $\mathrm{clip}_{[0,1]}$ не является эвристикой, а реализует проекцию Скорохода
на допустимую область $[0, 1]^n$ (reflected SDE). Согласно Гобе (2001), такая
проекция сохраняет слабую сходимость первого порядка $O(\Delta t)$ схемы
Эйлера–Маруямы.

Форма (2) ниже соответствует более ранней редакции с мультипликативной
диффузией $\sigma_j x_j dW_j$ и линейным членом восстановления $-\rho_j x_j$;
эквивалентность (2) и (5) при $\rho_j = 0$, log-normal $\sigma$ и абстрагированной
амплитуде шока — эмпирическая, фиксируется тестом
`test_compatible_with_old_operator`.

### 2.1. Дискретизация (реализация)

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

## 4a. Extended operator with recovery (METHODOLOGY_FINAL.md §10.2)

Расширенный оператор добавляет релаксационный член, моделирующий восстановление
секторов к стационарному baseline $x_0^{\text{baseline}}$:

$$x_{t+1} = \mathrm{clip}_{[0,1]}\!\Bigl(x_t + u_t + A\,x_t - \boldsymbol\kappa \odot (x_t - x_0^{\text{baseline}}) + \boldsymbol\sigma \odot \sqrt{\Delta t}\,\boldsymbol\varepsilon_t\Bigr) \tag{23}$$

где $\boldsymbol\kappa = (\kappa_e, \kappa_w, \kappa_\tau) \in [0, 1]^3$ — вектор
коэффициентов восстановления («доля деградации, устраняемая за один шаг $\Delta t$»).

**Обратная совместимость.** При $\boldsymbol\kappa = 0$ формула (23) в точности совпадает
с основным оператором (5); все результаты основной серии сохраняются как частный случай.

**Условие устойчивости.** $\rho(A - \mathrm{diag}(\boldsymbol\kappa)) < 1$. Для текущей
калибровки $\rho(A_{\text{wiod\_v3}}) = 0{,}46$ условие выполняется для любого
$\boldsymbol\kappa \in [0, 1]^3$.

**Интегральная метрика устойчивости Bruneau (формула 24):**

$$\mathcal{R}_i(s) = 1 - \frac{1}{T}\sum_{t=0}^{T} (x_{i,t} - x_{i,0}^{\text{baseline}})^{+}, \qquad \mathcal{R}_i \in [0, 1] \tag{24}$$

**Время возвращения в окрестность стационара (формула 25):**

$$\tau_i^{\text{rec}} = \min\{t > t_{\text{end}}(u) : x_{i,t} \leq x_{i,0}^{\text{baseline}} + \varepsilon_{\text{rec}}\}, \qquad \varepsilon_{\text{rec}} = 0{,}02 \tag{25}$$

**Реализация:** `services/risk_engine/operators/recovery.py` — **TODO** (Серия 5).
Sensitivity-анализ: $\kappa \in \{0;\, 0{,}1;\, 0{,}2;\, 0{,}3\}$ единообразно по секторам.

---

## 4b. Канонический DebtRank $K^{(DR)}$ (METHODOLOGY_FINAL.md §10.1)

Канонический оператор DebtRank в редакции Battiston et al. 2012, адаптированный
для инфраструктуры по линии Li et al. 2021. Реализует state machine с тремя
состояниями $\{N, O, F\}$ и абсорбирующим $F$:

1. **Правило перехода.** $F$ — абсорбирующее. $O \to F$ за один шаг. $N \to O$ при
   $h_i(t) \geq C_i$.
2. **Распространение дистресса.** Только узлы в состоянии $O$ передают дистресс:

$$h_i(t+1) = \min\!\Bigl\{1,\; h_i(t) + \sum_{j:\,s_j(t) = O} a_{ij}\,h_j(t)\Bigr\}, \qquad s_i(t) \neq F \tag{DR.1}$$

$$h_i(t+1) = h_i(t), \qquad s_i(t) = F \tag{DR.2}$$

3. **Инициализация.** $h(0) = x_0 + u$, $s(0)$ — по правилу перехода от состояния
   $N$ с $h(0)$.

**Метрика-индикатор (формула 22 METHODOLOGY_FINAL.md):**

$$I_i^{(DR)}(s, r) = \mathbf{1}\{s_i(T) = F\} \lor \mathbf{1}\{h_i(T) \geq C_i\}$$

**Назначение.** $K^{(DR)}$ — дополнительный baseline помимо threshold-cascade
$K^{(\text{cl})}$, применяется в расширенной серии 4 для проверки гипотезы
$H_1^{(DR)}$ (формула 22).

**Реализация:** `services/risk_engine/operators/k_dr.py` — **TODO**. Детерминирован
по построению; стохастический фон не используется.

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
| $\rho_j$ | Этап 4-ter рекалибровка | Диагностика `results/diagnostics/rho_sweep.md` | $\rho_A = 0.5$, $\rho_\text{rec} = 0.3$, $T_\text{steps}=50$ | `docs/methodology/calibration_rationale.md` |
| $x_j$ (Gross Output) | WIOD NIOT GO/TOT row | NIOT RUS+DEU+USA, 2014 | energy=246777, water=12950, transport=564730 | `data/calibration/wiod_sector_outputs.json` |
| $A^\star$ (Haimes) | $A^\star_{ij} = A_{ij}\cdot x_j/x_i$ | — | 3×3, $\rho(A^\star)=0.3955$ | `data/calibration/A_star_iim_canonical.json` |

**Примечание по $\sigma$:** калиброванные значения — в единицах $\text{ч}^{-1/2}$. При использовании в СДУ с безразмерным $\Delta t$ необходим перевод: $\sigma_\text{model} = \sigma_\text{calibrated} \cdot \sqrt{\Delta t_\text{hours}}$.

Значения $\sigma$ в таблице выше относятся к **исторической** (v1) процедуре на прямой
subsampled RV (Zhang 2005). Итоговая редакция методологии требует двухшаговой
процедуры ARIMA + Newey—West с последующей безразмерной нормировкой (раздел 5a).

---

## 5a. Калибровка $\sigma$ по METHODOLOGY_FINAL.md §5.2 (двухшаговая схема)

Финальная методология заменяет прямую оценку волатильности на двухшаговую процедуру
и добавляет acceptance-критерий через отношение сигнал/шум.

### Шаг 1. ARIMA pre-filtering

По ряду $\log x(t)$ оценивается AR($p$)-модель (порядок $p$ по критерию BIC);
остатки $\hat\varepsilon_t$ сохраняются как инновации с ожидаемым $\mathrm{ACF}(1) \approx 0$.

### Шаг 2. HAC-оценка Newey—West

На инновациях применяется оценка с lag-bandwidth $L = \lfloor 4(n/100)^{2/9} \rfloor$:

$$\widehat{\sigma_j^2}^{\text{NW}} = \hat\gamma_0 + 2\sum_{\ell=1}^{L}\!\Bigl(1 - \frac{\ell}{L+1}\Bigr)\,\hat\gamma_\ell \tag{17}$$

### Безразмерная нормировка

Для согласованности масштабов с порогом $\delta = 0{,}10$ применяется:

$$\sigma_j^{\text{dim}} = \frac{\sigma_j^{\text{raw}}}{1 - C_j} \tag{16}$$

### Контроль SNR (acceptance-критерий)

$$\mathrm{SNR}_j = \frac{\delta}{\sigma_j^{\text{dim}}\,\sqrt{\Delta t}} \geq 1 \tag{18}$$

При $\mathrm{SNR}_j < 1$ метрика $K^{(q)}$ работает в режиме инфляции срабатываний;
это зарегистрировано как критерий приёмки.

### Таблица калибровочных значений (по §5.2 METHODOLOGY_FINAL.md)

| Сектор | $\sigma_j^{\text{raw}}$ [ч$^{-1/2}$] | $C_j$ | $\sigma_j^{\text{dim}}$ | $\mathrm{SNR}_j$ |
|---|---|---|---|---|
| energy | <!-- TODO: value from calibrate_sigma.py (two-step ARIMA + NW) --> | $0{,}883$ | <!-- TODO --> | <!-- TODO --> |
| water | <!-- TODO: value from calibrate_sigma.py (two-step ARIMA + NW) --> | $0{,}646$ | <!-- TODO --> | <!-- TODO --> |
| transport | $0{,}000$ | $0{,}928$ | $0{,}000$ | — (детерминирован) |

*Таблица калибровки волатильности в безразмерной шкале. Значения «TODO» — по итогам
финализации `scripts/calibrate_sigma.py` (реализация — отдельная задача).*

Транспортный сектор моделируется как детерминированный ($\sigma_\tau = 0$) ввиду
отсутствия открытых высокочастотных операционных рядов: DfT Road Safety содержит
ежемесячные счёты ДТП — частота, недостаточная для оценки $\sigma$ на шаге
$\Delta t = 1$ ч. Экспертное назначение $\sigma_\tau$ внесло бы калибровочный
артефакт в ключевой сектор (METHODOLOGY_FINAL.md §5.2, §12.6).

### Pre-registered порог $\theta_{\text{node}}$ (формула 9)

Порог бинаризации классического оператора фиксируется предрегистрированным правилом:

$$\theta_{\text{node}} := \max_{j \in \{e, w, \tau\}} x_{j,0}^{\text{baseline}} + \Delta_{\text{margin}}, \qquad \Delta_{\text{margin}} \geq 0{,}05 \tag{9}$$

Для текущей калибровки $x_0^{\text{baseline}} = (0{,}667;\, 0{,}000;\, 0{,}333)$ формула (9)
даёт $\theta_{\text{node}} \geq 0{,}72$. В расчётах основной серии зафиксировано
$\theta_{\text{node}} = 0{,}70$ из условия $x_{e,0}^{\text{baseline}} = 0{,}667 < \theta_{\text{node}}$;
устойчивость основного вывода $H_1$ подтверждена sensitivity-анализом с плато
$K^{(q)}_\tau \in [0{,}876;\, 0{,}878]$ при $\theta_{\text{node}} \in [0{,}40;\, 0{,}90]$
(Серия 2, Таблица 3.4 ВКР).

NERC EOP-011 Level 2 Emergency Alert приводится как **исторический референс** для
пороговых моделей энергосистем, но не является источником значения $\theta_{\text{node}}$:
единообразное применение ко всем трём секторам $\{e, w, \tau\}$ требует привязки к
данным калибровки, а не к отраслевому нормативу.

---

## 6. Каскадные операторы (cascade_operators.py)

В соответствии с позиционированием работы как **синтеза трёх линий**
(Леонтьев / Ринальди / Баттистон, METHODOLOGY_FINAL.md §1) основной метод —
стохастический оператор (5), а для сравнительных серий реализована
семья из трёх операторов: линейный бинарный классический, линейный
непрерывный (IIM iterative) и нелинейный насыщающийся (NEVA/NLDR β=2).
Семья соответствует трём поколениям моделей каскадного распространения риска.

Канонический DebtRank $K^{(DR)}$ со state machine $\{N, O, F\}$
(§10.1 METHODOLOGY_FINAL.md, раздел 4b выше) предусмотрен как дополнительный
baseline в расширенной Серии 4, **не** как основной оператор работы.

Реализация: `services/risk_engine/cascade_operators.py`.
Unit-тесты: `tests/test_cascade_operators.py`.

### 6.1. Classical (бинарный порог)

$$x_i(t+1) = \mathrm{clip}_{[0,1]}\!\left(x_i(t) + \sum_j A_{ij}\,\mathbf{1}[x_j(t) \geq \theta]\right) \tag{10}$$

Реализация: `ClassicalOperator`. Использует порог $\theta$ (по умолчанию 0.5) —
сектор $j$ передаёт вклад только после бинарного превышения.

### 6.2. IIM iterative (линейный непрерывный, Haimes 2005)

$$q(t+1) = \mathrm{clip}_{[0,1]}\!\left(A^\star q(t) + c^\star\right) \tag{11}$$

где $A^\star$ — преобразованная матрица (§ 6.4), $c^\star$ — вектор внешнего спроса-шока.
При сходимости $q^\ast = (I - A^\star)^{-1}\,c^\star$.

Реализация: `IIMOperator`.

### 6.3. NEVA / NLDR (Barucca et al. 2020, β=2)

$$x_i(t+1) = \mathrm{clip}_{[0,1]}\!\left(x_i(0) + \sum_j A_{ij}\,\bigl(1 - (1 - x_j(t))^\beta\bigr)\right) \tag{12}$$

Реализация: `NevaOperator` (поддерживает $\beta \geq 1$, по умолчанию $\beta=2$).
Non-Linear DebtRank (NLDR): функция передачи $g_\beta(x) = 1 - (1-x)^\beta$
монотонно насыщается при $x \to 1$. $\beta=1$ → линейный DebtRank; $\beta=2$ → квадратичное
подавление малых сигналов (используется в NEVA).

---

## 6.4. IIM canonical (Haimes 2005 Part I eq. 11) — закрытая форма

Каноническая форма IIM использует преобразование матрицы коэффициентов Леонтьева $A$
в «intermediate-transactions intensity matrix» $A^\star$:

$$A^\star_{ij} = A_{ij} \cdot \frac{x_j}{x_i} \tag{13}$$

где $x_j$ — валовой выпуск (Gross Output) сектора $j$ (WIOD NIOT, колонка GO/TOT).
Это диагональное подобие $A^\star = D^{-1} A D$, $D = \mathrm{diag}(x)$, поэтому
спектральный радиус инвариантен: $\rho(A^\star) = \rho(A)$.

**Закрытая форма:**

$$q^\ast = (I - A^\star)^{-1}\,c^\star \tag{14}$$

где $c^\star$ — вектор нарушения (degraded demand), $q^\ast_i \in [0, 1]$ —
установившаяся «инoperability» сектора $i$.

Реализация: `services/risk_engine/iim_canonical.py` (`IIMCanonical.predict()`).
Артефакт: `data/calibration/A_star_iim_canonical.json` ($\rho(A^\star) = 0.3955$,
$x_\text{energy}=246\,777$, $x_\text{water}=12\,950$, $x_\text{transport}=564\,730$,
WIOD 2014, DEU+USA; RUS исключена для воды из-за $\text{GO}=0$).

**Скрипты:** `scripts/matrix_calibration/extract_sector_outputs.py` (извлечение $x_j$),
`scripts/matrix_calibration/apply_haimes_transformation.py` (построение $A^\star$).

---

## 6.5. Унифицированный MC harness

Для честного сравнения всех операторов на едином стохастическом фоне реализован
**единый MC harness** (`services/risk_engine/mc_harness.py`):

- `run_sde_once()` — одна траектория СДУ (Эйлер–Маруяма)
- `run_iim_once()` — одна траектория IIM iterative ($q(t+1) = \mathrm{clip}(A^\star q + c^\star)$)
- `run_neva_once()` — одна траектория NEVA/NLDR ($\beta=2$)

Все три функции принимают одинаковый `seed` и тот же массив $\sigma$-шума
(логарифмический, мультипликативный), что обеспечивает парное сравнение
траекторий методов на идентичных реализациях случайности.

**Драйверы:** `scripts/run_operator_comparison.py` (Этап 3),
`scripts/run_stage4_mc.py` (Этап 4: 15 сценариев × 3 оператора, N≥10³),
`scripts/validation/mae_comparison.py` (Этап 4-quint: IIM canonical vs NLDR).

---

## 6.6. Этап 4-quint: MAE IIM canonical vs NLDR

**Задача:** сравнить качество прогноза интенсивности деградации секторов двумя
детерминированными моделями на 4 исторических каскадах.

**Модели:**

- IIM canonical: $q = (I - A^\star)^{-1}\,c^\star$ (eq. 14)
- NLDR β=2: eq. (12), до сходимости

**События:** EUROPE_2006 (UCTE), TEXAS_2021 (FERC/NERC), INDIA_2012 (CEA), BALTIMORE_2024
(Dulin et al., Nat. Comm. 2025). Ground truth — иерархия: первичная (`cascade_events.yaml`
из регуляторных отчётов) → вторичная (`results/validation_real_events.json::reality.delta_approx`).

**Метрика:** MAE по не-инициатор секторам (LOO-эквивалентная агрегация).

**Результаты (`results/mae_comparison.json`):**

| Модель | MAE (общий) | MAE (out-of-sample) |
|--------|:-----------:|:-------------------:|
| IIM canonical | — | **0.1777** |
| NLDR β=2 | — | 0.2668 |

$\Delta = -50.2\%$ (IIM точнее NLDR). Исходная гипотеза H₁ (NLDR ≥25% точнее IIM) **не подтверждена**.

**Интерпретация:** при $\rho(A^\star) = 0.3955 \ll 1$ линейное затухание IIM даёт
консистентные умеренные прогнозы, тогда как нелинейная насыщающая функция NLDR $\beta=2$
переоценивает высокие значения (saturation bias при $x \to 1$ для сильносвязанных секторов).
Это — содержательный фундаментальный результат, а не аномалия.

Методология полностью описана в `docs/methodology/stage4_quint_iim_vs_nldr.md`.

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
