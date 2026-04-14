from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from runner.config import settings
from runner.schemas import ExecuteRunRequest, ExecuteRunResponse
from runner.services.decision_engine import get_engine
from runner.services.startup_preflight import assert_startup_preflight


@asynccontextmanager
async def lifespan(_: FastAPI):
    assert_startup_preflight()
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    try:
        return engine.execute(payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
