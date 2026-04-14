PYTHON ?= python3
PIP ?= $(PYTHON) -m pip
VENV_DIR ?= $(CURDIR)/.venv
VENV_PYTHON ?= $(CURDIR)/.venv/bin/python

.PHONY: bootstrap api-install api-dev runner-install runner-dev runner-check smoke-runner-provider web-install web-dev dev-up dev-down dev-status smoke-python smoke-web-json

bootstrap:
	./scripts/bootstrap-dev.sh

api-install:
	./scripts/bootstrap-dev.sh

api-dev:
	cd apps/api && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

runner-install:
	./scripts/bootstrap-dev.sh

runner-dev:
	cd services/agent-runner && uvicorn runner.main:app --reload --host 0.0.0.0 --port 8100

runner-check:
	$(VENV_PYTHON) scripts/check_runner_env.py

smoke-runner-provider:
	$(VENV_PYTHON) scripts/smoke_runner_provider.py

web-install:
	./scripts/bootstrap-dev.sh

web-dev:
	cd apps/web && npm run dev -- --host 0.0.0.0 --port 5173

dev-up:
	./scripts/dev-up.sh

dev-down:
	./scripts/dev-down.sh

dev-status:
	./scripts/dev-status.sh

smoke-python:
	$(VENV_PYTHON) scripts/check_runner_env.py
	$(VENV_PYTHON) -m compileall apps/api/app services/agent-runner/runner

smoke-web-json:
	$(PYTHON) -m json.tool apps/web/package.json >/dev/null
