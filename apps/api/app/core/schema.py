from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.engine import make_url

from app.core.config import SERVICE_ROOT, settings
from app.core.database import engine, get_pool_diagnostics
from app.services.partitioning import list_market_candle_partitions


ALEMBIC_INI_PATH = SERVICE_ROOT / "alembic.ini"


class RuntimeStorageCompatibilityError(RuntimeError):
    """Raised when the configured runtime database cannot safely serve traffic."""


def _build_alembic_config() -> Config:
    config = Config(str(ALEMBIC_INI_PATH))
    config.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    return config


@lru_cache(maxsize=1)
def get_required_schema_revision() -> str | None:
    script = ScriptDirectory.from_config(_build_alembic_config())
    return script.get_current_head()


def inspect_runtime_storage() -> dict[str, Any]:
    url = make_url(settings.database_url)
    status: dict[str, Any] = {
        "url": settings.safe_database_url,
        "backend": url.get_backend_name(),
        "driver": url.get_driver_name(),
        "status": "unknown",
        "server_version": None,
        "current_revision": None,
        "required_revision": get_required_schema_revision(),
        "compatible": False,
        "writable": False,
        "in_recovery": None,
        "pool": get_pool_diagnostics(),
        "market_candle_partitions": [],
        "error": None,
    }

    if status["backend"] != "postgresql":
        status["status"] = "unsupported_engine"
        status["error"] = f"TradeSkills requires PostgreSQL, got {status['backend']!r}."
        return status

    try:
        with engine.connect() as connection:
            status["server_version"] = connection.execute(text("SHOW server_version")).scalar_one()
            status["in_recovery"] = bool(connection.execute(text("SELECT pg_is_in_recovery()")).scalar_one())
            status["writable"] = not status["in_recovery"]
            context = MigrationContext.configure(connection)
            status["current_revision"] = context.get_current_revision()
        with engine.begin() as connection:
            from sqlalchemy.orm import Session

            session = Session(bind=connection, future=True)
            status["market_candle_partitions"] = list_market_candle_partitions(session)
            session.close()
    except SQLAlchemyError as exc:
        status["status"] = "unreachable"
        status["error"] = str(exc)
        return status

    status["compatible"] = status["current_revision"] == status["required_revision"]
    if not status["compatible"]:
        status["status"] = "stale_schema"
        status["error"] = (
            f"Expected schema revision {status['required_revision']}, "
            f"got {status['current_revision'] or 'unversioned'}."
        )
        return status

    if not status["writable"]:
        status["status"] = "read_only"
        status["error"] = "Connected PostgreSQL instance is in recovery/read-only mode."
        return status

    status["status"] = "ok"
    return status


def ensure_runtime_storage_compatible() -> dict[str, Any]:
    status = inspect_runtime_storage()
    if status["status"] != "ok":
        raise RuntimeStorageCompatibilityError(status["error"] or "Runtime storage is not compatible.")
    return status
