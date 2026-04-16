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
REDIS_PORT=6379
POSTGRES_PORT=5432
POSTGRES_DATA_DIR="$DEV_DIR/postgres-data"
LEGACY_SQLITE_PATH="$ROOT/data/runtime/trade_skills.db"
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

wait_for_port() {
  local name="$1"
  local port="$2"
  local pid="$3"
  local timeout_seconds="$4"
  local log_file="$5"
  local elapsed=0

  while (( elapsed < timeout_seconds )); do
    if [[ -n "$(listening_pid "$port")" ]]; then
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

  log "$name did not start listening on port $port within ${timeout_seconds}s"
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

ensure_postgres_cluster() {
  if [[ -d "$POSTGRES_DATA_DIR/base" ]]; then
    return 0
  fi

  require_cmd initdb
  mkdir -p "$POSTGRES_DATA_DIR"
  log "initializing local postgres cluster in $POSTGRES_DATA_DIR"
  initdb -D "$POSTGRES_DATA_DIR" >/dev/null
}

bootstrap_postgres_runtime_db() {
  require_cmd psql
  require_cmd createdb
  psql -h 127.0.0.1 -p "$POSTGRES_PORT" -d postgres -v ON_ERROR_STOP=1 <<'SQL' >/dev/null
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tradeskills') THEN
    CREATE ROLE tradeskills LOGIN PASSWORD 'tradeskills';
  END IF;
END
$$;
SQL

  if ! psql -h 127.0.0.1 -p "$POSTGRES_PORT" -lqt | cut -d '|' -f 1 | grep -qx ' tradeskills'; then
    createdb -h 127.0.0.1 -p "$POSTGRES_PORT" -O tradeskills tradeskills
  fi
}

warn_on_legacy_sqlite_runtime() {
  if [[ ! -f "$LEGACY_SQLITE_PATH" ]]; then
    return 0
  fi

  log "legacy SQLite runtime detected at $LEGACY_SQLITE_PATH"
  log "migrate demo data with: $ROOT/.venv/bin/python $ROOT/scripts/migrate_sqlite_to_postgres.py"
}

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

start_background_service() {
  local name="$1"
  local cwd="$2"
  shift 2

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

  log "starting $name"
  (
    cd "$cwd"
    nohup "$@" >"$log_file" 2>&1 < /dev/null &
    echo $! >"$pid_file"
  )

  pid="$(cat "$pid_file")"
  started_services+=("$name")
  sleep 2
  if ! pid_is_running "$pid"; then
    log "$name exited before becoming ready"
    tail -n 40 "$log_file" || true
    exit 1
  fi
  log "$name running with pid $pid"
}

start_port_service() {
  local name="$1"
  local cwd="$2"
  local port="$3"
  local timeout_seconds="$4"
  shift 4

  local pid_file log_file pid
  pid_file="$(pid_file_for "$name")"
  log_file="$(log_file_for "$name")"

  if [[ -f "$pid_file" ]]; then
    pid="$(cat "$pid_file")"
    if pid_is_running "$pid" && [[ -n "$(listening_pid "$port")" ]]; then
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
  wait_for_port "$name" "$port" "$pid" "$timeout_seconds" "$log_file"
  log "$name ready on port $port"
}

require_cmd curl
require_cmd lsof
require_cmd npm
require_cmd python3
require_file "$ROOT/scripts/bootstrap-dev.sh"
require_file "$ROOT/scripts/check_runner_env.py"
require_file "$ROOT/apps/api/.env"
require_file "$ROOT/apps/api/alembic.ini"
require_file "$ROOT/services/agent-runner/.env"
require_file "$ROOT/apps/web/.env.local"
require_file "$ROOT/apps/web/package.json"

if [[ -n "$(listening_pid "$POSTGRES_PORT")" ]]; then
  log "postgres already available on port $POSTGRES_PORT"
elif command -v postgres >/dev/null 2>&1 && command -v initdb >/dev/null 2>&1; then
  ensure_postgres_cluster
  start_port_service \
    postgres \
    "$ROOT" \
    "$POSTGRES_PORT" \
    20 \
    postgres -D "$POSTGRES_DATA_DIR" -p "$POSTGRES_PORT" -c listen_addresses=127.0.0.1
else
  log "postgres is required but nothing is listening on port $POSTGRES_PORT"
  log "install PostgreSQL locally or start a server on port $POSTGRES_PORT before running dev-up"
  exit 1
fi

bootstrap_postgres_runtime_db

if [[ -n "$(listening_pid "$REDIS_PORT")" ]]; then
  log "redis already available on port $REDIS_PORT"
elif command -v redis-server >/dev/null 2>&1; then
  start_port_service \
    redis \
    "$ROOT" \
    "$REDIS_PORT" \
    15 \
    redis-server --save "" --appendonly no --port "$REDIS_PORT"
else
  log "redis is required but nothing is listening on port $REDIS_PORT and redis-server is not installed"
  exit 1
fi

log "bootstrapping local environments and dependencies"
"$ROOT/scripts/bootstrap-dev.sh"
require_file "$ROOT/.venv/bin/python"
require_file "$ROOT/.venv/bin/alembic"

log "running PostgreSQL migrations"
(
  cd "$ROOT/apps/api"
  "$ROOT/.venv/bin/alembic" upgrade head
)
warn_on_legacy_sqlite_runtime

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

start_background_service \
  worker \
  "$ROOT/apps/api" \
  env TRADE_SKILLS_MARKET_SYNC_QUEUE_ENABLED=true TRADE_SKILLS_MARKET_SYNC_REDIS_URL=redis://127.0.0.1:6379/0 \
  "$ROOT/.venv/bin/python" -m app.runtime.market_sync_worker

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
log "worker: $LOG_DIR/worker.log"
log "logs:   $LOG_DIR"
