#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   cp test/curl.env.example test/curl.env
#   # edit variables if needed
#   source test/curl.env
#   bash test/run_scenarios.sh

ENV_FILE="${ENV_FILE:-test/curl.env}"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck source=/dev/null
  source "$ENV_FILE"
fi

: "${BASE_PROTOCOL:=http}"
: "${HOST:=localhost}"

: "${ENERGY_PORT:=8001}"
: "${WATER_PORT:=8002}"
: "${TRANSPORT_PORT:=8003}"
: "${RISK_PORT:=8004}"
: "${SIM_PORT:=8005}"

: "${SCENARIO_ID:=S1_energy_outage}"

# Important: use different run_id for different experiment blocks.
BASE_RUN_ID="${BASE_RUN_ID:-$(date +%s)}"
: "${MANUAL_RUN_ID:=$((BASE_RUN_ID + 1))}"
: "${CATALOG_RUN_ID:=$((BASE_RUN_ID + 2))}"
: "${CUSTOM_RUN_ID:=$((BASE_RUN_ID + 3))}"
: "${CUSTOM_CASCADE_RUN_ID:=$((BASE_RUN_ID + 6))}"
: "${INIT_FORCE_RUN_ID:=$((BASE_RUN_ID + 4))}"
: "${INIT_SCENARIO_RUN_ID:=$((BASE_RUN_ID + 5))}"

: "${OUTAGE_DURATION:=30}"
: "${OUTAGE_REASON:=qa_manual_test}"
: "${TRANSPORT_LOAD_AMOUNT:=0.25}"

: "${MONTE_CARLO_RUNS:=300}"
: "${MONTE_CARLO_START_RUN_ID:=$((BASE_RUN_ID + 1000))}"
: "${MONTE_CARLO_MIN_DURATION:=5}"
: "${MONTE_CARLO_MAX_DURATION:=30}"
: "${MONTE_CARLO_STOCHASTIC_SCALE:=0.0}"
: "${MONTE_CARLO_SECTOR:=energy}"
: "${MONTE_CARLO_ACTION:=outage}"

: "${RISK_METHOD:=quantitative}"

ENERGY_BASE="${BASE_PROTOCOL}://${HOST}:${ENERGY_PORT}/api/v1/energy"
WATER_BASE="${BASE_PROTOCOL}://${HOST}:${WATER_PORT}/api/v1/water"
TRANSPORT_BASE="${BASE_PROTOCOL}://${HOST}:${TRANSPORT_PORT}/api/v1/transport"
RISK_BASE="${BASE_PROTOCOL}://${HOST}:${RISK_PORT}/api/v1/risk"
SIM_BASE="${BASE_PROTOCOL}://${HOST}:${SIM_PORT}/api/v1/simulator"

LAST_RESPONSE=""

request_json() {
  local title="$1"
  shift
  echo
  echo "===== ${title} ====="
  echo "curl $*"
  LAST_RESPONSE="$(curl -sS "$@")"
  echo "$LAST_RESPONSE"
}

json_get() {
  local json="$1"
  local path="$2"
  JSON_INPUT="$json" JSON_PATH="$path" python - <<'PY'
import json
import os

obj = json.loads(os.environ["JSON_INPUT"])
path = os.environ["JSON_PATH"].split('.')
cur = obj
for p in path:
    if p.isdigit():
        cur = cur[int(p)]
    else:
        cur = cur[p]
if isinstance(cur, (dict, list)):
    print(json.dumps(cur, ensure_ascii=False))
else:
    print(cur)
PY
}

assert_close() {
  local lhs="$1"
  local rhs="$2"
  local eps="$3"
  python - <<PY
lhs=float("$lhs")
rhs=float("$rhs")
eps=float("$eps")
if abs(lhs-rhs) > eps:
    raise SystemExit(f"assert_close failed: |{lhs} - {rhs}| > {eps}")
print(f"assert_close ok: {lhs} ~ {rhs} (eps={eps})")
PY
}

echo "Run IDs => manual=${MANUAL_RUN_ID}, catalog=${CATALOG_RUN_ID}, custom=${CUSTOM_RUN_ID}, custom_cascade=${CUSTOM_CASCADE_RUN_ID}, init_force=${INIT_FORCE_RUN_ID}, init_scenario=${INIT_SCENARIO_RUN_ID}, mc_start=${MONTE_CARLO_START_RUN_ID}"

# 1) Manual block on dedicated run_id
request_json "init energy (manual run)" -X POST "${ENERGY_BASE}/init?scenario_id=${SCENARIO_ID}&run_id=${MANUAL_RUN_ID}&force=true"
request_json "init water (manual run)" -X POST "${WATER_BASE}/init?scenario_id=${SCENARIO_ID}&run_id=${MANUAL_RUN_ID}&force=true"
request_json "init transport (manual run)" -X POST "${TRANSPORT_BASE}/init?scenario_id=${SCENARIO_ID}&run_id=${MANUAL_RUN_ID}&force=true"

request_json "risk before manual outage" "${RISK_BASE}/current?scenario_id=${SCENARIO_ID}&run_id=${MANUAL_RUN_ID}&method=${RISK_METHOD}"
MANUAL_BEFORE="$(json_get "$LAST_RESPONSE" "total_risk")"
echo "manual_before=${MANUAL_BEFORE}"

request_json "energy simulate_outage (manual run)" -X POST \
  "${ENERGY_BASE}/simulate_outage?scenario_id=${SCENARIO_ID}&run_id=${MANUAL_RUN_ID}&step_index=1&action=outage" \
  -H 'Content-Type: application/json' \
  -d "{\"reason\":\"${OUTAGE_REASON}\",\"duration\":${OUTAGE_DURATION}}"

request_json "water check_energy_dependency (manual run)" -X POST \
  "${WATER_BASE}/check_energy_dependency?scenario_id=${SCENARIO_ID}&run_id=${MANUAL_RUN_ID}&step_index=2&action=dependency_check&source_duration=${OUTAGE_DURATION}"

request_json "transport check_energy_dependency (manual run)" -X POST \
  "${TRANSPORT_BASE}/check_energy_dependency?scenario_id=${SCENARIO_ID}&run_id=${MANUAL_RUN_ID}&step_index=3&action=dependency_check&source_duration=${OUTAGE_DURATION}"

request_json "risk after manual outage" "${RISK_BASE}/current?scenario_id=${SCENARIO_ID}&run_id=${MANUAL_RUN_ID}&method=${RISK_METHOD}"
MANUAL_AFTER="$(json_get "$LAST_RESPONSE" "total_risk")"
echo "manual_after=${MANUAL_AFTER}"

# 2) Catalog scenario on separate run_id
request_json "simulator catalog" "${SIM_BASE}/catalog"
request_json "run catalog scenario (isolated run_id)" -X POST "${SIM_BASE}/run_scenario?use_catalog=true" \
  -H 'Content-Type: application/json' \
  -d "{\"scenario_id\":\"${SCENARIO_ID}\",\"run_id\":${CATALOG_RUN_ID},\"init_all_sectors\":true}"
CATALOG_BEFORE="$(json_get "$LAST_RESPONSE" "before")"
CATALOG_RUN_ID_RESP="$(json_get "$LAST_RESPONSE" "run_id")"
echo "catalog_before=${CATALOG_BEFORE}, catalog_run_id=${CATALOG_RUN_ID_RESP}"

# 3) Custom scenario on separate run_id
request_json "run custom scenario (isolated run_id)" -X POST "${SIM_BASE}/run_scenario?use_catalog=false" \
  -H 'Content-Type: application/json' \
  -d "{\"scenario_id\":\"qa_custom_transport\",\"run_id\":${CUSTOM_RUN_ID},\"init_all_sectors\":true,\"steps\":[{\"step_index\":1,\"sector\":\"transport\",\"action\":\"load_increase\",\"params\":{\"amount\":${TRANSPORT_LOAD_AMOUNT}}}]}"
CUSTOM_BEFORE="$(json_get "$LAST_RESPONSE" "before")"
CUSTOM_RUN_ID_RESP="$(json_get "$LAST_RESPONSE" "run_id")"
CUSTOM_I_CL="$(json_get "$LAST_RESPONSE" "I_cl")"
CUSTOM_I_Q="$(json_get "$LAST_RESPONSE" "I_q")"
CUSTOM_CL_BEFORE="$(json_get "$LAST_RESPONSE" "method_cl_total_before")"
CUSTOM_CL_AFTER="$(json_get "$LAST_RESPONSE" "method_cl_total_after")"
echo "custom_before=${CUSTOM_BEFORE}, custom_run_id=${CUSTOM_RUN_ID_RESP}"

echo "custom transport-only diagnostics: I_cl=${CUSTOM_I_CL}, I_q=${CUSTOM_I_Q}, cl_before=${CUSTOM_CL_BEFORE}, cl_after=${CUSTOM_CL_AFTER}"
echo "NOTE: transport load scenario is intentionally an intra-sector control; with current dependency graph only energy propagates to other sectors, so I_cl/I_q may stay 0."

# 3b) Custom cascade scenario on separate run_id (explicit dependency checks)
request_json "run custom cascade scenario (isolated run_id)" -X POST "${SIM_BASE}/run_scenario?use_catalog=false" \
  -H 'Content-Type: application/json' \
  -d "{\"scenario_id\":\"qa_custom_energy_cascade\",\"run_id\":${CUSTOM_CASCADE_RUN_ID},\"init_all_sectors\":true,\"steps\":[{\"step_index\":1,\"sector\":\"energy\",\"action\":\"outage\",\"params\":{\"duration\":${OUTAGE_DURATION},\"reason\":\"custom_cascade\"}},{\"step_index\":2,\"sector\":\"water\",\"action\":\"dependency_check\",\"params\":{\"source_sector\":\"energy\",\"source_duration\":${OUTAGE_DURATION}}},{\"step_index\":3,\"sector\":\"transport\",\"action\":\"dependency_check\",\"params\":{\"source_sector\":\"energy\",\"source_duration\":${OUTAGE_DURATION}}}]}"
CUSTOM_CASCADE_I_CL="$(json_get "$LAST_RESPONSE" "I_cl")"
CUSTOM_CASCADE_I_Q="$(json_get "$LAST_RESPONSE" "I_q")"
echo "custom_cascade_indicators: I_cl=${CUSTOM_CASCADE_I_CL}, I_q=${CUSTOM_CASCADE_I_Q}, run_id=${CUSTOM_CASCADE_RUN_ID}"

# 4) Check init_all_sectors=true baseline equivalence with force=true on fresh run_ids
request_json "force init energy (equivalence run)" -X POST "${ENERGY_BASE}/init?scenario_id=${SCENARIO_ID}&run_id=${INIT_FORCE_RUN_ID}&force=true"
request_json "force init water (equivalence run)" -X POST "${WATER_BASE}/init?scenario_id=${SCENARIO_ID}&run_id=${INIT_FORCE_RUN_ID}&force=true"
request_json "force init transport (equivalence run)" -X POST "${TRANSPORT_BASE}/init?scenario_id=${SCENARIO_ID}&run_id=${INIT_FORCE_RUN_ID}&force=true"
request_json "risk after explicit force init" "${RISK_BASE}/current?scenario_id=${SCENARIO_ID}&run_id=${INIT_FORCE_RUN_ID}&method=quantitative"
FORCE_BASELINE="$(json_get "$LAST_RESPONSE" "total_risk")"

request_json "run_scenario init_all_sectors baseline check" -X POST "${SIM_BASE}/run_scenario?use_catalog=false" \
  -H 'Content-Type: application/json' \
  -d "{\"scenario_id\":\"qa_init_compare\",\"run_id\":${INIT_SCENARIO_RUN_ID},\"init_all_sectors\":true,\"steps\":[{\"step_index\":1,\"sector\":\"transport\",\"action\":\"load_increase\",\"params\":{\"amount\":0.0}}]}"
INIT_ALL_BEFORE="$(json_get "$LAST_RESPONSE" "before")"

assert_close "$FORCE_BASELINE" "$INIT_ALL_BEFORE" "1e-9"
echo "force_baseline=${FORCE_BASELINE}, init_all_before=${INIT_ALL_BEFORE}"

# 5) Monte Carlo (N>=100) + duration impact stats
request_json "monte_carlo" -X POST "${SIM_BASE}/monte_carlo" \
  -H 'Content-Type: application/json' \
  -d "{\"scenario_id\":\"${SCENARIO_ID}\",\"sector\":\"${MONTE_CARLO_SECTOR}\",\"mode\":\"real\",\"runs\":${MONTE_CARLO_RUNS},\"start_run_id\":${MONTE_CARLO_START_RUN_ID},\"duration_min\":${MONTE_CARLO_MIN_DURATION},\"duration_max\":${MONTE_CARLO_MAX_DURATION},\"initiator_action\":\"${MONTE_CARLO_ACTION}\",\"stochastic_scale\":${MONTE_CARLO_STOCHASTIC_SCALE}}"

JSON_MC="$LAST_RESPONSE" python - <<'PY'
import json
import os
import math
from statistics import fmean

obj = json.loads(os.environ["JSON_MC"])
runs = obj.get("runs_data", [])
if len(runs) < 100:
    raise SystemExit("Monte-Carlo result has less than 100 runs")

durations = [float(r["duration"]) for r in runs]
deltas = [float(r.get("delta_R", r.get("delta", 0.0))) for r in runs]

md = fmean(durations)
mr = fmean(deltas)
num = sum((d-md)*(r-mr) for d, r in zip(durations, deltas))
den_l = math.sqrt(sum((d-md)**2 for d in durations))
den_r = math.sqrt(sum((r-mr)**2 for r in deltas))
corr = num / (den_l * den_r) if den_l > 0 and den_r > 0 else float("nan")

bins = {
    "5-10": [r for d, r in zip(durations, deltas) if 5 <= d <= 10],
    "11-20": [r for d, r in zip(durations, deltas) if 11 <= d <= 20],
    "21-30": [r for d, r in zip(durations, deltas) if 21 <= d <= 30],
}
means = {k: (fmean(v) if v else None) for k, v in bins.items()}

print(f"MC diagnostics: corr(duration, ΔR)={corr:.6f}")
print("MC bin means ΔR:", means)
PY

# 5b) MC parity check with run_scenario for S1 at duration=30 (deterministic)
PARITY_RUN_ID="$((MONTE_CARLO_START_RUN_ID + MONTE_CARLO_RUNS + 1))"
MC_PARITY_START_RUN_ID="$((MONTE_CARLO_START_RUN_ID + MONTE_CARLO_RUNS + 1000))"

request_json "run_scenario parity baseline (S1, duration=30)" -X POST "${SIM_BASE}/run_scenario?use_catalog=true" \
  -H 'Content-Type: application/json' \
  -d "{\"scenario_id\":\"S1_energy_outage\",\"run_id\":${PARITY_RUN_ID},\"init_all_sectors\":true}"
PARITY_I_CL="$(json_get "$LAST_RESPONSE" "I_cl")"
PARITY_I_Q="$(json_get "$LAST_RESPONSE" "I_q")"
PARITY_AFTER="$(json_get "$LAST_RESPONSE" "after")"

request_json "mc parity deterministic (duration=30)" -X POST "${SIM_BASE}/monte_carlo" \
  -H 'Content-Type: application/json' \
  -d "{\"scenario_id\":\"S1_energy_outage\",\"sector\":\"energy\",\"mode\":\"real\",\"runs\":100,\"start_run_id\":${MC_PARITY_START_RUN_ID},\"duration_min\":30,\"duration_max\":30,\"initiator_action\":\"outage\",\"stochastic_scale\":0.0}"
MC_PARITY_AFTER="$(json_get "$LAST_RESPONSE" "runs_data.0.after")"
MC_PARITY_I_CL="$(json_get "$LAST_RESPONSE" "runs_data.0.I_cl")"
MC_PARITY_I_Q="$(json_get "$LAST_RESPONSE" "runs_data.0.I_q")"

assert_close "$PARITY_AFTER" "$MC_PARITY_AFTER" "1e-9"
if [[ "$PARITY_I_CL" != "1" || "$PARITY_I_Q" != "1" ]]; then
  echo "run_scenario parity baseline failed: expected I_cl=1 and I_q=1, got I_cl=${PARITY_I_CL}, I_q=${PARITY_I_Q}"
  exit 1
fi
if [[ "$MC_PARITY_I_CL" != "1" || "$MC_PARITY_I_Q" != "1" ]]; then
  echo "Monte-Carlo parity failed: expected I_cl=1 and I_q=1, got I_cl=${MC_PARITY_I_CL}, I_q=${MC_PARITY_I_Q}"
  exit 1
fi
echo "parity_ok: run_scenario_after=${PARITY_AFTER}, mc_after=${MC_PARITY_AFTER}, I_cl=${MC_PARITY_I_CL}, I_q=${MC_PARITY_I_Q}"

# 6) Negative checks
request_json "negative: unknown scenario" -X POST "${SIM_BASE}/run_scenario?use_catalog=true" \
  -H 'Content-Type: application/json' \
  -d '{"scenario_id":"UNKNOWN_SCENARIO","run_id":9999,"init_all_sectors":true}'

request_json "negative: monte_carlo invalid duration range" -X POST "${SIM_BASE}/monte_carlo" \
  -H 'Content-Type: application/json' \
  -d '{"scenario_id":"S1_energy_outage","sector":"energy","mode":"real","runs":100,"start_run_id":3000,"duration_min":20,"duration_max":10}'

request_json "negative: monte_carlo runs<100" -X POST "${SIM_BASE}/monte_carlo" \
  -H 'Content-Type: application/json' \
  -d '{"scenario_id":"S1_energy_outage","sector":"energy","mode":"real","runs":99,"start_run_id":3000,"duration_min":5,"duration_max":10}'

echo

echo "All scenario checks completed."
