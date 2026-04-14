from fastapi import APIRouter

from app.core.config import settings
from app.runtime.scheduler import scheduler_manager
from app.schemas import HealthResponse
from app.services.utils import datetime_to_ms, utc_now


router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        name=settings.app_name,
        status="ok",
        database_url=settings.database_url,
        agent_runner_base_url=settings.agent_runner_base_url,
        scheduler_running=scheduler_manager.is_running(),
        active_scheduler_jobs=scheduler_manager.job_count(),
        server_time_ms=datetime_to_ms(utc_now()),
    )
