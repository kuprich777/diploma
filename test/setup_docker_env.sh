#!/usr/bin/env bash
set -euo pipefail

# Script builds and starts the Diploma docker environment.
#
# Usage examples:
#   bash test/setup_docker_env.sh
#   bash test/setup_docker_env.sh --stack energy
#   bash test/setup_docker_env.sh --stack full --no-cache
#   bash test/setup_docker_env.sh --stack full --down

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

STACK="full"
NO_CACHE=0
ONLY_BUILD=0
DO_DOWN=0

usage() {
  cat <<'USAGE'
Usage: bash test/setup_docker_env.sh [options]

Options:
  --stack <full|energy>   Which compose stack to run (default: full)
  --no-cache              Build images without using cache
  --build-only            Only build images, do not run containers
  --down                  Stop and remove current stack before build/up
  -h, --help              Show this help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --stack)
      STACK="${2:-}"
      shift 2
      ;;
    --no-cache)
      NO_CACHE=1
      shift
      ;;
    --build-only)
      ONLY_BUILD=1
      shift
      ;;
    --down)
      DO_DOWN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

COMPOSE_FILE="docker-compose.yml"
if [[ "$STACK" == "energy" ]]; then
  COMPOSE_FILE="docker-compose.energy.yml"
elif [[ "$STACK" != "full" ]]; then
  echo "Unsupported stack: $STACK"
  echo "Allowed values: full, energy"
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is not installed or not in PATH"
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "docker compose plugin is unavailable"
  exit 1
fi

COMPOSE_CMD=(docker compose -f "$COMPOSE_FILE")
BUILD_ARGS=()
if [[ "$NO_CACHE" -eq 1 ]]; then
  BUILD_ARGS+=(--no-cache)
fi

echo "Using compose file: $COMPOSE_FILE"

if [[ "$DO_DOWN" -eq 1 ]]; then
  echo "[1/3] Stopping and removing existing stack..."
  "${COMPOSE_CMD[@]}" down --remove-orphans
fi

echo "[2/3] Building images..."
"${COMPOSE_CMD[@]}" build "${BUILD_ARGS[@]}"

if [[ "$ONLY_BUILD" -eq 1 ]]; then
  echo "Build completed (build-only mode)."
  exit 0
fi

echo "[3/3] Starting environment..."
"${COMPOSE_CMD[@]}" up -d --remove-orphans

echo
echo "Environment started. Current status:"
"${COMPOSE_CMD[@]}" ps

echo
echo "Tip: use 'docker compose -f $COMPOSE_FILE logs -f <service>' to inspect logs."
