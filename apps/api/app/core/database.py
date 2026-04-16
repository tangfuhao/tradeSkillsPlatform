from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


def _build_engine() -> Engine:
    url = make_url(settings.database_url)
    backend_name = url.get_backend_name()

    if backend_name == "sqlite":
        return create_engine(
            settings.database_url,
            connect_args={"check_same_thread": False},
            future=True,
        )

    if backend_name != "postgresql":
        return create_engine(settings.database_url, future=True, pool_pre_ping=True)

    connect_args: dict[str, Any] = {}
    engine_kwargs: dict[str, Any] = {
        "future": True,
        "pool_pre_ping": True,
    }

    connect_args["connect_timeout"] = settings.database_connect_timeout_seconds
    connect_args["application_name"] = settings.app_name
    engine_kwargs.update(
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout_seconds,
        pool_recycle=settings.database_pool_recycle_seconds,
        connect_args=connect_args,
    )

    return create_engine(settings.database_url, **engine_kwargs)


engine = _build_engine()


@event.listens_for(engine, "connect")
def _configure_connection(dbapi_connection, connection_record):  # noqa: ANN001, ARG001
    if engine.dialect.name != "postgresql":
        return

    cursor = dbapi_connection.cursor()
    cursor.execute(f"SET statement_timeout = {int(settings.database_statement_timeout_ms)}")
    cursor.execute(f"SET lock_timeout = {int(settings.database_lock_timeout_ms)}")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def bulk_operation_session(db: Session) -> Generator[None, None, None]:
    bind = db.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        yield
        return

    connection = db.connection()
    connection.exec_driver_sql(
        f"SET LOCAL statement_timeout = {int(settings.database_bulk_statement_timeout_ms)}"
    )
    yield


def get_pool_diagnostics() -> dict[str, Any]:
    pool = engine.pool
    diagnostics: dict[str, Any] = {
        "class": pool.__class__.__name__,
    }

    for name in ("size", "checkedin", "checkedout", "overflow"):
        accessor = getattr(pool, name, None)
        if callable(accessor):
            try:
                diagnostics[name] = accessor()
            except Exception:  # pragma: no cover - pool implementations vary
                diagnostics[name] = None
        else:
            diagnostics[name] = None

    status = getattr(pool, "status", None)
    if callable(status):
        try:
            diagnostics["status"] = status()
        except Exception:  # pragma: no cover - pool implementations vary
            diagnostics["status"] = None

    return diagnostics
