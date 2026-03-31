"""
Build validation comparison tables and summary statistics
from historical_case_mapping.csv and historical_vs_model_comparison.csv.

Outputs:
  validation/validation_tables.txt   — printable tables for thesis
  validation/validation_figures.py   — matplotlib figure code (run separately)
"""

import csv
import json
from pathlib import Path
from collections import Counter, defaultdict

BASE = Path(__file__).parent.parent
VAL = BASE / "validation"
RESULTS = BASE / "results"

# ---------------------------------------------------------------------------
# Load CSV data
# ---------------------------------------------------------------------------

def load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

case_mapping = load_csv(VAL / "historical_case_mapping.csv")
comparison = load_csv(VAL / "historical_vs_model_comparison.csv")

# Load key model results for numeric tables
def load_json(path):
    with open(path) as f:
        return json.load(f)

load_sweep = load_json(RESULTS / "load_sweep_s3_summary.json").get("results", [])
theta_sweep = load_json(RESULTS / "theta_sweep_s3_summary.json").get("results", [])
sev_sweep = load_json(RESULTS / "severity_sweep_water_summary.json").get("data", [])
roc = load_json(RESULTS / "roc_analysis_s3.json").get("roc_points", [])

output_lines = []


def section(title):
    output_lines.append("")
    output_lines.append("=" * 78)
    output_lines.append(f"  {title}")
    output_lines.append("=" * 78)


def table_row(*cols, widths):
    parts = []
    for val, w in zip(cols, widths):
        s = str(val)
        parts.append(s[:w].ljust(w))
    output_lines.append("  " + "  ".join(parts))


def divider(widths):
    output_lines.append("  " + "  ".join("-" * w for w in widths))


# ---------------------------------------------------------------------------
# Table 1: Historical case summary
# ---------------------------------------------------------------------------

section("Table 1. Historical Cases Mapped to Stand Scenarios")
header = ["Historical Case", "Year", "Init. Sector", "Stand Scenario", "Regime", "Consistency"]
widths = [34, 6, 12, 24, 12, 11]
table_row(*header, widths=widths)
divider(widths)
for row in case_mapping:
    # skip theoretical entries for this summary
    if row["comparison_type"] == "qualitative" and row["year"] in ("2001", "2010"):
        row_type = "theory"
    table_row(
        row["historical_case"][:34],
        row["year"][:6],
        row["initiating_sector"][:12],
        row["stand_scenario"][:24],
        row["stand_regime"][:12],
        row["consistency_assessment"],
        widths=widths,
    )
output_lines.append("")


# ---------------------------------------------------------------------------
# Table 2: Stand scenario parameters vs historical proxies
# ---------------------------------------------------------------------------

section("Table 2. Stand Scenario Parameters — Cross-referenced to Historical Analogs")
header2 = ["Scenario", "K_cl", "K_q", "Gap", "Duration", "Regime", "Historical Analog"]
widths2 = [22, 6, 6, 6, 12, 20, 28]
table_row(*header2, widths=widths2)
divider(widths2)
scenarios = [
    ("S1_energy_outage", "1.000", "1.000", "0.000", "[5,30] min", "extreme/saturated",
     "NE Blackout 2003; Sandy 2012"),
    ("S3_transport_load", "0.534", "0.956", "0.422", "[5,30] min", "marginal",
     "CAISO Flex Alerts 2022-24"),
    ("S4_water_partial", "0.416", "0.876", "0.460", "[5,30] min", "partial degradation",
     "Jackson MS 2022; TX URI 2021"),
    ("S1b_energy_partial", "0.423", "0.631", "0.208", "[5,30] min", "partial degradation",
     "TX URI (partial, ~40% loss)"),
]
for row in scenarios:
    table_row(*row, widths=widths2)
output_lines.append("")


# ---------------------------------------------------------------------------
# Table 3: Proxy comparison by sector and event
# ---------------------------------------------------------------------------

section("Table 3. Proxy Comparison — Observed vs Simulated Values")
header3 = ["Historical Case", "Sector", "Proxy Type", "Observed", "Simulated", "Type", "Consistency"]
widths3 = [32, 10, 24, 20, 18, 12, 11]
table_row(*header3, widths=widths3)
divider(widths3)
for row in comparison:
    if row["comparison_type"] in ("range", "regime", "quantitative"):
        table_row(
            row["historical_case"][:32],
            row["sector"][:10],
            row["observed_proxy_type"][:24],
            row["observed_proxy_value_or_range"][:20],
            f'{row["simulation_parameter"]}={row["simulation_value"]}'[:18],
            row["comparison_type"][:12],
            row["consistency_assessment"],
            widths=widths3,
        )
output_lines.append("")


# ---------------------------------------------------------------------------
# Table 4: Consistency summary by comparison type
# ---------------------------------------------------------------------------

section("Table 4. Consistency Summary by Comparison Type")
by_type = defaultdict(list)
for row in comparison:
    by_type[row["comparison_type"]].append(row["consistency_assessment"])

header4 = ["Comparison Type", "Total", "High", "Moderate", "Low", "High%"]
widths4 = [20, 7, 6, 9, 5, 7]
table_row(*header4, widths=widths4)
divider(widths4)
for ctype in ("range", "regime", "quantitative", "qualitative"):
    items = by_type.get(ctype, [])
    if not items:
        continue
    c = Counter(items)
    high_pct = round(100 * c["high"] / len(items)) if items else 0
    table_row(
        ctype, len(items), c["high"], c["moderate"], c["low"], f"{high_pct}%",
        widths=widths4,
    )
output_lines.append("")


# ---------------------------------------------------------------------------
# Table 5: Load sweep — model sensitivity coverage
# ---------------------------------------------------------------------------

section("Table 5. Load Sweep — Model Sensitivity (S3_transport_load, N=500/point)")
header5 = ["Load Amount", "K_cl", "K_q", "Gap (K_q-K_cl)", "Historical Analog Region"]
widths5 = [12, 7, 7, 15, 38]
table_row(*header5, widths=widths5)
divider(widths5)
analogs = {
    0.10: "CAISO mild flex event (~3-5% demand reduction proxy)",
    0.20: "CAISO moderate flex event (~8% reduction proxy)",
    0.25: "Light transport congestion (~10-15% mobility reduction)",
    0.40: "S3 calibrated: significant transport stress",
    0.50: "Major transport disruption (Sandy partial analog)",
    0.60: "Extreme transport load (pre-outage surge)",
}
for pt in load_sweep:
    la = pt.get("load_amount")
    k_cl = round(pt.get("K_cl", 0), 3)
    k_q = round(pt.get("K_q", 0), 3)
    gap = round(k_q - k_cl, 3)
    analog = analogs.get(la, "")
    table_row(f"{la:.2f}", k_cl, k_q, gap, analog, widths=widths5)
output_lines.append("")


# ---------------------------------------------------------------------------
# Table 6: Severity sweep — S4 water partial
# ---------------------------------------------------------------------------

section("Table 6. Severity Sweep — S4_water_partial (N=500/point)")
header6 = ["Severity", "K_cl", "K_q", "Gap", "Historical Proxy"]
widths6 = [10, 7, 7, 7, 46]
table_row(*header6, widths=widths6)
divider(widths6)
sev_analogs = {
    0.10: "Minor water pressure loss (<10% capacity)",
    0.20: "Moderate water degradation (Jackson early stage)",
    0.30: "Significant degradation (~15-20% population impacted)",
    0.45: "Near-critical water failure (Jackson peak; TX URI water partial)",
    0.50: "Critical water failure (~45% impact TX URI analog)",
    0.70: "S4 calibrated: major water infrastructure failure",
    0.80: "Near-total water system failure",
}
for pt in sev_sweep:
    sv = pt.get("severity")
    k_cl = round(pt.get("K_cl", 0), 3)
    k_q = round(pt.get("K_q", 0), 3)
    gap = round(k_q - k_cl, 3)
    analog = sev_analogs.get(sv, "")
    table_row(f"{sv:.2f}", k_cl, k_q, gap, analog, widths=widths6)
output_lines.append("")


# ---------------------------------------------------------------------------
# Table 7: ROC analysis — K_cl sensitivity across theta values
# ---------------------------------------------------------------------------

section("Table 7. ROC Analysis — Classical Sensitivity vs theta_node (S3, N=500)")
output_lines.append(
    "  NOTE: FPR=0 for ALL theta values. Classical detections ⊆ quantitative detections."
)
output_lines.append("")
header7 = ["theta_node", "TP", "FP", "FN", "TN", "K_cl (sens)", "K_q", "F1"]
widths7 = [10, 6, 6, 6, 6, 13, 7, 7]
table_row(*header7, widths=widths7)
divider(widths7)
for pt in roc:
    table_row(
        pt.get("theta_node"),
        pt.get("tp", ""), pt.get("fp", ""), pt.get("fn", ""), pt.get("tn", ""),
        round(pt.get("sensitivity_TPR", 0), 3),
        round(pt.get("K_q", 0), 3),
        round(pt.get("F1", 0), 3),
        widths=widths7,
    )
output_lines.append("")


# ---------------------------------------------------------------------------
# Key findings summary
# ---------------------------------------------------------------------------

section("Key Findings — Historical-Analog Validation")
findings = [
    "1. REGIME CONSISTENCY (HIGH): Three historical events (NE Blackout 2003, Sandy 2012,",
    "   TX URI 2021) confirm the EXTREME regime (K_cl=K_q=1.0 in S1). All produced",
    "   guaranteed cross-sector cascades — consistent with model's saturated detection.",
    "",
    "2. MARGINAL REGIME (HIGH): CAISO Flex Alerts 2022–2024 confirm the MARGINAL regime.",
    "   Sub-threshold risk propagation without classical threshold crossing matches",
    "   S3's K_cl=0.534 < K_q=0.956 gap (422/1000 runs: quantitative-only detection).",
    "",
    "3. MATRIX STRUCTURE (HIGH): UK CCRA and Rinaldi (2001) validate matrix edge ordering:",
    "   A[transport][energy]=0.5 > A[water][energy]=0.4 is consistent with CCRA",
    "   Class I dependency rankings and confirmed by NE Blackout transport impacts.",
    "",
    "4. BIDIRECTIONAL COUPLING (HIGH): TX URI 2021 confirms energy↔water bidirectionality.",
    "   Matrix implements both directions: A[water][energy]=0.4, A[energy][water]=0.2.",
    "   Asymmetry (energy→water stronger) matches observed dominance direction in URI.",
    "",
    "5. SUB-THRESHOLD DETECTION (HIGH): Quantitative method's higher sensitivity (K_q>>K_cl)",
    "   in marginal/partial regimes is consistent with documented sub-threshold events",
    "   (CAISO; Jackson early-stage; URI partial energy loss). Classical method would",
    "   miss these events — exactly as observed in real infrastructure management.",
    "",
    "6. PHASE TRANSITION (HIGH): Load sweep (Table 5) reproduces theoretical phase",
    "   transition behavior (Buldyrev 2010): cascade probability rises monotonically",
    "   with load, with K_q saturating earlier than K_cl — consistent with theory.",
    "",
    "7. DURATION RANGE (MODERATE): Model duration [5–30 min] covers cascade ONSET window",
    "   (NE Blackout cascade: ~8 min). Full event duration (days) is outside scope.",
    "   Model represents initial propagation phase — clearly stated limitation.",
    "",
    "8. POPULATION-TO-RISK MAPPING (LOW/QUALITATIVE): Model uses normalized [0,1] risk",
    "   without direct population mapping. Comparison to affected-population-share is",
    "   proxy-based and qualitative only.",
]
for line in findings:
    output_lines.append(f"  {line}")

output_lines.append("")


# ---------------------------------------------------------------------------
# Limitations
# ---------------------------------------------------------------------------

section("Limitations — Historical-Analog Validation")
limitations = [
    "L1. Temporal mismatch: Model duration [5–30 min] ≠ historical event duration [hours–days].",
    "    The model represents the cascade propagation window, not full event lifecycle.",
    "",
    "L2. Spatial aggregation: Model operates at sector (national/regional) level.",
    "    Historical events are geographically specific (city/state/region scale).",
    "    No direct spatial comparison is possible.",
    "",
    "L3. Risk normalization: Model uses normalized risk [0,1] without physical units.",
    "    Direct numeric comparison to MW lost, population affected requires additional",
    "    calibration that is outside current model scope.",
    "",
    "L4. Single-run duration is stochastic (Uniform[5,30 min]) — historical events",
    "    have variable and often much longer duration. K_cl, K_q are aggregated over",
    "    1000 stochastic runs; direct single-event comparison is not appropriate.",
    "",
    "L5. Some historical proxies are estimates or ranges from secondary sources.",
    "    Exact quantitative comparison is not always possible; regime-level comparison",
    "    is more reliable than point estimates.",
    "",
    "L6. The model does not include geographic interdependencies (co-location),",
    "    cybersecurity interdependencies, or temporal dependencies beyond propagation depth.",
    "",
    "L7. Historical data for transport-initiated cascades (S3 scenario analog) is",
    "    less abundant than energy-outage literature. CAISO analogy is partial.",
]
for line in limitations:
    output_lines.append(f"  {line}")

output_lines.append("")

# ---------------------------------------------------------------------------
# Write output
# ---------------------------------------------------------------------------
out_path = VAL / "validation_tables.txt"
with open(out_path, "w", encoding="utf-8") as f:
    f.write("\n".join(output_lines))

print(f"Written: {out_path}")
print(f"Lines: {len(output_lines)}")

# Also print to stdout
print("\n" + "\n".join(output_lines))
