# Stage 4 original results (ρ=0.95, T_steps=50)

**Status:** superseded by Stage 4-bis (ρ=0.70, T_steps=30).

Результаты Этапа 4 с исходными параметрами ρ(A) = 0.95, T_steps = 50.
Показали структурную сатурацию NLDR (K_cl=K_q=1.0 на всех 15 сценариях
для SDE и NEVA); IIM — severity-дискриминирован корректно (K_cl 0.04→0.42).

Сохранены для сравнения с пересчитанной версией Stage 4-bis.

## Файлы

| Файл | Источник |
|---|---|
| `stage4_mc_15x3.json` | полный MC: 15 сценариев × 3 операторов × N=1000 |
| `stage4_loo_robustness.json` | LOO пробник: S_energy_sev075 × 5 матриц |
| `A_empirical_bayesian_v1.json` | full-data Bayesian posterior, ρ(A)=0.95 after cap |
| `A_loo_v1.json` | LOO варианты матриц, все ρ=0.95 after cap |

## Отличия от Stage 4-bis

| Параметр | Stage 4 | Stage 4-bis |
|---|---|---|
| SPECTRAL_CAP | 0.95 | 0.70 |
| T_steps | 50 (5h real time @ dt=0.1) | 30 (3h real time @ dt=0.1) |
| остальное | идентично | идентично |
