"""
Этап 1.3 — Построение raw empirical матрицы A из авторского датасета Level 2.

Читает data/empirical_cascades/historical_dataset/cascade_events.yaml
Выход: data/calibration/A_empirical_v1.json

Семантика A[i][j] = средняя интенсивность воздействия на сектор i при инициаторе j,
усреднённая по событиям с initiator == j, где intensity задокументирована.

Ячейки без наблюдений → null (NaN), отдельно фиксируется observation_count.
Диагональ = 0 по соглашению (initiator не воздействует сам на себя).
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
EVENTS_YAML = ROOT / "data/empirical_cascades/historical_dataset/cascade_events.yaml"
OUTPUT_JSON = ROOT / "data/calibration/A_empirical_v1.json"

SECTORS = ("energy", "water", "transport")


def load_events() -> dict[str, Any]:
    with EVENTS_YAML.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_matrix(data: dict[str, Any]) -> tuple[dict, dict, dict]:
    # accumulators[i][j] = list of observed intensities for A[i][j]
    accumulators: dict[str, dict[str, list[float]]] = {
        i: {j: [] for j in SECTORS} for i in SECTORS
    }
    per_event_contributions: dict[str, dict[str, dict[str, Any]]] = {}

    for ev in data["events"]:
        ev_id = ev["id"]
        initiator = ev["initiator"]["sector"]
        per_event_contributions[ev_id] = {"initiator": initiator, "contributions": {}}

        for affected_sector, cell in ev["affected"].items():
            intensity = cell.get("intensity")
            if intensity == "DIAGONAL_NOT_APPLICABLE":
                continue
            if intensity == "NOT_DOCUMENTED_IN_SOURCE":
                per_event_contributions[ev_id]["contributions"][affected_sector] = {
                    "value": None,
                    "status": "not_documented",
                }
                continue
            # numeric
            accumulators[affected_sector][initiator].append(float(intensity))
            per_event_contributions[ev_id]["contributions"][affected_sector] = {
                "value": float(intensity),
                "status": "documented",
                "source_level": cell.get("source_level"),
            }

    # reduce to means
    matrix: dict[str, dict[str, float | None]] = {i: {j: None for j in SECTORS} for i in SECTORS}
    counts: dict[str, dict[str, int]] = {i: {j: 0 for j in SECTORS} for i in SECTORS}

    for i in SECTORS:
        for j in SECTORS:
            if i == j:
                matrix[i][j] = 0.0
                continue
            vals = accumulators[i][j]
            counts[i][j] = len(vals)
            matrix[i][j] = (sum(vals) / len(vals)) if vals else None

    return matrix, counts, per_event_contributions


def format_matrix_row(row: dict[str, float | None]) -> str:
    def fmt(x: float | None) -> str:
        if x is None:
            return "   nan "
        if isinstance(x, float) and math.isnan(x):
            return "   nan "
        return f"{x:6.3f} "
    return "[" + " ".join(fmt(row[j]) for j in SECTORS) + "]"


def main() -> None:
    data = load_events()
    matrix, counts, contributions = build_matrix(data)

    documented_off_diag = sum(
        1 for i in SECTORS for j in SECTORS if i != j and matrix[i][j] is not None
    )
    total_off_diag = len(SECTORS) * (len(SECTORS) - 1)

    output = {
        "schema_version": "1.0",
        "source": "authorial Level 2 dataset (data/empirical_cascades/historical_dataset/cascade_events.yaml)",
        "construction": "Per-cell mean over documented intensities; undocumented cells → null.",
        "sectors": list(SECTORS),
        "matrix_raw_mean": matrix,
        "observation_counts": counts,
        "coverage": {
            "documented_off_diagonal_cells": documented_off_diag,
            "total_off_diagonal_cells": total_off_diag,
            "coverage_fraction": documented_off_diag / total_off_diag,
        },
        "per_event_contributions": contributions,
    }

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_JSON.open("w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Wrote {OUTPUT_JSON.relative_to(ROOT)}")
    print(f"\nA_empirical_v1 (rows=affected, cols=initiator, order={SECTORS}):")
    for i in SECTORS:
        print(f"  {i:10s} {format_matrix_row(matrix[i])}")
    print(f"\nObservation counts (rows=affected, cols=initiator):")
    for i in SECTORS:
        row = " ".join(f"{counts[i][j]:3d}" for j in SECTORS)
        print(f"  {i:10s} [{row}]")
    print(f"\nCoverage: {documented_off_diag}/{total_off_diag} off-diagonal cells documented ({documented_off_diag/total_off_diag*100:.1f}%)")


if __name__ == "__main__":
    main()
