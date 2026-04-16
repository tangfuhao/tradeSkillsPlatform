#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_DIR="$ROOT/.dev/pids"

log() {
  printf '[dev-down] %s\n' "$*"
}

pid_is_running() {
  local pid="$1"
  kill -0 "$pid" >/dev/null 2>&1
}

stop_service() {
  local name="$1"
  local pid_file="$PID_DIR/$name.pid"
  local pid

  if [[ ! -f "$pid_file" ]]; then
    log "$name not running (no pid file)"
    return 0
  fi

  pid="$(cat "$pid_file")"
  if ! pid_is_running "$pid"; then
    rm -f "$pid_file"
    log "$name already stopped"
    return 0
  fi

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

stop_service web
stop_service worker
stop_service api
stop_service runner
