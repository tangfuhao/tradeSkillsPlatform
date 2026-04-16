from fastapi import APIRouter

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.schema import inspect_runtime_storage
from app.runtime.market_sync_loop import market_sync_loop_manager
from app.schemas import HealthResponse
from app.services.market_data_sync import get_csv_ingestion_backlog
from app.services.utils import datetime_to_ms, utc_now


router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    snapshot = market_sync_loop_manager.get_snapshot()
    database_status = inspect_runtime_storage()
    with SessionLocal() as db:
        ingest_backlog = get_csv_ingestion_backlog(db)
    overall_status = "ok" if database_status["status"] == "ok" else "degraded"
    return HealthResponse(
        name=settings.app_name,
        status=overall_status,
        database_url=settings.safe_database_url,
        database=database_status,
        agent_runner_base_url=settings.agent_runner_base_url,
        ingest_backlog=ingest_backlog,
        market_sync={
            "universe_active_count": snapshot.universe_active_count,
            "fresh_symbol_count": snapshot.fresh_symbol_count,
            "coverage_ratio": snapshot.coverage_ratio,
            "dispatch_as_of_ms": snapshot.last_successful_coverage_end_ms,
            "degraded": snapshot.degraded,
            "snapshot_age_ms": snapshot.snapshot_age_ms,
            "blocked_reason": snapshot.blocked_reason,
            "missing_symbol_count": snapshot.missing_symbol_count,
            "universe_version": snapshot.universe_version,
        },
        market_sync_loop_running=snapshot.market_sync_loop_running,
        last_sync_started_at_ms=snapshot.last_sync_started_at_ms,
        last_sync_completed_at_ms=snapshot.last_sync_completed_at_ms,
        last_sync_status=snapshot.last_sync_status,
        last_sync_error=snapshot.last_sync_error,
        server_time_ms=datetime_to_ms(utc_now()),
    )
