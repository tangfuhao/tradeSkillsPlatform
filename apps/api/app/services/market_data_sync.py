from __future__ import annotations

import csv
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import func, or_, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    CsvIngestionJob,
    MarketCandle,
    MarketCoverageSnapshot,
    MarketInstrument,
    MarketSyncAttempt,
    MarketSyncCursor,
    MarketSyncState,
)
from app.services.market_data_store import is_usdt_swap_symbol, parse_base_symbol, timeframe_to_ms
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


@dataclass(slots=True)
class MarketSyncSweepResult:
    success: bool
    status: str
    started_at_ms: int
    completed_at_ms: int
    coverage_start_ms_before: int | None = None
    coverage_end_ms_before: int | None = None
    coverage_start_ms_after: int | None = None
    coverage_end_ms_after: int | None = None
    advanced_coverage: bool = False
    inserted_rows: int = 0
    synced_symbols: int = 0
    failures: list[dict[str, Any]] = field(default_factory=list)
    error_message: str | None = None
    cutoff_ms: int | None = None
    universe_active_count: int = 0
    fresh_symbol_count: int = 0
    coverage_ratio: float = 0.0
    degraded: bool = False
    blocked_reason: str | None = None
    snapshot_age_ms: int | None = None
    missing_symbol_count: int = 0
    universe_version: int | None = None

    def is_healthy(self) -> bool:
        return self.status in {"succeeded", "no_advance"}

    def is_dispatchable(self) -> bool:
        return self.success and self.advanced_coverage and self.coverage_end_ms_after is not None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    target_cutoff = compute_startup_sync_cutoff()
    sync_sweep_result = sync_incremental_okx_history(db, cutoff=target_cutoff)
    finished_at = utc_now()
    return {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "imported_files": imported_files,
        "sync_sweep": sync_sweep_result.to_dict(),
        "sync_sweep_result": sync_sweep_result,
        "target_cutoff": target_cutoff.isoformat(),
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
        path.name,
        rows_seen,
        rows_inserted,
        rows_filtered,
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


def compute_startup_sync_cutoff(now: datetime | None = None) -> datetime:
    current = now or utc_now()
    target_date = (current - timedelta(days=settings.startup_sync_target_offset_days)).date()
    return datetime(target_date.year, target_date.month, target_date.day, 23, 59, tzinfo=timezone.utc)


def compute_live_sync_cutoff(now: datetime | None = None) -> datetime:
    current = now or utc_now()
    timeframe_ms = timeframe_to_ms(settings.historical_base_timeframe)
    current_ms = datetime_to_ms(current)
    latest_closed_open_time_ms = ((current_ms // timeframe_ms) * timeframe_ms) - timeframe_ms
    if latest_closed_open_time_ms < 0:
        latest_closed_open_time_ms = 0
    return ms_to_datetime(latest_closed_open_time_ms)


def get_market_data_coverage_ms(db: Session) -> tuple[int | None, int | None]:
    start_ms, end_ms = db.execute(
        select(func.min(MarketCandle.open_time_ms), func.max(MarketCandle.open_time_ms)).where(
            MarketCandle.timeframe == settings.historical_base_timeframe
        )
    ).one()
    return start_ms, end_ms


def sync_incremental_okx_history(db: Session, *, cutoff: datetime | None = None) -> MarketSyncSweepResult:
    started_at = utc_now()
    coverage_start_ms_before, coverage_end_ms_before = get_market_data_coverage_ms(db)
    effective_cutoff = cutoff or compute_startup_sync_cutoff(started_at)
    cutoff_ms = datetime_to_ms(effective_cutoff)

    if not settings.okx_incremental_sync_enabled:
        completed_at = utc_now()
        return MarketSyncSweepResult(
            success=False,
            status="disabled",
            started_at_ms=datetime_to_ms(started_at),
            completed_at_ms=datetime_to_ms(completed_at),
            coverage_start_ms_before=coverage_start_ms_before,
            coverage_end_ms_before=coverage_end_ms_before,
            coverage_start_ms_after=coverage_start_ms_before,
            coverage_end_ms_after=coverage_end_ms_before,
            error_message="OKX incremental sync is disabled by configuration.",
            cutoff_ms=cutoff_ms,
        )

    universe_version = datetime_to_ms(started_at)
    symbol_failures: list[dict[str, Any]] = []
    inserted_rows = 0
    synced_symbols = 0

    try:
        refresh_market_universe(db, universe_version=universe_version)
    except Exception as exc:
        completed_at = utc_now()
        return MarketSyncSweepResult(
            success=False,
            status="failed",
            started_at_ms=datetime_to_ms(started_at),
            completed_at_ms=datetime_to_ms(completed_at),
            coverage_start_ms_before=coverage_start_ms_before,
            coverage_end_ms_before=coverage_end_ms_before,
            coverage_start_ms_after=coverage_start_ms_before,
            coverage_end_ms_after=coverage_end_ms_before,
            error_message=str(exc),
            cutoff_ms=cutoff_ms,
            blocked_reason="universe_refresh_failed",
            universe_version=universe_version,
        )

    due_states = select_due_sync_states(db)
    for state in due_states[: settings.market_sync_cycle_symbol_limit]:
        sync_summary = sync_market_symbol(db, state.base_symbol, cutoff_ms=cutoff_ms)
        inserted_rows += int(sync_summary.get("inserted_rows") or 0)
        if sync_summary.get("status") == "completed":
            synced_symbols += 1
        if sync_summary.get("failure"):
            symbol_failures.append(sync_summary["failure"])

    coverage_snapshot = recompute_market_coverage_snapshot(db, universe_version=universe_version)
    coverage_start_ms_after, _ = get_market_data_coverage_ms(db)
    dispatch_as_of_ms = coverage_snapshot.get("dispatch_as_of_ms")
    previous_dispatch_ms = get_previous_dispatch_as_of_ms(db, exclude_snapshot_id=coverage_snapshot["id"])
    advanced_coverage = _coverage_advanced(previous_dispatch_ms, dispatch_as_of_ms)
    completed_at = utc_now()

    blocked_reason = coverage_snapshot.get("blocked_reason")
    degraded = bool(coverage_snapshot.get("degraded"))
    coverage_ratio = float(coverage_snapshot.get("coverage_ratio") or 0.0)
    active_symbol_count = int(coverage_snapshot.get("active_symbol_count") or 0)
    fresh_symbol_count = int(coverage_snapshot.get("fresh_symbol_count") or 0)
    missing_symbol_count = int(coverage_snapshot.get("missing_symbol_count") or 0)
    snapshot_created_at_ms = coverage_snapshot.get("created_at_ms")
    snapshot_age_ms = None
    if isinstance(snapshot_created_at_ms, int):
        snapshot_age_ms = datetime_to_ms(completed_at) - snapshot_created_at_ms

    success = dispatch_as_of_ms is not None and blocked_reason is None
    if success:
        status = "succeeded" if advanced_coverage else "no_advance"
    else:
        status = "blocked" if blocked_reason else "failed"

    error_parts = []
    if blocked_reason:
        error_parts.append(blocked_reason)
    if symbol_failures:
        error_parts.extend(_format_failure_message(item) for item in symbol_failures)

    return MarketSyncSweepResult(
        success=success,
        status=status,
        started_at_ms=datetime_to_ms(started_at),
        completed_at_ms=datetime_to_ms(completed_at),
        coverage_start_ms_before=coverage_start_ms_before,
        coverage_end_ms_before=coverage_end_ms_before,
        coverage_start_ms_after=coverage_start_ms_after,
        coverage_end_ms_after=dispatch_as_of_ms,
        advanced_coverage=advanced_coverage,
        inserted_rows=inserted_rows,
        synced_symbols=synced_symbols,
        failures=symbol_failures,
        error_message='; '.join(error_parts) if error_parts else None,
        cutoff_ms=cutoff_ms,
        universe_active_count=active_symbol_count,
        fresh_symbol_count=fresh_symbol_count,
        coverage_ratio=coverage_ratio,
        degraded=degraded,
        blocked_reason=blocked_reason,
        snapshot_age_ms=snapshot_age_ms,
        missing_symbol_count=missing_symbol_count,
        universe_version=coverage_snapshot.get("universe_version") or universe_version,
    )


def refresh_market_universe(db: Session, *, universe_version: int) -> dict[str, Any]:
    instruments = fetch_okx_swap_instruments()
    now = utc_now()

    active_instruments = [item for item in instruments if item["lifecycle_status"] == "active"]
    ranked_by_volume = sorted(
        active_instruments,
        key=lambda item: float(item.get("volume_24h_usd") or 0.0),
        reverse=True,
    )
    tier1_symbols = {
        item["instrument_id"]
        for item in ranked_by_volume[: settings.market_sync_tier1_symbol_count]
    }

    existing_by_symbol = {
        row.instrument_id: row
        for row in db.scalars(select(MarketInstrument).where(MarketInstrument.exchange == "okx")).all()
    }
    seen_symbols: set[str] = set()

    for payload in instruments:
        instrument_id = payload["instrument_id"]
        seen_symbols.add(instrument_id)
        instrument = existing_by_symbol.get(instrument_id)
        lifecycle_status = payload["lifecycle_status"]
        priority_tier = (
            "tier1"
            if lifecycle_status == "active" and instrument_id in tier1_symbols
            else "tier2"
            if lifecycle_status == "active"
            else "tier3"
        )
        if instrument is None:
            instrument = MarketInstrument(
                id=new_id("inst"),
                exchange="okx",
                instrument_id=instrument_id,
                base_symbol=payload["base_symbol"],
                quote_asset=payload["quote_asset"],
                instrument_type=payload["instrument_type"],
                bootstrap_status="pending" if lifecycle_status == "active" else "failed",
                discovered_at=now,
            )
        instrument.base_symbol = payload["base_symbol"]
        instrument.quote_asset = payload["quote_asset"]
        instrument.instrument_type = payload["instrument_type"]
        instrument.lifecycle_status = lifecycle_status
        instrument.priority_tier = priority_tier
        instrument.last_trade_price = payload.get("last_trade_price")
        instrument.volume_24h_usd = payload.get("volume_24h_usd")
        instrument.metadata_json = payload.get("metadata") or {}
        instrument.missed_refresh_count = 0
        if lifecycle_status == "active":
            instrument.last_seen_active_at = now
            instrument.delisted_at = None
            if instrument.bootstrap_status == "failed":
                instrument.bootstrap_status = "pending"
        db.add(instrument)
        ensure_market_sync_state(db, instrument, now)

    for instrument in existing_by_symbol.values():
        if instrument.instrument_id in seen_symbols:
            continue
        instrument.missed_refresh_count += 1
        if instrument.missed_refresh_count >= settings.market_sync_delist_after_missed_refreshes:
            instrument.lifecycle_status = "delisted"
            instrument.priority_tier = "tier3"
            instrument.delisted_at = instrument.delisted_at or now
        db.add(instrument)
        ensure_market_sync_state(db, instrument, now)

    db.commit()
    return {
        "active_symbol_count": sum(1 for item in instruments if item["lifecycle_status"] == "active"),
        "universe_version": universe_version,
    }


def ensure_market_sync_state(db: Session, instrument: MarketInstrument, now: datetime | None = None) -> MarketSyncState:
    current_time = now or utc_now()
    state = db.scalar(
        select(MarketSyncState).where(
            MarketSyncState.exchange == instrument.exchange,
            MarketSyncState.base_symbol == instrument.instrument_id,
            MarketSyncState.timeframe == settings.historical_base_timeframe,
        )
    )
    if state is None:
        state = MarketSyncState(
            id=new_id("syncstate"),
            exchange=instrument.exchange,
            base_symbol=instrument.instrument_id,
            timeframe=settings.historical_base_timeframe,
            next_sync_due_at=current_time,
            status="pending",
        )
    state.lifecycle_status = instrument.lifecycle_status
    state.priority_tier = instrument.priority_tier
    if state.next_sync_due_at is None:
        state.next_sync_due_at = current_time
    if instrument.lifecycle_status == "delisted":
        state.next_sync_due_at = current_time + timedelta(seconds=settings.market_sync_tier3_target_seconds)
    db.add(state)
    return state


def select_due_sync_states(db: Session, now: datetime | None = None) -> list[MarketSyncState]:
    current_time = now or utc_now()
    states = db.scalars(
        select(MarketSyncState)
        .where(
            MarketSyncState.timeframe == settings.historical_base_timeframe,
            or_(MarketSyncState.next_sync_due_at.is_(None), MarketSyncState.next_sync_due_at <= current_time),
        )
    ).all()

    def sort_key(state: MarketSyncState) -> tuple[int, int, int, int]:
        priority_rank = {"tier1": 0, "tier2": 1, "tier3": 2}.get(state.priority_tier, 3)
        freshness_deficit = 0
        if state.last_sync_completed_at is not None:
            freshness_deficit = max(datetime_to_ms(current_time) - datetime_to_ms(state.last_sync_completed_at), 0)
        last_synced = state.last_synced_open_time_ms or 0
        return (priority_rank, -freshness_deficit, last_synced, state.retry_count)

    return sorted(states, key=sort_key)


def sync_market_symbol(db: Session, base_symbol: str, *, cutoff_ms: int) -> dict[str, Any]:
    now = utc_now()
    state = db.scalar(
        select(MarketSyncState).where(
            MarketSyncState.exchange == "okx",
            MarketSyncState.base_symbol == base_symbol,
            MarketSyncState.timeframe == settings.historical_base_timeframe,
        )
    )
    instrument = db.scalar(
        select(MarketInstrument).where(
            MarketInstrument.exchange == "okx",
            MarketInstrument.instrument_id == base_symbol,
        )
    )
    if state is None or instrument is None:
        return {"status": "skipped", "inserted_rows": 0}
    if not acquire_sync_lease(db, state, owner=_market_sync_owner(), now=now):
        return {"status": "leased", "inserted_rows": 0}

    queue_name = determine_sync_queue(state)
    attempt = create_market_sync_attempt(db, base_symbol=base_symbol, queue_name=queue_name)
    inserted_rows = 0
    status = "completed"
    failure: dict[str, Any] | None = None
    page_count = 0

    try:
        latest_local_ms = resolve_latest_local_ms(db, base_symbol, state)
        bootstrap_required = instrument.bootstrap_status != "ready" or latest_local_ms is None
        gap_ms = max((cutoff_ms - latest_local_ms), 0) if latest_local_ms is not None else None
        state.last_sync_started_at = now
        if bootstrap_required:
            inserted_rows, latest_synced_ms, page_count = bootstrap_recent_symbol_from_okx(
                db,
                base_symbol,
                cutoff_ms=cutoff_ms,
            )
            if latest_synced_ms is None:
                raise RuntimeError("bootstrap returned no market candles")
            instrument.bootstrap_status = "ready"
            state.last_synced_open_time_ms = latest_synced_ms
            state.fresh_coverage_end_ms = latest_synced_ms
            state.notes_json = {**(state.notes_json or {}), "backfill_pending": False}
        elif gap_ms is not None and gap_ms > settings.market_sync_bootstrap_window_hours * 60 * 60_000:
            inserted_rows, latest_synced_ms, page_count = bootstrap_recent_symbol_from_okx(
                db,
                base_symbol,
                cutoff_ms=cutoff_ms,
            )
            if latest_synced_ms is None:
                raise RuntimeError("recent bootstrap returned no market candles")
            state.last_synced_open_time_ms = latest_synced_ms
            state.fresh_coverage_end_ms = latest_synced_ms
            state.notes_json = {
                **(state.notes_json or {}),
                "backfill_pending": True,
                "backfill_anchor_open_time_ms": latest_local_ms,
            }
        elif latest_local_ms is not None and latest_local_ms >= cutoff_ms:
            state.fresh_coverage_end_ms = latest_local_ms
        else:
            inserted_rows, latest_synced_ms, page_count, budget_hit = sync_symbol_from_okx(
                db,
                base_symbol,
                latest_local_ms or 0,
                cutoff_ms,
                max_pages=settings.market_sync_symbol_max_pages_per_run,
            )
            if latest_synced_ms is not None:
                state.last_synced_open_time_ms = latest_synced_ms
                state.fresh_coverage_end_ms = latest_synced_ms
            state.notes_json = {**(state.notes_json or {}), "budget_hit": budget_hit}

        state.status = "completed"
        state.retry_count = 0
        state.last_error = None
        state.last_sync_completed_at = utc_now()
        state.next_sync_due_at = state.last_sync_completed_at + timedelta(seconds=_target_sync_interval_seconds(state.priority_tier))
        if instrument.lifecycle_status == "active":
            instrument.bootstrap_status = "ready"
        db.add(instrument)
        db.add(state)
        upsert_sync_cursor(
            db,
            base_symbol,
            state.last_synced_open_time_ms or 0,
            "completed",
            {
                "priority_tier": state.priority_tier,
                "fresh_coverage_end_ms": state.fresh_coverage_end_ms,
                "queue_name": queue_name,
            },
            started_at=state.last_sync_started_at,
            completed_at=state.last_sync_completed_at,
        )
        complete_market_sync_attempt(
            db,
            attempt,
            status="completed",
            page_count=page_count,
            inserted_rows=inserted_rows,
            retryable=False,
            notes={"priority_tier": state.priority_tier},
        )
    except Exception as exc:
        db.rollback()
        state = db.scalar(select(MarketSyncState).where(MarketSyncState.id == state.id))
        instrument = db.scalar(select(MarketInstrument).where(MarketInstrument.id == instrument.id))
        attempt = db.scalar(select(MarketSyncAttempt).where(MarketSyncAttempt.id == attempt.id))
        assert state is not None
        assert instrument is not None
        assert attempt is not None
        retryable = is_retryable_sync_exception(exc)
        delay_seconds = _retry_delay_seconds(state.retry_count + 1, retryable=retryable)
        state.status = "failed"
        state.retry_count = min(state.retry_count + 1, settings.market_sync_retry_limit)
        state.last_error = str(exc)
        state.last_sync_started_at = state.last_sync_started_at or now
        state.last_sync_completed_at = utc_now()
        state.next_sync_due_at = state.last_sync_completed_at + timedelta(seconds=delay_seconds)
        if instrument.bootstrap_status != "ready":
            instrument.bootstrap_status = "failed"
        db.add(instrument)
        db.add(state)
        upsert_sync_cursor(
            db,
            base_symbol,
            state.last_synced_open_time_ms or 0,
            "failed",
            {"error": str(exc), "priority_tier": state.priority_tier},
            started_at=state.last_sync_started_at,
            completed_at=state.last_sync_completed_at,
        )
        complete_market_sync_attempt(
            db,
            attempt,
            status="failed",
            page_count=page_count,
            inserted_rows=inserted_rows,
            retryable=retryable,
            error_message=str(exc),
        )
        status = "failed"
        failure = {
            "base_symbol": base_symbol,
            "reason": "sync_error",
            "message": str(exc),
            "retryable": retryable,
        }
    finally:
        refreshed_state = db.scalar(select(MarketSyncState).where(MarketSyncState.base_symbol == base_symbol))
        if refreshed_state is not None:
            release_sync_lease(db, refreshed_state)

    return {
        "status": status,
        "inserted_rows": inserted_rows,
        "failure": failure,
    }


def acquire_sync_lease(db: Session, state: MarketSyncState, *, owner: str, now: datetime | None = None) -> bool:
    current_time = now or utc_now()
    if state.lease_owner and state.lease_expires_at and state.lease_expires_at > current_time:
        return False
    state.lease_owner = owner
    state.lease_expires_at = current_time + timedelta(seconds=settings.market_sync_lease_ttl_seconds)
    db.add(state)
    db.commit()
    return True


def release_sync_lease(db: Session, state: MarketSyncState) -> None:
    state.lease_owner = None
    state.lease_expires_at = None
    db.add(state)
    db.commit()


def determine_sync_queue(state: MarketSyncState) -> str:
    if state.priority_tier == "tier1":
        return "symbol-sync-high"
    if state.priority_tier == "tier2":
        return "symbol-sync-normal"
    return "symbol-sync-backfill"


def resolve_latest_local_ms(db: Session, base_symbol: str, state: MarketSyncState) -> int | None:
    if state.last_synced_open_time_ms is not None:
        return state.last_synced_open_time_ms
    latest_local_ms = db.scalar(
        select(func.max(MarketCandle.open_time_ms)).where(
            MarketCandle.base_symbol == base_symbol,
            MarketCandle.market_symbol == base_symbol,
            MarketCandle.timeframe == settings.historical_base_timeframe,
        )
    )
    return latest_local_ms


def bootstrap_recent_symbol_from_okx(db: Session, base_symbol: str, *, cutoff_ms: int) -> tuple[int, int | None, int]:
    start_ms = max(cutoff_ms - (settings.market_sync_bootstrap_window_hours * 60 * 60_000), 0)
    inserted_rows = 0
    latest_synced_ms: int | None = None
    oldest_page_ms: int | None = None
    page_count = 0
    after_cursor: int | None = None

    while page_count < settings.market_sync_symbol_max_pages_per_run:
        candles = fetch_okx_history_candles_with_retry(base_symbol, after_open_time_ms=after_cursor)
        if not candles:
            break
        parsed_rows, page_min_ms, page_max_ms = build_okx_candle_rows(base_symbol, candles, min_open_time_ms=start_ms, max_open_time_ms=cutoff_ms)
        if parsed_rows:
            inserted_rows += insert_candle_batch(db, parsed_rows)
            latest_synced_ms = page_max_ms if latest_synced_ms is None else max(latest_synced_ms, page_max_ms)
        page_count += 1
        if page_min_ms is None:
            break
        oldest_page_ms = page_min_ms
        if oldest_page_ms <= start_ms:
            break
        after_cursor = oldest_page_ms
        time.sleep(settings.okx_request_pause_seconds)

    return inserted_rows, latest_synced_ms, page_count


def sync_symbol_from_okx(
    db: Session,
    base_symbol: str,
    latest_local_ms: int,
    cutoff_ms: int,
    *,
    max_pages: int | None = None,
) -> tuple[int, int | None, int, bool]:
    cursor_ms = latest_local_ms
    inserted_rows = 0
    page_count = 0
    max_page_budget = max_pages or settings.market_sync_symbol_max_pages_per_run
    while cursor_ms < cutoff_ms and page_count < max_page_budget:
        candles = fetch_okx_history_candles_with_retry(base_symbol, before_open_time_ms=cursor_ms)
        if not candles:
            break
        parsed_rows, _, page_max_ms = build_okx_candle_rows(base_symbol, candles, min_open_time_ms=cursor_ms + 1, max_open_time_ms=cutoff_ms)
        if parsed_rows:
            inserted_rows += insert_candle_batch(db, parsed_rows)
        if page_max_ms is None or page_max_ms <= cursor_ms:
            break
        cursor_ms = page_max_ms
        page_count += 1
        time.sleep(settings.okx_request_pause_seconds)
    budget_hit = page_count >= max_page_budget and cursor_ms < cutoff_ms
    logger.info(
        "OKX symbol sync finished for %s from %s to %s (inserted_rows=%s page_count=%s)",
        base_symbol,
        ms_to_datetime(latest_local_ms).isoformat(),
        ms_to_datetime(cursor_ms).isoformat(),
        inserted_rows,
        page_count,
    )
    return inserted_rows, cursor_ms if cursor_ms > latest_local_ms else latest_local_ms, page_count, budget_hit


def build_okx_candle_rows(
    base_symbol: str,
    candles: list[list[Any]],
    *,
    min_open_time_ms: int | None = None,
    max_open_time_ms: int | None = None,
) -> tuple[list[dict[str, Any]], int | None, int | None]:
    parsed_rows: list[dict[str, Any]] = []
    min_seen_ms: int | None = None
    max_seen_ms: int | None = None
    now = utc_now()
    for item in candles:
        open_time_ms = int(item[0])
        min_seen_ms = open_time_ms if min_seen_ms is None else min(min_seen_ms, open_time_ms)
        max_seen_ms = open_time_ms if max_seen_ms is None else max(max_seen_ms, open_time_ms)
        if min_open_time_ms is not None and open_time_ms < min_open_time_ms:
            continue
        if max_open_time_ms is not None and open_time_ms > max_open_time_ms:
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
    return parsed_rows, min_seen_ms, max_seen_ms


def fetch_okx_swap_instruments() -> list[dict[str, Any]]:
    tickers = fetch_okx_swap_tickers()
    response = httpx.get(
        f"{settings.okx_api_base_url}/api/v5/public/instruments",
        params={"instType": "SWAP"},
        timeout=20.0,
    )
    response.raise_for_status()
    payload = response.json()
    items = payload.get("data", [])
    instruments: list[dict[str, Any]] = []
    for item in items:
        inst_id = str(item.get("instId") or "").strip().upper()
        if not inst_id.endswith("-USDT-SWAP"):
            continue
        state = (item.get("state") or "live").lower()
        lifecycle_status = "active" if state == "live" else "suspended" if state == "suspend" else "delisted"
        ticker = tickers.get(inst_id, {})
        instruments.append(
            {
                "instrument_id": inst_id,
                "base_symbol": inst_id,
                "quote_asset": "USDT",
                "instrument_type": "SWAP",
                "lifecycle_status": lifecycle_status,
                "last_trade_price": parse_optional_float(ticker.get("last")),
                "volume_24h_usd": parse_optional_float(ticker.get("volCcy24h")) or parse_optional_float(ticker.get("vol24h")),
                "metadata": {"raw_state": state},
            }
        )
    return instruments


def fetch_okx_swap_tickers() -> dict[str, dict[str, Any]]:
    response = httpx.get(
        f"{settings.okx_api_base_url}/api/v5/market/tickers",
        params={"instType": "SWAP"},
        timeout=20.0,
    )
    response.raise_for_status()
    payload = response.json()
    items = payload.get("data", [])
    return {str(item.get("instId") or "").strip().upper(): item for item in items}


def fetch_okx_active_usdt_swap_symbols() -> set[str]:
    return {
        item["instrument_id"]
        for item in fetch_okx_swap_instruments()
        if item["lifecycle_status"] in {"active", "suspended"}
    }


def fetch_okx_history_candles(
    base_symbol: str,
    before_open_time_ms: int | None = None,
    after_open_time_ms: int | None = None,
    *,
    limit: int | None = None,
) -> list[list[Any]]:
    params = {
        "instId": base_symbol,
        "bar": settings.historical_base_timeframe,
        "limit": str(limit or settings.okx_history_limit),
    }
    if before_open_time_ms is not None:
        params["before"] = str(before_open_time_ms)
    if after_open_time_ms is not None:
        params["after"] = str(after_open_time_ms)
    response = httpx.get(
        f"{settings.okx_api_base_url}/api/v5/market/history-candles",
        params=params,
        timeout=20.0,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data", [])
    return list(reversed(data))


def fetch_okx_history_candles_with_retry(
    base_symbol: str,
    before_open_time_ms: int | None = None,
    after_open_time_ms: int | None = None,
) -> list[list[Any]]:
    last_exc: Exception | None = None
    for attempt in range(1, settings.market_sync_retry_limit + 1):
        try:
            return fetch_okx_history_candles(
                base_symbol,
                before_open_time_ms=before_open_time_ms,
                after_open_time_ms=after_open_time_ms,
            )
        except Exception as exc:
            last_exc = exc
            if not is_retryable_sync_exception(exc) or attempt >= settings.market_sync_retry_limit:
                raise
            time.sleep(min(2 ** (attempt - 1), 5))
    if last_exc is not None:
        raise last_exc
    return []


def create_market_sync_attempt(db: Session, *, base_symbol: str, queue_name: str) -> MarketSyncAttempt:
    attempt = MarketSyncAttempt(
        id=new_id("syncattempt"),
        exchange="okx",
        base_symbol=base_symbol,
        timeframe=settings.historical_base_timeframe,
        queue_name=queue_name,
        status="running",
        started_at=utc_now(),
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt


def complete_market_sync_attempt(
    db: Session,
    attempt: MarketSyncAttempt,
    *,
    status: str,
    page_count: int,
    inserted_rows: int,
    retryable: bool,
    error_message: str | None = None,
    notes: dict[str, Any] | None = None,
) -> None:
    attempt.status = status
    attempt.page_count = page_count
    attempt.inserted_rows = inserted_rows
    attempt.retryable = retryable
    attempt.error_message = error_message
    attempt.notes_json = notes or {}
    attempt.completed_at = utc_now()
    db.add(attempt)
    db.commit()


def recompute_market_coverage_snapshot(db: Session, *, universe_version: int | None = None) -> dict[str, Any]:
    active_instruments = db.scalars(
        select(MarketInstrument).where(MarketInstrument.lifecycle_status == "active")
    ).all()
    states = {
        row.base_symbol: row
        for row in db.scalars(
            select(MarketSyncState).where(MarketSyncState.lifecycle_status == "active")
        ).all()
    }
    active_symbol_count = len(active_instruments)
    tier1_symbols = [item.instrument_id for item in active_instruments if item.priority_tier == "tier1"]
    candidate_times = sorted(
        {
            state.fresh_coverage_end_ms
            for state in states.values()
            if state.fresh_coverage_end_ms is not None
        },
        reverse=True,
    )
    dispatch_as_of_ms: int | None = None
    coverage_ratio = 0.0
    degraded = False
    blocked_reason: str | None = None
    missing_symbols: list[str] = []
    fresh_symbol_count = 0
    tier1_fresh_symbol_count = 0

    required_ratio = settings.market_sync_required_coverage_ratio
    for candidate in candidate_times:
        fresh_symbols = [
            instrument.instrument_id
            for instrument in active_instruments
            if (state := states.get(instrument.instrument_id)) is not None
            and state.fresh_coverage_end_ms is not None
            and state.fresh_coverage_end_ms >= candidate
            and instrument.bootstrap_status == "ready"
        ]
        tier1_fresh = [symbol for symbol in tier1_symbols if symbol in fresh_symbols]
        ratio = (len(fresh_symbols) / active_symbol_count) if active_symbol_count else 0.0
        if ratio >= required_ratio and len(tier1_fresh) == len(tier1_symbols):
            dispatch_as_of_ms = candidate
            fresh_symbol_count = len(fresh_symbols)
            tier1_fresh_symbol_count = len(tier1_fresh)
            coverage_ratio = ratio
            degraded = ratio < 1.0
            missing_symbols = [
                instrument.instrument_id
                for instrument in active_instruments
                if instrument.instrument_id not in fresh_symbols
            ][:10]
            break

    if dispatch_as_of_ms is None:
        if active_symbol_count == 0:
            blocked_reason = "no_active_universe"
        elif any(symbol not in states or states[symbol].fresh_coverage_end_ms is None for symbol in tier1_symbols):
            blocked_reason = "tier1_incomplete"
        else:
            blocked_reason = "coverage_below_threshold"
        fresh_symbol_count = sum(
            1
            for instrument in active_instruments
            if (state := states.get(instrument.instrument_id)) is not None
            and state.fresh_coverage_end_ms is not None
            and instrument.bootstrap_status == "ready"
        )
        tier1_fresh_symbol_count = sum(
            1
            for symbol in tier1_symbols
            if (state := states.get(symbol)) is not None and state.fresh_coverage_end_ms is not None
        )
        coverage_ratio = (fresh_symbol_count / active_symbol_count) if active_symbol_count else 0.0
        missing_symbols = [
            instrument.instrument_id
            for instrument in active_instruments
            if instrument.instrument_id not in states
            or states[instrument.instrument_id].fresh_coverage_end_ms is None
            or instrument.bootstrap_status != "ready"
        ][:10]

    snapshot = MarketCoverageSnapshot(
        id=new_id("covsnap"),
        active_symbol_count=active_symbol_count,
        fresh_symbol_count=fresh_symbol_count,
        tier1_symbol_count=len(tier1_symbols),
        tier1_fresh_symbol_count=tier1_fresh_symbol_count,
        coverage_ratio=coverage_ratio,
        dispatch_as_of_ms=dispatch_as_of_ms,
        degraded=degraded,
        blocked_reason=blocked_reason,
        universe_version=universe_version,
        missing_symbol_count=max(active_symbol_count - fresh_symbol_count, 0),
        missing_symbols_json=missing_symbols,
        notes_json={},
        created_at=utc_now(),
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return coverage_snapshot_to_dict(snapshot)


def get_latest_market_coverage_snapshot(db: Session) -> dict[str, Any] | None:
    snapshot = db.scalar(select(MarketCoverageSnapshot).order_by(MarketCoverageSnapshot.created_at.desc()).limit(1))
    if snapshot is None:
        return None
    return coverage_snapshot_to_dict(snapshot)


def coverage_snapshot_to_dict(snapshot: MarketCoverageSnapshot) -> dict[str, Any]:
    created_at_ms = datetime_to_ms(snapshot.created_at)
    return {
        "id": snapshot.id,
        "active_symbol_count": snapshot.active_symbol_count,
        "fresh_symbol_count": snapshot.fresh_symbol_count,
        "tier1_symbol_count": snapshot.tier1_symbol_count,
        "tier1_fresh_symbol_count": snapshot.tier1_fresh_symbol_count,
        "coverage_ratio": snapshot.coverage_ratio,
        "dispatch_as_of_ms": snapshot.dispatch_as_of_ms,
        "degraded": snapshot.degraded,
        "blocked_reason": snapshot.blocked_reason,
        "missing_symbol_count": snapshot.missing_symbol_count,
        "missing_symbols_sample": snapshot.missing_symbols_json or [],
        "universe_version": snapshot.universe_version,
        "created_at_ms": created_at_ms,
    }


def get_previous_dispatch_as_of_ms(db: Session, *, exclude_snapshot_id: str | None = None) -> int | None:
    query = select(MarketCoverageSnapshot).order_by(MarketCoverageSnapshot.created_at.desc())
    snapshots = db.scalars(query.limit(2 if exclude_snapshot_id else 1)).all()
    for snapshot in snapshots:
        if exclude_snapshot_id and snapshot.id == exclude_snapshot_id:
            continue
        return snapshot.dispatch_as_of_ms
    return None


def get_fresh_market_symbols_for_dispatch(db: Session, dispatch_as_of_ms: int) -> set[str]:
    rows = db.scalars(
        select(MarketSyncState.base_symbol)
        .join(MarketInstrument, MarketInstrument.instrument_id == MarketSyncState.base_symbol)
        .where(
            MarketInstrument.lifecycle_status == "active",
            MarketInstrument.bootstrap_status == "ready",
            MarketSyncState.fresh_coverage_end_ms.is_not(None),
            MarketSyncState.fresh_coverage_end_ms >= dispatch_as_of_ms,
        )
    ).all()
    return set(rows)


def get_market_sync_gate_status(db: Session) -> dict[str, Any]:
    snapshot = get_latest_market_coverage_snapshot(db)
    if snapshot is None:
        return {
            "status": "blocked",
            "dispatch_as_of_ms": None,
            "coverage_ratio": 0.0,
            "degraded": False,
            "blocked_reason": "no_snapshot",
            "snapshot_age_ms": None,
            "universe_active_count": 0,
            "fresh_symbol_count": 0,
            "missing_symbol_count": 0,
            "missing_symbols_sample": [],
            "universe_version": None,
        }
    snapshot_age_ms = datetime_to_ms(utc_now()) - int(snapshot["created_at_ms"])
    status = "blocked"
    if snapshot["dispatch_as_of_ms"] is not None and snapshot_age_ms <= int(settings.live_data_freshness_seconds * 1000):
        status = "degraded" if snapshot["degraded"] else "healthy"
    elif snapshot["blocked_reason"] is None:
        status = "stale"
    return {
        "status": status,
        "dispatch_as_of_ms": snapshot["dispatch_as_of_ms"],
        "coverage_ratio": snapshot["coverage_ratio"],
        "degraded": snapshot["degraded"],
        "blocked_reason": snapshot["blocked_reason"],
        "snapshot_age_ms": snapshot_age_ms,
        "universe_active_count": snapshot["active_symbol_count"],
        "fresh_symbol_count": snapshot["fresh_symbol_count"],
        "missing_symbol_count": snapshot["missing_symbol_count"],
        "missing_symbols_sample": snapshot["missing_symbols_sample"],
        "universe_version": snapshot["universe_version"],
    }


def is_retryable_sync_exception(exc: Exception) -> bool:
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {408, 409, 425, 429, 500, 502, 503, 504}
    return False


def _retry_delay_seconds(retry_count: int, *, retryable: bool) -> float:
    if not retryable:
        return settings.market_sync_non_retryable_delay_seconds
    return min(30.0 * (2 ** max(retry_count - 1, 0)), settings.market_sync_non_retryable_delay_seconds)


def _market_sync_owner() -> str:
    return "market-sync-loop"


def _target_sync_interval_seconds(priority_tier: str) -> float:
    if priority_tier == "tier1":
        return settings.market_sync_tier1_target_seconds
    if priority_tier == "tier2":
        return settings.market_sync_tier2_target_seconds
    return settings.market_sync_tier3_target_seconds


def build_source_fingerprint(path: Path) -> str:
    stat = path.stat()
    return f"{path.resolve()}::{stat.st_size}::{stat.st_mtime_ns}"


def parse_optional_float(value: str | float | None) -> float | None:
    if value in {None, "", "None", "null"}:
        return None
    return float(value)


def _coverage_advanced(before_ms: int | None, after_ms: int | None) -> bool:
    if after_ms is None:
        return False
    if before_ms is None:
        return True
    return after_ms > before_ms


def _format_failure_message(failure: dict[str, Any]) -> str:
    symbol = failure.get("base_symbol") or "unknown"
    reason = failure.get("reason") or "sync_error"
    message = failure.get("message")
    if message:
        return f"{symbol}:{reason}:{message}"
    return f"{symbol}:{reason}"
