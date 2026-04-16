#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy import MetaData, Table, create_engine, func, inspect, select, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.sqltypes import Boolean, DateTime, JSON


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
DEFAULT_SOURCE_SQLITE_PATH = ROOT / "data" / "runtime" / "trade_skills.db"
ROW_BATCH_SIZE = 2_000
CANDLE_BATCH_SIZE = 25_000

APP = SimpleNamespace()

TABLE_ORDER = (
    "skills",
    "strategy_states",
    "backtest_runs",
    "live_tasks",
    "execution_strategy_states",
    "portfolio_books",
    "portfolio_positions",
    "portfolio_fills",
    "run_traces",
    "trace_execution_details",
    "live_signals",
    "market_instruments",
    "market_sync_states",
    "market_sync_attempts",
    "market_coverage_snapshots",
    "market_sync_cursors",
    "csv_ingestion_jobs",
    "market_candles",
)


@dataclass(slots=True)
class TableMigrationResult:
    table: str
    source_rows: int
    inserted_rows: int
    target_rows: int

    @property
    def verified(self) -> bool:
        return self.source_rows == self.target_rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="One-time migration of TradeSkills demo runtime data from SQLite to PostgreSQL."
    )
    parser.add_argument(
        "--source-sqlite-path",
        type=Path,
        default=DEFAULT_SOURCE_SQLITE_PATH,
        help=f"Path to the legacy SQLite runtime database (default: {DEFAULT_SOURCE_SQLITE_PATH}).",
    )
    parser.add_argument(
        "--target-database-url",
        default=None,
        help="Override TRADE_SKILLS_DATABASE_URL for the PostgreSQL target.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Skip inserts and only compare source/target counts plus market-candle coverage stats.",
    )
    parser.add_argument(
        "--allow-non-empty-target",
        action="store_true",
        help="Allow running against a target that already has data. Verification then compares absolute counts.",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=None,
        help="Optional path to write the migration summary as JSON.",
    )
    parser.add_argument(
        "--sample-symbol",
        default=None,
        help="Optional market symbol to use for sample-query parity checks (defaults to the densest symbol in SQLite).",
    )
    return parser.parse_args()


def init_app(target_database_url: str | None) -> None:
    if target_database_url:
        os.environ["TRADE_SKILLS_DATABASE_URL"] = target_database_url
    if str(API_ROOT) not in sys.path:
        sys.path.insert(0, str(API_ROOT))

    import app.models  # noqa: F401
    from app.core.database import Base, SessionLocal
    from app.models import MarketCandle
    from app.core.schema import ensure_runtime_storage_compatible
    from app.services.market_data_store import build_market_snapshot, fetch_candles, get_market_data_coverage_ranges
    from app.services.market_data_sync import insert_candle_batch
    from app.services.partitioning import ensure_market_candle_partitions
    from app.services.utils import datetime_to_ms, ensure_utc, ms_to_datetime, utc_now

    APP.Base = Base
    APP.MarketCandle = MarketCandle
    APP.SessionLocal = SessionLocal
    APP.ensure_runtime_storage_compatible = ensure_runtime_storage_compatible
    APP.build_market_snapshot = build_market_snapshot
    APP.fetch_candles = fetch_candles
    APP.get_market_data_coverage_ranges = get_market_data_coverage_ranges
    APP.insert_candle_batch = insert_candle_batch
    APP.ensure_market_candle_partitions = ensure_market_candle_partitions
    APP.datetime_to_ms = datetime_to_ms
    APP.ensure_utc = ensure_utc
    APP.ms_to_datetime = ms_to_datetime
    APP.utc_now = utc_now


def main() -> int:
    args = parse_args()
    init_app(args.target_database_url)

    source_path = args.source_sqlite_path.expanduser().resolve()
    if not source_path.is_file():
        raise SystemExit(f"SQLite source database does not exist: {source_path}")

    compatibility = APP.ensure_runtime_storage_compatible()
    print(
        f"Target PostgreSQL ready: {compatibility['url']} "
        f"(revision {compatibility['current_revision']})"
    )

    source_engine = create_engine(f"sqlite:///{source_path}", future=True)
    source_metadata = MetaData()
    source_metadata.reflect(bind=source_engine)

    source_tables = set(source_metadata.tables)
    target_tables = APP.Base.metadata.tables
    missing = [name for name in TABLE_ORDER if name not in source_tables and name != "market_candles"]
    if missing:
        print(f"Source SQLite is missing legacy tables that now exist only in PostgreSQL: {', '.join(missing)}")

    inspector = inspect(source_engine)
    available_source_tables = set(inspector.get_table_names())
    migration_tables = [name for name in TABLE_ORDER if name in available_source_tables]

    with source_engine.connect() as source_connection, APP.SessionLocal() as db:
        if not args.allow_non_empty_target and not args.verify_only:
            non_empty = _find_non_empty_target_tables(db, migration_tables, target_tables)
            if non_empty:
                formatted = ", ".join(f"{name}={count}" for name, count in non_empty.items())
                raise SystemExit(
                    "Refusing to migrate into a non-empty PostgreSQL target. "
                    f"Found rows in: {formatted}. Re-run with --allow-non-empty-target if this is intentional."
                )

        results: list[TableMigrationResult] = []
        for table_name in migration_tables:
            if table_name == "market_candles":
                result = migrate_market_candles(
                    db,
                    source_connection,
                    source_metadata.tables[table_name],
                    verify_only=args.verify_only,
                )
            else:
                result = migrate_regular_table(
                    db,
                    source_connection,
                    source_metadata.tables[table_name],
                    target_tables[table_name],
                    verify_only=args.verify_only,
                )
            results.append(result)
            print(
                f"{table_name}: source={result.source_rows} inserted={result.inserted_rows} "
                f"target={result.target_rows} verified={result.verified}"
            )

        coverage = compare_market_candle_coverage(source_connection, db)
        sample_query_parity = compare_sample_market_queries(
            source_engine,
            db,
            sample_symbol=args.sample_symbol,
        )
        summary = {
            "source_sqlite_path": str(source_path),
            "target_database_url": compatibility["url"],
            "verify_only": args.verify_only,
            "tables": [
                {
                    "table": item.table,
                    "source_rows": item.source_rows,
                    "inserted_rows": item.inserted_rows,
                    "target_rows": item.target_rows,
                    "verified": item.verified,
                }
                for item in results
            ],
            "market_candle_coverage": coverage,
            "sample_query_parity": sample_query_parity,
            "verified": (
                all(item.verified for item in results)
                and coverage["verified"]
                and sample_query_parity["verified"]
            ),
        }

        if args.report_path is not None:
            report_path = args.report_path.expanduser().resolve()
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
            print(f"Wrote migration report to {report_path}")

        print(json.dumps(summary, indent=2, ensure_ascii=True))
        return 0 if summary["verified"] else 1


def _find_non_empty_target_tables(
    db: Session,
    table_names: list[str],
    target_tables: dict[str, Table],
) -> dict[str, int]:
    non_empty: dict[str, int] = {}
    for table_name in table_names:
        target_table = target_tables[table_name]
        count = int(db.execute(select(func.count()).select_from(target_table)).scalar_one())
        if count:
            non_empty[table_name] = count
    return non_empty


def migrate_regular_table(
    db: Session,
    source_connection: Connection,
    source_table: Table,
    target_table: Table,
    *,
    verify_only: bool,
) -> TableMigrationResult:
    source_rows = int(source_connection.execute(select(func.count()).select_from(source_table)).scalar_one())
    inserted_rows = 0
    if not verify_only and source_rows:
        result = source_connection.execution_options(stream_results=True).execute(select(source_table))
        batch: list[dict[str, Any]] = []
        for raw_row in result.mappings():
            mapped_row = _transform_row(target_table.name, dict(raw_row))
            if mapped_row is None:
                continue
            batch.append(_normalize_for_target(target_table, mapped_row))
            if len(batch) >= ROW_BATCH_SIZE:
                inserted_rows += _insert_batch(db, target_table, batch)
                batch.clear()
        if batch:
            inserted_rows += _insert_batch(db, target_table, batch)

    target_rows = int(db.execute(select(func.count()).select_from(target_table)).scalar_one())
    return TableMigrationResult(
        table=target_table.name,
        source_rows=source_rows,
        inserted_rows=inserted_rows,
        target_rows=target_rows,
    )


def migrate_market_candles(
    db: Session,
    source_connection: Connection,
    source_table: Table,
    *,
    verify_only: bool,
) -> TableMigrationResult:
    source_rows, min_open_time_ms, max_open_time_ms = source_connection.execute(
        select(
            func.count(),
            func.min(source_table.c.open_time_ms),
            func.max(source_table.c.open_time_ms),
        )
    ).one()
    source_rows = int(source_rows or 0)
    inserted_rows = 0

    if source_rows and not verify_only:
        _prepare_candle_partitions(db, int(min_open_time_ms), int(max_open_time_ms))
        candle_columns = [column for column in source_table.columns if column.name != "id"]
        result = source_connection.execution_options(stream_results=True).execute(select(*candle_columns))
        batch: list[dict[str, Any]] = []
        for raw_row in result.mappings():
            batch.append(_transform_market_candle(dict(raw_row)))
            if len(batch) >= CANDLE_BATCH_SIZE:
                inserted_rows += int(APP.insert_candle_batch(db, batch))
                batch.clear()
        if batch:
            inserted_rows += int(APP.insert_candle_batch(db, batch))

    target_rows = int(
        db.execute(select(func.count()).select_from(APP.Base.metadata.tables["market_candles"])).scalar_one()
    )
    return TableMigrationResult(
        table="market_candles",
        source_rows=source_rows,
        inserted_rows=inserted_rows,
        target_rows=target_rows,
    )


def compare_market_candle_coverage(source_connection: Connection, db: Session) -> dict[str, Any]:
    source = source_connection.execute(
        text(
            """
        SELECT
            COUNT(*) AS row_count,
            MIN(open_time_ms) AS min_open_time_ms,
            MAX(open_time_ms) AS max_open_time_ms,
            COUNT(DISTINCT market_symbol) AS symbol_count
        FROM market_candles
        """
        )
    ).mappings().one()
    target_table = APP.Base.metadata.tables["market_candles"]
    target = db.execute(
        select(
            func.count().label("row_count"),
            func.min(target_table.c.open_time_ms).label("min_open_time_ms"),
            func.max(target_table.c.open_time_ms).label("max_open_time_ms"),
            func.count(func.distinct(target_table.c.market_symbol)).label("symbol_count"),
        )
    ).mappings().one()

    source_payload = {key: int(value) if value is not None else None for key, value in source.items()}
    target_payload = {key: int(value) if value is not None else None for key, value in target.items()}
    return {
        "source": source_payload,
        "target": target_payload,
        "verified": source_payload == target_payload,
    }


def compare_sample_market_queries(
    source_engine,
    db: Session,
    *,
    sample_symbol: str | None,
) -> dict[str, Any]:
    source_session_factory = sessionmaker(bind=source_engine, autoflush=False, autocommit=False, future=True)
    with source_session_factory() as source_db:
        effective_symbol = sample_symbol or _select_sample_symbol(source_db)
        if effective_symbol is None:
            return {"verified": True, "reason": "no_market_candles"}

        as_of_ms = _select_sample_as_of_ms(source_db, effective_symbol)
        if as_of_ms is None:
            return {"verified": True, "reason": "no_as_of_ms"}

        as_of = APP.ms_to_datetime(as_of_ms)
        source_payload = _build_sample_query_payload(source_db, effective_symbol, as_of)
        target_payload = _build_sample_query_payload(db, effective_symbol, as_of)
        return {
            "symbol": effective_symbol,
            "as_of_ms": as_of_ms,
            "source": source_payload,
            "target": target_payload,
            "verified": source_payload == target_payload,
        }


def _prepare_candle_partitions(db: Session, min_open_time_ms: int, max_open_time_ms: int) -> None:
    anchor = max(APP.ms_to_datetime(max_open_time_ms), APP.utc_now())
    minimum = APP.ms_to_datetime(min_open_time_ms)
    months_back = _month_distance(minimum, anchor)
    APP.ensure_market_candle_partitions(
        db,
        months_back=months_back,
        months_ahead=3,
        anchor=anchor,
    )


def _month_distance(start: datetime, end: datetime) -> int:
    start_month = datetime(start.year, start.month, 1, tzinfo=timezone.utc)
    end_month = datetime(end.year, end.month, 1, tzinfo=timezone.utc)
    return max(0, (end_month.year - start_month.year) * 12 + (end_month.month - start_month.month))


def _select_sample_symbol(db: Session) -> str | None:
    row = db.execute(
        select(
            APP.MarketCandle.market_symbol,
            func.count().label("row_count"),
        )
        .where(APP.MarketCandle.timeframe == "1m")
        .group_by(APP.MarketCandle.market_symbol)
        .order_by(func.count().desc(), APP.MarketCandle.market_symbol.asc())
        .limit(1)
    ).first()
    return str(row[0]) if row is not None else None


def _select_sample_as_of_ms(db: Session, symbol: str) -> int | None:
    return db.scalar(
        select(func.max(APP.MarketCandle.open_time_ms)).where(
            APP.MarketCandle.market_symbol == symbol,
            APP.MarketCandle.timeframe == "1m",
        )
    )


def _build_sample_query_payload(db: Session, symbol: str, as_of: datetime) -> dict[str, Any]:
    candles = APP.fetch_candles(
        db,
        market_symbol=symbol,
        timeframe="15m",
        limit=5,
        end_time=as_of,
    )
    snapshot = APP.build_market_snapshot(db, as_of=as_of, limit=5)
    coverage_ranges = APP.get_market_data_coverage_ranges(db)
    return {
        "fetch_candles_15m": _normalize_payload(candles),
        "market_snapshot_top5": _normalize_payload(snapshot.get("market_candidates") or []),
        "coverage_ranges_top5": [
            {
                "start_ms": APP.datetime_to_ms(start),
                "end_ms": APP.datetime_to_ms(end),
            }
            for start, end in coverage_ranges[:5]
        ],
    }


def _insert_batch(db: Session, target_table: Table, batch: list[dict[str, Any]]) -> int:
    primary_key_columns = [column.name for column in target_table.primary_key.columns]
    stmt = postgresql_insert(target_table).values(batch)
    if primary_key_columns:
        stmt = stmt.on_conflict_do_nothing(index_elements=primary_key_columns)
        stmt = stmt.returning(*target_table.primary_key.columns)
    result = db.execute(stmt)
    db.commit()
    if primary_key_columns:
        return len(result.all())
    return int(result.rowcount or 0)


def _normalize_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalize_payload(val) for key, val in sorted(value.items())}
    if isinstance(value, list):
        return [_normalize_payload(item) for item in value]
    if isinstance(value, float):
        return round(value, 10)
    return value


def _transform_row(table_name: str, row: dict[str, Any]) -> dict[str, Any] | None:
    if table_name == "backtest_runs":
        return _transform_backtest_run(row)
    if table_name == "live_tasks":
        return _transform_live_task(row)
    if table_name == "live_signals":
        return _transform_live_signal(row)
    if table_name == "csv_ingestion_jobs":
        return _transform_csv_ingestion_job(row)
    return row


def _transform_backtest_run(row: dict[str, Any]) -> dict[str, Any]:
    status = str(row.get("status") or "queued")
    created_at = _coerce_datetime(row.get("created_at"))
    updated_at = _coerce_datetime(row.get("updated_at"))
    terminal_statuses = {"completed", "failed", "stopped"}
    started_statuses = terminal_statuses | {"running", "paused", "stopping"}
    row.update(
        revision=1,
        claim_token=None,
        claim_owner=None,
        claim_acquired_at=None,
        claim_expires_at=None,
        last_heartbeat_at=None,
        run_started_at=created_at if status in started_statuses else None,
        finished_at=updated_at if status in terminal_statuses else None,
    )
    return row


def _transform_live_task(row: dict[str, Any]) -> dict[str, Any]:
    row.update(
        revision=1,
        last_claimed_slot_as_of_ms=None,
        execution_claim_token=None,
        execution_claim_owner=None,
        execution_claimed_at=None,
        execution_claim_expires_at=None,
    )
    return row


def _transform_live_signal(row: dict[str, Any]) -> dict[str, Any]:
    signal_json = _coerce_json(row.get("signal_json")) or {}
    trigger_time = _coerce_datetime(row.get("trigger_time"))
    execution_time_ms = signal_json.get("execution_time_ms")
    if not isinstance(execution_time_ms, int) and trigger_time is not None:
        execution_time_ms = APP.datetime_to_ms(trigger_time)
    coverage = signal_json.get("coverage") if isinstance(signal_json, dict) else {}
    dispatch_as_of_ms = signal_json.get("dispatch_as_of_ms")
    if dispatch_as_of_ms is None and isinstance(coverage, dict):
        dispatch_as_of_ms = coverage.get("dispatch_as_of_ms")
    row.update(
        signal_json=signal_json,
        execution_time_ms=execution_time_ms,
        dispatch_as_of_ms=dispatch_as_of_ms,
        trigger_origin=str(signal_json.get("trigger_origin") or "manual"),
    )
    return row


def _transform_csv_ingestion_job(row: dict[str, Any]) -> dict[str, Any]:
    started_at = _coerce_datetime(row.get("started_at"))
    completed_at = _coerce_datetime(row.get("completed_at"))
    requested_at = started_at or completed_at or APP.utc_now()
    rows_inserted = int(row.get("rows_inserted") or 0)
    row.update(
        requested_at=requested_at,
        runner_id=None,
        rows_staged=rows_inserted,
    )
    return row


def _transform_market_candle(row: dict[str, Any]) -> dict[str, Any]:
    row.pop("id", None)
    return {
        **row,
        "confirm": _coerce_bool(row.get("confirm")),
        "is_old_contract": _coerce_bool(row.get("is_old_contract")),
        "created_at": _coerce_datetime(row.get("created_at")),
        "updated_at": _coerce_datetime(row.get("updated_at")),
    }


def _normalize_for_target(target_table: Table, row: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for column in target_table.columns:
        if column.name not in row:
            continue
        normalized[column.name] = _coerce_value(column.type, row[column.name])
    return normalized


def _coerce_value(column_type: Any, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(column_type, JSON):
        return _coerce_json(value)
    if isinstance(column_type, Boolean):
        return _coerce_bool(value)
    if isinstance(column_type, DateTime):
        return _coerce_datetime(value)
    return value


def _coerce_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "t", "yes", "y"}:
        return True
    if normalized in {"0", "false", "f", "no", "n"}:
        return False
    return bool(value)


@lru_cache(maxsize=16_384)
def _parse_datetime_text(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    return APP.ensure_utc(parsed)


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return APP.ensure_utc(value)
    if isinstance(value, str):
        return _parse_datetime_text(value)
    raise TypeError(f"Unsupported datetime value: {value!r}")


@lru_cache(maxsize=16_384)
def _parse_json_text(value: str) -> Any:
    return json.loads(value)


def _coerce_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        return _parse_json_text(normalized)
    return value


if __name__ == "__main__":
    raise SystemExit(main())
