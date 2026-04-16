#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_DIR="$ROOT/.dev/pids"
LOG_DIR="$ROOT/.dev/logs"

listening_pid() {
  local port="$1"
  lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | head -n 1 || true
}

show_service() {
  local name="$1"
  local url="$2"
  local pid_file="$PID_DIR/$name.pid"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file")"
    if kill -0 "$pid" >/dev/null 2>&1; then
      printf '%-8s running pid=%s url=%s log=%s\n' "$name" "$pid" "$url" "$LOG_DIR/$name.log"
      return 0
    fi
  fi
  printf '%-8s stopped\n' "$name"
}

show_dependency() {
  local name="$1"
  local port="$2"
  local url="$3"
  local pid_file="$PID_DIR/$name.pid"
  local pid=""

  if [[ -f "$pid_file" ]]; then
    pid="$(cat "$pid_file")"
    if kill -0 "$pid" >/dev/null 2>&1; then
      printf '%-8s running pid=%s url=%s log=%s\n' "$name" "$pid" "$url" "$LOG_DIR/$name.log"
      return 0
    fi
  fi

  pid="$(listening_pid "$port")"
  if [[ -n "$pid" ]]; then
    printf '%-8s external pid=%s url=%s\n' "$name" "$pid" "$url"
    return 0
  fi

  printf '%-8s stopped\n' "$name"
}

show_dependency redis 6379 redis://127.0.0.1:6379
show_service runner http://127.0.0.1:8100/healthz
show_service api http://127.0.0.1:8000/api/v1/health
show_service worker background
show_service web http://127.0.0.1:5173
