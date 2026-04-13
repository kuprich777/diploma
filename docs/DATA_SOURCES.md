# Источники данных и протокол калибровки

---

## 1. HAI ICS Security Dataset

**Путь:** `/Users/kuprich/Documents/diploma_repo/datasets/dataset hai /hai/` (с пробелом в имени)  
**Версия:** hai-21.03 (рекомендуемая)  
**Лицензия:** CC BY 4.0  
**Скачать:** https://www.kaggle.com/datasets/icsdataset/hai-security-dataset

### Структура

```
hai-21.03/
├── train1.csv.gz   (~100–200 MB gzip)
├── train2.csv.gz
├── train3.csv.gz
├── test1.csv.gz
├── test2.csv.gz
├── test3.csv.gz
├── test4.csv.gz
└── test5.csv.gz
```

Итого: **1 323 608 строк**, 1 сек/запись, ~92 колонки.

### Ключевые колонки

| Колонка | Процесс | Единицы | Использование |
|---------|---------|---------|--------------|
| `attack` | — | 0=норма, >0=атака | фильтр нормального режима |
| `P2_CO_rpm` | P2 (турбина) | об/мин | σ_energy, C_energy |
| `P2_VT01` | P2 (турбина) | В (вибрация) | σ_energy, C_energy |
| `P4_ST_PO` | P4 (ГИЛ пар) | МВт (симул.) | σ_energy, C_energy |
| `P4_HT_PO` | P4 (ГИЛ гидро) | МВт (симул.) | σ_energy, C_energy |
| `P4_ST_LD` | P4 (ГИЛ пар) | МВт (симул.) | σ_energy, C_energy |
| `P4_HT_LD` | P4 (ГИЛ гидро) | МВт (симул.) | σ_energy, C_energy |
| `P3_LIT01` | P3 (вода) | мм (уровень) | σ_water, C_water |
| `P3_PIT01` | P3 (вода) | мбар (давление) | σ_water, C_water |
| `P3_FIT01` | P3 (вода) | л/мин (поток) | σ_water, C_water |

### Нормирование

Калибровка C требует нормирования в $[0,1]$: $x_j = \text{sensor} / x_\text{nom}$.  
Номинальные значения (из максимума по всему датасету):

```python
HAI_NOMINAL = {
    "P2_CO_rpm": 54822.0, "P2_VT01": 13.1,
    "P4_ST_LD": 499.6, "P4_HT_LD": 83.1,
    "P4_ST_PO": 498.9, "P4_HT_PO": 89.6,
    "P3_LIT01": 20489.0, "P3_PIT01": 7090.0, "P3_FIT01": 7761.0,
}
```

### Результаты калибровки (текущие)

| Параметр | Значение | Скрипт |
|----------|---------|--------|
| σ_energy (ICS, медиана P4_ST/HT) | 6.54 ч⁻¹/² | `scripts/calibrate_sigma.py` |
| σ_water (медиана P3) | 18.08 ч⁻¹/² | `scripts/calibrate_sigma.py` |
| C_energy (нормированный q95) | 0.883 | `scripts/calibrate_capacity.py` |
| C_water (нормированный q95) | 0.646 | `scripts/calibrate_capacity.py` |

---

## 2. Kelmarsh Farm SCADA

**Путь:** `/Users/kuprich/Documents/diploma_repo/datasets/kelmarsh/`  
**Лицензия:** CC BY 4.0  
**Источник:** Zenodo record 5841834  

### Структура

```
kelmarsh/
├── Kelmarsh_WT_static.csv          # Паспортные данные (6 турбин Senvion MM92)
├── Kelmarsh_WT_dataSignalMapping.csv
├── Kelmarsh_SCADA_2016_3082/       # 6 файлов Turbine_Data_*.csv
├── Kelmarsh_SCADA_2017_3083/       # ...
├── Kelmarsh_SCADA_2018_3084/
├── Kelmarsh_SCADA_2019_3085/
├── Kelmarsh_SCADA_2020_3086/
└── Kelmarsh_SCADA_2021_3087/
```

**Итого:** 36 файлов `Turbine_Data_Kelmarsh_*.csv`, ~52700 строк/файл (366 дней × 144 записи/день).

### Формат файла

- 9 строк комментариев (строки 0–8), в т.ч. имя турбины и тип
- Строка 9: заголовок `# Date and time, Wind speed (m/s), ..., Power (kW), ...`
- Данные с 10-й строки, интервал 10 минут

### Ключевые параметры

| Параметр | Значение |
|----------|---------|
| Турбина | Senvion MM92 |
| Номинальная мощность | 2050 кВт |
| Диаметр ротора | 92 м |
| Интервал данных | 10 мин |
| Период | 2016–2021 |

### Результаты калибровки

| Параметр | Значение | Скрипт |
|----------|---------|--------|
| σ_wind (медиана по 36 файлам) | 0.790 ч⁻¹/² | `scripts/calibrate_sigma.py` |
| C_wind (q95 нормированной мощности) | 0.976 | `scripts/calibrate_capacity.py` |

---

## 3. UK DfT Road Safety Open Data

**Путь:** `/Users/kuprich/Documents/diploma_repo/datasets/Road safety open data/`  
**Источник:** https://www.data.gov.uk/dataset/road-accidents-safety-data  
**Период:** 2020–2024 (последние 5 лет)  

### Файлы

| Файл | Размер | Строки | Содержание |
|------|--------|--------|-----------|
| `dft-road-casualty-statistics-vehicle-last-5-years.csv` | ~97 МБ | 920 692 | Транспортные средства, участвующие в ДТП |
| `dft-road-casualty-statistics-collision-last-5-years.csv` | ~94 МБ | 503 475 | Данные ДТП (дата, место, тяжесть) |
| `dft-road-casualty-statistics-casualty-last-5-years.csv` | ~50 МБ | — | Пострадавшие |

### Использование для C_transport

Фильтр: `vehicle_type ∈ {20, 21}` (грузовые 3.5–7.5 т и ≥7.5 т)  
Метод: ежемесячный подсчёт ДТП с участием HGV → нормировка → q95.

| Параметр | Значение |
|----------|---------|
| HGV ДТП (2020–2024) | 16 117 уникальных инцидентов |
| Месяцев | 60 (2020-01 — 2024-12) |
| Min/Max ежемесячно | 105 / 345 |
| **C_transport (q95 нормированный)** | **0.928** |

---

## 4. WIOD 2016 National Input-Output Tables

**Путь:** `./matrix_doc/sources/NIOTS/` (внутри репозитория)  
**Источник:** http://www.wiod.org/database/niots16  
**Файлов:** 43 страны (`*_NIOT_nov16.xlsx`)  

### Секторальные коды (ISIC Rev.4)

| Сектор модели | Коды WIOD | Название |
|--------------|-----------|---------|
| energy | D35 | Electricity, gas, steam and air conditioning supply |
| water | E36, E37-E39 | Water collection, treatment; sewerage, waste |
| transport | H49, H50, H51, H52, H53 | Land, water, air, pipeline, auxiliary transport |

**Страны для калибровки A:** RUS, DEU, USA (год 2014)  
**Примечание:** для RUS вода q_j = 0 (сектор отсутствует в NIOT) → nanmean только DEU+USA.

### Результаты

| Параметр | Значение | Файл |
|----------|---------|------|
| A_leontief (3×3 mean RUS+DEU+USA) | см. ниже | `data/calibration/A_leontief.json` |
| Спектральный радиус | < 0.95 (нормирован) | — |
| Spearman ρ vs A_wiod_v3 | 0.714 | — |

Матрица A_mean (Leontief):
```
              energy    water    transport
energy        0.000     x.xxx     x.xxx
water         x.xxx     0.000     x.xxx
transport     x.xxx     x.xxx     0.000
```
(актуальные значения в `data/calibration/A_leontief.json`)

---

## 5. EAGLE-I Energy Outage Dataset

**Путь:** `./Energy Outage Dataset/`  
**Источник:** DOE OEDI (Open Energy Data Initiative)  
**Период:** 2014–2023, американские округа  

### Использование

Данные для валидации: Texas 2021 (зимний шторм Uri), корреляция отключений электроэнергии с X_energy(t).

**Статус:** данные загружены, валидационный скрипт (`scripts/validate_historical.py`) — TODO.

---

## 6. Протокол нехватки данных

Если при запуске калибровочного скрипта данные недостаточны или отсутствуют,  
скрипт выводит структурированное сообщение и **останавливается** (sys.exit):

```
🔴 ДАННЫЕ НЕДОСТАТОЧНЫ

Параметр:           [имя параметра]
Что нужно:          [требование]
Что есть:           [что найдено]
Почему не подходит: [причина]
Рекомендация:       [источник / инструкция]
```

**Принцип:** никогда не подставлять синтетические или литературные значения вместо  
недостающих эмпирических данных. Остановиться и сообщить.
