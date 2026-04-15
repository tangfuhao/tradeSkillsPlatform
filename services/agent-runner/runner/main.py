from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from runner.config import settings
from runner.schemas import (
    ExecuteRunRequest,
    ExecuteRunResponse,
    SkillEnvelopeExtractRequest,
    SkillEnvelopeExtractResponse,
)
from runner.services.decision_engine import get_engine
from runner.services.runtime_errors import to_http_exception
from runner.services.skill_envelope_runtime import OpenAISkillEnvelopeExtractionEngine
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
        raise to_http_exception(exc) from exc


@app.post("/v1/skills/extract-envelope", response_model=SkillEnvelopeExtractResponse)
def extract_skill_envelope(payload: SkillEnvelopeExtractRequest) -> SkillEnvelopeExtractResponse:
    engine = OpenAISkillEnvelopeExtractionEngine()
    try:
        return engine.extract(payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise to_http_exception(exc) from exc
