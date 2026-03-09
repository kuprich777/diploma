#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   cp test/curl.env.example test/curl.env
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

: "${BASE_RUN_ID:=$(date +%s)}"
: "${DEFAULT_SCENARIOS:=S1_energy_outage,S2_water_outage,S3_transport_load}"
: "${MONTE_CARLO_RUNS:=100}"
: "${MONTE_CARLO_MIN_DURATION:=5}"
: "${MONTE_CARLO_MAX_DURATION:=30}"
: "${MONTE_CARLO_STOCHASTIC_SCALE:=0.15}"

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
cur = obj
for p in os.environ["JSON_PATH"].split('.'):
    cur = cur[int(p)] if p.isdigit() else cur[p]
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

init_all_services() {
  local scenario_id="$1"
  local run_id="$2"
  request_json "init energy (${scenario_id}:${run_id})" -X POST "${ENERGY_BASE}/init?scenario_id=${scenario_id}&run_id=${run_id}&force=true"
  request_json "init water (${scenario_id}:${run_id})" -X POST "${WATER_BASE}/init?scenario_id=${scenario_id}&run_id=${run_id}&force=true"
  request_json "init transport (${scenario_id}:${run_id})" -X POST "${TRANSPORT_BASE}/init?scenario_id=${scenario_id}&run_id=${run_id}&force=true"
}

run_catalog_scenario() {
  local scenario_id="$1"
  local run_id="$2"
  local seed="$3"

  request_json "run catalog scenario ${scenario_id} (run_id=${run_id}, seed=${seed})" -X POST "${SIM_BASE}/run_scenario?use_catalog=true" \
    -H 'Content-Type: application/json' \
    -d "{\"scenario_id\":\"${scenario_id}\",\"run_id\":${run_id},\"seed\":${seed},\"init_all_sectors\":true,\"stochastic_scale\":0.2}"

  local before after delta i_cl i_q steps_count
  before="$(json_get "$LAST_RESPONSE" "before")"
  after="$(json_get "$LAST_RESPONSE" "after")"
  delta="$(json_get "$LAST_RESPONSE" "delta")"
  i_cl="$(json_get "$LAST_RESPONSE" "I_cl")"
  i_q="$(json_get "$LAST_RESPONSE" "I_q")"
  steps_count="$(json_get "$LAST_RESPONSE" "steps" | python - <<'PY'
import json,sys
print(len(json.load(sys.stdin)))
PY
)"

  echo "summary[${scenario_id}] before=${before} after=${after} delta=${delta} I_cl=${i_cl} I_q=${i_q} steps=${steps_count}"
}

run_custom_queue_scenario() {
  local run_id="$1"
  local seed="$2"

  # Explicitly includes dependency checks to exercise new interaction behavior.
  request_json "run custom queue-heavy scenario (run_id=${run_id})" -X POST "${SIM_BASE}/run_scenario?use_catalog=false" \
    -H 'Content-Type: application/json' \
    -d "{\"scenario_id\":\"S_custom_matrix_queue\",\"run_id\":${run_id},\"seed\":${seed},\"init_all_sectors\":true,\"stochastic_scale\":0.3,\"steps\":[
      {\"step_index\":1,\"sector\":\"energy\",\"action\":\"outage\",\"params\":{\"duration\":25,\"reason\":\"queue_test\"}},
      {\"step_index\":2,\"sector\":\"water\",\"action\":\"dependency_check\",\"params\":{\"source_sector\":\"energy\",\"source_duration\":25}},
      {\"step_index\":3,\"sector\":\"transport\",\"action\":\"dependency_check\",\"params\":{\"source_sector\":\"energy\",\"source_duration\":25}},
      {\"step_index\":4,\"sector\":\"transport\",\"action\":\"load_increase\",\"params\":{\"amount\":0.2}}
    ]}"

  local after
  after="$(json_get "$LAST_RESPONSE" "after")"
  echo "summary[S_custom_matrix_queue] after=${after}"
}

run_monte_carlo() {
  local scenario_id="$1"
  local sector="$2"
  local start_run_id="$3"
  local seed="$4"

  request_json "monte_carlo ${scenario_id} (${sector})" -X POST "${SIM_BASE}/monte_carlo" \
    -H 'Content-Type: application/json' \
    -d "{\"scenario_id\":\"${scenario_id}\",\"sector\":\"${sector}\",\"mode\":\"real\",\"runs\":${MONTE_CARLO_RUNS},\"start_run_id\":${start_run_id},\"duration_min\":${MONTE_CARLO_MIN_DURATION},\"duration_max\":${MONTE_CARLO_MAX_DURATION},\"initiator_action\":\"outage\",\"stochastic_scale\":${MONTE_CARLO_STOCHASTIC_SCALE},\"base_seed\":${seed}}"

  local mean_delta p95 k_cl k_q
  mean_delta="$(json_get "$LAST_RESPONSE" "mean_delta")"
  p95="$(json_get "$LAST_RESPONSE" "p95_delta")"
  k_cl="$(json_get "$LAST_RESPONSE" "K_cl")"
  k_q="$(json_get "$LAST_RESPONSE" "K_q")"
  echo "mc[${scenario_id}] mean_delta=${mean_delta} p95=${p95} K_cl=${k_cl} K_q=${k_q}"
}

echo "Base run id: ${BASE_RUN_ID}"
request_json "simulator catalog" "${SIM_BASE}/catalog"

IFS=',' read -r -a SCENARIOS <<<"${DEFAULT_SCENARIOS}"
RUN_SEQ=0

for scenario in "${SCENARIOS[@]}"; do
  run_id=$((BASE_RUN_ID + 10 + RUN_SEQ))
  seed=$((BASE_RUN_ID + 100 + RUN_SEQ))
  run_catalog_scenario "$scenario" "$run_id" "$seed"

  case "$scenario" in
    S1_*) mc_sector="energy" ;;
    S2_*) mc_sector="water" ;;
    S3_*) mc_sector="transport" ;;
    *) mc_sector="energy" ;;
  esac

  run_monte_carlo "$scenario" "$mc_sector" "$((BASE_RUN_ID + 1000 + RUN_SEQ * 200))" "$((BASE_RUN_ID + 2000 + RUN_SEQ * 200))"
  RUN_SEQ=$((RUN_SEQ + 1))
done

# Additional custom scenario for matrix/queue interaction.
run_custom_queue_scenario "$((BASE_RUN_ID + 500))" "$((BASE_RUN_ID + 900))"

# Baseline consistency check for init_all_sectors equivalence.
INIT_COMPARE_RUN_ID="$((BASE_RUN_ID + 700))"
init_all_services "S_init_compare" "$INIT_COMPARE_RUN_ID"
request_json "risk baseline after explicit init" "${RISK_BASE}/current?scenario_id=S_init_compare&run_id=${INIT_COMPARE_RUN_ID}&method=quantitative"
FORCE_BASELINE="$(json_get "$LAST_RESPONSE" "total_risk")"

request_json "run_scenario baseline check with init_all_sectors" -X POST "${SIM_BASE}/run_scenario?use_catalog=false" \
  -H 'Content-Type: application/json' \
  -d "{\"scenario_id\":\"S_init_compare\",\"run_id\":$((INIT_COMPARE_RUN_ID + 1)),\"seed\":$((BASE_RUN_ID + 701)),\"init_all_sectors\":true,\"steps\":[{\"step_index\":1,\"sector\":\"transport\",\"action\":\"load_increase\",\"params\":{\"amount\":0.0}}]}"
INIT_ALL_BEFORE="$(json_get "$LAST_RESPONSE" "before")"
assert_close "$FORCE_BASELINE" "$INIT_ALL_BEFORE" "1e-9"

echo
echo "All updated scenario checks completed."
