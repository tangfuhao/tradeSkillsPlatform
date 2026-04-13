from fastapi import FastAPI

from runner.config import settings
from runner.schemas import ExecuteRunRequest, ExecuteRunResponse
from runner.services.decision_engine import get_engine


app = FastAPI(title=settings.app_name, version="0.1.0")


@app.get("/healthz")
def healthz() -> dict:
    return {
        "status": "ok",
        "service": settings.app_name,
        "provider": settings.provider,
    }


@app.post("/v1/runs/execute", response_model=ExecuteRunResponse)
def execute_run(payload: ExecuteRunRequest) -> ExecuteRunResponse:
    engine = get_engine()
    return engine.execute(payload)
