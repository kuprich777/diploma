# Robustness Report

**Source:** Fallback: Росстат 2019 + Eurostat DE 2019 + BEA USA 2017

## Pairwise Spearman Rank Correlation

| Pair | ρ | Sign agreement |
|---|---|---|
| russia_vs_germany | 1.0000 | 6/6 |
| russia_vs_usa | 0.9429 | 6/6 |
| germany_vs_usa | 0.9429 | 6/6 |

**Mean ρ = 0.9619** (threshold: 0.7)

## Sign Matrix

### russia
- A[energy][water]: sign=+1
- A[energy][transport]: sign=+1
- A[water][energy]: sign=+1
- A[water][transport]: sign=+1
- A[transport][energy]: sign=+1
- A[transport][water]: sign=+1

### germany
- A[energy][water]: sign=+1
- A[energy][transport]: sign=+1
- A[water][energy]: sign=+1
- A[water][transport]: sign=+1
- A[transport][energy]: sign=+1
- A[transport][water]: sign=+1

### usa
- A[energy][water]: sign=+1
- A[energy][transport]: sign=+1
- A[water][energy]: sign=+1
- A[water][transport]: sign=+1
- A[transport][energy]: sign=+1
- A[transport][water]: sign=+1

## Rank Mean Std (lower = more consistent)

rank_std_mean = 0.1571

## Expert vs Calibrated

| Metric | Value |
|---|---|
| MAE | 0.1478 |
| RMSE | 0.1760 |
| Spearman ρ | 0.2571 |
| Sign agreement | 6/6 |
