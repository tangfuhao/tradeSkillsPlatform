#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_DIR="$ROOT/.dev/pids"

WEB_PORT=5173
API_PORT=8000
RUNNER_PORT=8100
REDIS_PORT=6379
POSTGRES_PORT=5432

log() {
  printf '[dev-down] %s\n' "$*"
}

pid_is_running() {
  local pid="$1"
  kill -0 "$pid" >/dev/null 2>&1
}

# Return the PID listening on the given TCP port, or empty string if none.
listening_pid() {
  local port="$1"
  lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | head -n 1 || true
}

kill_pid() {
  local name="$1"
  local pid="$2"
  local pid_file="$PID_DIR/$name.pid"

  log "stopping $name (pid $pid)"
  kill "$pid" >/dev/null 2>&1 || true

  for _ in {1..10}; do
    if ! pid_is_running "$pid"; then
      rm -f "$pid_file"
      log "$name stopped"
      return 0
    fi
    sleep 1
  done

  log "$name did not stop gracefully; sending SIGKILL"
  kill -9 "$pid" >/dev/null 2>&1 || true
  rm -f "$pid_file"
}

# kill_port_orphan <name> <port>
# If anything is still listening on the port (e.g. a child process that
# survived after the tracked parent was killed), terminate it.
kill_port_orphan() {
  local name="$1"
  local port="$2"
  local orphan
  orphan="$(listening_pid "$port")"
  if [[ -n "$orphan" ]]; then
    log "$name orphan process still on port $port (pid $orphan); killing"
    kill "$orphan" >/dev/null 2>&1 || true
    for _ in {1..5}; do
      if ! pid_is_running "$orphan"; then
        return 0
      fi
      sleep 1
    done
    kill -9 "$orphan" >/dev/null 2>&1 || true
  fi
}

# stop_service <name> [port]
# Stops a service by pid file. If no pid file is found and a port is supplied,
# falls back to killing whatever process is listening on that port.
# After killing the tracked pid, also cleans up any port-level orphan (e.g.
# a child process spawned by the tracked parent, such as npm -> node/vite).
stop_service() {
  local name="$1"
  local port="${2:-}"
  local pid_file="$PID_DIR/$name.pid"
  local pid

  if [[ -f "$pid_file" ]]; then
    pid="$(cat "$pid_file")"
    if pid_is_running "$pid"; then
      kill_pid "$name" "$pid"
    else
      rm -f "$pid_file"
      log "$name already stopped"
    fi
    # Even if the tracked pid is gone, a child process may still hold the port.
    if [[ -n "$port" ]]; then
      kill_port_orphan "$name" "$port"
    fi
    return 0
  fi

  # No pid file — try the port fallback when a port was supplied.
  if [[ -n "$port" ]]; then
    pid="$(listening_pid "$port")"
    if [[ -n "$pid" ]]; then
      log "$name pid file missing; found orphan process on port $port"
      kill_pid "$name" "$pid"
      return 0
    fi
  fi

  log "$name not running (no pid file)"
}

stop_service web    "$WEB_PORT"
stop_service worker
stop_service api    "$API_PORT"
stop_service runner "$RUNNER_PORT"
stop_service redis  "$REDIS_PORT"
stop_service postgres "$POSTGRES_PORT"
