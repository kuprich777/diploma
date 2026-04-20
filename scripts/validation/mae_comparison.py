"""
MAE comparison — canonical IIM (Haimes 2005) vs NLDR (Barucca/NEVA)
on 4 documented cascade events.

Inputs:
  - data/calibration/A_star_iim_canonical.json  (Haimes A* matrix)
  - results/validation_real_events.json         (NLDR per-event predictions
                                                 + secondary-source ground truth)
  - data/empirical_cascades/historical_dataset/cascade_events.yaml
        (primary initiator metadata; primary intensities used when documented)

Method:
  - IIM prediction:    q = (I - A*)^{-1} c*,  c*[initiator] = amplitude, 0 else.
  - NLDR prediction:   median_final_delta from stage4_ter MC (per sector).
  - Initiator amplitude + non-initiator GT:
        primary (cascade_events.yaml) where documented,
        otherwise secondary (validation_real_events.json::reality.delta_approx).
  - MAE over non-initiator sectors with numeric GT.

Output:
  - results/mae_comparison.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from services.risk_engine.iim_canonical import IIMCanonical  # noqa: E402

A_STAR_PATH = REPO_ROOT / "data" / "calibration" / "A_star_iim_canonical.json"
EVENTS_YAML = REPO_ROOT / "data" / "empirical_cascades" / "historical_dataset" / "cascade_events.yaml"
NLDR_PATH = REPO_ROOT / "results" / "validation_real_events.json"
OUT_PATH = REPO_ROOT / "results" / "mae_comparison.json"

SECTOR_ORDER = ["energy", "water", "transport"]

# Map YAML id → validation_real_events.json key.
EVENT_KEY_MAP = {
    "EUROPE_2006": "europe_2006",
    "TEXAS_2021": "texas_2021",
    "INDIA_2012": "india_2012",
    "BALTIMORE_2024": "baltimore_2024",
}


def parse_primary_intensity(value) -> float | None:
    """Return float if cascade_events.yaml cell is numeric, else None."""
    if isinstance(value, (int, float)):
        return float(value)
    return None


def primary_amplitude_from_yaml(event: dict) -> float | None:
    """Return documented initiator amplitude if the YAML has primary_amplitude."""
    amp = event["initiator"].get("primary_amplitude")
    if isinstance(amp, dict) and isinstance(amp.get("value"), (int, float)):
        return float(amp["value"])
    return None


def main() -> None:
    iim = IIMCanonical.from_json(A_STAR_PATH)

    with EVENTS_YAML.open() as f:
        events_yaml = yaml.safe_load(f)["events"]
    events_by_id = {e["id"]: e for e in events_yaml}

    nldr_data = json.loads(NLDR_PATH.read_text())["events"]

    per_event = []
    for yaml_id, nldr_key in EVENT_KEY_MAP.items():
        event = events_by_id[yaml_id]
        initiator = event["initiator"]["sector"]

        nldr_event = nldr_data[nldr_key]
        secondary_gt = {s: float(nldr_event["reality"][s]["delta_approx"])
                        for s in SECTOR_ORDER}
        nldr_pred = {SECTOR_ORDER[i]: float(nldr_event["model"]["median_final_delta"][i])
                     for i in range(len(SECTOR_ORDER))}

        # Primary GT overrides secondary GT where documented in YAML.
        affected = event.get("affected", {}) or {}
        primary_overrides: dict[str, float] = {}
        for sector, cell in affected.items():
            if sector == initiator:
                continue
            if isinstance(cell, dict):
                v = parse_primary_intensity(cell.get("intensity"))
                if v is not None:
                    primary_overrides[sector] = v

        gt = dict(secondary_gt)
        gt.update(primary_overrides)  # primary wins when documented
        gt_source = {s: ("primary" if s in primary_overrides else "secondary")
                     for s in SECTOR_ORDER}

        # Initiator amplitude: primary if documented, else secondary (reality).
        amp_primary = primary_amplitude_from_yaml(event)
        amp_secondary = float(nldr_event["reality"][initiator]["delta_approx"])
        amplitude = amp_primary if amp_primary is not None else amp_secondary
        amp_source = "primary" if amp_primary is not None else "secondary"

        # IIM prediction.
        c_star = np.zeros(len(SECTOR_ORDER))
        c_star[SECTOR_ORDER.index(initiator)] = amplitude
        q = iim.predict(c_star)
        iim_pred = {SECTOR_ORDER[i]: float(q[i]) for i in range(len(SECTOR_ORDER))}

        # MAE over non-initiator sectors.
        iim_abs_err = {s: abs(iim_pred[s] - gt[s]) for s in SECTOR_ORDER if s != initiator}
        nldr_abs_err = {s: abs(nldr_pred[s] - gt[s]) for s in SECTOR_ORDER if s != initiator}
        mae_iim = float(np.mean(list(iim_abs_err.values())))
        mae_nldr = float(np.mean(list(nldr_abs_err.values())))

        per_event.append({
            "event_id": yaml_id,
            "initiator": initiator,
            "amplitude": amplitude,
            "amplitude_source": amp_source,
            "ground_truth": gt,
            "ground_truth_source": gt_source,
            "iim_pred": iim_pred,
            "nldr_pred": nldr_pred,
            "iim_abs_err": iim_abs_err,
            "nldr_abs_err": nldr_abs_err,
            "mae_iim": mae_iim,
            "mae_nldr": mae_nldr,
        })

        print(f"\n[{yaml_id}]  initiator={initiator}  "
              f"amplitude={amplitude:.3f} ({amp_source})")
        print(f"  GT        : {gt}  source={gt_source}")
        print(f"  IIM pred  : { {k: round(v,4) for k,v in iim_pred.items()} }")
        print(f"  NLDR pred : { {k: round(v,4) for k,v in nldr_pred.items()} }")
        print(f"  MAE_IIM   = {mae_iim:.4f}")
        print(f"  MAE_NLDR  = {mae_nldr:.4f}")

    # Aggregate (LOO-equivalent since no parameters are re-fit per event).
    mae_iim_oos = float(np.mean([r["mae_iim"] for r in per_event]))
    mae_nldr_oos = float(np.mean([r["mae_nldr"] for r in per_event]))
    delta = (mae_iim_oos - mae_nldr_oos) / mae_iim_oos if mae_iim_oos > 0 else 0.0
    if delta >= 0.25:
        h1_status = "CONFIRMED"
    elif delta >= 0.10:
        h1_status = "PARTIAL"
    else:
        h1_status = "NOT_CONFIRMED"

    # Sector bias: mean signed error over events excluding initiator.
    bias = {"iim": {}, "nldr": {}}
    for sector in SECTOR_ORDER:
        iim_errs = []
        nldr_errs = []
        for r in per_event:
            if sector == r["initiator"]:
                continue
            iim_errs.append(r["iim_pred"][sector] - r["ground_truth"][sector])
            nldr_errs.append(r["nldr_pred"][sector] - r["ground_truth"][sector])
        bias["iim"][sector] = float(np.mean(iim_errs)) if iim_errs else None
        bias["nldr"][sector] = float(np.mean(nldr_errs)) if nldr_errs else None

    summary = {
        "schema_version": 1,
        "method_iim": "Canonical IIM, Haimes 2005 Part I eq.(11); q=(I-A*)^-1 c*",
        "method_nldr": "NLDR / NEVA stage-4-ter MC, median_final_delta per sector",
        "ground_truth_primary_source": "data/empirical_cascades/historical_dataset/cascade_events.yaml",
        "ground_truth_secondary_source": "results/validation_real_events.json::events[*].reality.delta_approx",
        "mae_iim_oos": mae_iim_oos,
        "mae_nldr_oos": mae_nldr_oos,
        "delta_fraction": delta,
        "delta_percent": delta * 100.0,
        "h1_threshold_percent": 25.0,
        "h1_status": h1_status,
        "bias": bias,
        "per_event": per_event,
    }
    OUT_PATH.write_text(json.dumps(summary, indent=2))

    print("\n=== RESULT ===")
    print(f"MAE_IIM_oos  = {mae_iim_oos:.4f}")
    print(f"MAE_NLDR_oos = {mae_nldr_oos:.4f}")
    print(f"Delta        = {delta * 100:+.1f}%  (threshold +25%)")
    print(f"H_1 status   : {h1_status}")
    print("\nSector bias (mean signed error, non-initiator):")
    for s in SECTOR_ORDER:
        print(f"  {s:<10s}  IIM={bias['iim'][s]}  NLDR={bias['nldr'][s]}")
    print(f"\nSaved: {OUT_PATH}")


if __name__ == "__main__":
    main()
