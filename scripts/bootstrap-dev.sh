#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEV_DIR="$ROOT/.dev"
STATE_DIR="$DEV_DIR/bootstrap"
mkdir -p "$STATE_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-$ROOT/.venv}"
VENV_PYTHON="$VENV_DIR/bin/python"
PYTHON_DEPS_STAMP="$STATE_DIR/python-deps.sha256"
WEB_DEPS_STAMP="$STATE_DIR/web-deps.sha256"

API_REQUIREMENTS="$ROOT/apps/api/requirements.txt"
RUNNER_REQUIREMENTS="$ROOT/services/agent-runner/requirements.txt"
WEB_PACKAGE_JSON="$ROOT/apps/web/package.json"
WEB_PACKAGE_LOCK="$ROOT/apps/web/package-lock.json"
WEB_NODE_MODULES="$ROOT/apps/web/node_modules"

log() {
  printf '[bootstrap-dev] %s\n' "$*"
}

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    log "missing required command: $cmd"
    exit 1
  fi
}

require_file() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    log "missing required file: $path"
    exit 1
  fi
}

write_stamp() {
  local path="$1"
  local value="$2"
  local tmp_file
  tmp_file="$(mktemp "${path}.tmp.XXXXXX")"
  printf '%s\n' "$value" >"$tmp_file"
  mv "$tmp_file" "$path"
}

fingerprint_files() {
  "$PYTHON_BIN" - "$@" <<'PY'
import hashlib
import pathlib
import sys

digest = hashlib.sha256()
for raw_path in sys.argv[1:]:
    path = pathlib.Path(raw_path)
    digest.update(str(path).encode("utf-8"))
    digest.update(b"\0")
    digest.update(path.read_bytes())
    digest.update(b"\0")
print(digest.hexdigest())
PY
}

ensure_venv() {
  if [[ -x "$VENV_PYTHON" ]]; then
    return 0
  fi
  log "creating virtual environment at $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
}

python_dependencies_healthy() {
  if [[ ! -x "$VENV_PYTHON" ]]; then
    return 1
  fi
  "$VENV_PYTHON" - <<'PY' >/dev/null 2>&1
import importlib

modules = [
    "alembic",
    "apscheduler",
    "fastapi",
    "httpx",
    "jsonschema",
    "openai",
    "pydantic_settings",
    "psycopg",
    "sqlalchemy",
    "uvicorn",
]
for name in modules:
    importlib.import_module(name)
PY
}

ensure_python_dependencies() {
  local fingerprint current

  ensure_venv
  fingerprint="$(fingerprint_files "$API_REQUIREMENTS" "$RUNNER_REQUIREMENTS")"
  current="$(cat "$PYTHON_DEPS_STAMP" 2>/dev/null || true)"

  if [[ "$current" == "$fingerprint" ]] && python_dependencies_healthy; then
    log "python dependencies already up to date"
    return 0
  fi

  log "installing Python dependencies into $VENV_DIR"
  "$VENV_PYTHON" -m pip install \
    --disable-pip-version-check \
    -r "$API_REQUIREMENTS" \
    -r "$RUNNER_REQUIREMENTS"
  write_stamp "$PYTHON_DEPS_STAMP" "$fingerprint"
}

ensure_web_dependencies() {
  local fingerprint current
  local install_cmd=(npm install --no-audit --no-fund)
  local fingerprint_inputs=("$WEB_PACKAGE_JSON")

  if [[ -f "$WEB_PACKAGE_LOCK" ]]; then
    install_cmd=(npm ci --no-audit --no-fund)
    fingerprint_inputs+=("$WEB_PACKAGE_LOCK")
  fi

  fingerprint="$(fingerprint_files "${fingerprint_inputs[@]}")"
  current="$(cat "$WEB_DEPS_STAMP" 2>/dev/null || true)"

  if [[ "$current" == "$fingerprint" && -d "$WEB_NODE_MODULES" ]]; then
    log "web dependencies already up to date"
    return 0
  fi

  log "installing web dependencies"
  (
    cd "$ROOT/apps/web"
    # Cursor sometimes prepends its own Node binary to PATH. Ubuntu's packaged npm
    # expects the distro Node runtime/module layout; ensure we use /usr/bin/node.
    PATH="/usr/bin:$PATH" "${install_cmd[@]}"
  )
  write_stamp "$WEB_DEPS_STAMP" "$fingerprint"
}

main() {
  require_cmd "$PYTHON_BIN"
  require_cmd npm
  require_file "$API_REQUIREMENTS"
  require_file "$RUNNER_REQUIREMENTS"
  require_file "$WEB_PACKAGE_JSON"

  ensure_python_dependencies
  ensure_web_dependencies
  log "bootstrap complete"
}

main "$@"
