from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from datetime import datetime

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


# --- Scenario catalog S (control variable of the experiment) ---
# The catalog is fixed during a series of experiments to ensure comparability.
SCENARIO_CATALOG: dict[str, dict] = {
    "S1_energy_outage": {
        "description": "Отказ энергоснабжения: инициатор energy, outage 30 минут",
        "steps": [
            {"step_index": 1, "sector": "energy", "action": "outage", "params": {"duration": 30, "reason": "scenario"}},
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
            payload = {"amount": amount}
            for url in candidates:
                try:
                    resp = await client.post(url, params=q, json=payload)
                    if resp.status_code < 400:
                        return resp.json()
                except httpx.HTTPError:
                    continue
            raise HTTPException(status_code=502, detail=f"{sector} service load_increase failed")

        if action in {"adjust_production", "adjust_consumption"}:
            amount = params.get("amount", params.get("value"))
            if amount is None:
                raise HTTPException(status_code=400, detail="params.amount is required for adjust_* actions")
            endpoint = "adjust_production" if action == "adjust_production" else "adjust_consumption"
            candidates = [
                _build_url(base, f"/api/v1/{sector}/{endpoint}"),
                _build_url(base, f"/{sector}/{endpoint}"),
                _build_url(base, f"/api/v1/{endpoint}"),
                _build_url(base, f"/{endpoint}"),
            ]
            # Domain services accept amount as a query parameter.
            for url in candidates:
                try:
                    resp = await client.post(url, params={**q, "amount": amount})
                    if resp.status_code < 400:
                        return resp.json()
                except httpx.HTTPError:
                    continue
            raise HTTPException(status_code=502, detail=f"{sector} service {endpoint} failed")

    raise HTTPException(status_code=400, detail=f"Unsupported action: {action}")

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

    # If run_id is not provided, generate a reproducible-ish id for an interactive run
    # (Monte-Carlo provides run_id explicitly).
    run_id: int = int(req.run_id) if req.run_id is not None else int(datetime.utcnow().timestamp())

    # --- 1. Resolve scenario steps (catalog S or explicit) ---
    if use_catalog and (not req.steps or len(req.steps) == 0):
        if scenario_id not in SCENARIO_CATALOG:
            raise HTTPException(status_code=404, detail=f"Unknown scenario_id: {scenario_id}")
        steps = [ScenarioStep(**s) for s in SCENARIO_CATALOG[scenario_id]["steps"]]
    else:
        steps = req.steps

    steps = sorted(steps, key=lambda s: s.step_index)

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
            await _init_sector_state(sector, scenario_id, run_id)

    # --- 3. Read initial state x_0 for both methods ---
    base_cl = await fetch_risk(scenario_id, run_id, method="classical")
    base_q = await fetch_risk(scenario_id, run_id, method="quantitative")

    base_total_cl = float(base_cl.get("total_risk", 0.0))
    base_total_q = float(base_q.get("total_risk", 0.0))

    # --- 4. Apply operator F(x, s): sequential execution of steps ---
    # Mathematically: x_T = F(x_0, s)
    # For cascade indicators we track all t <= T, as in formulas I^(cl)(s,r), I^(q)(s,r).
    step_logs: list[dict] = []
    non_initiators = [s for s in ("energy", "water", "transport") if s != initiator]

    non_initiator_threshold_classical = 1.0
    delta_sector_threshold = 0.1

    classical_cascade_seen = False
    quantitative_max_delta = {s: 0.0 for s in non_initiators}

    final_cl = base_cl
    final_q = base_q

    for step in steps:
        out = await _apply_step(step, scenario_id, run_id)
        step_logs.append(out)

        # Evaluate state at each t (not only at t=T), consistent with methodology formulas.
        final_cl = await fetch_risk(scenario_id, run_id, method="classical")
        final_q = await fetch_risk(scenario_id, run_id, method="quantitative")

        if any(float(final_cl.get(f"{s}_risk", 0.0)) >= non_initiator_threshold_classical for s in non_initiators):
            classical_cascade_seen = True

        for s in non_initiators:
            delta_s = float(final_q.get(f"{s}_risk", 0.0)) - float(base_q.get(f"{s}_risk", 0.0))
            if delta_s > quantitative_max_delta[s]:
                quantitative_max_delta[s] = delta_s

    # --- 5. Final state x_T for both operators ---
    final_total_cl = float(final_cl.get("total_risk", 0.0))
    final_total_q = float(final_q.get("total_risk", 0.0))

    delta_cl = final_total_cl - base_total_cl
    delta_q = final_total_q - base_total_q

    # --- Cascade indicators (methodology-aligned) ---
    # I^(cl)(s,r) = 1 if exists non-initiator and exists t <= T with binary risk flag.
    I_cl = 1 if classical_cascade_seen else 0

    # I^(q)(s,r) = 1 if exists non-initiator with max_{t<=T}(x_{i,t} - x_{i,0}) >= delta.
    I_q = 1 if any(quantitative_max_delta[s] >= delta_sector_threshold for s in non_initiators) else 0

    # --- 6. Return both F_cl and F_q results with new fields ---
    return ScenarioRunResult(
        scenario_id=scenario_id,
        run_id=run_id,
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


async def _init_sector_state(sector: str, scenario_id: str, run_id: int) -> None:
    base = _service_base_for_sector(sector)
    # try common prefixes
    candidates = [
        _build_url(base, f"/api/v1/{sector}/init"),
        _build_url(base, f"/{sector}/init"),
        _build_url(base, "/api/v1/init"),
        _build_url(base, "/init"),
    ]
    params = {"scenario_id": scenario_id, "run_id": run_id}
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
        duration = random.randint(req.duration_min, req.duration_max)

        # Real mode (only)
        # Initialize all sector states
        await _init_sector_state("energy", req.scenario_id, run_id)
        await _init_sector_state("water", req.scenario_id, run_id)
        await _init_sector_state("transport", req.scenario_id, run_id)

        base_risk_cl = await fetch_risk(req.scenario_id, run_id, method="classical")
        base_risk_q = await fetch_risk(req.scenario_id, run_id, method="quantitative")

        base_total = float(base_risk_q.get("total_risk", 0.0))
        base_total_cl = float(base_risk_cl.get("total_risk", 0.0))

        initiator_action = getattr(req, "initiator_action", "outage")

        if initiator_action == "outage":
            step = ScenarioStep(
                step_index=1,
                sector=req.sector,
                action="outage",
                params={"duration": duration, "reason": "mc_outage"},
            )
            await _apply_step(step, req.scenario_id, run_id)

        elif initiator_action == "load_increase":
            amount = float(getattr(req, "load_amount", 0.25))
            step = ScenarioStep(
                step_index=1,
                sector=req.sector,
                action="load_increase",
                params={"amount": amount},
            )
            await _apply_step(step, req.scenario_id, run_id)

        else:
            raise HTTPException(status_code=400, detail=f"Unknown initiator_action: {initiator_action}")

        after_risk_cl = await fetch_risk(req.scenario_id, run_id, method="classical")
        after_risk_q = await fetch_risk(req.scenario_id, run_id, method="quantitative")

        after_total = float(after_risk_q.get("total_risk", 0.0))
        after_total_cl = float(after_risk_cl.get("total_risk", 0.0))

        # --- Cascade indicators ---
        initiator = req.sector
        non_initiators = [s for s in ("energy", "water", "transport") if s != initiator]

        # Classical: cascade if any non-initiator has binary risk >= threshold (usually 1.0)
        I_cl = 1 if any(
            float(after_risk_cl.get(f"{s}_risk", 0.0)) >= req.non_initiator_threshold_classical
            for s in non_initiators
        ) else 0

        # Quantitative: cascade if any non-initiator sector risk increased by at least δ
        I_q = 1 if any(
            (float(after_risk_q.get(f"{s}_risk", 0.0)) - float(base_risk_q.get(f"{s}_risk", 0.0)))
            >= req.delta_sector_threshold
            for s in non_initiators
        ) else 0

        effective_delta = after_total - base_total
        after = after_total

        deltas.append(effective_delta)

        extra = dict(
            method_cl_total_before=base_total_cl,
            method_cl_total_after=after_total_cl,
            method_q_total_before=base_total,
            method_q_total_after=after,
            I_cl=I_cl,
            I_q=I_q,
            delta_R=effective_delta,
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
    )
