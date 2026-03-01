from fastapi import APIRouter, HTTPException, Query
from typing import Optional
import time
import hashlib
import json

import httpx
import random
import statistics
import math

from config import Settings
from utils.logging import setup_logging

from schemas import (
    MonteCarloRequest,
    MonteCarloRun,
    MonteCarloResult,
    ScenarioStep,
    ScenarioRequest,
    ScenarioRunResult,
    ScenarioCatalog,
    CatalogScenario,
)

logger = setup_logging()
settings = Settings()
router = APIRouter(prefix="/api/v1/simulator", tags=["simulator"])

# Baseline vectors x0 cached per experimental key (scenario_id, run_id).
BASELINE_VECTORS: dict[tuple[str, int], dict[str, float]] = {}


# --- Scenario catalog S (control variable of the experiment) ---
# The catalog is fixed during a series of experiments to ensure comparability.
SCENARIO_CATALOG: dict[str, dict] = {
    "S1_energy_outage": {
        "description": "Отказ энергоснабжения: инициатор energy, outage 30 минут",
        "steps": [
            {"step_index": 1, "sector": "energy", "action": "outage", "params": {"duration": 30, "reason": "scenario"}},
            {"step_index": 2, "sector": "water", "action": "dependency_check", "params": {"source_sector": "energy", "source_duration": 30}},
            {"step_index": 3, "sector": "transport", "action": "dependency_check", "params": {"source_sector": "energy", "source_duration": 30}},
        ],
    },
    "S2_water_outage": {
        "description": "Отказ водоснабжения: инициатор water, outage 30 минут",
        "steps": [
            {"step_index": 1, "sector": "water", "action": "outage", "params": {"duration": 30, "reason": "scenario"}},
        ],
    },
    "S3_transport_load": {
        "description": "Рост нагрузки транспорта: инициатор transport, load_increase (amount)",
        "steps": [
            {"step_index": 1, "sector": "transport", "action": "load_increase", "params": {"amount": 0.25}},
        ],
    },
}


async def fetch_risk(
    scenario_id: str | None = None,
    run_id: int | None = None,
    method: str | None = None,
) -> dict:
    """Забирает текущий интегральный риск из risk_engine.

    Если указаны scenario_id и run_id, риск запрашивается для конкретного прогона (s,r),
    что необходимо для независимости сценариев и прогонов Monte Carlo.
    """
    base = settings.RISK_ENGINE_URL.rstrip("/")
    # Expected base: http://risk_engine:8000/api/v1
    if base.endswith("/api/v1"):
        url = f"{base}/risk/current"
    elif base.endswith("/api/v1/risk"):
        url = f"{base}/current"
    else:
        # Fallback for legacy configs
        url = f"{base}/api/v1/risk/current"

    params = {}
    if scenario_id is not None:
        params["scenario_id"] = scenario_id
    if run_id is not None:
        params["run_id"] = run_id
    if method is not None:
        params["method"] = method

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as e:
        logger.error(f"❌ Failed to fetch risk from {url}: {e}")
        raise HTTPException(status_code=502, detail="Risk engine is unavailable")


# --- Helper: fetch dependency matrix meta (version, order) from risk_engine ---
async def fetch_dependency_matrix_meta() -> dict:
    """Fetch dependency matrix metadata (version, order) from risk_engine."""
    base = settings.RISK_ENGINE_URL.rstrip("/")
    if base.endswith("/api/v1"):
        url = f"{base}/risk/dependency_matrix"
    elif base.endswith("/api/v1/risk"):
        url = f"{base}/dependency_matrix"
    else:
        url = f"{base}/api/v1/risk/dependency_matrix"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as e:
        logger.warning(f"⚠️ Failed to fetch dependency matrix meta from {url}: {e}")
        return {}

async def _apply_step(step: ScenarioStep, scenario_id: str, run_id: int) -> dict:
    """Apply one ScenarioStep to a domain microservice.

    Contract: every call is tagged with (scenario_id, run_id, step_index, action)
    to guarantee state isolation and reproducibility.
    """
    sector = step.sector
    action = step.action
    params = dict(step.params or {})
    base = _service_base_for_sector(sector)

    q = {
        "scenario_id": scenario_id,
        "run_id": run_id,
        "step_index": step.step_index,
        "action": action,
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        if action == "outage":
            duration = int(params.get("duration", 10))
            reason = str(params.get("reason", "scenario"))
            candidates = [
                _build_url(base, f"/api/v1/{sector}/simulate_outage"),
                _build_url(base, f"/{sector}/simulate_outage"),
                _build_url(base, "/api/v1/simulate_outage"),
                _build_url(base, "/simulate_outage"),
            ]
            payload = {"reason": reason, "duration": duration}
            for url in candidates:
                try:
                    resp = await client.post(url, params=q, json=payload)
                    if resp.status_code < 400:
                        return resp.json()
                except httpx.HTTPError:
                    continue
            raise HTTPException(status_code=502, detail=f"{sector} service outage failed")

        if action == "dependency_check":
            source_sector = str(params.get("source_sector", "energy")).strip().lower()
            if source_sector not in {"energy", "water", "transport"}:
                raise HTTPException(status_code=400, detail=f"Unsupported source_sector for dependency_check: {source_sector}")

            source_duration = int(params.get("source_duration", 0))
            source_degradation = float(params.get("source_degradation", 0.0))

            candidates = [
                _build_url(base, f"/api/v1/{sector}/check_{source_sector}_dependency"),
                _build_url(base, f"/{sector}/check_{source_sector}_dependency"),
                _build_url(base, f"/api/v1/check_{source_sector}_dependency"),
                _build_url(base, f"/check_{source_sector}_dependency"),
            ]

            for url in candidates:
                try:
                    resp = await client.post(
                        url,
                        params={
                            **q,
                            "source_duration": source_duration,
                            "source_degradation": source_degradation,
                        },
                    )
                    if resp.status_code < 400:
                        return resp.json()
                except httpx.HTTPError:
                    continue
            raise HTTPException(status_code=502, detail=f"{sector} service dependency_check failed for source={source_sector}")

        if action == "resolve_outage":
            candidates = [
                _build_url(base, f"/api/v1/{sector}/resolve_outage"),
                _build_url(base, f"/{sector}/resolve_outage"),
                _build_url(base, "/api/v1/resolve_outage"),
                _build_url(base, "/resolve_outage"),
            ]
            for url in candidates:
                try:
                    resp = await client.post(url, params=q)
                    if resp.status_code < 400:
                        return resp.json()
                except httpx.HTTPError:
                    continue
            raise HTTPException(status_code=502, detail=f"{sector} service resolve_outage failed")

        if action == "load_increase":
            amount = float(params.get("amount", 0.1))
            candidates = [
                _build_url(base, f"/api/v1/{sector}/increase_load"),
                _build_url(base, f"/{sector}/increase_load"),
                _build_url(base, "/api/v1/increase_load"),
                _build_url(base, "/increase_load"),
                _build_url(base, f"/api/v1/{sector}/update_load"),
                _build_url(base, f"/{sector}/update_load"),
            ]
            for url in candidates:
                try:
                    if url.endswith("update_load"):
                        # Fallback for services that only support absolute load update
                        resp = await client.post(url, params=q, json={"load": amount})
                    else:
                        # Primary contract for load_increase: query param amount
                        resp = await client.post(url, params={**q, "amount": amount})
                    if resp.status_code < 400:
                        return resp.json()
                except httpx.HTTPError:
                    continue
            raise HTTPException(status_code=502, detail=f"{sector} service load_increase failed")

        if action in {"adjust_production", "adjust_consumption"}:
            value = params.get("value")
            if value is None:
                raise HTTPException(status_code=400, detail="params.value is required for adjust_* actions")
            endpoint = "adjust_production" if action == "adjust_production" else "adjust_consumption"
            candidates = [
                _build_url(base, f"/api/v1/{sector}/{endpoint}"),
                _build_url(base, f"/{sector}/{endpoint}"),
                _build_url(base, f"/api/v1/{endpoint}"),
                _build_url(base, f"/{endpoint}"),
            ]
            # Many services accept the value as query param
            for url in candidates:
                try:
                    resp = await client.post(url, params={**q, "value": value})
                    if resp.status_code < 400:
                        return resp.json()
                except httpx.HTTPError:
                    continue
            raise HTTPException(status_code=502, detail=f"{sector} service {endpoint} failed")

    raise HTTPException(status_code=400, detail=f"Unsupported action: {action}")


def _generate_run_id() -> int:
    """Generate unique run_id for ad-hoc/manual invocations.

    Uses nanosecond clock + random suffix to avoid collisions between close requests.
    """
    return int(f"{time.time_ns()}{random.randint(100, 999)}")


def _derive_seed(scenario_id: str, run_id: int, explicit_seed: int | None = None) -> int:
    if explicit_seed is not None:
        return int(explicit_seed)
    digest = hashlib.sha256(f"{scenario_id}:{run_id}".encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _cache_key_for_run(
    *,
    scenario_id: str,
    method: str,
    duration: int | None,
    theta: float,
    delta_threshold: float,
    matrix_A_version: str | None,
    weights_version: str | None,
    run_id: int,
    seed: int,
) -> str:
    return "|".join(
        [
            f"scenario={scenario_id}",
            f"method={method}",
            f"duration={duration if duration is not None else 'na'}",
            f"theta={theta:.6f}",
            f"delta_threshold={delta_threshold:.6f}",
            f"A={matrix_A_version or 'na'}",
            f"w={weights_version or 'na'}",
            f"run_id={run_id}",
            f"seed={seed}",
        ]
    )


def _x0_hash(base_vec: dict[str, float]) -> str:
    payload = json.dumps(base_vec, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _randomize_steps_for_run(
    *,
    steps: list[ScenarioStep],
    rng: random.Random,
    stochastic_scale: float,
) -> tuple[list[ScenarioStep], dict[str, float]]:
    if stochastic_scale <= 0.0:
        return steps, {}

    effective: dict[str, float] = {}
    randomized_steps: list[ScenarioStep] = []
    for step in steps:
        params = dict(step.params or {})
        if step.action in {"outage", "dependency_check"} and "source_duration" in params:
            src = max(1.0, float(params.get("source_duration", 1.0)))
            noise = rng.gauss(0.0, stochastic_scale)
            params["source_duration"] = max(1, int(round(src * (1.0 + noise))))
            effective[f"step_{step.step_index}_source_duration"] = float(params["source_duration"])
        if step.action == "outage" and "duration" in params:
            base_duration = max(1.0, float(params.get("duration", 1.0)))
            noise = rng.gauss(0.0, stochastic_scale)
            params["duration"] = max(1, int(round(base_duration * (1.0 + noise))))
            effective[f"step_{step.step_index}_duration"] = float(params["duration"])
        if step.action == "load_increase" and "amount" in params:
            base_amount = max(0.0, float(params.get("amount", 0.0)))
            noise = rng.gauss(0.0, stochastic_scale)
            params["amount"] = max(0.0, base_amount * (1.0 + noise))
            effective[f"step_{step.step_index}_amount"] = float(params["amount"])
        randomized_steps.append(
            ScenarioStep(
                step_index=step.step_index,
                sector=step.sector,
                action=step.action,
                params=params,
            )
        )
    return randomized_steps, effective

@router.get("/catalog", response_model=ScenarioCatalog)
async def get_scenario_catalog() -> ScenarioCatalog:
    scenarios: list[CatalogScenario] = []
    for sid, meta in SCENARIO_CATALOG.items():
        steps = [ScenarioStep(**st) for st in meta.get("steps", [])]
        scenarios.append(
            CatalogScenario(
                scenario_id=sid,
                description=meta.get("description", ""),
                steps=steps,
            )
        )
    return ScenarioCatalog(scenarios=scenarios)


@router.post("/run_scenario", response_model=ScenarioRunResult)
async def run_scenario(
    req: ScenarioRequest,
    use_catalog: bool = Query(
        default=True,
        description="Если true и steps пустой, используется SCENARIO_CATALOG[scenario_id]",
    ),
) -> ScenarioRunResult:
    scenario_id = req.scenario_id

    # Never reuse run_id across independent calls: for manual run_scenario
    # generate a high-entropy identifier.
    run_id: int = int(req.run_id) if req.run_id is not None else _generate_run_id()

    # --- 1. Resolve scenario steps (catalog S or explicit) ---
    if use_catalog and (not req.steps or len(req.steps) == 0):
        if scenario_id not in SCENARIO_CATALOG:
            raise HTTPException(status_code=404, detail=f"Unknown scenario_id: {scenario_id}")
        steps = [ScenarioStep(**s) for s in SCENARIO_CATALOG[scenario_id]["steps"]]
    else:
        steps = req.steps

    steps = sorted(steps, key=lambda s: s.step_index)
    seed = _derive_seed(scenario_id, run_id, req.seed)
    rng = random.Random(seed)
    steps, randomized_params = _randomize_steps_for_run(
        steps=steps,
        rng=rng,
        stochastic_scale=float(req.stochastic_scale),
    )

    # Initiator i0 is defined by the first step's sector
    if not steps:
        raise HTTPException(status_code=400, detail="Scenario has no steps")
    initiator = steps[0].sector
    if initiator not in {"energy", "water", "transport"}:
        raise HTTPException(status_code=400, detail=f"Unknown initiator sector: {initiator}")

    # Fetch model versions for reproducibility (best-effort)
    dm_meta = await fetch_dependency_matrix_meta()
    matrix_A_version: Optional[str] = dm_meta.get("version") if isinstance(dm_meta, dict) else None

    # Weights version is not yet versioned in risk_engine; keep as None for now
    weights_version: Optional[str] = None

    # --- 2. Initialise state x_0 for all sectors if requested ---
    if req.init_all_sectors:
        for sector in ("energy", "water", "transport"):
            await _init_sector_state(sector, scenario_id, run_id, force=True)

    # --- 3. Read initial state x_0 for both methods ---
    base_cl = await fetch_risk(scenario_id, run_id, method="classical")
    base_q = await fetch_risk(scenario_id, run_id, method="quantitative")
    base_vec_cl = dict(_sector_risk_vector(base_cl))
    base_vec_q = dict(_sector_risk_vector(base_q))
    BASELINE_VECTORS[(scenario_id, run_id)] = dict(base_vec_q)
    x0_hash = _x0_hash(base_vec_q)

    base_total_cl = float(base_cl.get("total_risk", 0.0))
    base_total_q = float(base_q.get("total_risk", 0.0))
    non_initiators = [s for s in ("energy", "water", "transport") if s != initiator]

    # --- 4. Apply operator F(x, s): sequential execution of steps ---
    # Mathematically: x_T = F(x_0, s)
    step_logs: list[dict] = []
    theta_classical = float(req.theta_classical)
    step_vectors_cl: list[dict[str, float]] = []
    for step in steps:
        out = await _apply_step(step, scenario_id, run_id)

        # Methodological rule for classical mode:
        # y_i,t = I(Δx_i,t >= θ), I_cl = 1 if ∃ t for any non-initiator i != i0.
        step_cl = await fetch_risk(scenario_id, run_id, method="classical")
        step_delta_cl = _vector_delta(_sector_risk_vector(step_cl), base_vec_cl)
        step_vectors_cl.append(_sector_risk_vector(step_cl))
        step_I_cl = 1 if any(float(step_delta_cl.get(s, 0.0)) >= theta_classical for s in non_initiators) else 0

        out["step_I_cl"] = step_I_cl
        out["step_delta_x_cl"] = step_delta_cl
        step_logs.append(out)

    # --- 5. Read final state x_T for both operators ---
    final_cl = await fetch_risk(scenario_id, run_id, method="classical")
    final_q = await fetch_risk(scenario_id, run_id, method="quantitative")

    final_total_cl = float(final_cl.get("total_risk", 0.0))
    final_total_q = float(final_q.get("total_risk", 0.0))
    final_vec_cl = _sector_risk_vector(final_cl)
    final_vec_q = _sector_risk_vector(final_q)
    delta_vec_cl = _vector_delta(final_vec_cl, base_vec_cl)
    delta_vec_q = _vector_delta(final_vec_q, base_vec_q)

    delta_cl = final_total_cl - base_total_cl
    delta_q = final_total_q - base_total_q

    # --- Cascade indicators (methodology-aligned) ---
    I_cl = compute_I_cl_over_steps(base_vec_cl, step_vectors_cl, theta_classical, initiator)

    # Quantitative: cascade if any non-initiator increased by at least δ
    delta_sector_threshold = 0.1
    I_q = 1 if any(float(delta_vec_q.get(s, 0.0)) >= delta_sector_threshold for s in non_initiators) else 0

    cache_key = _cache_key_for_run(
        scenario_id=scenario_id,
        method="both",
        duration=max((int(st.params.get("duration", 0)) for st in steps if "duration" in (st.params or {})), default=0),
        theta=theta_classical,
        delta_threshold=delta_sector_threshold,
        matrix_A_version=matrix_A_version,
        weights_version=weights_version,
        run_id=run_id,
        seed=seed,
    )
    logger.info(
        "🧪 run diagnostics: scenario_id=%s run_id=%s seed=%s x0_hash=%s cache_key=%s cache_hit=%s randomized_params=%s",
        scenario_id,
        run_id,
        seed,
        x0_hash,
        cache_key,
        False,
        randomized_params,
    )

    # --- 6. Return both F_cl and F_q results with new fields ---
    return ScenarioRunResult(
        scenario_id=scenario_id,
        run_id=run_id,
        seed=seed,
        cache_key=cache_key,
        cache_hit=False,
        randomized_params=randomized_params or None,
        x0_hash=x0_hash,
        initiator=initiator,
        matrix_A_version=matrix_A_version,
        weights_version=weights_version,
        before=base_total_q,
        after=final_total_q,
        delta=delta_q,
        steps=step_logs,
        method_cl_total_before=base_total_cl,
        method_cl_total_after=final_total_cl,
        method_q_total_before=base_total_q,
        method_q_total_after=final_total_q,
        delta_cl=delta_cl,
        delta_q=delta_q,
        I_cl=I_cl,
        I_q=I_q,
        baseline_x0=base_vec_q,
        before_vec_q=base_vec_q,
        after_vec_q=final_vec_q,
        delta_vec_q=delta_vec_q,
        before_vec_cl=base_vec_cl,
        after_vec_cl=final_vec_cl,
        delta_vec_cl=delta_vec_cl,
        delta_x_q=delta_vec_q,
        delta_x_cl=delta_vec_cl,
        theta_classical=theta_classical,
        delta_sector_threshold=delta_sector_threshold,
    )


def _service_base_for_sector(sector: str) -> str:
    s = sector.strip().lower()
    if s == "energy":
        return settings.ENERGY_SERVICE_URL.rstrip("/")
    if s == "water":
        return settings.WATER_SERVICE_URL.rstrip("/")
    if s == "transport":
        return settings.TRANSPORT_SERVICE_URL.rstrip("/")
    raise HTTPException(status_code=400, detail=f"Unknown sector: {sector}")


def _build_url(base: str, path: str) -> str:
    # base can be either http://host:port or include /api/v1/<sector>
    b = base.rstrip("/")
    p = path if path.startswith("/") else f"/{path}"
    return f"{b}{p}"


def _sector_risk_vector(risk_payload: dict) -> dict[str, float]:
    return {
        "energy": float(risk_payload.get("energy_risk", 0.0)),
        "water": float(risk_payload.get("water_risk", 0.0)),
        "transport": float(risk_payload.get("transport_risk", 0.0)),
    }


def outage_impact_from_duration(duration: int, max_duration: int) -> float:
    """Monotonic outage impact in [0,1] without centering."""
    if max_duration <= 0:
        return 0.0
    return max(0.0, min(1.0, float(duration) / float(max_duration)))


def _vector_delta(final_vec: dict[str, float], base_vec: dict[str, float]) -> dict[str, float]:
    return {
        "energy": float(final_vec.get("energy", 0.0)) - float(base_vec.get("energy", 0.0)),
        "water": float(final_vec.get("water", 0.0)) - float(base_vec.get("water", 0.0)),
        "transport": float(final_vec.get("transport", 0.0)) - float(base_vec.get("transport", 0.0)),
    }




def compute_I_cl_over_steps(
    base_vec: dict[str, float],
    step_vecs: list[dict[str, float]],
    theta: float,
    initiator: str,
) -> int:
    non_initiators = [s for s in ("energy", "water", "transport") if s != initiator]
    for step_vec in step_vecs:
        delta = _vector_delta(step_vec, base_vec)
        if any(float(delta.get(s, 0.0)) >= theta for s in non_initiators):
            return 1
    return 0


def compute_duration_delta_correlation(durations: list[int], deltas: list[float]) -> float | None:
    if len(durations) < 2 or len(set(durations)) <= 1:
        return None
    try:
        return float(statistics.correlation(durations, deltas))
    except Exception:
        return None


def _build_mc_steps(req: MonteCarloRequest, duration: int, dependency_multiplier: float = 1.0) -> list[ScenarioStep]:
    """Build MC steps so each run is executed by the same scenario executor as run_scenario."""
    initiator_action = getattr(req, "initiator_action", "outage")

    if initiator_action == "outage":
        outage_duration = max(1, int(round(duration * dependency_multiplier)))
        if req.sector == "energy":
            return [
                ScenarioStep(
                    step_index=1,
                    sector="energy",
                    action="outage",
                    params={"duration": outage_duration, "reason": "mc_outage"},
                ),
                ScenarioStep(
                    step_index=2,
                    sector="water",
                    action="dependency_check",
                    params={"source_sector": "energy", "source_duration": outage_duration},
                ),
                ScenarioStep(
                    step_index=3,
                    sector="transport",
                    action="dependency_check",
                    params={"source_sector": "energy", "source_duration": outage_duration},
                ),
            ]

        return [
            ScenarioStep(
                step_index=1,
                sector=req.sector,
                action="outage",
                params={"duration": outage_duration, "reason": "mc_outage"},
            ),
        ]

    if initiator_action == "load_increase":
        amount = float(getattr(req, "load_amount", 0.25))
        noisy_amount = max(0.0, amount * dependency_multiplier)
        return [
            ScenarioStep(
                step_index=1,
                sector=req.sector,
                action="load_increase",
                params={"amount": noisy_amount},
            ),
        ]

    raise HTTPException(status_code=400, detail=f"Unknown initiator_action: {initiator_action}")


async def _init_sector_state(sector: str, scenario_id: str, run_id: int, force: bool = False) -> None:
    base = _service_base_for_sector(sector)
    # try common prefixes
    candidates = [
        _build_url(base, f"/api/v1/{sector}/init"),
        _build_url(base, f"/{sector}/init"),
        _build_url(base, "/api/v1/init"),
        _build_url(base, "/init"),
    ]
    params = {"scenario_id": scenario_id, "run_id": run_id, "force": str(force).lower()}
    async with httpx.AsyncClient(timeout=10.0) as client:
        last_exc = None
        for url in candidates:
            try:
                resp = await client.post(url, params=params)
                if resp.status_code < 400:
                    return
            except httpx.HTTPError as e:
                last_exc = e
        logger.error(f"❌ Failed to init sector={sector} via any known init endpoint")
        if last_exc:
            raise HTTPException(status_code=502, detail=f"{sector} service init failed")
        raise HTTPException(status_code=502, detail=f"{sector} service init failed")



async def _simulate_outage(sector: str, duration: int, scenario_id: str, run_id: int, step_index: int) -> dict:
    base = _service_base_for_sector(sector)
    candidates = [
        _build_url(base, f"/api/v1/{sector}/simulate_outage"),
        _build_url(base, f"/{sector}/simulate_outage"),
        _build_url(base, "/api/v1/simulate_outage"),
        _build_url(base, "/simulate_outage"),
    ]
    params = {
        "scenario_id": scenario_id,
        "run_id": run_id,
        "step_index": step_index,
        "action": "outage",
    }
    payload = {"reason": "mc_outage", "duration": duration}
    async with httpx.AsyncClient(timeout=10.0) as client:
        for url in candidates:
            try:
                resp = await client.post(url, params=params, json=payload)
                if resp.status_code < 400:
                    return resp.json()
            except httpx.HTTPError:
                continue
    logger.error(f"❌ Failed to simulate outage for sector={sector}")
    raise HTTPException(status_code=502, detail=f"{sector} service outage failed")


# --- Experiment Registry helper ---
async def _post_experiment_registry(payload: dict) -> None:
    """Send experiment summary to reporting service (Experiment Registry).

    This must never break Monte-Carlo execution: failures are logged as warnings.
    """
    base = getattr(settings, "REPORTING_SERVICE_URL", None)
    if not base:
        logger.warning("⚠️ REPORTING_SERVICE_URL is not set; skipping experiment registry export")
        return

    url = base.rstrip("/") + "/experiments/register"

    try:
        def _sanitize_json(obj):
            if isinstance(obj, float):
                return obj if math.isfinite(obj) else 0.0
            if isinstance(obj, dict):
                return {k: _sanitize_json(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_sanitize_json(v) for v in obj]
            return obj

        payload = _sanitize_json(payload)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code >= 400:
                logger.warning(f"⚠️ Reporting registry rejected payload: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.warning(f"⚠️ Experiment registry export failed: {e}")


@router.post("/monte_carlo", response_model=MonteCarloResult)
async def run_monte_carlo(req: MonteCarloRequest):
    """Моделирует серию прогонов сценария методом Монте‑Карло.

    В публичном API поддерживается только режим `real` (вычислительный эксперимент через микросервисы).

    Для каждого прогона r формируется ключ (scenario_id, run_id), инициализируются доменные сервисы,
    выполняется инициирующее воздействие, после чего дважды запрашивается риск из risk_engine:
    - method=classical
    - method=quantitative

    Далее вычисляются индикаторы выявления каскада I_cl и I_q и агрегированные метрики K^(cl), K^(q), Δ%.
    """

    if req.duration_max < req.duration_min:
        raise HTTPException(status_code=400, detail="duration_max must be >= duration_min")

    if req.runs < 100:
        raise HTTPException(
            status_code=400,
            detail="For stable K(N) and quantile comparison use runs >= 100 (recommended 300+)",
        )

    logger.info(
        f"🎲 Monte-Carlo start: scenario_id={req.scenario_id}, mode={req.mode}, sector={req.sector}, runs={req.runs}, "
        f"duration=[{req.duration_min}, {req.duration_max}]"
    )

    # Public API: only real mode is supported
    if req.mode != "real":
        raise HTTPException(status_code=400, detail="Only mode=real is supported in public API")

    # base_total = None  # will be fetched per run after init

    runs_data: list[MonteCarloRun] = []
    deltas: list[float] = []

    for i in range(1, req.runs + 1):
        # методологически: r = start_run_id..start_run_id+runs-1
        run_id = int(req.start_run_id) + (i - 1)
        seed = _derive_seed(req.scenario_id, run_id, req.base_seed + i - 1 if req.base_seed is not None else None)
        rng = random.Random(seed)
        duration = rng.randint(req.duration_min, req.duration_max)
        dependency_multiplier = 1.0
        if float(getattr(req, "stochastic_scale", 0.0)) > 0.0:
            noise = rng.gauss(0.0, float(req.stochastic_scale))
            dependency_multiplier = max(0.0, 1.0 + noise)

        steps = _build_mc_steps(req, duration, dependency_multiplier=dependency_multiplier)
        scenario_res = await run_scenario(
            ScenarioRequest(
                scenario_id=req.scenario_id,
                run_id=run_id,
                seed=seed,
                method="both",
                steps=steps,
                init_all_sectors=True,
                theta_classical=req.theta_classical,
                stochastic_scale=req.stochastic_scale,
            ),
            use_catalog=False,
        )

        base_total = float(scenario_res.before)
        after = float(scenario_res.after)
        effective_delta = float(scenario_res.delta)
        base_total_cl = float(scenario_res.method_cl_total_before or 0.0)
        after_total_cl = float(scenario_res.method_cl_total_after or 0.0)
        base_vec_q = dict(scenario_res.before_vec_q or {})
        after_vec_q = dict(scenario_res.after_vec_q or {})
        delta_vec_q = dict(scenario_res.delta_vec_q or {})
        base_vec_cl = dict(scenario_res.before_vec_cl or {})
        after_vec_cl = dict(scenario_res.after_vec_cl or {})
        delta_vec_cl = dict(scenario_res.delta_vec_cl or {})
        I_cl = int(scenario_res.I_cl or 0)
        I_q = int(scenario_res.I_q or 0)

        deltas.append(effective_delta)

        extra = dict(
            method_cl_total_before=base_total_cl,
            method_cl_total_after=after_total_cl,
            method_q_total_before=base_total,
            method_q_total_after=after,
            I_cl=I_cl,
            I_q=I_q,
            delta_R=effective_delta,
            before_vec_q=base_vec_q,
            after_vec_q=after_vec_q,
            delta_vec_q=delta_vec_q,
            before_vec_cl=base_vec_cl,
            after_vec_cl=after_vec_cl,
            delta_vec_cl=delta_vec_cl,
            theta_classical=req.theta_classical,
            delta_sector_threshold=req.delta_sector_threshold,
            seed=scenario_res.seed,
            cache_key=scenario_res.cache_key,
            cache_hit=scenario_res.cache_hit,
            randomized_params=scenario_res.randomized_params,
            x0_hash=scenario_res.x0_hash,
        )

        runs_data.append(
            MonteCarloRun(
                scenario_id=req.scenario_id,
                run_id=run_id,
                run=i,
                before=base_total,
                after=after,
                delta=effective_delta,
                duration=duration,
                **extra,
            )
        )

        logger.debug(
            f"🎲 Monte-Carlo run={i}: duration={duration}, before={float(base_total):.3f}, after={float(after):.3f}, Δ={float(effective_delta):.3f}"
        )

    if not deltas:
        raise HTTPException(status_code=500, detail="No Monte-Carlo runs executed")

    icl = [r.I_cl for r in runs_data if r.I_cl is not None]
    iq = [r.I_q for r in runs_data if r.I_q is not None]

    K_cl = float(statistics.fmean(icl)) if icl else 0.0
    K_q = float(statistics.fmean(iq)) if iq else 0.0

    # Δ% must be JSON-compliant (no inf/NaN). When K_cl == 0, use an epsilon-denominator.
    eps = 1e-9
    denom = K_cl if K_cl > 0 else eps
    Delta_percent = float((K_q - K_cl) / denom * 100.0)
    if not math.isfinite(Delta_percent):
        Delta_percent = 0.0

    mean_delta = float(statistics.fmean(deltas))
    min_delta = float(min(deltas))
    max_delta = float(max(deltas))

    sorted_deltas = sorted(deltas)
    idx_95 = max(0, int(0.95 * (len(sorted_deltas) - 1)))
    p95_delta = float(sorted_deltas[idx_95])

    logger.info(
        f"🎲 Monte-Carlo done: meanΔ={mean_delta:.4f}, minΔ={min_delta:.4f}, "
        f"maxΔ={max_delta:.4f}, p95Δ={p95_delta:.4f}"
    )

    std_delta = float(statistics.pstdev(deltas)) if len(deltas) > 1 else 0.0
    if std_delta == 0.0:
        logger.warning("⚠️ ΔR has zero variance; check duration influence / saturation")
    duration_correlation = compute_duration_delta_correlation([r.duration for r in runs_data], deltas)

    # --- Experiment Registry export (reporting service) ---
    payload = {
        "scenario_id": req.scenario_id,
        "n_runs": req.runs,
        "delta_threshold": req.delta_sector_threshold,
        "matrix_A_version": getattr(req, "matrix_A_version", None),
        "weights_version": getattr(req, "weights_version", None),
        "git_commit": getattr(req, "git_commit", None),
        "K_cl": K_cl,
        "K_q": K_q,
        "Delta_percent": Delta_percent,
        "distributions": {
            "delta_R": [float(r.delta_R) for r in runs_data if r.delta_R is not None],
            "I_cl": [int(r.I_cl) for r in runs_data if r.I_cl is not None],
            "I_q": [int(r.I_q) for r in runs_data if r.I_q is not None],
        },
        "runs": [
            {
                "scenario_id": r.scenario_id,
                "run_id": r.run_id,
                "run": r.run,
                "before": r.before,
                "after": r.after,
                "delta": r.delta,
                "delta_R": r.delta_R,
                "duration": r.duration,
                "method_cl_total_before": r.method_cl_total_before,
                "method_cl_total_after": r.method_cl_total_after,
                "method_q_total_before": r.method_q_total_before,
                "method_q_total_after": r.method_q_total_after,
                "I_cl": r.I_cl,
                "I_q": r.I_q,
                "initiator": req.sector,
            }
            for r in runs_data
        ],
    }

    await _post_experiment_registry(payload)

    return MonteCarloResult(
        scenario_id=req.scenario_id,
        mode=req.mode,
        sector=req.sector,
        runs=req.runs,
        mean_delta=mean_delta,
        min_delta=min_delta,
        max_delta=max_delta,
        p95_delta=p95_delta,
        K_cl=K_cl,
        K_q=K_q,
        Delta_percent=Delta_percent,
        runs_data=runs_data,
        theta_classical=req.theta_classical,
        delta_sector_threshold=req.delta_sector_threshold,
        duration_correlation=duration_correlation,
    )
