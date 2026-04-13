import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
from app.runtime.scheduler import scheduler_manager
from app.services.market_data_sync import run_startup_market_data_sync
from app.services.utils import utc_now


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
        Base.metadata.create_all(bind=engine)
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
            "server_time": utc_now().isoformat(),
        }

    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
