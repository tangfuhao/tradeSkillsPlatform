import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.schema import ensure_runtime_storage_compatible
from app.runtime.market_sync_queue import build_market_sync_queue
from app.runtime.market_sync_loop import market_sync_loop_manager
from app.services.market_data_sync import discover_local_csv_ingestion_jobs, run_startup_market_data_sync
from app.services.partitioning import ensure_market_candle_partitions
from app.services.utils import datetime_to_ms, utc_now


logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    def on_startup() -> None:
        storage_status = ensure_runtime_storage_compatible()
        logger.info(
            "Runtime storage ready: backend=%s revision=%s server=%s",
            storage_status["backend"],
            storage_status["current_revision"],
            storage_status["server_version"],
        )
        with SessionLocal() as db:
            partition_status = ensure_market_candle_partitions(db)
        logger.info("Ensured market candle partitions: %s", partition_status)
        with SessionLocal() as db:
            try:
                discovery_summary = discover_local_csv_ingestion_jobs(db)
                logger.info(
                    "Registered CSV ingest backlog: scanned=%s discovered=%s pending=%s running=%s failed=%s",
                    discovery_summary["scanned_count"],
                    discovery_summary["discovered_count"],
                    discovery_summary["backlog"]["pending_count"],
                    discovery_summary["backlog"]["running_count"],
                    discovery_summary["backlog"]["failed_count"],
                )
            except Exception:
                logger.exception("Failed to discover pending CSV ingest jobs.")
                if settings.startup_sync_require_success:
                    raise
        startup_sync_result = None
        if settings.market_sync_queue_enabled:
            try:
                queue = build_market_sync_queue()
                queue.enqueue_universe_refresh()
                queue.enqueue_coverage_aggregate()
                queue.close()
                logger.info("Queued initial market sync jobs for external worker.")
            except Exception:
                logger.exception("Failed to queue initial market sync jobs.")
                if settings.startup_sync_require_success:
                    raise
        else:
            if settings.startup_sync_blocking:
                with SessionLocal() as db:
                    try:
                        summary = run_startup_market_data_sync(db)
                        startup_sync_result = summary.get("sync_sweep_result")
                        logger.info("Startup market-data sync complete: %s", summary)
                    except Exception:
                        logger.exception("Startup market-data sync failed.")
                        if settings.startup_sync_require_success:
                            raise
            if startup_sync_result is not None:
                market_sync_loop_manager.record_sync_result(startup_sync_result)
            market_sync_loop_manager.start()
            if startup_sync_result is not None and startup_sync_result.is_healthy():
                try:
                    dispatch_results = market_sync_loop_manager.dispatch_current_coverage()
                    logger.info("Initial live eligibility evaluation complete: %s", dispatch_results)
                except Exception:
                    logger.exception("Initial live eligibility evaluation failed.")

    @app.on_event("shutdown")
    def on_shutdown() -> None:
        market_sync_loop_manager.shutdown()

    @app.get("/healthz")
    def healthz() -> dict:
        return {
            "status": "ok",
            "service": settings.app_name,
            "server_time_ms": datetime_to_ms(utc_now()),
        }

    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
