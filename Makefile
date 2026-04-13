PYTHON ?= python3
PIP ?= $(PYTHON) -m pip

.PHONY: api-install api-dev runner-install runner-dev web-install web-dev smoke-python smoke-web-json

api-install:
	cd apps/api && $(PIP) install -r requirements.txt

api-dev:
	cd apps/api && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

runner-install:
	cd services/agent-runner && $(PIP) install -r requirements.txt

runner-dev:
	cd services/agent-runner && uvicorn runner.main:app --reload --host 0.0.0.0 --port 8100

web-install:
	cd apps/web && npm install

web-dev:
	cd apps/web && npm run dev -- --host 0.0.0.0 --port 5173

smoke-python:
	$(PYTHON) -m compileall apps/api/app services/agent-runner/runner

smoke-web-json:
	$(PYTHON) -m json.tool apps/web/package.json >/dev/null
