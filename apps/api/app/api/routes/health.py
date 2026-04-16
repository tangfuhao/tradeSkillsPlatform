from fastapi import APIRouter

from app.core.config import settings
from app.runtime.market_sync_loop import market_sync_loop_manager
from app.schemas import HealthResponse
from app.services.utils import datetime_to_ms, utc_now


router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    snapshot = market_sync_loop_manager.get_snapshot()
    return HealthResponse(
        name=settings.app_name,
        status="ok",
        database_url=settings.database_url,
        agent_runner_base_url=settings.agent_runner_base_url,
        market_sync_loop_running=snapshot.market_sync_loop_running,
        last_sync_started_at_ms=snapshot.last_sync_started_at_ms,
        last_sync_completed_at_ms=snapshot.last_sync_completed_at_ms,
        last_sync_status=snapshot.last_sync_status,
        last_sync_error=snapshot.last_sync_error,
        server_time_ms=datetime_to_ms(utc_now()),
    )
