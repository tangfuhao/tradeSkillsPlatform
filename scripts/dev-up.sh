#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEV_DIR="$ROOT/.dev"
PID_DIR="$DEV_DIR/pids"
LOG_DIR="$DEV_DIR/logs"
mkdir -p "$PID_DIR" "$LOG_DIR"

API_PORT=8000
RUNNER_PORT=8100
WEB_PORT=5173
API_HEALTH_URL="http://127.0.0.1:${API_PORT}/api/v1/health"
RUNNER_HEALTH_URL="http://127.0.0.1:${RUNNER_PORT}/healthz"
WEB_HEALTH_URL="http://127.0.0.1:${WEB_PORT}"

started_services=()

log() {
  printf '[dev-up] %s\n' "$*"
}

require_file() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    log "missing required file: $path"
    exit 1
  fi
}

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    log "missing required command: $cmd"
    exit 1
  fi
}

pid_file_for() {
  printf '%s/%s.pid' "$PID_DIR" "$1"
}

log_file_for() {
  printf '%s/%s.log' "$LOG_DIR" "$1"
}

pid_is_running() {
  local pid="$1"
  kill -0 "$pid" >/dev/null 2>&1
}

read_pid() {
  local name="$1"
  local pid_file
  pid_file="$(pid_file_for "$name")"
  if [[ -f "$pid_file" ]]; then
    cat "$pid_file"
  fi
}

listening_pid() {
  local port="$1"
  lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | head -n 1 || true
}

ensure_port_available() {
  local name="$1"
  local port="$2"
  local existing_pid
  existing_pid="$(listening_pid "$port")"
  if [[ -z "$existing_pid" ]]; then
    return 0
  fi

  local tracked_pid
  tracked_pid="$(read_pid "$name")"
  if [[ -n "$tracked_pid" && "$tracked_pid" == "$existing_pid" ]] && pid_is_running "$tracked_pid"; then
    return 0
  fi

  log "port $port is already in use by pid $existing_pid; stop that process before running dev-up"
  exit 1
}

wait_for_http() {
  local name="$1"
  local url="$2"
  local pid="$3"
  local timeout_seconds="$4"
  local log_file="$5"
  local elapsed=0

  while (( elapsed < timeout_seconds )); do
    if curl --silent --fail "$url" >/dev/null 2>&1; then
      return 0
    fi
    if ! pid_is_running "$pid"; then
      log "$name exited before becoming ready"
      if [[ -f "$log_file" ]]; then
        tail -n 40 "$log_file" || true
      fi
      exit 1
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done

  log "$name did not become ready within ${timeout_seconds}s"
  if [[ -f "$log_file" ]]; then
    tail -n 40 "$log_file" || true
  fi
  exit 1
}

cleanup_started_services() {
  local name pid pid_file
  for name in "${started_services[@]:-}"; do
    pid_file="$(pid_file_for "$name")"
    if [[ -f "$pid_file" ]]; then
      pid="$(cat "$pid_file")"
      if pid_is_running "$pid"; then
        kill "$pid" >/dev/null 2>&1 || true
      fi
      rm -f "$pid_file"
    fi
  done
}

trap cleanup_started_services ERR

start_service() {
  local name="$1"
  local cwd="$2"
  local health_url="$3"
  local port="$4"
  local timeout_seconds="$5"
  shift 5

  local pid_file log_file pid
  pid_file="$(pid_file_for "$name")"
  log_file="$(log_file_for "$name")"

  if [[ -f "$pid_file" ]]; then
    pid="$(cat "$pid_file")"
    if pid_is_running "$pid"; then
      log "$name already running with pid $pid"
      return 0
    fi
    rm -f "$pid_file"
  fi

  ensure_port_available "$name" "$port"

  log "starting $name"
  (
    cd "$cwd"
    nohup "$@" >"$log_file" 2>&1 < /dev/null &
    echo $! >"$pid_file"
  )

  pid="$(cat "$pid_file")"
  started_services+=("$name")
  wait_for_http "$name" "$health_url" "$pid" "$timeout_seconds" "$log_file"
  log "$name ready on $health_url"
}

require_cmd curl
require_cmd lsof
require_cmd npm
require_file "$ROOT/.venv/bin/python"
require_file "$ROOT/scripts/check_runner_env.py"
require_file "$ROOT/apps/api/.env"
require_file "$ROOT/services/agent-runner/.env"
require_file "$ROOT/apps/web/.env.local"
require_file "$ROOT/apps/web/package.json"
if [[ ! -d "$ROOT/apps/web/node_modules" ]]; then
  log "missing web dependencies at $ROOT/apps/web/node_modules; run 'make web-install' first"
  exit 1
fi

log "running Agent Runner environment checks"
"$ROOT/.venv/bin/python" "$ROOT/scripts/check_runner_env.py"

start_service \
  runner \
  "$ROOT/services/agent-runner" \
  "$RUNNER_HEALTH_URL" \
  "$RUNNER_PORT" \
  30 \
  "$ROOT/.venv/bin/python" -m uvicorn runner.main:app --reload --host 0.0.0.0 --port "$RUNNER_PORT"

start_service \
  api \
  "$ROOT/apps/api" \
  "$API_HEALTH_URL" \
  "$API_PORT" \
  120 \
  "$ROOT/.venv/bin/python" -m uvicorn app.main:app --reload --host 0.0.0.0 --port "$API_PORT"

start_service \
  web \
  "$ROOT/apps/web" \
  "$WEB_HEALTH_URL" \
  "$WEB_PORT" \
  30 \
  npm run dev -- --host 0.0.0.0 --port "$WEB_PORT"

trap - ERR

log "all services are ready"
log "web:    http://127.0.0.1:${WEB_PORT}"
log "api:    http://127.0.0.1:${API_PORT}/api/v1/health"
log "runner: http://127.0.0.1:${RUNNER_PORT}/healthz"
log "logs:   $LOG_DIR"
