from __future__ import annotations

import csv
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import CsvIngestionJob, MarketCandle, MarketSyncCursor
from app.services.market_data_store import is_usdt_swap_symbol, parse_base_symbol
from app.services.utils import datetime_to_ms, ms_to_datetime, new_id, utc_now


logger = logging.getLogger(__name__)

BULK_BATCH_SIZE = 10_000
SQLITE_MAX_VARS = 900

_SECONDARY_INDEXES = [
    ("ix_market_candle_symbol_time", "market_candles", "(market_symbol, timeframe, open_time_ms)"),
    ("ix_market_candle_base_time", "market_candles", "(base_symbol, timeframe, open_time_ms)"),
    ("ix_market_candles_exchange", "market_candles", "(exchange)"),
    ("ix_market_candles_market_symbol", "market_candles", "(market_symbol)"),
    ("ix_market_candles_base_symbol", "market_candles", "(base_symbol)"),
    ("ix_market_candles_open_time_ms", "market_candles", "(open_time_ms)"),
]


def _drop_secondary_indexes(db: Session) -> None:
    for idx_name, _, _ in _SECONDARY_INDEXES:
        db.execute(text(f"DROP INDEX IF EXISTS {idx_name}"))
    db.commit()
    logger.info("Dropped %d secondary indexes for bulk import.", len(_SECONDARY_INDEXES))


def _rebuild_secondary_indexes(db: Session) -> None:
    for idx_name, table, columns in _SECONDARY_INDEXES:
        db.execute(text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} {columns}"))
    db.commit()
    logger.info("Rebuilt %d secondary indexes after bulk import.", len(_SECONDARY_INDEXES))


def run_startup_market_data_sync(db: Session) -> dict[str, Any]:
    started_at = utc_now()
    imported_files = import_local_csv_seed_data(db)
    synced_symbols = sync_incremental_okx_history(db)
    finished_at = utc_now()
    return {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "imported_files": imported_files,
        "synced_symbols": synced_symbols,
        "target_cutoff": compute_sync_cutoff().isoformat(),
    }


def import_local_csv_seed_data(db: Session) -> int:
    csv_paths = sorted(settings.historical_data_dir.glob(settings.historical_csv_glob))
    pending_paths: list[tuple[Path, str]] = []
    for path in csv_paths:
        fingerprint = build_source_fingerprint(path)
        existing = db.scalar(
            select(CsvIngestionJob).where(
                CsvIngestionJob.source_fingerprint == fingerprint,
                CsvIngestionJob.status == "completed",
            )
        )
        if existing is not None:
            continue
        pending_paths.append((path, fingerprint))

    if not pending_paths:
        return 0

    logger.info("Bulk CSV import: %d files to process. Dropping secondary indexes...", len(pending_paths))
    _drop_secondary_indexes(db)

    imported_count = 0
    try:
        for path, fingerprint in pending_paths:
            ingest_csv_file(db, path, fingerprint)
            imported_count += 1
    finally:
        logger.info("Rebuilding secondary indexes...")
        _rebuild_secondary_indexes(db)

    return imported_count


def ingest_csv_file(db: Session, path: Path, fingerprint: str) -> None:
    logger.info("Importing historical CSV seed: %s", path)
    job = db.scalar(select(CsvIngestionJob).where(CsvIngestionJob.source_fingerprint == fingerprint))
    if job is None:
        job = CsvIngestionJob(
            id=new_id("csvjob"),
            source_path=str(path),
            source_fingerprint=fingerprint,
            status="running",
            started_at=utc_now(),
            notes_json={"timeframe": settings.historical_base_timeframe},
        )
        db.add(job)
        db.commit()
        db.refresh(job)
    else:
        job.source_path = str(path)
        job.status = "running"
        job.rows_seen = 0
        job.rows_filtered = 0
        job.rows_inserted = 0
        job.coverage_start_ms = None
        job.coverage_end_ms = None
        job.error_message = None
        job.started_at = utc_now()
        job.completed_at = None
        job.notes_json = {"timeframe": settings.historical_base_timeframe}
        db.add(job)
        db.commit()
        db.refresh(job)

    rows_seen = 0
    rows_filtered = 0
    rows_inserted = 0
    coverage_start_ms: int | None = None
    coverage_end_ms: int | None = None
    batch: list[dict[str, Any]] = []
    now = utc_now()

    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for raw_row in reader:
                rows_seen += 1
                normalized = normalize_csv_row(raw_row, now)
                if normalized is None:
                    rows_filtered += 1
                    continue
                ot = normalized["open_time_ms"]
                coverage_start_ms = ot if coverage_start_ms is None else min(coverage_start_ms, ot)
                coverage_end_ms = ot if coverage_end_ms is None else max(coverage_end_ms, ot)
                batch.append(normalized)
                if len(batch) >= BULK_BATCH_SIZE:
                    rows_inserted += _flush_batch(db, batch)
                    batch.clear()
            if batch:
                rows_inserted += _flush_batch(db, batch)
        db.commit()
    except Exception as exc:
        db.rollback()
        job.status = "failed"
        job.rows_seen = rows_seen
        job.rows_filtered = rows_filtered
        job.rows_inserted = rows_inserted
        job.error_message = str(exc)
        job.completed_at = utc_now()
        db.add(job)
        db.commit()
        raise

    job.status = "completed"
    job.rows_seen = rows_seen
    job.rows_filtered = rows_filtered
    job.rows_inserted = rows_inserted
    job.coverage_start_ms = coverage_start_ms
    job.coverage_end_ms = coverage_end_ms
    job.completed_at = utc_now()
    db.add(job)
    db.commit()
    logger.info(
        "CSV import completed: %s (rows_seen=%s rows_inserted=%s rows_filtered=%s)",
        path.name, rows_seen, rows_inserted, rows_filtered,
    )


def _flush_batch(db: Session, batch: list[dict[str, Any]]) -> int:
    """Execute insert statements for a batch without committing (caller commits)."""
    if not batch:
        return 0
    column_count = max(len(batch[0]), 1)
    chunk_size = max(SQLITE_MAX_VARS // column_count, 1)
    total = 0
    for i in range(0, len(batch), chunk_size):
        chunk = batch[i : i + chunk_size]
        stmt = sqlite_insert(MarketCandle).values(chunk)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["exchange", "market_symbol", "timeframe", "open_time_ms"]
        )
        result = db.execute(stmt)
        total += int(result.rowcount or 0)
    return total


def insert_candle_batch(db: Session, batch: list[dict[str, Any]]) -> int:
    """Public API used by OKX incremental sync (commits per batch)."""
    total = _flush_batch(db, batch)
    db.commit()
    return total


def normalize_csv_row(row: dict[str, str], now: datetime | None = None) -> dict[str, Any] | None:
    market_symbol = (row.get("instrument_name") or "").strip()
    if not market_symbol or not is_usdt_swap_symbol(market_symbol):
        return None
    if (row.get("confirm") or "0").strip() != "1":
        return None
    open_time_ms = int(row["open_time"])
    base_symbol = parse_base_symbol(market_symbol)
    ts = now or utc_now()
    return {
        "exchange": "okx",
        "market_symbol": market_symbol,
        "base_symbol": base_symbol,
        "quote_asset": "USDT",
        "instrument_type": "SWAP",
        "timeframe": settings.historical_base_timeframe,
        "open_time_ms": open_time_ms,
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "vol": float(row["vol"] or 0),
        "vol_ccy": parse_optional_float(row.get("vol_ccy")),
        "vol_quote": parse_optional_float(row.get("vol_quote")),
        "confirm": True,
        "is_old_contract": "#OLD#" in market_symbol,
        "source": "csv",
        "created_at": ts,
        "updated_at": ts,
    }


def compute_sync_cutoff(now: datetime | None = None) -> datetime:
    current = now or utc_now()
    target_date = (current - timedelta(days=settings.startup_sync_target_offset_days)).date()
    return datetime(target_date.year, target_date.month, target_date.day, 23, 59, tzinfo=timezone.utc)


def sync_incremental_okx_history(db: Session) -> int:
    if not settings.okx_incremental_sync_enabled:
        logger.info("OKX incremental sync is disabled by configuration; skipping startup API catch-up.")
        return 0

    active_symbols = fetch_okx_active_usdt_swap_symbols()
    if not active_symbols:
        logger.warning("No active OKX USDT swap instruments were returned; skipping API sync.")
        return 0

    known_symbols = set(
        db.scalars(
            select(MarketCandle.base_symbol)
            .where(MarketCandle.timeframe == settings.historical_base_timeframe)
            .distinct()
        ).all()
    )
    sync_symbols = sorted(symbol for symbol in known_symbols if symbol in active_symbols)
    cutoff_ms = datetime_to_ms(compute_sync_cutoff())
    synced_count = 0
    for base_symbol in sync_symbols:
        latest_local_ms = db.scalar(
            select(func.max(MarketCandle.open_time_ms)).where(
                MarketCandle.base_symbol == base_symbol,
                MarketCandle.market_symbol == base_symbol,
                MarketCandle.timeframe == settings.historical_base_timeframe,
            )
        )
        if latest_local_ms is None:
            continue
        gap_days = max((cutoff_ms - latest_local_ms) / (24 * 60 * 60_000), 0)
        if gap_days > settings.okx_incremental_max_gap_days:
            upsert_sync_cursor(
                db,
                base_symbol,
                latest_local_ms,
                "skipped",
                {
                    "reason": "gap_too_large_for_incremental_api_sync",
                    "gap_days": round(gap_days, 2),
                    "max_gap_days": settings.okx_incremental_max_gap_days,
                },
            )
            continue
        if latest_local_ms >= cutoff_ms:
            upsert_sync_cursor(db, base_symbol, latest_local_ms, "completed", {"reason": "already_current"})
            continue
        inserted_rows, last_synced_ms = sync_symbol_from_okx(db, base_symbol, latest_local_ms, cutoff_ms)
        upsert_sync_cursor(
            db,
            base_symbol,
            last_synced_ms,
            "completed",
            {"inserted_rows": inserted_rows, "cutoff_ms": cutoff_ms},
        )
        synced_count += 1
    return synced_count


def sync_symbol_from_okx(db: Session, base_symbol: str, latest_local_ms: int, cutoff_ms: int) -> tuple[int, int]:
    cursor_ms = latest_local_ms
    inserted_rows = 0
    while cursor_ms < cutoff_ms:
        candles = fetch_okx_history_candles(base_symbol, cursor_ms)
        if not candles:
            break
        parsed_rows: list[dict[str, Any]] = []
        next_cursor_ms = cursor_ms
        now = utc_now()
        for item in candles:
            open_time_ms = int(item[0])
            next_cursor_ms = max(next_cursor_ms, open_time_ms)
            if open_time_ms <= cursor_ms or open_time_ms > cutoff_ms:
                continue
            parsed_rows.append(
                {
                    "exchange": "okx",
                    "market_symbol": base_symbol,
                    "base_symbol": base_symbol,
                    "quote_asset": "USDT",
                    "instrument_type": "SWAP",
                    "timeframe": settings.historical_base_timeframe,
                    "open_time_ms": open_time_ms,
                    "open": float(item[1]),
                    "high": float(item[2]),
                    "low": float(item[3]),
                    "close": float(item[4]),
                    "vol": float(item[5] or 0),
                    "vol_ccy": parse_optional_float(item[6]),
                    "vol_quote": parse_optional_float(item[7]),
                    "confirm": str(item[8]) == "1",
                    "is_old_contract": False,
                    "source": "okx_history_api",
                    "created_at": now,
                    "updated_at": now,
                }
            )
        if parsed_rows:
            inserted_rows += insert_candle_batch(db, parsed_rows)
        if next_cursor_ms <= cursor_ms:
            break
        cursor_ms = next_cursor_ms
        time.sleep(settings.okx_request_pause_seconds)
    logger.info(
        "OKX incremental sync finished for %s from %s to %s (inserted_rows=%s)",
        base_symbol,
        ms_to_datetime(latest_local_ms).isoformat(),
        ms_to_datetime(cursor_ms).isoformat(),
        inserted_rows,
    )
    return inserted_rows, cursor_ms


def fetch_okx_active_usdt_swap_symbols() -> set[str]:
    response = httpx.get(
        f"{settings.okx_api_base_url}/api/v5/public/instruments",
        params={"instType": "SWAP"},
        timeout=20.0,
    )
    response.raise_for_status()
    payload = response.json()
    items = payload.get("data", [])
    return {
        item.get("instId")
        for item in items
        if (item.get("instId") or "").endswith("-USDT-SWAP") and item.get("state") in {None, "live", "suspend"}
    }


def fetch_okx_history_candles(base_symbol: str, before_open_time_ms: int) -> list[list[Any]]:
    response = httpx.get(
        f"{settings.okx_api_base_url}/api/v5/market/history-candles",
        params={
            "instId": base_symbol,
            "bar": settings.historical_base_timeframe,
            "before": str(before_open_time_ms),
            "limit": str(settings.okx_history_limit),
        },
        timeout=20.0,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data", [])
    return list(reversed(data))


def upsert_sync_cursor(db: Session, base_symbol: str, last_synced_open_time_ms: int, status: str, notes: dict[str, Any]) -> None:
    cursor = db.scalar(
        select(MarketSyncCursor).where(
            MarketSyncCursor.exchange == "okx",
            MarketSyncCursor.base_symbol == base_symbol,
            MarketSyncCursor.timeframe == settings.historical_base_timeframe,
            MarketSyncCursor.source_kind == "okx_history_api",
        )
    )
    if cursor is None:
        cursor = MarketSyncCursor(
            id=new_id("cursor"),
            exchange="okx",
            base_symbol=base_symbol,
            timeframe=settings.historical_base_timeframe,
            source_kind="okx_history_api",
        )
    cursor.status = status
    cursor.last_synced_open_time_ms = last_synced_open_time_ms
    cursor.notes_json = notes
    cursor.last_sync_completed_at = utc_now()
    db.add(cursor)
    db.commit()


def build_source_fingerprint(path: Path) -> str:
    stat = path.stat()
    return f"{path.resolve()}::{stat.st_size}::{stat.st_mtime_ns}"


def parse_optional_float(value: str | float | None) -> float | None:
    if value in {None, "", "None", "null"}:
        return None
    return float(value)
