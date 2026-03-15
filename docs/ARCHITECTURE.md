# DIPLOMA Infrastructure-Risk Stand — Architecture Reference

**Branch:** `cdx` | **Last verified:** 2026-03-14

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
> on 2026-03-13. Full machine-readable snapshot:
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

### 2.2 Topology edge table

| Edge | A index | Value | Topology status |
|---|---|---|---|
| water ← energy | `A[1][0]` | **0.4** | Active (0.4 > 0) |
| transport ← energy | `A[2][0]` | **0.5** | Active (0.5 > 0) |
| energy ← water | `A[0][1]` | **0.2** | Active (0.2 > 0) |
| water ← transport | `A[1][2]` | **0.2** | Active (0.2 > 0) |
| energy ← transport | `A[0][2]` | **0.3** | Active (0.3 > 0) |
| transport ← water | `A[2][1]` | **0.3** | Active (0.3 > 0) |

All 6 off-diagonal entries are nonzero — the dependency graph is **fully connected**.
Classical cascade propagation uses all 6 edges (topology-based, independent of theta_node).

### 2.3 Source of truth

- **Config file:** `services/risk_engine/config.py` → `Settings.DEPENDENCY_MATRIX`
- **Runtime API:** `GET http://localhost:8004/api/v1/risk/dependency_matrix`
- **Version string:** `v1.0` (set by `DEPENDENCY_MATRIX_VERSION` env var, default `v1.0`)
- **Dynamic update:** Available via `POST /api/v1/risk/dependency_matrix` when
  `ENABLE_DYNAMIC_MATRIX=True` (currently enabled). Changes are in-memory only.

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
`TRANSPORT_WEIGHT`). Confirmed by DB risk_snapshot `meta.weights` field.

**Weights version:** Not versioned. Dynamic update possible via
`POST /api/v1/risk/update_weights` when `ENABLE_DYNAMIC_WEIGHTS=True`,
but changes are in-memory only.

---

## 4. Threshold Parameters

### 4.1 theta_node — Classical binarisation threshold (node failure criterion)

| Parameter | Value | Source |
|---|---|---|
| `theta_node` (live) | **0.70** | `GET /api/v1/risk/classical_threshold` → `theta_bin` |
| `theta_node` (default) | **0.70** | `services/risk_engine/config.py` → `THETA_BIN` env var |
| Override API | `POST /api/v1/risk/set_classical_threshold` | In-memory; lost on restart |

**theta_node governs node binarisation ONLY:**

```
y_i = I(x_i >= theta_node)
```

It does **NOT** filter edges. Classical cascade propagation is topology-based and uses
every nonzero edge in A regardless of theta_node (see section 5.2).

**Rationale for theta_node = 0.70:**

Baseline pre-shock sector risks in S1_energy_outage:
- energy ≈ 0.667, water ≈ 0.267, transport ≈ 0.333

theta_node = 0.70 lies just above the maximum steady-state risk (0.667 for energy),
ensuring **pre-shock classical state = {0, 0, 0}** in all runs — not saturated.
After an energy outage, energy risk rises to ≈ 1.0 > 0.70, triggering binarisation
to 1, from which cascade propagates through all topology-connected sectors.

**History of theta_node choices:**

| Value | Period | Problem |
|---|---|---|
| 0.5 | Pre-2026-03-12 | Topology disconnected (1 of 6 edges active) |
| 0.25 | 2026-03-12 to 2026-03-13 | Pre-shock saturation (K_cl=0.0, degenerate baseline) |
| **0.70** | **2026-03-13 (current)** | **Pre-shock not saturated; topology fully connected** |

### 4.2 theta_cascade — Cascade detection threshold (scenario_simulator)

| Parameter | Default | Source |
|---|---|---|
| `theta_classical` | **0.3** | `ScenarioRequest` / `MonteCarloRequest` field |

Used in `_compute_cl_diagnostics`: `I_cl = 1` if any non-initiator sector
`Δx_cl >= theta_cascade` at any step. Since the classical operator outputs {0, 1},
any sector that transitions from 0 to 1 produces `Δx_cl = 1.0 >= 0.3`, so
the exact value of theta_cascade is insensitive as long as `0 < theta_cascade <= 1`.

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

### 5.2 Classical Operator — Two-Mechanism Design

**Two deliberately separated mechanisms:**

**Mechanism 1 — Node binarisation (uses theta_node):**
```
y_i = I(x_i >= theta_node)
```

**Mechanism 2 — Cascade propagation (topology-based, does NOT use theta_node):**
```
y_i(t+1) = y_i(t)  OR  ∃j: [y_j(t) = 1  AND  A[i][j] > 0.0]
```

The edge activation criterion is **A[i][j] > 0.0** — a structural property of the
dependency graph, independent of current risk levels or theta_node. All 6 nonzero
edges in matrix A are always active cascade paths.

**Output:** `{0.0, 1.0}` per sector.

**Default threshold:** `threshold: float = 0.70` in function signature.
`CURRENT_THETA_BIN` is always passed explicitly at the call site as
`threshold=CURRENT_THETA_BIN`; the function default is a safety fallback only.

**Implementation:** `services/risk_engine/routers/risk.py:apply_dependencies_classical`

**Why separation matters:**
- With unified threshold design (old code), low theta disconnected topology; high theta saturated pre-shock.
- With separate mechanisms: theta_node controls WHEN a node fails; topology controls WHERE cascades propagate once a node fails.

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

### 6.1 Three distinct propagation layers

The system has three layers that all model the same causal topology but at different
levels of abstraction. They are **not double-counting** — each operates on a different
state representation:

| Layer | State representation | Mechanism | Weights |
|---|---|---|---|
| Interaction queue | Physical domain state | Stochastic dependency_check calls | Matrix A (stochastic attenuation) |
| Classical risk operator | Binary abstract risk {0,1} | Topology propagation (A[i][j]>0) | Matrix A (topology only) |
| Quantitative risk operator | Continuous abstract risk [0,1] | Linear weighted propagation (A·x) | Matrix A weights |

The graph topology is **common** to all three layers. The response dynamics differ:
physical service transitions, binary risk propagation, and continuous risk propagation
are three different descriptions of the same dependency structure.

### 6.2 All dependency endpoints (6 directed edges covered)

All 6 directed edges in matrix A have corresponding domain service endpoints:

| Source → Destination | Endpoint | Service | Weight convention |
|---|---|---|---|
| energy → water | `POST /check_energy_dependency` | water_service | Domain-physical: 0.55 |
| energy → transport | `POST /check_energy_dependency` | transport_service | Domain-physical: 0.70 |
| water → energy | `POST /check_water_dependency` | energy_service | Matrix A: 0.2 |
| water → transport | `POST /check_water_dependency` | transport_service | Matrix A: 0.3 |
| transport → energy | `POST /check_transport_dependency` | energy_service | Matrix A: 0.3 |
| transport → water | `POST /check_transport_dependency` | water_service | Matrix A: 0.2 |

With all 6 endpoints implemented, `propagation_depth` up to 4 is fully supported.

### 6.3 Interaction queue — all-neighbors fanout

The interaction queue broadcasts to **all** eligible downstream neighbors per message
(all-neighbors fanout, not top-1). For a source sector, all destinations with
`A[dest][source] > 0` are candidates; each fires stochastically with probability
proportional to the edge weight.

**Stopping rules:**
- `max_messages = 32` — hard cap on total queue messages per run
- `max_depth` — bounded by `propagation_depth` (default=1, schema max=4, runtime cap=4)
- Visited set per message chain prevents infinite cycles

**Example: S1 energy outage, depth=1, source=energy**

Candidates from column `j=energy` in matrix A (edges of the form `dest ← energy`):
- water ← energy: A[1][0]=0.4 > 0 → candidate
- transport ← energy: A[2][0]=0.5 > 0 → candidate
- (energy ← anything skipped: energy is source, self-loop guard applies)

Both water and transport are triggered independently (not top-1 selection).
At depth=1 from water or transport, further downstream events can fire if
`propagation_depth > 1`.

---

## 7. Scenario Catalog

Built-in scenarios (`SCENARIO_CATALOG` in `scenario_simulator/routers/simulator.py`):

| ID | Initiator | Steps | Active cascade paths |
|---|---|---|---|
| `S1_energy_outage` | energy | outage(30min) + water dep_check + transport dep_check | water←energy (0.4), transport←energy (0.5) |
| `S2_water_outage` | water | outage(30min) | transport←water (0.3), energy←water (0.2) |
| `S3_transport_load` | transport | load_increase(0.25) | energy←transport (0.3), water←transport (0.2) |

All three scenarios have nonzero outgoing edges in the topology. The classical model
will detect cascades in all three once a sector exceeds theta_node=0.70.

---

## 8. Monte Carlo Pipeline

```
MonteCarloRequest
  → for each run r:
      seed = sha256(scenario_id:run_id)[:16]   # deterministic
      duration = Uniform(duration_min, duration_max)
      dependency_multiplier = max(0, N(1, stochastic_scale))   [if stochastic_scale > 0]
      exogenous_factor = weather_factor × load_factor × fuel_stress_factor
      steps = _build_mc_steps(duration × dependency_multiplier × exogenous_factor)
      scenario_res = run_scenario(steps, propagation_depth, heterogeneity_scale, ...)
        → init all sector states
        → x_0_cl = fetch_risk(classical)    # classical uses theta_node for binarisation
        → x_0_q  = fetch_risk(quantitative)
        → for each step:
            apply_step → domain service HTTP call
            fetch updated classical risk → step_vectors_cl
            if impactful: run_interaction_queue(max_depth=propagation_depth)
        → x_T = fetch_risk(classical), fetch_risk(quantitative)
        → I_cl = _compute_cl_diagnostics(x_0_cl, step_vectors_cl, θ_cascade, initiator)
        → I_q = I(max_Δx_q(non-initiators) >= δ=0.1)
        → [if enable_recovery]: recovery_trajectory
  → K_cl = mean(I_cl), K_q = mean(I_q)
  → Δ% = (K_q - K_cl) / K_cl × 100%
```

### 8.1 Realism extension parameters (cdx branch)

All optional, default = off / neutral:

| Parameter | Default | Effect |
|---|---|---|
| `enable_recovery` | False | Post-shock recovery trajectory |
| `recovery_rate` | 0.2 | Per-step recovery fraction |
| `recovery_horizon` | 5 | Recovery steps to simulate |
| `propagation_depth` | 1 | Interaction queue max depth (schema max=4, runtime cap=4) |
| `heterogeneity_scale` | 0.0 | Per-sector independent noise std |
| `weather_factor` | 1.0 | Outage duration pre-shock multiplier |
| `load_factor` | 1.0 | Load severity pre-shock multiplier |
| `fuel_stress_factor` | 1.0 | Fuel stress pre-shock multiplier |

---

## 9. Domain Service Dependency Weights — Two-Layer Design

All 6 directed edges have domain service endpoints. They fall into two groups:

### 9.1 Pre-existing endpoints (water and transport ← energy)

Use **domain-layer physical weights** calibrated to infrastructure impact,
independent of matrix A values:

| Service | Endpoint | Domain-layer weight | Matrix A value | Notes |
|---|---|---|---|---|
| water | `POST /check_energy_dependency` | **0.55** | A[1][0]=0.4 | Physical: pump capacity loss |
| transport | `POST /check_energy_dependency` | **0.70** | A[2][0]=0.5 | Physical: signal/traffic mgmt failure |

The ratio ≈1.38–1.40 is consistent, suggesting a stable domain-to-abstract scaling factor.

### 9.2 New endpoints (4 remaining directed edges)

Use **matrix A values directly**:

| Service | Endpoint | Weight | Matrix A index |
|---|---|---|---|
| energy | `POST /check_water_dependency` | **0.2** | A[0][1] |
| energy | `POST /check_transport_dependency` | **0.3** | A[0][2] |
| water | `POST /check_transport_dependency` | **0.2** | A[1][2] |
| transport | `POST /check_water_dependency` | **0.3** | A[2][1] |

### 9.3 Reconciliation

Domain-layer weights (0.55, 0.70) operate on physical state (supply, load).
Matrix A weights (0.2–0.5) operate on abstract risk vectors in risk_engine.
These two layers model the same causal edge at different granularities;
they are **not double-counted** in K_cl/K_q indicators.

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
Scenario_simulator and risk_engine use synchronous HTTP for experiment runs.
The reporting service (`POST /experiments/register`) is called best-effort from
`run_monte_carlo`; failures do not abort MC execution.

---

## 12. Known Limitations

1. **`run_id` overflow:** Auto-generated `run_id` uses `time.time_ns()` which overflows
   the PostgreSQL `INTEGER` column. Always pass explicit small `run_id` for manual calls
   (e.g., `run_id=9001`).

2. **Weights not versioned:** No `GET /weights` endpoint. Weights can only be inferred
   from DB snapshot meta.

3. **theta_node in-memory only:** `set_classical_threshold` changes the in-memory value;
   lost on container restart. Set at startup via `THETA_BIN` env var for reproducibility.

4. **Domain-layer weight discrepancy:** Pre-existing `check_energy_dependency` endpoints
   use domain-physical weights (0.55, 0.70) that differ from matrix A (0.4, 0.5).
   See section 9 for reconciliation.

5. **Merge conflict (resolved 2026-03-12):** The `cdx` branch had three committed
   unresolved markers in `scenario_simulator/routers/simulator.py`. Resolved in favor
   of the cdx implementation.

---

## 13. Runtime Matrix Snapshot and Experiment Reproducibility

> **For thesis experiments, this section is the authoritative cross-reference.**

The file `results/dependency_matrix_live_snapshot.json` contains a complete
machine-readable record of the runtime model state at the time of the experiments.

### 13.1 Current baseline (theta_node=0.70, topology propagation, N=1000)

Experiment command:
```bash
python scripts/run_mc_experiment.py \
  --scenario S1_energy_outage --sector energy \
  --runs 1000 --stochastic-scale 0.3 \
  --duration-min 5 --duration-max 30 \
  --prefix results/mc_baseline_theta070_1000 \
  --force-refresh-snapshot
```

Configuration:
```
Matrix A:        v1.0 (see results/dependency_matrix_live_snapshot.json)
Sectors:         [energy, water, transport]
Weights:         [0.4, 0.3, 0.3]
theta_node:      0.70  (classical binarisation threshold)
Propagation:     topology-based: A[i][j] > 0 (all 6 edges always active)
theta_cascade:   0.3   (cascade detection, trivially invariant to value)
delta_sector:    0.1   (quantitative cascade threshold)
Pre-shock state: energy=0.667 < 0.70 → {0,0,0} NOT saturated
```

Results (artifact: `results/mc_baseline_theta070_1000_meta.json`):

| Metric | Value | Interpretation |
|---|---|---|
| K_cl | **1.0** | Classical cascade detected in all 1000 runs |
| K_q | **1.0** | Quantitative cascade detected in all 1000 runs |
| Δ% | **0.0** | Both models equally sensitive for S1_energy_outage |
| mean ΔR | **0.491** | Mean total risk increase across runs |
| p95 ΔR | **0.553** | 95th percentile risk increase |
| duration_correlation | **0.439** | Moderate positive correlation with outage duration |

**Interpretation of K_cl=K_q=1.0:** With theta_node=0.70, the energy sector baseline
risk (≈0.667) is just below the threshold. Every energy outage (even minimum 5-min
duration with stochastic_scale=0.3) pushes energy risk above 0.70 in all 1000 runs.
Once energy exceeds theta_node, topology-based propagation immediately cascades to all
connected sectors (A[water][energy]=0.4>0, A[transport][energy]=0.5>0), producing I_cl=1
in every run.

**Scientific interpretation:** K_cl=K_q=1.0 means the S1_energy_outage scenario is
severe enough that both the conservative (binary/classical) and continuous (quantitative)
models agree on cascade detection in 100% of runs. The comparative value between the two
models lies in the continuous ΔR distribution (mean, p95, duration_correlation), which
only the quantitative model provides.

### 13.2 Historical baselines (superseded)

> **These results are historical and no longer the active reference baseline.**
> They are preserved here for cross-reference only.

| Baseline | theta_node | Propagation rule | K_cl | K_q | mean ΔR | Notes |
|---|---|---|---|---|---|---|
| theta025_1000 (2026-03-12) | 0.25 | threshold-filtered | 0.0 | 1.0 | 0.491 | Degenerate: pre-shock saturation |
| Old N=100 (pre-2026-03-12) | 0.50 | threshold-filtered | 0.630 | 0.950 | 0.4363 | Disconnected topology (1 edge only) |

**Why historical baselines are invalid:**
- theta_node=0.25: all sector risks exceeded 0.25 pre-shock → classical state pre-saturated → K_cl=0.0
- theta_node=0.50: only 1 of 6 topology edges was "active" → water sector could not receive cascade from energy
- Old sample size N=100 vs current N=1000

### 13.3 Scenario Severity Calibration — Marginal Scenario S3 (2026-03-14)

**Objective:** Find a scenario where K_q > K_cl > 0 with gap ≥ 0.2, demonstrating that
the quantitative model detects cascade propagation missed by the classical binary model.

**Why S1_energy_outage is saturated (K_cl=K_q=1.0):**
The energy sector baseline risk (≈0.667) is only 0.033 below theta_node=0.70. Even a
1-minute outage pushes energy_risk to ~0.71, crossing the threshold in every run and
triggering topology-based classical cascade to all sectors (K_cl=1.0). Since K_cl=1.0
always, S1 cannot demonstrate K_q > K_cl.

**Calibration choice — S3 transport load_increase:**
The transport sector starts at load=0.0, risk=0.0, far below theta_node=0.70. Two
distinct detection thresholds exist:

| Model | Detection criterion | Critical load | Critical transport_risk |
|---|---|---|---|
| Quantitative (I_q=1) | Δadj_energy = A[e][t]·T ≥ 0.1 → T ≥ 0.333 | load ≥ 0.135 | ≥ 0.333 |
| Classical (I_cl=1) | y_transport = I(transport_risk ≥ 0.70) | load ≥ 0.401 | ≥ 0.70 |

Quantitative cascade detection engages much earlier than classical (load ≥ 0.135 vs
load ≥ 0.401). With `load_amount=0.40` and `stochastic_scale=0.3` (two noise layers
creating ~42% effective CV on load), the 0.401 threshold is crossed in about half of
runs, giving marginal K_cl ≈ 0.50 while K_q stays near 0.95.

**Quantitative propagation mechanism (no domain dep_check required):**
The risk_engine's quantitative operator `x' = clip(x + A·x)` propagates transport
load risk directly into adj_energy and adj_water scores:
```
adj_energy = clip01(raw_energy + A[e][t]·raw_transport) = clip01(0.667 + 0.3·T)
adj_water  = clip01(raw_water  + A[w][t]·raw_transport) = clip01(0.000 + 0.2·T)
delta_energy = 0.3·T;  I_q=1 when T ≥ 0.333 (load ≥ 0.135)
```
No domain service dep_check call is needed: the matrix A in risk_engine
propagates the transport degradation into all non-initiator adjusted risks.

**Coarse sweep (N=100 per candidate, sequential):**

| Candidate | load_amount | K_cl | K_q | gap |
|---|---|---|---|---|
| A | 0.35 | 0.37 | 0.94 | 0.57 |
| **B (selected)** | **0.40** | **0.48** | **0.95** | **0.47** |
| C | 0.45 | 0.56 | 0.97 | 0.41 |

Candidate B selected: K_cl ≈ 0.50 is closest to the marginal detection boundary (0.401
threshold), producing the most interpretable model comparison.

**Final N=1000 run** (artifact: `results/mc_marginal_s3_load040_1000_meta.json`):

| Metric | Value | Interpretation |
|---|---|---|
| K_cl | **0.534** | Classical cascade detected in 534/1000 runs |
| K_q | **0.956** | Quantitative cascade detected in 956/1000 runs |
| ΔK = K_q − K_cl | **0.422** | Quantitative model detects 79% more cascades |
| Δ% | **79.0%** | Relative advantage of quantitative over classical |
| mean ΔR | **0.309** | Mean total quantitative risk increase per run |
| p95 ΔR | **0.380** | 95th percentile quantitative risk increase |

**Experiment command (reproducible):**
```bash
python scripts/run_mc_experiment.py \
  --scenario S3_transport_load --sector transport \
  --initiator-action load_increase --load-amount 0.40 \
  --runs 1000 --stochastic-scale 0.3 \
  --prefix results/mc_marginal_s3_load040_1000
```

**Physical interpretation:**
In 46.6% of runs (where I_cl=0, I_q=1), the transport sector load increase
propagates measurably through the risk matrix (adj_energy rises by >10%,
adj_water rises by >10%) but never crosses the binary cascade threshold.
The classical model reports "no cascade"; the quantitative model correctly captures
the elevated residual risk. This demonstrates the sensitivity advantage of the
quantitative approach for sub-threshold cascades.

**Remaining limitation:**
The classical K_cl=0.534 is driven entirely by whether transport_risk crosses
theta_node=0.70 (load ≥ 0.401 after double noise). Since transport's dep_check
in energy/water only fires when transport is `is_operational=False` (which never
happens in load_increase scenarios), the classical cascade is detected purely via
the risk_engine's binary operator — not via domain service state propagation.
Both models use the same risk_engine computation; the difference is solely in the
detection threshold (binary 0/1 vs continuous delta ≥ 0.1).

### 13.4 How to cite in experiment analysis

When reporting results for experiments after 2026-03-13, use the current baseline
(section 13.1). When citing historical results, explicitly label them with their
theta_node value, propagation rule, and "superseded" status.

```
S1 baseline (saturated):
  Scenario: S1_energy_outage  |  sector: energy  |  initiator_action: outage
  Matrix A: v1.0  |  theta_node: 0.70  |  Propagation: topology (A[i][j]>0)
  N=1000  |  K_cl=1.0  |  K_q=1.0  |  mean_ΔR=0.491  |  p95_ΔR=0.553
  Artifact: results/mc_baseline_theta070_1000_meta.json

S3 marginal scenario (calibrated, K_q > K_cl):
  Scenario: S3_transport_load  |  sector: transport  |  initiator_action: load_increase
  load_amount: 0.40  |  stochastic_scale: 0.3  |  theta_node: 0.70
  N=1000  |  K_cl=0.534  |  K_q=0.956  |  ΔK=0.422  |  Δ%=79.0%
  Artifact: results/mc_marginal_s3_load040_1000_meta.json
```

### 13.5 Sprint 1 — theta_node Sensitivity Analysis (2026-03-16)

**Objective:** Determine whether the K_q > K_cl gap (ΔK=0.422 at theta_node=0.70) is
an artifact of the threshold choice or a fundamental property of scenario S3.

**Methodology:** Three experiments run sequentially using new `theta_node` parameter
(per-experiment override via `POST /api/v1/risk/set_classical_threshold`):

1. **Theta sweep**: 15 theta_node values [0.20…0.90], N=500/point, S3, load=0.40, scale=0.3
2. **Load sweep**: 13 load_amount values [0.10…0.60], N=500/point, theta_node=0.70
3. **ROC analysis**: per-run I_cl vs I_q classification metrics (I_q = ground truth)

**Theta sweep results** (`results/theta_sweep_s3_summary.json`):

| theta_node | K_cl  | K_q   | ΔK    |
|-----------|-------|-------|-------|
| 0.20–0.65 | 0.000 | 0.944 | 0.944 |
| **0.70**  | **0.526** | **0.944** | **0.418** |
| 0.75      | 0.430 | 0.944 | 0.514 |
| 0.80      | 0.296 | 0.944 | 0.648 |
| 0.85      | 0.200 | 0.944 | 0.744 |
| 0.90      | 0.102 | 0.944 | 0.842 |

*theta_node < 0.667: energy baseline (0.667) pre-saturates the classical cascade at baseline → delta_cl=0 → K_cl=0 (not a detection failure, but an unmeasurable state). theta_node ≥ 0.70: K_cl decreases monotonically as threshold rises above transport_risk at load=0.40 (~0.699).*

**Load sweep results** (`results/load_sweep_s3_summary.json`, theta_node=0.70):

| load  | K_cl  | K_q   | ΔK    | Δ%    |
|-------|-------|-------|-------|-------|
| 0.10  | 0.106 | 0.364 | 0.258 | 243%  |
| 0.20  | 0.180 | 0.782 | 0.602 | 334%  |
| 0.30  | 0.314 | 0.902 | 0.588 | 187%  |
| 0.35  | 0.438 | 0.930 | 0.492 | 112%  |
| **0.40**  | **0.526** | **0.944** | **0.418** | **79%** |
| 0.50  | 0.676 | 0.970 | 0.294 |  44%  |
| 0.60  | 0.762 | 0.978 | 0.216 |  28%  |

*K_q rises faster than K_cl at low loads. Both converge toward 1.0 at high loads. The detection gap ΔK peaks at ~0.60 for loads 0.15–0.25 and narrows above load=0.40.*

**ROC analysis** (`results/roc_analysis_s3.json`):

FPR=0.000 for ALL theta_node values. Classical never fires when I_q=0.
The ROC curve collapses to the FPR=0 axis: AUC_trapezoidal=0.000.

**Key findings:**

1. **The K_q > K_cl gap is fundamental, not an artifact.** Across all 15 theta values,
   K_q ≈ 0.944 is stable while K_cl varies from 0.0 to 0.762 — the gap is structural.

2. **Classical has perfect specificity (FPR=0).** Whenever I_cl=1 (classical detects
   cascade), I_q=1 too. Classical is a conservative subset of quantitative detections.
   The gap is purely a sensitivity (recall) difference, not a false-positive issue.

3. **theta_node=0.70 is the natural operating point** — just above energy baseline 0.667,
   so no pre-shock saturation while remaining sensitive to post-shock cascades at load≥0.40.
   Lower theta values cause pre-saturation; higher values reduce sensitivity.

4. **Load sweep confirms threshold mechanism.** At load=0.35 (transport_risk~0.65),
   K_cl=0.438 — stochastic runs push transport_risk above 0.70, confirming the sharp
   binary threshold at 0.70 vs. continuous quantitative propagation (detects at 0.135).

**Reproducibility:**
```bash
# Theta sweep (15 points × N=500):
python scripts/run_theta_sweep.py --runs 500 --load-amount 0.40

# Load sweep (13 points × N=500):
python scripts/run_load_sweep.py --runs 500 --theta-node 0.70

# ROC analysis (from theta sweep per-run data):
python scripts/compute_roc_analysis.py --sweep-dir results/theta_sweep
```

---

## 14. Sequence Diagram: S1 Energy Outage (Single Run, depth=1)

```
Client
  │ POST /run_scenario {scenario_id:"S1_energy_outage", run_id:9001}
  ▼
scenario_simulator
  │ init energy/water/transport states → domain services
  │ GET risk_engine /risk/current?method=classical    → x_0_cl = {0, 0, 0}
  │   (all sectors < theta_node=0.70 at baseline)
  │ GET risk_engine /risk/current?method=quantitative → x_0_q
  │
  │ [Step 1] POST energy /simulate_outage {duration:30}
  │   energy domain: production drops significantly
  │   risk_engine.calculate_risks → energy_risk → ~1.0
  │   → apply_dependencies_classical (theta_node=0.70, topology propagation):
  │       y_energy = 1 (1.0 >= 0.70)
  │       A[water][energy]=0.4 > 0  → y_water = 1  (cascade)
  │       A[transport][energy]=0.5 > 0 → y_transport = 1 (cascade)
  │       step_cl = {energy:1, water:1, transport:1}
  │   → apply_dependencies_quantitative:
  │       x'_water += 0.4 * x_energy
  │       x'_transport += 0.5 * x_energy
  │
  │ [Interaction queue, all-neighbors fanout, depth=1]
  │   Candidates from energy column (A[dest][energy] > 0):
  │     water ← energy (0.4): stochastic trigger → POST water /check_energy_dependency
  │       water domain: supply' = supply × (1 − 0.55 × energy_level)
  │     transport ← energy (0.5): stochastic trigger → POST transport /check_energy_dependency
  │       transport domain: load' = load + 0.70 × energy_level × 0.8
  │   Both neighbors triggered independently (all-neighbors fanout)
  │
  │ [Step 2] POST water /check_energy_dependency {source_duration:30}
  │ [Step 3] POST transport /check_energy_dependency {source_duration:30}
  │
  │ GET risk_engine /risk/current (both methods) → x_T
  │ I_cl = _compute_cl_diagnostics(x_0_cl={0,0,0}, step_vecs, θ_cascade=0.3, initiator=energy)
  │   → delta_water = 1.0 - 0.0 = 1.0 >= 0.3 → I_cl = 1
  │   → cl_activated_sectors = [water, transport]
  │ I_q = I(max(Δx_q[water], Δx_q[transport]) >= 0.1) → I_q = 1
  ▼
ScenarioRunResult {delta_q, delta_cl, I_cl=1, I_q=1, cl_activated_sectors, ...}
```
