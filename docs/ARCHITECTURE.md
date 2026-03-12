# DIPLOMA Infrastructure-Risk Stand — Architecture Reference

**Branch:** `cdx` | **Last verified:** 2026-03-12

This document describes the **actual runtime architecture** of the DIPLOMA
infrastructure-risk simulation stand. All numerical values are cross-referenced
against the live running stack and the authoritative runtime snapshot at
[`results/dependency_matrix_live_snapshot.json`](../results/dependency_matrix_live_snapshot.json).

---

## 1. Service Inventory

| Service | Internal port | Host port | Role |
|---|---|---|---|
| `energy_service` | 8000 | 8001 | Energy sector domain model |
| `water_service` | 8000 | 8002 | Water sector domain model |
| `transport_service` | 8000 | 8003 | Transport sector domain model |
| `risk_engine` | 8000 | 8004 | Risk operators, dependency matrix, aggregation |
| `scenario_simulator` | 8000 | 8005 | Scenario execution, Monte Carlo, cascade indicators |
| `reporting` | 8000 | 8010 | Experiment registry |
| `ingestor` | — | — | RabbitMQ consumer → DB writer |
| `normalizer` | — | — | Pre-processing pipeline |
| `diploma-db` | 5432 | 5432 | PostgreSQL (shared) |
| `diploma-rabbitmq` | 5672 | — | AMQP broker |

---

## 2. Dependency Matrix A — Live Runtime State

> **This section reflects the actual live model.** Verified by direct API query
> on 2026-03-12. Full machine-readable snapshot:
> `results/dependency_matrix_live_snapshot.json`.

### 2.1 Matrix values (version `v1.0`)

Sectors order (canonical, fixed): **[energy, water, transport]**

Matrix semantics: `A[i][j]` = influence of sector **j** (source) on sector **i** (destination).

```
          src: energy  water  transport
dest energy  [  0.0     0.2     0.3  ]   ← energy depends on water and transport
dest water   [  0.4     0.0     0.2  ]   ← water depends on energy and transport
dest transp  [  0.5     0.3     0.0  ]   ← transport depends on energy and water
```

### 2.2 Edge table

| Edge | A index | Value | Status at θ_bin=0.5 |
|---|---|---|---|
| water ← energy | `A[1][0]` | **0.4** | INACTIVE (0.4 < 0.5) |
| transport ← energy | `A[2][0]` | **0.5** | **ACTIVE** (0.5 ≥ 0.5) |
| energy ← water | `A[0][1]` | **0.2** | INACTIVE |
| water ← transport | `A[1][2]` | **0.2** | INACTIVE |
| energy ← transport | `A[0][2]` | **0.3** | INACTIVE |
| transport ← water | `A[2][1]` | **0.3** | INACTIVE |

**Important topology note:** The matrix is fully connected — all 6 off-diagonal entries
are non-zero. This is **not** a 2-edge simplified model. Earlier summaries that described
only `A[water][energy]=0.4` and `A[transport][energy]=0.5` were citing the two
pedagogically dominant edges, not the complete matrix.

### 2.3 Source of truth

- **Config file:** `services/risk_engine/config.py` → `Settings.DEPENDENCY_MATRIX`
- **Runtime API:** `GET http://localhost:8004/api/v1/risk/dependency_matrix`
- **Version string:** `v1.0` (set by `DEPENDENCY_MATRIX_VERSION` env var, default `v1.0`)
- **Runtime drift:** None detected. Live API returns values identical to config.py.
- **Dynamic update:** Available via `POST /api/v1/risk/dependency_matrix` when
  `ENABLE_DYNAMIC_MATRIX=True` (currently enabled). Changes are in-memory only and
  lost on container restart.

---

## 3. Sector Weights

Weights are used to compute the aggregated `total_risk`:

```
total_risk = (adj_energy × w_e + adj_water × w_w + adj_transport × w_t) / (w_e + w_w + w_t)
```

| Sector | Weight |
|---|---|
| energy | **0.4** |
| water | **0.3** |
| transport | **0.3** |

**Source:** `services/risk_engine/config.py` (`ENERGY_WEIGHT`, `WATER_WEIGHT`,
`TRANSPORT_WEIGHT`). Confirmed by DB risk_snapshot `meta.weights` field
(via `GET /api/v1/risk/history`).

**Weights version:** Not versioned. No `GET /weights` endpoint exists. Dynamic
update is possible via `POST /api/v1/risk/update_weights` when
`ENABLE_DYNAMIC_WEIGHTS=True`, but changes are in-memory only.

---

## 4. Threshold Parameters

### 4.1 θ_bin — Classical binarisation threshold

| Parameter | Value | Source |
|---|---|---|
| `theta_bin` (live) | **0.5** | `GET /api/v1/risk/classical_threshold` |
| `theta_bin` (default) | **0.5** | Hardcoded in `ClassicalOperator` constructor |
| Override API | `POST /api/v1/risk/set_classical_threshold` | In-memory; lost on restart |

**θ_bin governs two distinct operations in `ClassicalOperator`:**

1. **Binarisation:** `y_i = I(x_i ≥ θ_bin)` — converts continuous sector risk to binary.
2. **Edge activation:** an edge `A[i][j]` fires in one-step propagation only if
   `A[i][j] ≥ θ_bin`. At θ_bin=0.5, only `transport ← energy` (0.5 ≥ 0.5) is active.

This means **K_cl is structurally sensitive to θ_bin** through topology changes:

| θ_bin | Active edges | Cascade sectors (S1 energy outage) | Expected K_cl |
|---|---|---|---|
| 0.3 | water←energy, transport←energy, transport←water, energy←transport | water + transport | ~0.84 |
| 0.4 | water←energy, transport←energy, transport←water | water + transport | ~0.73 |
| 0.5 | transport←energy only | transport only | ~0.63 |
| 0.6 | none | none | ~0.0 |

### 4.2 θ_cascade — Cascade detection threshold (scenario_simulator)

| Parameter | Default | Source |
|---|---|---|
| `theta_classical` | **0.3** | `ScenarioRequest` / `MonteCarloRequest` field |

**Trivial invariance:** Since `ClassicalOperator` outputs `{0, 1}`, sector risk
deltas `Δx_cl ∈ {−1, 0, 1}`. Therefore `I_cl = I(Δx_cl ≥ θ_cascade)` is
identical for any `θ_cascade ∈ (0, 1]`. Sensitivity analysis of θ_cascade produces
flat results. True sensitivity is only via θ_bin (section 4.1).

---

## 5. Risk Operators

### 5.1 Quantitative Operator

**Formula:** `x' = clip(x + A·x, 0, 1)`

Applied per sector:
```
x'_i = clip(x_i + Σ_j A[i][j] · x_j)
```

With full 3×3 matrix A and initial energy degradation `x_energy = r_E`:
```
x'_water     = clip(x_water     + 0.4·r_E + 0.2·x_transport)
x'_transport = clip(x_transport + 0.5·r_E + 0.3·x_water)
x'_energy    = clip(x_energy    + 0.2·x_water + 0.3·x_transport)
```

**Implementation:** `services/risk_engine/routers/risk.py:apply_dependencies_quantitative`

### 5.2 Classical Operator

**Formula:**
1. `y_i = I(x_i ≥ θ_bin)` — binarisation
2. `y_i(t+1) = y_i(t) OR ∃j: [y_j(t)=1 AND A[i][j] ≥ θ_bin]` — one-step propagation

**Output:** `{0.0, 1.0}` per sector.

**Implementation:** `services/risk_engine/routers/risk.py:apply_dependencies_classical`

### 5.3 Cascade Indicators

| Indicator | Method | Formula |
|---|---|---|
| `I_cl` | Classical | `1` if any non-initiator sector `Δx_cl ≥ θ_cascade` at any step |
| `I_q` | Quantitative | `1` if any non-initiator `Δx_q ≥ δ=0.1` at final state |
| `K_cl` | MC aggregate | `mean(I_cl)` over N runs |
| `K_q` | MC aggregate | `mean(I_q)` over N runs |
| `Δ%` | Comparison | `(K_q − K_cl) / K_cl × 100%` |

**Per-run diagnostics (added in cdx branch):** `cl_activated_sectors`,
`cl_first_activation_step` in `ScenarioRunResult` and `MonteCarloRun`.

---

## 6. Propagation Architecture

### 6.1 Three-layer propagation (double-counting assessment)

Propagation from a source sector to downstream sectors involves **three distinct layers**:

| Layer | File | Mechanism |
|---|---|---|
| Domain service | `water_service/routers/water.py:check_energy_dependency` | Hardcoded weight 0.55 on physical supply |
| Domain service | `transport_service/routers/transport.py:check_energy_dependency` | Hardcoded weight 0.70 on load |
| Interaction queue | `scenario_simulator/routers/simulator.py:_run_interaction_queue` | Matrix A drives stochastic `dependency_check` fanout |
| Risk operators | `risk_engine/routers/risk.py:apply_dependencies_{q,cl}` | Matrix A applied to abstract risk vectors |

These layers are **not pure double-counts**: domain services operate on physical
state (supply, load), while risk operators operate on abstract risk values. However,
they represent the same causal relationship through different state representations.

### 6.2 Multi-hop propagation constraint

`propagation_depth` (default=1) controls the interaction queue depth.

**Architectural limitation:** Domain services only implement `check_energy_dependency`
endpoints on water and transport. Energy has **no** `check_water_dependency` or
`check_transport_dependency` endpoint. With the full 3×3 matrix, `depth=2` attempts
second-hop paths (e.g., transport→energy, water→transport) which fail because these
endpoints do not exist. Best-effort exception handling logs a warning and skips these
steps — the run does not abort.

**Practical implication:** `propagation_depth=1` is the only fully supported depth
with the current domain service implementation. Depth=2 is gracefully degraded.

### 6.3 Interaction queue behavior (depth=1, S1 energy outage)

At depth=0, the queue inspects column `j=energy` in matrix A:
- water ← energy: weight=0.4 → candidate
- transport ← energy: weight=0.5 → candidate (top-1 by weight)

With **top-1 fanout rule**, only transport is triggered at depth=0.
Then at depth=1 from transport: no sectors depend on transport in the S1 scenario
path (matrix A column transport has values 0.3, 0.2 for water←transport and
energy←transport, but those paths attempt unsupported endpoints).

---

## 7. Scenario Catalog

Built-in scenarios (`SCENARIO_CATALOG` in `scenario_simulator/routers/simulator.py`):

| ID | Initiator | Steps | Key dependency |
|---|---|---|---|
| `S1_energy_outage` | energy | outage(30min) + water dep_check + transport dep_check | water←energy, transport←energy |
| `S2_water_outage` | water | outage(30min) | none (no water outgoing edges with active θ_bin=0.5) |
| `S3_transport_load` | transport | load_increase(0.25) | none (no transport outgoing active edges) |

---

## 8. Monte Carlo Pipeline

```
MonteCarloRequest
  → for each run r:
      seed = sha256(scenario_id:run_id)[:16]   # deterministic
      duration = Uniform(duration_min, duration_max)
      dependency_multiplier = 1 + N(0, stochastic_scale)   [if stochastic_scale > 0]
      exogenous_factor = weather_factor × load_factor × fuel_stress_factor
      steps = _build_mc_steps(duration × dependency_multiplier × exogenous_factor)
      scenario_res = run_scenario(steps, propagation_depth, heterogeneity_scale, ...)
        → init all sector states
        → x_0 = fetch_risk(classical), fetch_risk(quantitative)
        → for each step:
            apply_step → domain service HTTP call
            fetch updated classical risk → step_vectors_cl
            if impactful: run_interaction_queue(max_depth=propagation_depth)
        → x_T = fetch_risk(classical), fetch_risk(quantitative)
        → I_cl = _compute_cl_diagnostics(x_0, step_vectors_cl, θ_cascade, initiator)
        → I_q = I(max_Δx_q(non-initiators) >= δ=0.1)
        → [if enable_recovery]: recovery_trajectory = x_0 + (x_T - x_0)·(1-rate)^t
  → K_cl = mean(I_cl), K_q = mean(I_q)
  → Δ% = (K_q - K_cl) / K_cl × 100%
```

### 8.1 Realism extension parameters (cdx branch)

All optional, default = off / neutral:

| Parameter | Default | Effect |
|---|---|---|
| `enable_recovery` | False | Post-shock recovery trajectory (additive) |
| `recovery_rate` | 0.2 | Per-step recovery fraction |
| `recovery_horizon` | 5 | Recovery steps to simulate |
| `propagation_depth` | 1 | Interaction queue max depth |
| `heterogeneity_scale` | 0.0 | Per-sector independent noise std |
| `weather_factor` | 1.0 | Outage duration pre-shock multiplier |
| `load_factor` | 1.0 | Load severity pre-shock multiplier |
| `fuel_stress_factor` | 1.0 | Fuel stress pre-shock multiplier |

---

## 9. Domain Service Internal Dependency Weights

Water and transport services implement hardcoded dependency weights that are
**independent of matrix A**:

| Service | Endpoint | Hardcoded weight | Effect |
|---|---|---|---|
| water | `POST /check_energy_dependency` | `dependency_weight = 0.55` | `supply' = supply × (1 − 0.55 × source_level)` |
| transport | `POST /check_energy_dependency` | `dependency_weight = 0.70` | `load' = load + 0.70 × source_level × 0.8` |

These weights affect the physical domain state (supply, load), which is then
fetched by `risk_engine` and passed through matrix A. The chain is:

```
energy outage → (hardcoded 0.55/0.70) → water/transport domain state
             → risk_engine fetch → (matrix A) → adjusted risk vector
```

---

## 10. Data Layer

### 10.1 Risk snapshots

Table: `risk.risk_snapshots`

| Column | Description |
|---|---|
| `energy_risk`, `water_risk`, `transport_risk` | Per-sector adjusted risks |
| `total_risk` | Weighted aggregate |
| `meta` (JSON) | `{weights, method, matrix_A_version, scenario_id, run_id, ...}` |
| `calculated_at` | Timestamp |

### 10.2 Domain service tables

Each domain service maintains its own per-`(scenario_id, run_id)` state table,
enabling full isolation of MC runs and reproducible replay.

---

## 11. Async Messaging (RabbitMQ)

Ingestor and normalizer consume from RabbitMQ for event-driven ingestion.
The scenario_simulator and risk_engine use synchronous HTTP for experiment runs.
The reporting service (`POST /experiments/register`) is called best-effort from
`run_monte_carlo`; failures do not abort MC execution.

---

## 12. Known Limitations

1. **`run_id` overflow:** Auto-generated `run_id` uses `time.time_ns()` which overflows
   the PostgreSQL `INTEGER` column. Always pass explicit small `run_id` values for
   manual calls (e.g., `run_id=9001`).

2. **Weights not versioned:** No `GET /weights` endpoint. No `weights_version` field
   in `ScenarioRunResult`. Weights can only be inferred from DB snapshot meta.

3. **θ_bin in-memory only:** `set_classical_threshold` changes the in-memory value;
   lost on container restart. Experiments requiring specific θ_bin must set it at
   startup via API.

4. **propagation_depth > 1:** Best-effort only. Second-hop paths fail silently for
   non-energy source sectors (missing domain service endpoints). See section 6.2.

5. **Top-1 fanout rule:** The interaction queue only triggers the highest-weight
   downstream dependency per message, not all non-zero edges. This is a deliberate
   design choice for computational efficiency.

6. **Merge conflict (resolved):** The `cdx` branch had three committed unresolved
   `<<<<<<< HEAD` / `>>>>>>> cdx` markers in `scenario_simulator/routers/simulator.py`
   that made the service a Python syntax error. Resolved 2026-03-12 in favor of the
   cdx implementation.

---

## 13. Runtime Matrix Snapshot and Experiment Reproducibility

> **For thesis experiments, this section is the authoritative cross-reference.**

The file `results/dependency_matrix_live_snapshot.json` contains a complete
machine-readable record of the runtime model state at the time of the experiments:

- exact matrix A with version tag
- sector ordering
- sector weights
- θ_bin value
- θ_cascade default
- domain service hardcoded weights
- topology note (fully connected 3×3)
- edge activation table at θ_bin=0.5

### How to cite in experiment analysis

When reporting results for S1 energy outage Monte Carlo experiments, the following
parameters characterize the model completely:

```
Matrix A:    v1.0 (see dependency_matrix_live_snapshot.json)
Sectors:     [energy, water, transport]
Weights:     [0.4, 0.3, 0.3]
θ_bin:       0.5  (classical threshold)
θ_cascade:   0.3  (cascade detection, trivially invariant)
δ_sector:    0.1  (quantitative cascade threshold)
Active cl edges at θ_bin=0.5:  transport ← energy only (A[2][0]=0.5 ≥ 0.5)
```

Baseline MC results (stochastic_scale=0.3, duration=[5,30], N=1000 runs):

| Metric | Value |
|---|---|
| K_cl | 0.630 |
| K_q | 0.950 |
| mean ΔR | 0.4363 |
| p95 ΔR | 0.6700 |

### Discrepancy note

Earlier project summaries described the matrix as having only two main edges
(water←energy=0.4, transport←energy=0.5). This was an incomplete description of
the pedagogically dominant edges for S1 scenario analysis. The **actual runtime
matrix is fully connected** with 6 non-zero edges. This does not affect the
interpretation of S1 baseline results (the dominant cascade path remains
transport←energy), but it is important for multi-hop analysis and for any scenario
involving non-energy initiators (S2 water outage, S3 transport load).

---

## 14. Sequence Diagram: S1 Energy Outage (Single Run)

```
Client
  │ POST /run_scenario {scenario_id:"S1_energy_outage", run_id:9001}
  ▼
scenario_simulator
  │ init energy/water/transport states → domain services
  │ GET risk_engine /risk/current?method=classical   → x_0_cl
  │ GET risk_engine /risk/current?method=quantitative → x_0_q
  │
  │ [Step 1] POST energy /simulate_outage {duration:30}
  │   risk_engine.calculate_risks(x_energy_degraded)
  │   → apply_dependencies_quantitative: x'_water=0.4*x_E, x'_transport=0.5*x_E
  │   → apply_dependencies_classical: y_transport=1 if x_E>=0.5
  │
  │ [Interaction queue depth=1] POST transport /check_energy_dependency
  │   transport domain: load' = load + 0.7 * energy_degradation * 0.8
  │
  │ [Step 2] POST water /check_energy_dependency {source_duration:30}
  │   water domain: supply' = supply * (1 - 0.55 * energy_level)
  │
  │ [Step 3] POST transport /check_energy_dependency {source_duration:30}
  │   (transport already degraded by queue, step reinforces)
  │
  │ GET risk_engine /risk/current (both methods) → x_T
  │ compute I_cl, I_q, delta_q, delta_cl
  │ [if enable_recovery] compute recovery trajectory
  ▼
ScenarioRunResult {delta_q, delta_cl, I_cl, I_q, cl_activated_sectors, ...}
```
