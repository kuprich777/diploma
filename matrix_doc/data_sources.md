# Data Sources

## Attempts (in priority order)

- OECD ICIO: requires manual download (~200 MB CSV). SKIP.
- WIOD 2016: requires manual download (.xlsb). SKIP.
-   Eurostat FAILED: No module named 'eurostat'
- BEA Use Table: requires manual download (.xlsx). SKIP.
- All external sources unavailable. Using FALLBACK (Russia + Germany + USA).
- 
=== Calibration per Country ===
- 
  russia (Росстат, ТЗВ-2019 (ОКВЭД2: D35, E36-39, H49-53), 2019):
-     A[energy] = [0.0000  0.3842  0.2460]
-     A[water] = [0.0801  0.0000  0.0299]
-     A[transport] = [0.5000  0.2562  0.0000]
- 
  germany (Eurostat SIOT, Germany 2019 (NACE: D35, E36, H49-53), 2019):
-     A[energy] = [0.0000  0.2551  0.1154]
-     A[water] = [0.1039  0.0000  0.0220]
-     A[transport] = [0.5000  0.1515  0.0000]
- 
  usa (BEA Use Table, USA 2017 (NAICS: 22, 2213, 48TW), 2017):
-     A[energy] = [0.0000  0.3346  0.0458]
-     A[water] = [0.0631  0.0000  0.0078]
-     A[transport] = [0.5000  0.1917  0.0000]
- 
=== Robustness Check ===
-   Mean Spearman ρ across countries: 0.9619
-   russia_vs_germany: ρ=1.0000, sign_match=6/6
-   russia_vs_usa: ρ=0.9429, sign_match=6/6
-   germany_vs_usa: ρ=0.9429, sign_match=6/6
- 
=== Final Calibrated Matrix (mean across countries, rescaled) ===
-   A[energy] = [0.0000  0.3246  0.1357]
-   A[water] = [0.0824  0.0000  0.0199]
-   A[transport] = [0.5000  0.1998  0.0000]
- 
=== Expert vs Calibrated Comparison ===
-   MAE  = 0.1478
-   RMSE = 0.1760
-   Spearman ρ = 0.2571
-   Sign agreement = 6/6

## Selected Source

**Fallback: Росстат 2019 + Eurostat DE 2019 + BEA USA 2017**

## Sector Codes

| Sector | ISIC Rev.4 / NACE Rev.2 / ОКВЭД2 | NAICS |
|---|---|---|
| energy    | D35 (Electricity, gas, steam)         | 22 (Utilities) |
| water     | E36-E39 (Water supply, sewerage)      | 2213 |
| transport | H49-H53 (Transportation and storage)  | 48TW |
