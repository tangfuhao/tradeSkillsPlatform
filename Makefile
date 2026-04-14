PYTHON ?= python3
PIP ?= $(PYTHON) -m pip
VENV_PYTHON ?= $(CURDIR)/.venv/bin/python

.PHONY: api-install api-dev runner-install runner-dev runner-check smoke-runner-provider web-install web-dev dev-up dev-down dev-status smoke-python smoke-web-json

api-install:
	cd apps/api && $(PIP) install -r requirements.txt

api-dev:
	cd apps/api && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

runner-install:
	cd services/agent-runner && $(PIP) install -r requirements.txt

runner-dev:
	cd services/agent-runner && uvicorn runner.main:app --reload --host 0.0.0.0 --port 8100

runner-check:
	$(VENV_PYTHON) scripts/check_runner_env.py

smoke-runner-provider:
	$(VENV_PYTHON) scripts/smoke_runner_provider.py

web-install:
	cd apps/web && npm install

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
