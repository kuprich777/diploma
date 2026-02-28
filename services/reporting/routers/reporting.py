# services/reporting/routers/reporting.py

import csv
import html
import math
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models import Experiment, ExperimentResult, ExperimentRun, RiskOverviewSnapshot, SectorStatusSnapshot
from schemas import (
    ExperimentRegisterIn,
    ExperimentRegisterOut,
    ReportingSummary,
    RiskHistoryItem,
    RiskHistoryResponse,
    RiskOverviewSnapshotOut,
    RiskSummary,
    SectorState,
    SectorStatusSnapshotOut,
    SnapshotListResponse,
)
from utils.logging import setup_logging

logger = setup_logging()

router = APIRouter(prefix="/api/v1/reporting", tags=["reporting"])


def _safe_float(value: float | int | None) -> float:
    try:
        result = float(value)
        if math.isfinite(result):
            return result
    except (TypeError, ValueError):
        pass
    return 0.0


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = q * (len(sorted_vals) - 1)
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return sorted_vals[lo]
    w = idx - lo
    return sorted_vals[lo] * (1 - w) + sorted_vals[hi] * w


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


def _svg_canvas(title: str, width: int = 1000, height: int = 620) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect x="0" y="0" width="100%" height="100%" fill="#f2f2f2"/>',
        f'<text x="500" y="30" text-anchor="middle" font-size="28" font-family="Arial">{html.escape(title)}</text>',
    ]


def _write_svg(path: Path, lines: list[str]) -> Path:
    lines.append("</svg>")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _histogram(values: list[float], bins: int, x_min: float, x_max: float) -> list[int]:
    if x_max <= x_min:
        x_max = x_min + 1e-9
    width = (x_max - x_min) / bins
    hist = [0] * bins
    for value in values:
        idx = int((value - x_min) / width)
        if idx < 0:
            idx = 0
        if idx >= bins:
            idx = bins - 1
        hist[idx] += 1
    return hist


def _plot_distribution_svg(report_dir: Path, delta_cl: list[float], delta_q: list[float]) -> Path:
    path = report_dir / "01_distribution_delta_r.svg"
    lines = _svg_canvas("Распределение прироста интегрального риска ΔR")

    x0, y0, w, h = 90, 80, 840, 460
    lines += [
        f'<rect x="{x0}" y="{y0}" width="{w}" height="{h}" fill="white" stroke="#666"/>',
        f'<text x="{x0 + w/2}" y="580" text-anchor="middle" font-size="20" font-family="Arial">ΔR</text>',
        f'<text x="30" y="{y0 + h/2}" text-anchor="middle" font-size="20" transform="rotate(-90,30,{y0 + h/2})" font-family="Arial">Частота</text>',
    ]

    all_vals = delta_cl + delta_q
    x_min = min(all_vals) if all_vals else 0.0
    x_max = max(all_vals) if all_vals else 1.0
    bins = 24
    h_cl = _histogram(delta_cl, bins, x_min, x_max)
    h_q = _histogram(delta_q, bins, x_min, x_max)
    max_y = max(max(h_cl, default=0), max(h_q, default=0), 1)

    bin_px = w / bins
    for i in range(bins):
        cl_h = h * (h_cl[i] / max_y)
        q_h = h * (h_q[i] / max_y)
        x = x0 + i * bin_px
        lines.append(f'<rect x="{x:.2f}" y="{y0 + h - cl_h:.2f}" width="{bin_px:.2f}" height="{cl_h:.2f}" fill="#1f77b4" fill-opacity="0.45"/>')
        lines.append(f'<rect x="{x:.2f}" y="{y0 + h - q_h:.2f}" width="{bin_px:.2f}" height="{q_h:.2f}" fill="#ff7f0e" fill-opacity="0.45"/>')

    p95_cl, p99_cl = _quantile(delta_cl, 0.95), _quantile(delta_cl, 0.99)
    p95_q, p99_q = _quantile(delta_q, 0.95), _quantile(delta_q, 0.99)

    def x_to_px(v: float) -> float:
        if x_max <= x_min:
            return x0
        return x0 + ((v - x_min) / (x_max - x_min)) * w

    for val, color, dash in [(p95_cl, "#1f77b4", "8,6"), (p99_cl, "#1f77b4", "2,6"), (p95_q, "#ff7f0e", "8,6"), (p99_q, "#ff7f0e", "2,6")]:
        xx = x_to_px(val)
        lines.append(f'<line x1="{xx:.2f}" y1="{y0}" x2="{xx:.2f}" y2="{y0+h}" stroke="{color}" stroke-width="2" stroke-dasharray="{dash}"/>')

    lines += [
        '<rect x="650" y="90" width="260" height="90" fill="white" stroke="#888"/>',
        '<rect x="665" y="108" width="20" height="12" fill="#1f77b4" fill-opacity="0.45"/><text x="695" y="119" font-size="16">Классический метод</text>',
        '<rect x="665" y="138" width="20" height="12" fill="#ff7f0e" fill-opacity="0.45"/><text x="695" y="149" font-size="16">Количественный метод</text>',
        f'<text x="95" y="60" font-size="16">Classical: p95={p95_cl:.4f}, p99={p99_cl:.4f} | Quantitative: p95={p95_q:.4f}, p99={p99_q:.4f}</text>',
    ]
    return _write_svg(path, lines)


def _plot_boxplot_svg(report_dir: Path, delta_cl: list[float], delta_q: list[float]) -> Path:
    path = report_dir / "02_boxplot_delta_r.svg"
    lines = _svg_canvas("Прирост интегрального риска ΔR")
    x0, y0, w, h = 90, 80, 840, 460
    lines.append(f'<rect x="{x0}" y="{y0}" width="{w}" height="{h}" fill="white" stroke="#666"/>')

    all_vals = delta_cl + delta_q
    y_min = min(all_vals) if all_vals else 0.0
    y_max = max(all_vals) if all_vals else 1.0
    if y_max <= y_min:
        y_max = y_min + 1e-9

    def y_to_px(v: float) -> float:
        return y0 + h - ((v - y_min) / (y_max - y_min)) * h

    def draw_box(data: list[float], cx: float, label: str):
        if not data:
            return
        q1, q2, q3 = _quantile(data, 0.25), _quantile(data, 0.5), _quantile(data, 0.75)
        low, high = min(data), max(data)
        mean = sum(data) / len(data)
        bw = 120
        lines.extend([
            f'<line x1="{cx}" y1="{y_to_px(low):.2f}" x2="{cx}" y2="{y_to_px(high):.2f}" stroke="#333"/>',
            f'<rect x="{cx-bw/2}" y="{y_to_px(q3):.2f}" width="{bw}" height="{(y_to_px(q1)-y_to_px(q3)):.2f}" fill="#ddd" stroke="#333"/>',
            f'<line x1="{cx-bw/2}" y1="{y_to_px(q2):.2f}" x2="{cx+bw/2}" y2="{y_to_px(q2):.2f}" stroke="#e67e22" stroke-width="2"/>',
            f'<circle cx="{cx}" cy="{y_to_px(mean):.2f}" r="6" fill="#2ca02c"/>',
            f'<text x="{cx}" y="580" text-anchor="middle" font-size="22">{html.escape(label)}</text>',
        ])

    draw_box(delta_cl, x0 + w * 0.25, "Классический метод")
    draw_box(delta_q, x0 + w * 0.75, "Количественный метод")
    return _write_svg(path, lines)


def _plot_convergence_svg(report_dir: Path, i_cl: list[int], i_q: list[int], theta: float) -> Path:
    path = report_dir / "03_convergence_k.svg"
    lines = _svg_canvas(f"Сходимость оценки полноты выявления каскадов (θ={theta:.3f})")
    x0, y0, w, h = 90, 80, 840, 460
    lines.append(f'<rect x="{x0}" y="{y0}" width="{w}" height="{h}" fill="white" stroke="#666"/>')

    n = max(len(i_cl), 1)
    k_cl, k_q = [], []
    s_cl = s_q = 0
    for idx in range(n):
        s_cl += int(i_cl[idx]) if idx < len(i_cl) else 0
        s_q += int(i_q[idx]) if idx < len(i_q) else 0
        step = idx + 1
        k_cl.append(s_cl / step)
        k_q.append(s_q / step)

    def pt(i: int, v: float) -> tuple[float, float]:
        x = x0 + (i / (n - 1 if n > 1 else 1)) * w
        y = y0 + h - v * h
        return x, y

    def polyline(values: list[float], color: str) -> str:
        pts = [pt(i, v) for i, v in enumerate(values)]
        serialized = " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)
        return f'<polyline points="{serialized}" fill="none" stroke="{color}" stroke-width="2.5"/>'

    lines.append(polyline(k_cl, "#1f77b4"))
    lines.append(polyline(k_q, "#ff7f0e"))
    lines += [
        '<rect x="670" y="90" width="230" height="70" fill="white" stroke="#888"/>',
        '<line x1="685" y1="112" x2="720" y2="112" stroke="#1f77b4" stroke-width="3"/><text x="730" y="117" font-size="16">Классический метод</text>',
        '<line x1="685" y1="142" x2="720" y2="142" stroke="#ff7f0e" stroke-width="3"/><text x="730" y="147" font-size="16">Количественный метод</text>',
    ]
    return _write_svg(path, lines)


def _build_charts(report_dir: Path, payload: ExperimentRegisterIn) -> list[Path]:
    if not payload.runs:
        return []

    delta_cl = [_safe_float(r.method_cl_total_after) - _safe_float(r.method_cl_total_before) for r in payload.runs]
    delta_q = [_safe_float(r.delta_R if r.delta_R is not None else r.delta) for r in payload.runs]
    i_cl = [int(r.I_cl or 0) for r in payload.runs]
    i_q = [int(r.I_q or 0) for r in payload.runs]

    return [
        _plot_distribution_svg(report_dir, delta_cl, delta_q),
        _plot_boxplot_svg(report_dir, delta_cl, delta_q),
        _plot_convergence_svg(report_dir, i_cl, i_q, payload.delta_threshold),
    ]


async def fetch_json(url: str, name: str):
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
    logger.info("📊 Generating LIVE summary report")

    energy = await fetch_json(f"{settings.ENERGY_SERVICE_URL}/status", "energy")
    water = await fetch_json(f"{settings.WATER_SERVICE_URL}/status", "water")
    transport = await fetch_json(f"{settings.TRANSPORT_SERVICE_URL}/status", "transport")
    risk = await fetch_json(f"{settings.RISK_ENGINE_URL}/current", "risk_engine")

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

    db.add(SectorStatusSnapshot(sectors={"energy": energy, "water": water, "transport": transport}))
    db.add(
        RiskOverviewSnapshot(
            energy_risk=risk["energy_risk"],
            water_risk=risk["water_risk"],
            transport_risk=risk["transport_risk"],
            total_risk=risk["total_risk"],
            meta={"source": "live"},
        )
    )
    db.commit()

    return ReportingSummary(sectors=sectors, risk=risk_summary, source="live")


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
        db.add(
            ExperimentRun(
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
        )

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
    return SnapshotListResponse(items=[SectorStatusSnapshotOut.model_validate(r).dict() for r in rows], count=len(rows))


@router.get("/snapshots/risk", response_model=SnapshotListResponse)
async def list_risk_snapshots(limit: int = 50, db: Session = Depends(get_db)):
    rows = db.query(RiskOverviewSnapshot).order_by(desc(RiskOverviewSnapshot.snapshot_at)).limit(limit).all()
    return SnapshotListResponse(items=[RiskOverviewSnapshotOut.model_validate(r).dict() for r in rows], count=len(rows))
