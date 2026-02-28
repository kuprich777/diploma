# services/reporting/routers/reporting.py

import csv
from datetime import datetime
from pathlib import Path

import httpx
import matplotlib
import numpy as np
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import desc
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models import (
    SectorStatusSnapshot,
    RiskOverviewSnapshot,
    Experiment,
    ExperimentRun,
    ExperimentResult,
)
from schemas import (
    ReportingSummary,
    SectorState,
    RiskSummary,
    RiskHistoryResponse,
    RiskHistoryItem,
    SectorStatusSnapshotOut,
    RiskOverviewSnapshotOut,
    SnapshotListResponse,
    ExperimentRegisterIn,
    ExperimentRegisterOut,
)
from utils.logging import setup_logging

matplotlib.use("Agg")
import matplotlib.pyplot as plt

logger = setup_logging()

router = APIRouter(prefix="/api/v1/reporting", tags=["reporting"])


def _safe_float(value: float | int | None) -> float:
    if value is None:
        return 0.0
    try:
        val = float(value)
        if np.isnan(val) or np.isinf(val):
            return 0.0
        return val
    except (TypeError, ValueError):
        return 0.0


def _mk_report_dir() -> Path:
    root = Path(settings.REPORTS_DIR)
    root.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%m%d-%H%M")
    report_dir = root / stamp
    if report_dir.exists():
        report_dir = root / datetime.now().strftime("%m%d-%H%M%S")

    report_dir.mkdir(parents=True, exist_ok=False)
    return report_dir


def _save_csv_summary(report_dir: Path, payload: ExperimentRegisterIn) -> Path:
    csv_path = report_dir / "summary.csv"
    fields = [
        "created_at",
        "scenario_id",
        "n_runs",
        "delta_threshold",
        "matrix_A_version",
        "weights_version",
        "git_commit",
        "K_cl",
        "K_q",
        "Delta_percent",
        "run",
        "run_id",
        "initiator",
        "duration",
        "before",
        "after",
        "delta",
        "delta_cl",
        "delta_q",
        "I_cl",
        "I_q",
    ]

    with csv_path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields)
        writer.writeheader()

        now = datetime.now().isoformat()
        for run in payload.runs:
            delta_cl = _safe_float(run.method_cl_total_after) - _safe_float(run.method_cl_total_before)
            delta_q = _safe_float(run.delta_R if run.delta_R is not None else run.delta)
            writer.writerow(
                {
                    "created_at": now,
                    "scenario_id": payload.scenario_id,
                    "n_runs": payload.n_runs,
                    "delta_threshold": payload.delta_threshold,
                    "matrix_A_version": payload.matrix_A_version,
                    "weights_version": payload.weights_version,
                    "git_commit": payload.git_commit,
                    "K_cl": payload.K_cl,
                    "K_q": payload.K_q,
                    "Delta_percent": payload.Delta_percent,
                    "run": run.run,
                    "run_id": run.run_id,
                    "initiator": run.initiator,
                    "duration": run.duration,
                    "before": _safe_float(run.before),
                    "after": _safe_float(run.after),
                    "delta": _safe_float(run.delta),
                    "delta_cl": delta_cl,
                    "delta_q": delta_q,
                    "I_cl": run.I_cl,
                    "I_q": run.I_q,
                }
            )

    return csv_path


def _plot_distribution(report_dir: Path, delta_cl: np.ndarray, delta_q: np.ndarray) -> Path:
    fig, ax = plt.subplots(figsize=(12, 7))
    bins = 30

    ax.hist(delta_cl, bins=bins, density=True, alpha=0.4, color="#1f77b4", label="Классический метод")
    ax.hist(delta_q, bins=bins, density=True, alpha=0.4, color="#ff7f0e", label="Количественный метод")

    if delta_cl.size > 1:
        hist_cl, edges_cl = np.histogram(delta_cl, bins=bins, density=True)
        centers_cl = (edges_cl[:-1] + edges_cl[1:]) / 2
        ax.plot(centers_cl, hist_cl, color="#2ca02c", linewidth=2)
    if delta_q.size > 1:
        hist_q, edges_q = np.histogram(delta_q, bins=bins, density=True)
        centers_q = (edges_q[:-1] + edges_q[1:]) / 2
        ax.plot(centers_q, hist_q, color="#d62728", linewidth=2)

    p95_cl, p99_cl = np.quantile(delta_cl, [0.95, 0.99]) if delta_cl.size else (0.0, 0.0)
    p95_q, p99_q = np.quantile(delta_q, [0.95, 0.99]) if delta_q.size else (0.0, 0.0)
    ax.axvline(p95_cl, linestyle="--", color="#1f77b4", linewidth=1.5)
    ax.axvline(p99_cl, linestyle=":", color="#1f77b4", linewidth=1.5)
    ax.axvline(p95_q, linestyle="--", color="#ff7f0e", linewidth=1.5)
    ax.axvline(p99_q, linestyle=":", color="#ff7f0e", linewidth=1.5)

    ax.set_title("Распределение прироста интегрального риска ΔR")
    ax.set_xlabel("ΔR")
    ax.set_ylabel("Плотность")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper right")

    note = (
        f"Classical: p95={p95_cl:.4f}, p99={p99_cl:.4f} | "
        f"Quantitative: p95={p95_q:.4f}, p99={p99_q:.4f}"
    )
    ax.text(0.01, 0.97, note, transform=ax.transAxes, va="top")

    path = report_dir / "01_distribution_delta_r.png"
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def _plot_boxplot(report_dir: Path, delta_cl: np.ndarray, delta_q: np.ndarray) -> Path:
    fig, ax = plt.subplots(figsize=(10, 7))
    ax.boxplot(
        [delta_cl.tolist(), delta_q.tolist()],
        labels=["Классический метод", "Количественный метод"],
        showmeans=True,
        meanprops={"marker": "^", "markerfacecolor": "#2ca02c", "markeredgecolor": "#2ca02c"},
    )
    ax.set_title("Прирост интегрального риска ΔR")
    ax.set_ylabel("ΔR")
    ax.grid(True, alpha=0.25)

    path = report_dir / "02_boxplot_delta_r.png"
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def _plot_convergence(report_dir: Path, i_cl: np.ndarray, i_q: np.ndarray, theta: float) -> Path:
    fig, ax = plt.subplots(figsize=(12, 7))
    x = np.arange(1, len(i_cl) + 1)

    k_cl = np.cumsum(i_cl) / x
    k_q = np.cumsum(i_q) / x

    ax.plot(x, k_cl, label="Классический метод", color="#1f77b4")
    ax.plot(x, k_q, label="Количественный метод", color="#ff7f0e")
    ax.set_title(f"Сходимость оценки полноты выявления каскадов (θ={theta:.3f})")
    ax.set_xlabel("Число прогонов Monte Carlo")
    ax.set_ylabel("Оценка вероятности каскада K(N)")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper right")

    path = report_dir / "03_convergence_k.png"
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def _build_charts(report_dir: Path, payload: ExperimentRegisterIn) -> list[Path]:
    if not payload.runs:
        return []

    delta_cl = np.array(
        [_safe_float(r.method_cl_total_after) - _safe_float(r.method_cl_total_before) for r in payload.runs],
        dtype=float,
    )
    delta_q = np.array(
        [_safe_float(r.delta_R if r.delta_R is not None else r.delta) for r in payload.runs],
        dtype=float,
    )

    i_cl = np.array([int(r.I_cl or 0) for r in payload.runs], dtype=float)
    i_q = np.array([int(r.I_q or 0) for r in payload.runs], dtype=float)

    return [
        _plot_distribution(report_dir, delta_cl, delta_q),
        _plot_boxplot(report_dir, delta_cl, delta_q),
        _plot_convergence(report_dir, i_cl, i_q, payload.delta_threshold),
    ]


async def fetch_json(url: str, name: str):
    """Унифицированный запрос к сервисам с обработкой ошибок."""
    try:
        async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT) as client:
            resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"❌ Failed to fetch {name}: {e}")
        raise HTTPException(status_code=503, detail=f"{name} service unavailable")


@router.get("/summary", response_model=ReportingSummary)
async def summary(db: Session = Depends(get_db)):
    """
    Отдаёт:
      - текущее состояние energy/water/transport (онлайн)
      - текущий риск (онлайн)
    и сохраняет снапшоты в БД reporting.
    """

    logger.info("📊 Generating LIVE summary report")

    # 1. Получаем состояния всех секторов
    energy = await fetch_json(f"{settings.ENERGY_SERVICE_URL}/status", "energy")
    water = await fetch_json(f"{settings.WATER_SERVICE_URL}/status", "water")
    transport = await fetch_json(f"{settings.TRANSPORT_SERVICE_URL}/status", "transport")

    # 2. Получаем текущий риск
    risk = await fetch_json(f"{settings.RISK_ENGINE_URL}/current", "risk_engine")

    # 3. Формируем DTO
    sectors = [
        SectorState(name="energy", is_operational=energy["is_operational"], details=energy),
        SectorState(name="water", is_operational=water["is_operational"], details=water),
        SectorState(name="transport", is_operational=transport["is_operational"], details=transport),
    ]

    risk_summary = RiskSummary(
        energy_risk=risk["energy_risk"],
        water_risk=risk["water_risk"],
        transport_risk=risk["transport_risk"],
        total_risk=risk["total_risk"],
        calculated_at=risk["calculated_at"],
    )

    # 4. Сохраняем снапшоты в БД (кэш)
    sector_snapshot = SectorStatusSnapshot(
        sectors={
            "energy": energy,
            "water": water,
            "transport": transport,
        }
    )
    risk_snapshot = RiskOverviewSnapshot(
        energy_risk=risk["energy_risk"],
        water_risk=risk["water_risk"],
        transport_risk=risk["transport_risk"],
        total_risk=risk["total_risk"],
        meta={"source": "live"},
    )

    db.add(sector_snapshot)
    db.add(risk_snapshot)
    db.commit()

    logger.info("💾 LIVE summary saved into reporting schema")

    return ReportingSummary(
        sectors=sectors,
        risk=risk_summary,
        source="live",
    )


@router.post("/experiments/register", response_model=ExperimentRegisterOut)
async def register_experiment(payload: ExperimentRegisterIn, db: Session = Depends(get_db)):
    if payload.n_runs <= 0:
        raise HTTPException(status_code=400, detail="n_runs must be positive")

    experiment = Experiment(
        scenario_id=payload.scenario_id,
        method="both",
        n_runs=payload.n_runs,
        delta_threshold=payload.delta_threshold,
        matrix_A_version=payload.matrix_A_version,
        weights_version=payload.weights_version,
        git_commit=payload.git_commit,
        started_at=datetime.utcnow(),
        finished_at=datetime.utcnow(),
        params={"source": "scenario_simulator", "reported_runs": len(payload.runs)},
    )
    db.add(experiment)
    db.flush()

    for run in payload.runs:
        run_row = ExperimentRun(
            experiment_id=experiment.id,
            scenario_id=run.scenario_id,
            run_id=run.run_id,
            initiator=run.initiator,
            params={
                "duration": run.duration,
                "before": run.before,
                "after": run.after,
                "delta": run.delta,
                "delta_R": run.delta_R,
                "method_cl_total_before": run.method_cl_total_before,
                "method_cl_total_after": run.method_cl_total_after,
                "method_q_total_before": run.method_q_total_before,
                "method_q_total_after": run.method_q_total_after,
                "I_cl": run.I_cl,
                "I_q": run.I_q,
                "run_index": run.run,
            },
            started_at=datetime.utcnow(),
            finished_at=datetime.utcnow(),
            is_success=True,
        )
        db.add(run_row)

    db.add(
        ExperimentResult(
            experiment_id=experiment.id,
            K_cl=payload.K_cl,
            K_q=payload.K_q,
            Delta_percent=payload.Delta_percent,
            distributions=payload.distributions,
            meta={"reporting": "filesystem+db"},
        )
    )
    db.commit()

    report_dir = _mk_report_dir()
    csv_file = _save_csv_summary(report_dir, payload)
    chart_paths = _build_charts(report_dir, payload)

    logger.info(f"📁 Experiment report created: {report_dir}")

    return ExperimentRegisterOut(
        experiment_id=experiment.id,
        report_dir=str(report_dir),
        csv_file=str(csv_file),
        charts=[str(p) for p in chart_paths],
    )


@router.get("/risk/history", response_model=RiskHistoryResponse)
async def risk_history(limit: int = 100, db: Session = Depends(get_db)):
    """
    Возвращает историю сохранённых оценок риска.
    Отлично подходит для построения графиков.
    """
    logger.info(f"📈 Fetching risk history, limit={limit}")

    if limit <= 0:
        raise HTTPException(status_code=400, detail="limit must be positive")

    rows = db.query(RiskOverviewSnapshot).order_by(desc(RiskOverviewSnapshot.snapshot_at)).limit(limit).all()

    items = [
        RiskHistoryItem(
            snapshot_at=r.snapshot_at,
            energy_risk=r.energy_risk,
            water_risk=r.water_risk,
            transport_risk=r.transport_risk,
            total_risk=r.total_risk,
        )
        for r in rows
    ]

    return RiskHistoryResponse(items=items, count=len(items))


@router.get("/snapshots/sectors", response_model=SnapshotListResponse)
async def list_sector_snapshots(limit: int = 50, db: Session = Depends(get_db)):
    rows = db.query(SectorStatusSnapshot).order_by(desc(SectorStatusSnapshot.snapshot_at)).limit(limit).all()

    return SnapshotListResponse(
        items=[SectorStatusSnapshotOut.model_validate(r).dict() for r in rows],
        count=len(rows),
    )


@router.get("/snapshots/risk", response_model=SnapshotListResponse)
async def list_risk_snapshots(limit: int = 50, db: Session = Depends(get_db)):
    rows = db.query(RiskOverviewSnapshot).order_by(desc(RiskOverviewSnapshot.snapshot_at)).limit(limit).all()

    return SnapshotListResponse(
        items=[RiskOverviewSnapshotOut.model_validate(r).dict() for r in rows],
        count=len(rows),
    )
