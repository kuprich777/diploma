# Summary: A_calibrated v2.0 — Monte Carlo Results

**Generated:** 2026-04-06  
**Matrix version:** A_calibrated v2.0 (OLS, Росстат+Eurostat+BEA)  
**θ_node = 0.70 | θ_cascade = 0.30 | δ = 0.10 | stochastic_scale = 0.30**

---

## Main Results Table (N = 1000 per scenario)

| Scenario | Matrix | K_cl | K_q | ΔK | Δ% | H₁ (ΔK > 0) |
|---|---|---|---|---|---|---|
| S3 transport load=0.40 | A_expert v1.0 | 0.534 | 0.956 | +0.422 | +79% | ✓ |
| S3 transport load=0.40 | **A_calibrated v2.0** | **0.454** | **0.355** | **−0.099** | **−22%** | **✗ reversed** |
| S4 water load=0.70 | A_expert v1.0 | 0.416 | 0.876 | +0.460 | +111% | ✓ |
| S4 water load=0.70 | **A_calibrated v2.0** | **0.399** | **0.812** | **+0.413** | **+104%** | **✓** |
| S1 energy outage | A_calibrated v2.0 | 1.000 | 0.980 | −0.020 | −2% | (saturated) |
| S1b energy load=0.01 | A_calibrated v2.0 | 0.381 | 0.000 | −0.381 | — | ✗ reversed |
| S5 transport load=0.35 | A_calibrated v2.0 | 0.341 | 0.238 | −0.103 | −30% | ✗ reversed |

---

## Sweep Results

### S3 Load Sweep (transport sector, A_calibrated v2.0, N = 500/point)

| load_amount | K_cl | K_q | ΔK | Pattern |
|---|---|---|---|---|
| 0.10 | 0.000 | 0.000 | 0.000 | No cascade |
| 0.15 | 0.008 | 0.004 | −0.004 | K_cl > K_q |
| 0.20 | 0.038 | 0.016 | −0.022 | K_cl > K_q |
| 0.25 | 0.096 | 0.068 | −0.028 | K_cl > K_q |
| 0.30 | 0.182 | 0.116 | −0.066 | K_cl > K_q |
| 0.35 | 0.336 | 0.222 | −0.114 | K_cl > K_q |
| 0.40 | 0.446 | 0.360 | −0.086 | K_cl > K_q |
| 0.45 | 0.544 | 0.452 | −0.092 | K_cl > K_q |
| 0.50 | 0.626 | 0.544 | −0.082 | K_cl > K_q |
| 0.55 | 0.686 | 0.620 | −0.066 | K_cl > K_q |
| 0.60 | 0.738 | 0.676 | −0.062 | K_cl > K_q |

**Key finding:** With A_calibrated v2.0, K_cl > K_q for ALL transport load values.
Compare with A_expert v1.0: K_q >> K_cl for load ≥ 0.15.

### S4 Severity Sweep (water sector, A_calibrated v2.0, N = 500/point)

| severity | K_cl | K_q | ΔK | H₁ |
|---|---|---|---|---|
| 0.10 | 0.000 | 0.000 | 0.000 | — |
| 0.20 | 0.000 | 0.016 | +0.016 | ✓ |
| 0.30 | 0.006 | 0.126 | +0.120 | ✓ |
| 0.40 | 0.044 | 0.376 | +0.332 | ✓ |
| 0.50 | 0.118 | 0.586 | +0.468 | ✓ |
| 0.60 | 0.252 | 0.726 | +0.474 | ✓ |
| **0.70** | **0.408** | **0.820** | **+0.412** | **✓** |
| 0.80 | 0.536 | 0.868 | +0.332 | ✓ |

**Key finding:** With A_calibrated v2.0, K_q > K_cl for ALL water severity levels ≥ 0.20.
H₁ confirmed for water-initiated cascades with both matrices.

#### Comparison S4: Expert v1.0 vs Calibrated v2.0

| severity | K_q (v1.0) | K_q (v2.0) | K_cl (v1.0) | K_cl (v2.0) |
|---|---|---|---|---|
| 0.10 | 0.360 | 0.000 | 0.024 | 0.000 |
| 0.40 | 0.564 | 0.376 | 0.072 | 0.044 |
| 0.70 | 0.878 | 0.820 | 0.426 | 0.408 |
| 0.80 | 0.900 | 0.868 | 0.546 | 0.536 |

Both matrices agree at high severity (K_q ≈ 0.87 at sev=0.80). Main difference:
v2.0 has higher activation threshold (~0.20 vs ~0.05 for v1.0).

---

## Interpretation

### Why S3 reversed (K_cl > K_q) with calibrated matrix?

- A[energy][transport] dropped 0.30 → 0.136 (calibrated)
- A[water][transport] dropped 0.20 → 0.020 (calibrated)
- Quantitative propagation: δ_energy = 0.136 × Δ_transport. For Δ_transport ≈ 0.4 in a typical run: δ_energy ≈ 0.054 < δ_threshold = 0.10 → K_q = 0
- Classical propagation: topology-based, not magnitude-based. If transport risk ≥ θ_node = 0.70, all connected sectors (energy, water) get cascade regardless of edge weight.
- Result: Classical finds cascades that quantitative misses (false alarms by classical, or true alarms quantitative under-detects).

### Why S4 H₁ holds?

- A[energy][water] increased 0.20 → 0.325 (calibrated)
- Quantitative: δ_energy = 0.325 × Δ_water. For Δ_water ≈ 0.35: δ_energy ≈ 0.114 > δ_threshold = 0.10 → K_q fires
- Classical: requires water risk ≥ 0.70, which happens less often for moderate severity
- Result: Quantitative detects cascades earlier (at lower severity) than classical.

### Robustness of H₁

H₁ (K_q > K_cl) is sensitive to which sector initiates the shock:
- **Energy → transport propagation (A[transport][energy] = 0.5):** unchanged by calibration → S1 still saturated
- **Transport → other propagation:** weakened by calibration → S3 H₁ reverses
- **Water → energy propagation:** strengthened by calibration → S4 H₁ confirmed

Thesis recommendation: Present H₁ as sector-conditional — "quantitative detects more
cascades for water-initiated events; classical may over-detect for transport-initiated events."

---

## Artifacts

| File | Description |
|---|---|
| `mc_s1b_calibrated_1000_full.json` | S1b N=1000 raw results |
| `mc_s3_calibrated_1000_full.json` | S3 N=1000 raw results |
| `mc_s4_calibrated_1000_full.json` | S4 N=1000 raw results |
| `mc_s5_calibrated_1000_full.json` | S5 N=1000 raw results |
| `severity_sweep_water_summary.csv` | S4 severity sweep (v2.0) |
| `load_sweep_s3_summary.csv` | S3 load sweep (v2.0, when complete) |
| `figures/K_cl_vs_K_q_by_scenario.png` | Main comparison bar chart |
| `figures/comparison_expert_vs_calibrated.png` | Expert vs calibrated scatter |
