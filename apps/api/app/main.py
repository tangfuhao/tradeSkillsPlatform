import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from app.api.router import api_router
from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
from app.runtime.scheduler import scheduler_manager
from app.services.market_data_sync import run_startup_market_data_sync
from app.services.utils import datetime_to_ms, utc_now


logger = logging.getLogger(__name__)


def ensure_runtime_schema() -> None:
    inspector = inspect(engine)
    if "backtest_runs" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("backtest_runs")}
    statements: list[str] = []

    if "total_trigger_count" not in existing_columns:
        statements.append("ALTER TABLE backtest_runs ADD COLUMN total_trigger_count INTEGER NOT NULL DEFAULT 0")
    if "completed_trigger_count" not in existing_columns:
        statements.append("ALTER TABLE backtest_runs ADD COLUMN completed_trigger_count INTEGER NOT NULL DEFAULT 0")
    if "control_requested" not in existing_columns:
        statements.append("ALTER TABLE backtest_runs ADD COLUMN control_requested VARCHAR(32)")
    if "last_processed_trace_index" not in existing_columns:
        statements.append("ALTER TABLE backtest_runs ADD COLUMN last_processed_trace_index INTEGER")
    if "last_processed_trigger_time_ms" not in existing_columns:
        statements.append("ALTER TABLE backtest_runs ADD COLUMN last_processed_trigger_time_ms BIGINT")

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
    logger.info("Applied runtime schema bootstrap statements: %s", len(statements))


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
        Base.metadata.create_all(bind=engine)
        ensure_runtime_schema()
        if settings.startup_sync_blocking:
            with SessionLocal() as db:
                try:
                    summary = run_startup_market_data_sync(db)
                    logger.info("Startup market-data sync complete: %s", summary)
                except Exception:
                    logger.exception("Startup market-data sync failed.")
                    if settings.startup_sync_require_success:
                        raise
        scheduler_manager.restore_live_tasks()

    @app.on_event("shutdown")
    def on_shutdown() -> None:
        scheduler_manager.shutdown()

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
