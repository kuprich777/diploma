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
: "${RUN_ID:=1001}"

: "${OUTAGE_DURATION:=30}"
: "${OUTAGE_REASON:=qa_manual_test}"
: "${TRANSPORT_LOAD_AMOUNT:=0.25}"

: "${MONTE_CARLO_RUNS:=5}"
: "${MONTE_CARLO_START_RUN_ID:=2000}"
: "${MONTE_CARLO_MIN_DURATION:=5}"
: "${MONTE_CARLO_MAX_DURATION:=30}"
: "${MONTE_CARLO_SECTOR:=energy}"
: "${MONTE_CARLO_ACTION:=outage}"

: "${RISK_METHOD:=quantitative}"

ENERGY_BASE="${BASE_PROTOCOL}://${HOST}:${ENERGY_PORT}/api/v1/energy"
WATER_BASE="${BASE_PROTOCOL}://${HOST}:${WATER_PORT}/api/v1/water"
TRANSPORT_BASE="${BASE_PROTOCOL}://${HOST}:${TRANSPORT_PORT}/api/v1/transport"
RISK_BASE="${BASE_PROTOCOL}://${HOST}:${RISK_PORT}/api/v1/risk"
SIM_BASE="${BASE_PROTOCOL}://${HOST}:${SIM_PORT}/api/v1/simulator"

call() {
  local title="$1"
  shift
  echo
  echo "===== ${title} ====="
  echo "curl $*"
  curl -sS "$@"
  echo
}

# 1) Init baseline states
call "init energy" -X POST "${ENERGY_BASE}/init?scenario_id=${SCENARIO_ID}&run_id=${RUN_ID}&force=true"
call "init water" -X POST "${WATER_BASE}/init?scenario_id=${SCENARIO_ID}&run_id=${RUN_ID}&force=true"
call "init transport" -X POST "${TRANSPORT_BASE}/init?scenario_id=${SCENARIO_ID}&run_id=${RUN_ID}&force=true"

# 2) Check baseline statuses
call "energy status" "${ENERGY_BASE}/status?scenario_id=${SCENARIO_ID}&run_id=${RUN_ID}"
call "water status" "${WATER_BASE}/status?scenario_id=${SCENARIO_ID}&run_id=${RUN_ID}"
call "transport status" "${TRANSPORT_BASE}/status?scenario_id=${SCENARIO_ID}&run_id=${RUN_ID}"

# 3) Baseline risk
call "risk before scenario" "${RISK_BASE}/current?scenario_id=${SCENARIO_ID}&run_id=${RUN_ID}&method=${RISK_METHOD}"

# 4) Manual outage scenario in energy + dependency checks
call "energy simulate_outage" -X POST \
  "${ENERGY_BASE}/simulate_outage?scenario_id=${SCENARIO_ID}&run_id=${RUN_ID}&step_index=1&action=outage" \
  -H 'Content-Type: application/json' \
  -d "{\"reason\":\"${OUTAGE_REASON}\",\"duration\":${OUTAGE_DURATION}}"

call "water check_energy_dependency" -X POST \
  "${WATER_BASE}/check_energy_dependency?scenario_id=${SCENARIO_ID}&run_id=${RUN_ID}&step_index=2&action=dependency_check"

call "transport check_energy_dependency" -X POST \
  "${TRANSPORT_BASE}/check_energy_dependency?scenario_id=${SCENARIO_ID}&run_id=${RUN_ID}&step_index=2&action=dependency_check"

# 5) Risk after outage
call "risk after outage" "${RISK_BASE}/current?scenario_id=${SCENARIO_ID}&run_id=${RUN_ID}&method=${RISK_METHOD}"

# 6) Run catalog scenario through scenario_simulator
call "simulator catalog" "${SIM_BASE}/catalog"

call "run catalog scenario" -X POST "${SIM_BASE}/run_scenario?use_catalog=true" \
  -H 'Content-Type: application/json' \
  -d "{\"scenario_id\":\"${SCENARIO_ID}\",\"run_id\":${RUN_ID},\"init_all_sectors\":true}"

# 7) Run custom scenario (transport load increase)
call "run custom scenario" -X POST "${SIM_BASE}/run_scenario?use_catalog=false" \
  -H 'Content-Type: application/json' \
  -d "{\"scenario_id\":\"qa_custom_transport\",\"run_id\":${RUN_ID},\"init_all_sectors\":true,\"steps\":[{\"step_index\":1,\"sector\":\"transport\",\"action\":\"load_increase\",\"params\":{\"amount\":${TRANSPORT_LOAD_AMOUNT}}}]}"

# 8) Monte Carlo scenario
call "monte_carlo" -X POST "${SIM_BASE}/monte_carlo" \
  -H 'Content-Type: application/json' \
  -d "{\"scenario_id\":\"${SCENARIO_ID}\",\"sector\":\"${MONTE_CARLO_SECTOR}\",\"mode\":\"real\",\"runs\":${MONTE_CARLO_RUNS},\"start_run_id\":${MONTE_CARLO_START_RUN_ID},\"duration_min\":${MONTE_CARLO_MIN_DURATION},\"duration_max\":${MONTE_CARLO_MAX_DURATION},\"initiator_action\":\"${MONTE_CARLO_ACTION}\"}"

# 9) Negative checks
call "negative: unknown scenario" -X POST "${SIM_BASE}/run_scenario?use_catalog=true" \
  -H 'Content-Type: application/json' \
  -d '{"scenario_id":"UNKNOWN_SCENARIO","run_id":9999,"init_all_sectors":true}'

call "negative: monte_carlo invalid duration range" -X POST "${SIM_BASE}/monte_carlo" \
  -H 'Content-Type: application/json' \
  -d '{"scenario_id":"S1_energy_outage","sector":"energy","mode":"real","runs":3,"start_run_id":3000,"duration_min":20,"duration_max":10}'
