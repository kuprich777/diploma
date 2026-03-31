# real_data_validation

Валидационный модуль стохастической модели системных рисков на данных,
приближённых к реальным историческим каскадным событиям.

## Цель

Проверить, воспроизводится ли преимущество **количественного оператора** (K_q > K_cl)
на прокси-данных двух реальных блэкаутов:
- **Texas 2021** — аномальное похолодание, 4.5 млн домохозяйств без света (FERC/NERC 2021)
- **India 2012** — крупнейший блэкаут в истории, ~670 млн человек (CEA 2012)

## Структура

```
real_data_validation/
├── data/
│   ├── texas_2021_proxy.csv     # 168 строк (7 суток, почасово)
│   ├── india_2012_proxy.csv     # 48 строк (48 часов)
│   └── data_sources.md          # описание источников и методики прокси
├── results/
│   ├── A_calibrated.json        # калиброванная матрица A (после calibrate_A.py)
│   ├── validation_results.json  # K_cl, K_q, Δ% для всех кейсов (после run_validation.py)
│   ├── VALIDATION_REPORT.md     # итоговый отчёт (после generate_report.py)
│   └── figures/
│       ├── fig1_timeseries.png
│       ├── fig2_cascade_comparison.png
│       └── fig3_A_heatmap.png
├── generate_proxy_data.py       # (пере)генерация CSV-файлов с seed=42
├── calibrate_A.py               # OLS-калибровка матрицы A
├── run_validation.py            # MC-прогон, вычисление K_cl / K_q
├── generate_report.py           # Markdown-отчёт + 3 графика matplotlib
├── README.md
└── requirements.txt
```

## Быстрый старт

```bash
# из папки real_data_validation/
pip install -r requirements.txt

python calibrate_A.py       # → results/A_calibrated.json
python run_validation.py    # → results/validation_results.json
python generate_report.py   # → results/VALIDATION_REPORT.md + figures/
```

Для воспроизведения CSV из исходного кода:
```bash
python generate_proxy_data.py
```

## Модель

Оператор распространения рисков (идентичен основному эксперименту):

```
x_{t+1} = clip[0,1](x_t + u_t + A · x_t)
```

- `x_t ∈ [0,1]³` — вектор деградации (энергетика, вода, транспорт)
- `u_t` — вектор внешнего шока
- `A` — матрица межсекторального влияния

**Каскадные индикаторы:**
- `I_cl = 1` если `any(x >= θ=0.70) AND any(A·y > δ=0.10)`, `y = I(x >= θ)` — *классический*
- `I_q = 1` если `any(A·x > δ=0.10)` — *количественный*

`K_cl = mean(I_cl)`, `K_q = mean(I_q)` по N=1000 прогонам MC.

## Зависимости

```
numpy>=1.24
pandas>=1.5
matplotlib>=3.6
scipy>=1.10
```

## Воспроизводимость

Все случайные числа — через `np.random.default_rng(seed=42)`.
