"""
Этап 4.1 — Leave-One-Out калибровка матрицы A.

Методология:
  Для каждого события k ∈ {EUROPE_2006, TEXAS_2021, INDIA_2012, BALTIMORE_2024}:
    1. Исключаем k из датасета.
    2. Применяем Beta-Binomial posterior к оставшимся 3 событиям.
    3. Применяем спектральную нормализацию (cap ρ=0.95).
  Получаем 4 LOO-матрицы A^(−k) + full-data A для референса.

Вход:  data/empirical_cascades/historical_dataset/cascade_events.yaml
Выход: data/calibration/A_loo_v1.json (словарь по event_id)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from scipy.stats import beta as beta_dist

ROOT = Path(__file__).resolve().parents[2]
EVENTS_YAML = ROOT / "data/empirical_cascades/historical_dataset/cascade_events.yaml"
OUTPUT_JSON = ROOT / "data/calibration/A_loo_v1.json"

SECTORS = ("energy", "water", "transport")
PRIOR_ALPHA = 1.0
PRIOR_BETA = 1.0
# ρ=0.50: см. обоснование в bayesian_posterior.py (Этап 4-ter recalibration).
SPECTRAL_CAP = 0.50


def load_events() -> list[dict[str, Any]]:
    with EVENTS_YAML.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)["events"]


def extract_observations(events: list[dict]) -> dict[str, dict[str, list[float]]]:
    obs = {i: {j: [] for j in SECTORS} for i in SECTORS}
    for ev in events:
        initiator = ev["initiator"]["sector"]
        for affected, cell in ev["affected"].items():
            val = cell.get("intensity")
            if isinstance(val, (int, float)) and affected != initiator:
                obs[affected][initiator].append(float(val))
    return obs


def posterior_matrix(obs: dict) -> tuple[np.ndarray, dict]:
    mat = np.zeros((3, 3))
    details = {i: {} for i in SECTORS}
    for ii, i in enumerate(SECTORS):
        for jj, j in enumerate(SECTORS):
            if i == j:
                details[i][j] = {"diagonal": True}
                continue
            xs = obs[i][j]
            n = len(xs)
            s = float(sum(xs))
            a = PRIOR_ALPHA + s
            b = PRIOR_BETA + n - s
            mean = a / (a + b)
            mat[ii, jj] = mean
            details[i][j] = {
                "n": n,
                "sum": s,
                "alpha": a,
                "beta": b,
                "mean": mean,
                "ci95": [float(beta_dist.ppf(0.025, a, b)), float(beta_dist.ppf(0.975, a, b))],
            }
    return mat, details


def spectral_cap(mat: np.ndarray, cap: float) -> tuple[np.ndarray, dict]:
    rho = float(np.max(np.abs(np.linalg.eigvals(mat))))
    meta = {"rho_before": rho, "cap": cap}
    if rho > cap:
        mat = mat * (cap / rho)
        meta["rescaled"] = True
        meta["rho_after"] = cap
    else:
        meta["rescaled"] = False
        meta["rho_after"] = rho
    return mat, meta


def build_one(events: list[dict], held_out: str | None) -> dict:
    if held_out is None:
        subset = events
    else:
        subset = [e for e in events if e["id"] != held_out]
    obs = extract_observations(subset)
    mat_raw, details = posterior_matrix(obs)
    mat_capped, spec = spectral_cap(mat_raw.copy(), SPECTRAL_CAP)
    return {
        "held_out": held_out,
        "events_used": [e["id"] for e in subset],
        "matrix_raw": mat_raw.tolist(),
        "matrix_capped": mat_capped.tolist(),
        "spectral": spec,
        "cell_details": details,
    }


def main() -> None:
    events = load_events()
    ids = [e["id"] for e in events]

    out = {
        "schema_version": "1.0",
        "sectors": list(SECTORS),
        "prior": {"alpha": PRIOR_ALPHA, "beta": PRIOR_BETA},
        "spectral_cap": SPECTRAL_CAP,
        "full_data": build_one(events, held_out=None),
        "loo": {eid: build_one(events, held_out=eid) for eid in ids},
    }

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_JSON.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"Wrote {OUTPUT_JSON.relative_to(ROOT)}")
    print(f"\nLOO variants ({len(ids)}):")
    for eid in ids:
        mat = np.array(out["loo"][eid]["matrix_capped"])
        print(f"\n--- held out: {eid} ---  ρ_before={out['loo'][eid]['spectral']['rho_before']:.4f}")
        print(f"  {'':10s} " + " ".join(f"{j:>8s}" for j in SECTORS))
        for i_idx, i in enumerate(SECTORS):
            row = " ".join(f"{mat[i_idx, jj]:8.4f}" for jj in range(3))
            print(f"  {i:10s} {row}")


if __name__ == "__main__":
    main()
