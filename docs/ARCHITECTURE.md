# Architecture — Infrastructure Risk Cascade Modeling System

> **Scope**: Computational experiment platform for a master's thesis on inter-sector cascade failure modeling in critical infrastructure. All architecture notes in this document reflect the actual code state as of the date of writing.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Service Inventory](#2-service-inventory)
3. [Interaction Model](#3-interaction-model)
4. [Domain Services — State and Risk Computation](#4-domain-services--state-and-risk-computation)
5. [Risk Engine — Propagation Operators](#5-risk-engine--propagation-operators)
6. [Scenario Simulator — Experiment Execution](#6-scenario-simulator--experiment-execution)
7. [Monte Carlo Subsystem](#7-monte-carlo-subsystem)
8. [Asynchronous Messaging (RabbitMQ)](#8-asynchronous-messaging-rabbitmq)
9. [Data Layer](#9-data-layer)
10. [Reporting and Analytics](#10-reporting-and-analytics)
11. [Research Modes and Reproducibility](#11-research-modes-and-reproducibility)
12. [Known Limitations and Maturity Assessment](#12-known-limitations-and-maturity-assessment)

---

## 1. System Overview

The system implements a microservice-based platform for computational experiments studying how a failure event in one infrastructure sector (energy, water, transport) propagates across sector boundaries under two risk propagation models: a *quantitative* (continuous linear) model and a *classical* (binary rule-based) model.

The core research question is whether quantitative modeling detects cascade failures more sensitively than classical modeling, measured by the cascade frequency ratio `K_q / K_cl` and its statistical stability over Monte Carlo runs `K(N)`.

The platform is designed to run reproducible experiments under controlled conditions:
- Deterministic runs: `stochastic_scale=0.0`, same `(scenario_id, run_id)` → identical results.
- Research runs: `stochastic_scale=0.3`, produces variance required for thesis-quality `K(N)` convergence analysis.

---

## 2. Service Inventory

| Service | Port (host) | Role | Database | RabbitMQ |
|---|---|---|---|---|
| `energy_service` | 8001 | Energy sector state and risk | PostgreSQL | Publisher |
| `water_service` | 8002 | Water sector state and risk | PostgreSQL | Publisher |
| `transport_service` | 8003 | Transport sector state and risk | PostgreSQL | Publisher |
| `risk_engine` | 8004 | Risk propagation and aggregation | PostgreSQL | Publisher + Consumer |
| `scenario_simulator` | 8005 | Scenario execution and Monte Carlo | None | None |
| `reporting` | 8010 | Snapshots and summary analytics | PostgreSQL | None |
| `ingestor` | (none) | Raw event ingestion | PostgreSQL | None |
| `normalizer` | (none) | Event normalization (skeleton) | PostgreSQL | None |
| `db` | 5433 | PostgreSQL 16 | — | — |
| `rabbitmq` | 5672, 15672 | AMQP broker + management UI | — | — |

**Notes:**
- `ingestor` and `normalizer` have no exposed host ports and are not called by `scenario_simulator`.
- `scenario_simulator` has no `db` dependency; it is stateless except for an in-memory `BASELINE_VECTORS` dict.
- Docker healthchecks for application services use `curl -f http://localhost:8000/health`, but service images do not ship `curl`. This causes all 6 application services to be labeled "unhealthy" in `docker ps`, but they start and serve requests normally. The issue is non-blocking and does not affect experiment execution.

---

## 3. Interaction Model

### 3.1 Synchronous (HTTP) call graph

```
scenario_simulator (8005)
  │
  ├── POST /api/v1/energy/simulate_outage        → energy_service (8001)
  ├── POST /api/v1/water/simulate_outage         → water_service  (8002)
  ├── POST /api/v1/transport/load_increase       → transport_service (8003)
  ├── POST /api/v1/energy/init_state             → energy_service
  ├── POST /api/v1/water/init_state              → water_service
  ├── POST /api/v1/transport/init_state          → transport_service
  └── GET  /api/v1/risk/current                  → risk_engine (8004)
       │
       ├── GET /api/v1/energy/risk/current        → energy_service
       ├── GET /api/v1/water/risk/current         → water_service
       └── GET /api/v1/transport/risk/current     → transport_service

reporting (8010)
  ├── GET /api/v1/energy/status                  → energy_service
  ├── GET /api/v1/water/status                   → water_service
  ├── GET /api/v1/transport/status               → transport_service
  └── GET /api/v1/risk/current                   → risk_engine
```

### 3.2 Asynchronous (RabbitMQ) event flow

Exchange: `infrastructure_events` (topic).

```
energy_service   ──publish──► energy.state_changed   ──► risk_engine (consumer)
water_service    ──publish──► water.state_changed     ──► risk_engine (consumer)
transport_service──publish──► transport.state_changed ──► risk_engine (consumer)
risk_engine      ──publish──► risk.updated
```

`risk_engine` maintains an in-memory sector cache keyed by `(scenario_id, run_id, sector)`. On each `*.state_changed` event it recomputes the integral risk and publishes `risk.updated`. This is a fast-path that bypasses HTTP polling during event-driven scenarios.

In Monte Carlo simulations, `scenario_simulator` calls domain services synchronously and reads risk from `risk_engine` via HTTP after each step. The async path runs in parallel but is not the primary data path for Monte Carlo.

### 3.3 Dependency startup order

```
db + rabbitmq → energy_service
                energy_service → water_service
                energy_service + water_service → transport_service
                all domain services + normalizer → risk_engine
                risk_engine → scenario_simulator
                risk_engine + normalizer + scenario_simulator → reporting
```

---

## 4. Domain Services — State and Risk Computation

### 4.1 Energy service (`services/energy_service`)

**State**: `production` (MW), `consumption` (MW), `operational` flag.

**Nominal state** (after Fix #1, March 2026):
```
DEFAULT_PRODUCTION  = 1000.0 MW
DEFAULT_CONSUMPTION =  700.0 MW   # = UTILIZATION_LOW × PRODUCTION → risk₀ = 0
```

**Risk formula** (`routers/energy.py`):
```
util      = consumption / production
util_term = clip((util - UTILIZATION_LOW) / (UTILIZATION_HIGH - UTILIZATION_LOW), 0, 1)
            where UTILIZATION_LOW=0.7, UTILIZATION_HIGH=1.0

energy_risk = OUTAGE_BASE_RISK × (1 + OUTAGE_DURATION_WEIGHT × duration / MAX_OUTAGE_DURATION)
              × util_term   (if outage active)
            = 0.0           (nominal: util=0.7 → util_term=0)
```

At nominal state (`consumption=700, production=1000`): `util=0.7`, `util_term=0`, `energy_risk=0.0`. This satisfies the methodological requirement `x₀=0`.

**Key endpoints**:
- `POST /api/v1/energy/init_state` — reset to nominal
- `POST /api/v1/energy/simulate_outage` — apply outage with duration
- `GET  /api/v1/energy/risk/current` — return current `energy_risk` in [0,1]
- `GET  /api/v1/energy/status` — full state snapshot

**Persistence**: per-`(scenario_id, run_id)` rows in PostgreSQL. Each `init_state` call creates or resets the row for that key.

### 4.2 Water service (`services/water_service`)

**State**: `supply`, `demand`, `operational` flag.

**Risk formula**: degradation-based, continuous. On outage the supply drops, degradation = `max(0, demand - supply) / demand`.

**Dependency**: receives `dependency_check` steps that adjust its state based on energy outage parameters.

### 4.3 Transport service (`services/transport_service`)

**State**: current load level.

**Key actions**:
- `load_increase` — increase load by `amount` (fraction, e.g. 0.25 = 25%)
- `dependency_check` — apply cross-sector influence from source sector

**Risk proxy**: proportional to excess load above nominal.

---

## 5. Risk Engine — Propagation Operators

Source: `services/risk_engine/`

### 5.1 Dependency matrix A (v1.0)

Sectors order: `[energy, water, transport]`

```
A[i][j] = influence of sector j on sector i

         energy  water  transport
energy  [ 0.0    0.2    0.3 ]
water   [ 0.4    0.0    0.2 ]
transport[ 0.5   0.3    0.0 ]
```

Sector weights for integral risk aggregation:
```
w_energy    = 0.4
w_water     = 0.3
w_transport = 0.3
```

Both the matrix and weights are runtime-configurable via `POST /api/v1/risk/dependency_matrix` and `POST /api/v1/risk/update_weights` when `ENABLE_DYNAMIC_MATRIX=true` / `ENABLE_DYNAMIC_WEIGHTS=true`. Changes are in-memory only (lost on container restart).

### 5.2 QuantitativeOperator (`operators.py`)

One-step dynamics:
```
x_{t+1} = clip₍₀,₁₎(x_t + u_t + A · x_t)
```

where `u_t` is the external disturbance applied at this step (e.g. increase in energy risk due to outage) and `A · x_t` is the cross-sector propagation term.

Cascade detection criterion: `∃ i ≠ i₀, ∃ t > 0 : x_{i,t} - x_{i,0} ≥ δ` (default `δ = 0.1`).

### 5.3 ClassicalOperator (`operators.py`)

**Step 1 — Binarisation** (after applying disturbance):
```
ỹ_i = clip(x_i + u_i)
y_i = I(ỹ_i ≥ θ)   →  {0, 1},   θ = CLASSICAL_THRESHOLD = 0.5
```

**Step 2 — One-step cascade propagation**:
```
y_i' = y_i  OR  ∃ j ≠ i : (y_j = 1  AND  A[i][j] ≥ θ)
```

Cascade detection criterion: `∃ i ≠ i₀, ∃ t > 0 : x_{i,t}^{cl} ≥ θ_classical` (default `θ_classical = 0.3`).

### 5.4 Integral risk aggregation

```
R_t = Σᵢ w_i · x_{i,t}
```

Computed by `RiskAggregator` (`aggregator.py`).

### 5.5 calculate_risks() flow

`GET /api/v1/risk/current` or `POST /api/v1/risk/recalculate` → `calculate_risks()`:

1. **Fast-path**: if all three sectors have cache entries for `(scenario_id, run_id)`, use in-memory values.
2. **HTTP fallback**: concurrently fetch from `energy_service`, `water_service`, `transport_service` via `/risk/current` endpoints.
3. Apply chosen operator (`quantitative` or `classical`).
4. Compute integral risk via `RiskAggregator`.
5. Optionally save `RiskSnapshot` to PostgreSQL.

---

## 6. Scenario Simulator — Experiment Execution

Source: `services/scenario_simulator/routers/simulator.py`

### 6.1 Scenario catalog

Four fixed scenarios (control variable of the experiment):

| ID | Description | Steps | Initiator |
|---|---|---|---|
| `S1_energy_outage` | Energy outage, 30 min | 3 (outage + 2× dependency_check) | energy |
| `S2_water_outage` | Water outage, 30 min | 1 (outage) | water |
| `S3_transport_load` | Transport load increase +25% | 1 (load_increase) | transport |
| `S4_cyclic_transport_load` | Cyclic ±25% load, 4 half-steps | 4 (alternating load_increase) | transport |

S4 has alternating signs: steps [+0.25, -0.25, +0.25, -0.25].

### 6.2 run_scenario() — single scenario execution

`POST /api/v1/simulator/run_scenario` with `ScenarioRequest`:

```
1. Generate run_id (auto-increment or use provided)
2. init_all_sectors: POST init_state to all three domain services
3. Read baseline risk vector x₀ via risk_engine GET /current
4. Save x₀ to BASELINE_VECTORS[(scenario_id, run_id)]
5. For each step in scenario:
   a. Apply action to target domain service (outage / load_increase / dependency_check)
   b. If stochastic_scale > 0: _randomize_steps_for_run() perturbs params
   c. Record step response
   d. Collect risk vector x_t (q and cl) after each step
6. Read final risk vector x_T via risk_engine
7. Compute ΔR = R_T - R₀, I_q, I_cl indicators
8. Return ScenarioRunResult with full trajectory, delta_x vectors, both method results
```

Step actions map to domain service endpoints:
- `outage` → `POST /simulate_outage` on target sector
- `load_increase` → `POST /load_increase` on target sector
- `dependency_check` → `POST /dependency_check` on target sector
- `adjust_production` / `adjust_consumption` / `resolve_outage` → respective endpoints

### 6.3 Interaction queue (`_run_interaction_queue`)

For scenarios where the catalog includes `dependency_check` steps (S1, S2), the simulator executes a limited queue-based fanout:
- `max_depth = 1`, `max_messages = 4`
- For each non-initiating sector, posts a `dependency_check` with the source sector and duration
- Uses a stochastic matrix (`_INTERACTION_MATRIX`) for probabilistic selection under `stochastic_scale > 0`

### 6.4 State isolation

Each `run_scenario` call resets all domain services to nominal state before executing the scenario steps. This ensures that runs with different `run_id` values do not interfere. The key is `(scenario_id, run_id)`, which is passed to all domain service calls and to `risk_engine` for risk queries.

---

## 7. Monte Carlo Subsystem

Source: `services/scenario_simulator/routers/simulator.py` (`run_monte_carlo`)

`POST /api/v1/simulator/monte_carlo` with `MonteCarloRequest`.

### 7.1 Per-run pipeline

For each run `r` in `[start_run_id, start_run_id + runs - 1]`:

1. Compute `seed = hash(scenario_id + str(run_id))` (deterministic) or from `base_seed + r` if `base_seed` provided.
2. `_build_mc_steps(req, duration)` — build the step sequence for this run:
   - `outage`: 3 steps (outage + 2× dependency_check), duration sampled from `[duration_min, duration_max]`
   - `load_increase`: 1 step with `amount = load_amount × dependency_multiplier`
   - `cyclic_load`: `2 × cyclic_periods` steps with alternating ±amplitude
3. `dependency_multiplier = max(0, 1 + N(0, stochastic_scale))` — per-run noise
4. Execute the run via `run_scenario_core()` (same logic as `run_scenario`)
5. Record `MonteCarloRun` with `before`, `after`, `delta`, `duration`, cascade indicators

### 7.2 _build_mc_steps for cyclic_load

```python
steps = []
for period in range(cyclic_periods):
    noisy_amplitude = max(0.0, load_amount * dependency_multiplier)
    steps.append(ScenarioStep(action="load_increase", params={"amount": +noisy_amplitude}, ...))
    steps.append(ScenarioStep(action="load_increase", params={"amount": -noisy_amplitude}, ...))
```

Step indices are sequential starting from 1.

### 7.3 Aggregate statistics (MonteCarloResult)

```
mean_delta  = mean(deltas)
min_delta   = min(deltas)
max_delta   = max(deltas)
p95_delta   = 95th percentile of deltas

K_q  = fraction of runs where I_q = 1  (quantitative cascade detected)
K_cl = fraction of runs where I_cl = 1 (classical cascade detected)
Δ%   = (K_q - K_cl) / (K_cl + ε) × 100%   where ε = 1e-9

duration_correlation = Pearson r(duration, delta) across all runs
```

### 7.4 Calibrated parameter space for thesis experiments

Based on calibration study (sessions Jan–Mar 2026):

| Parameter | Unit-test default | Research mode |
|---|---|---|
| `stochastic_scale` | 0.0 | 0.3 |
| `duration_min` | 5 | 5 |
| `duration_max` | 60 | **30** |
| `runs` | 100 (minimum) | 300+ |

`duration_max=30` is required to avoid upper-tail ceiling saturation. With `[5,60]` and `stochastic_scale=0.3`, approximately 12% of runs hit `energy_risk=1.0` (saturation artifact); with `[5,30]` saturation is 0% and `p95_delta=0.67`.

---

## 8. Asynchronous Messaging (RabbitMQ)

Source: `shared/messaging.py` (mounted as `/app/messaging.py` in energy, water, transport, risk_engine)

### 8.1 Exchange and routing keys

```
Exchange: infrastructure_events (topic)

Routing keys:
  energy.state_changed
  water.state_changed
  transport.state_changed
  risk.updated
```

### 8.2 Event envelope schema

```json
{
  "event_type": "energy.state_changed",
  "scenario_id": "S1_energy_outage",
  "run_id": "42",
  "sector": "energy",
  "timestamp_step": 1,
  "payload": {
    "risk_level": 0.45,
    "operational": true,
    ...
  },
  "version_A": "v1.0",
  "version_w": "v1.0"
}
```

### 8.3 Dead-letter queue (DLQ)

`shared/messaging.py` configures a DLX (dead-letter exchange) and `infrastructure_events.dlq`. Messages that exceed max retry count or cause consumer exceptions are routed here. Inspectable via `GET /api/v1/risk/admin/dead-letters` (non-destructive peek using `ack_requeue_true`).

### 8.4 risk_engine consumer

On startup, `risk_engine` subscribes to `energy.state_changed`, `water.state_changed`, `transport.state_changed`. `handle_sector_event()` updates `_sector_cache[(scenario_id, run_id, sector)]` and fires `asyncio.create_task(_recompute_and_publish(...))` to recompute and publish `risk.updated`.

`scenario_simulator` and `reporting` do not subscribe to RabbitMQ. `scenario_simulator` does not publish events.

---

## 9. Data Layer

### 9.1 PostgreSQL (shared instance, `diploma` database)

All domain services and `risk_engine` use the same PostgreSQL instance (`db:5432` inside Docker, `localhost:5433` from host). Each service owns its own schema/tables.

**energy_service**: `energy_states` table — `(id, scenario_id, run_id, production, consumption, operational, calculated_at)`

**water_service**: `water_states` table — similar structure

**transport_service**: `transport_states` table — similar structure

**risk_engine**: `risk_snapshots` table — `(id, energy_risk, water_risk, transport_risk, total_risk, meta JSONB, calculated_at)`

**ingestor**: `raw_events` table in `INGESTOR_SCHEMA` — stores raw JSON event blobs

### 9.2 In-memory state (scenario_simulator)

`BASELINE_VECTORS: dict[(scenario_id, run_id), dict[str, float]]` — cached baseline `x₀` per run key. This cache is process-local and lost on container restart. It is used to avoid re-fetching the baseline on result assembly.

### 9.3 Snapshots (reporting)

`reporting` writes `SectorSnapshot` and `RiskSnapshot` records to its own tables when `GET /summary` is called. The endpoint fetches live state from domain services + risk_engine, then persists the snapshot and returns it.

---

## 10. Reporting and Analytics

Source: `services/reporting/routers/reporting.py`

**Implemented endpoints**:

| Endpoint | Description |
|---|---|
| `GET /api/v1/reporting/summary` | Fetch live sector states + risk, save snapshot |
| `GET /api/v1/reporting/risk/history` | Historical risk snapshots from DB |
| `GET /api/v1/reporting/snapshots/sectors` | Historical sector snapshots from DB |
| `GET /api/v1/reporting/snapshots/risk` | Historical risk snapshots from DB |

The `summary` endpoint is the primary entry point for external monitoring. It calls all three domain services and risk_engine in parallel, then saves a combined snapshot.

**Experiment Registry**: The `MonteCarloResult` (from `scenario_simulator`) contains all run-level data. Post-experiment persistence (writing results to a persistent experiment log) would be done via a separate `_post_experiment_registry()` call in `simulator.py`, but this path is present as a stub and not fully wired to a durable store beyond the in-memory result returned by the API.

---

## 11. Research Modes and Reproducibility

### 11.1 Deterministic mode (`stochastic_scale=0.0`)

- `dependency_multiplier = max(0, 1 + N(0, 0.0)) = 1.0` always
- Seed = `hash(scenario_id + str(run_id))` — reproducible from key alone
- Same `(scenario_id, run_id)` → identical `delta`, `I_q`, `I_cl` across all invocations
- Used by all unit tests in `tests/test_*.py`

### 11.2 Research mode (`stochastic_scale=0.3`)

- `dependency_multiplier ~ max(0, N(1, 0.3))` per run — introduces variance
- `_randomize_steps_for_run()` applies additional noise to step durations and amounts
- Required for thesis-quality `K(N)` convergence analysis
- Produces `std_delta ≈ 0.20` for S1 with calibrated `[5,30]` duration range
- **Must be stated explicitly in the methodology section** of the thesis

### 11.3 Research validation script

`services/scenario_simulator/tests/validate_mc_research.py` — standalone (not pytest):

```bash
cd services/scenario_simulator
python tests/validate_mc_research.py --runs 300 --base-url http://localhost:8005
```

Runs S1 (energy outage) and S3 (transport load) in research mode, prints:
- ΔR distribution: `mean_delta`, `std_delta`, `min_delta`, `max_delta`, `p95_delta`
- Cascade indicators: `K_q`, `K_cl`, `Δ%`
- Duration correlation
- Assessment table with pass/fail criteria

### 11.4 Matrix versioning

`DEPENDENCY_MATRIX_VERSION` (default `v1.0`) is embedded in every `RiskSnapshot.meta` and every `risk.updated` event envelope. When the matrix is updated via API, the version is auto-incremented. This allows post-hoc identification of which matrix was active for each snapshot.

---

## 12. Known Limitations and Maturity Assessment

### 12.1 Functional limitations

| Component | Status | Notes |
|---|---|---|
| energy_service | Stable | Nominal risk = 0.0 verified |
| water_service | Stable | Degradation formula functional |
| transport_service | Stable | Load_increase and cyclic_load functional |
| risk_engine | Stable | Both operators, matrix versioning, DLQ inspect |
| scenario_simulator | Stable | S1–S4, Monte Carlo, stochastic_scale, cyclic_load |
| reporting | Partial | 4 endpoints functional; no experiment registry write path |
| ingestor | Partial | `POST /ingest` stores raw events; no downstream consumer |
| normalizer | Skeleton | `POST /run` returns 0 processed; core logic not implemented |

### 12.2 Architectural constraints

**Docker healthchecks**: All 6 application service containers show as "unhealthy" in `docker ps` because the base images lack `curl`. The services are functionally healthy. Fix would require changing the healthcheck command to use Python's `urllib` or switching to `python:3.11-slim-curl`.

**scenario_simulator is stateless**: `BASELINE_VECTORS` is an in-memory dict, not persisted. Container restart between experiment steps would lose cached baselines. This is acceptable for single-session experiments but would break multi-session replay.

**Classical saturation sensitivity**: `ClassicalOperator` with `θ=0.5` binarizes energy risk. Because `A[transport][energy]=0.5 ≥ θ`, any energy failure immediately cascades to transport at the classical level. The threshold choice is a model parameter, not a bug, but it means the classical model is highly sensitive to the energy sector.

**`Δ%` overflow for K_cl=0**: When `K_cl=0` (e.g. S3 transport load), `Δ% = (K_q - 0) / (0 + 1e-9) × 100%` produces a very large number (~10¹⁰%). This is arithmetically correct but should be interpreted as "K_cl not defined for this scenario type" in the thesis. It is not a code defect.

**No horizontal scaling**: Domain services store per-`(scenario_id, run_id)` state in a shared PostgreSQL table. Multiple parallel scenario_simulator workers calling the same `(scenario_id, run_id)` would produce race conditions. Monte Carlo runs are serialized within `run_monte_carlo()` to avoid this.

**RabbitMQ async path is not the primary MC path**: During Monte Carlo, `scenario_simulator` reads risk via HTTP after each step. The RabbitMQ `risk.updated` events are published asynchronously and may arrive out of order relative to HTTP responses. The two paths do not conflict because MC uses HTTP exclusively; the async cache is used only by monitoring and `reporting`.

### 12.3 Thesis methodology alignment

The implementation satisfies the following methodological requirements:

- **R₀ = 0** at baseline: verified, `energy_risk_nominal = 0.0` with `consumption=700`
- **No classical pre-saturation**: verified, `energy_risk=0 < θ=0.5` at baseline
- **Non-degenerate ΔR variance**: verified with `stochastic_scale=0.3`, `std≈0.20`
- **K(N) convergence**: achievable with `runs≥300`, `stochastic_scale=0.3`, `duration=[5,30]`
- **Scenario reproducibility**: guaranteed by `(scenario_id, run_id)` key isolation and deterministic seed

The dependency matrix `A v1.0` and weights `{e:0.4, w:0.3, t:0.3}` are fixed model parameters that should be reported in the thesis as calibration constants with their version string `v1.0`.
