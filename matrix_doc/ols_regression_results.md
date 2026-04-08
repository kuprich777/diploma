# OLS Regression Results
Source: Fallback: Росстат 2019 + Eurostat DE 2019 + BEA USA 2017
Method: direct requirements a_raw[i][j] = X[i][j] / output[j],
        weighted by self-consumption x_self[j] = X[j][j] / output[j]
        a_ols[i][j] = a_raw[i][j] / x_self[j]
Note: R² proxy = contribution share a_raw[i,j] / Σ_j a_raw[i,j]

## russia (2019)
| i (dest) | j (src) | X[i,j] | output[j] | a_raw | x_self | a_ols | contrib_share |
|---|---|---|---|---|---|---|---|
| energy | water | 12 | 1420 | 0.008451 | 0.0331 | 0.255319 | 0.2854 |
| energy | transport | 189 | 8930 | 0.021165 | 0.1295 | 0.163495 | 0.7146 |
| water | energy | 98 | 11240 | 0.008719 | 0.1639 | 0.053203 | 0.7719 |
| water | transport | 23 | 8930 | 0.002576 | 0.1295 | 0.019896 | 0.2281 |
| transport | energy | 612 | 11240 | 0.054448 | 0.1639 | 0.332248 | 0.9062 |
| transport | water | 8 | 1420 | 0.005634 | 0.0331 | 0.170213 | 0.0938 |

Calibrated A_russia (rescaled to max=0.5):
```
[[0.     0.3842 0.246 ]
 [0.0801 0.     0.0299]
 [0.5    0.2562 0.    ]]
```

## germany (2019)
| i (dest) | j (src) | X[i,j] | output[j] | a_raw | x_self | a_ols | contrib_share |
|---|---|---|---|---|---|---|---|
| energy | water | 320 | 42500 | 0.007529 | 0.0494 | 0.152381 | 0.4329 |
| energy | transport | 2150 | 218000 | 0.009862 | 0.1431 | 0.068910 | 0.5671 |
| water | energy | 1850 | 162000 | 0.011420 | 0.1840 | 0.062081 | 0.8586 |
| water | transport | 410 | 218000 | 0.001881 | 0.1431 | 0.013141 | 0.1414 |
| transport | energy | 8900 | 162000 | 0.054938 | 0.1840 | 0.298658 | 0.9247 |
| transport | water | 190 | 42500 | 0.004471 | 0.0494 | 0.090476 | 0.0753 |

Calibrated A_germany (rescaled to max=0.5):
```
[[0.     0.2551 0.1154]
 [0.1039 0.     0.022 ]
 [0.5    0.1515 0.    ]]
```

## usa (2017)
| i (dest) | j (src) | X[i,j] | output[j] | a_raw | x_self | a_ols | contrib_share |
|---|---|---|---|---|---|---|---|
| energy | water | 890 | 98000 | 0.009082 | 0.0327 | 0.278125 | 0.5614 |
| energy | transport | 5400 | 761000 | 0.007096 | 0.1866 | 0.038028 | 0.4386 |
| water | energy | 4100 | 482000 | 0.008506 | 0.1622 | 0.052430 | 0.8756 |
| water | transport | 920 | 761000 | 0.001209 | 0.1866 | 0.006479 | 0.1244 |
| transport | energy | 32500 | 482000 | 0.067427 | 0.1622 | 0.415601 | 0.9284 |
| transport | water | 510 | 98000 | 0.005204 | 0.0327 | 0.159375 | 0.0716 |

Calibrated A_usa (rescaled to max=0.5):
```
[[0.     0.3346 0.0458]
 [0.0631 0.     0.0078]
 [0.5    0.1917 0.    ]]
```

