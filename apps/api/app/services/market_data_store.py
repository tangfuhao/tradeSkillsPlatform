from __future__ import annotations

import copy
import threading
import time
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import case, desc, func, literal, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import CsvIngestionJob, MarketCandle, MarketInstrument, MarketOverviewState, MarketSyncState
from app.services.utils import datetime_to_ms, ms_to_datetime, new_id, utc_now

_OVERVIEW_CACHE_LOCK = threading.Lock()
_OVERVIEW_REFRESH_LOCK = threading.Lock()
_OVERVIEW_CACHE_PAYLOAD: dict[str, Any] | None = None
_OVERVIEW_CACHE_AT_MONOTONIC = 0.0


def normalize_timeframe(value: str) -> str:
    text_value = value.strip()
    if not text_value:
        raise ValueError("timeframe is required")
    suffix = text_value[-1].lower()
    amount = int(text_value[:-1])
    if suffix not in {"m", "h", "d"} or amount <= 0:
        raise ValueError(f"Unsupported timeframe: {value}")
    return f"{amount}{suffix}"



def timeframe_to_ms(value: str) -> int:
    normalized = normalize_timeframe(value)
    amount = int(normalized[:-1])
    suffix = normalized[-1]
    if suffix == "m":
        return amount * 60_000
    if suffix == "h":
        return amount * 60 * 60_000
    if suffix == "d":
        return amount * 24 * 60 * 60_000
    raise ValueError(f"Unsupported timeframe: {value}")



def parse_base_symbol(market_symbol: str) -> str:
    return market_symbol.split("#OLD#")[0]



def is_usdt_swap_symbol(market_symbol: str) -> bool:
    return parse_base_symbol(market_symbol).endswith("-USDT-SWAP")



def bucket_open_time_ms(open_time_ms: int, timeframe_ms: int) -> int:
    return (open_time_ms // timeframe_ms) * timeframe_ms



def fetch_candles(
    db: Session,
    market_symbol: str,
    timeframe: str,
    limit: int = 200,
    end_time: datetime | None = None,
) -> list[dict[str, Any]]:
    normalized_timeframe = normalize_timeframe(timeframe)
    end_time_ms = datetime_to_ms(end_time or utc_now()) if end_time else None
    if normalized_timeframe == settings.historical_base_timeframe:
        query = select(MarketCandle).where(
            MarketCandle.market_symbol == market_symbol,
            MarketCandle.timeframe == settings.historical_base_timeframe,
        )
        if end_time_ms is not None:
            query = query.where(MarketCandle.open_time_ms <= end_time_ms)
        rows = db.scalars(query.order_by(MarketCandle.open_time_ms.desc()).limit(limit)).all()
        return [serialize_candle(row) for row in reversed(rows)]

    timeframe_ms = timeframe_to_ms(normalized_timeframe)
    effective_end_time_ms = end_time_ms
    if effective_end_time_ms is None:
        effective_end_time_ms = db.scalar(
            select(func.max(MarketCandle.open_time_ms)).where(
                MarketCandle.market_symbol == market_symbol,
                MarketCandle.timeframe == settings.historical_base_timeframe,
            )
        )
    if effective_end_time_ms is None:
        return []

    lookback_start_ms = max(effective_end_time_ms - (timeframe_ms * max(limit, 1) * 4), 0)
    bucket_expr = _bucket_expr(MarketCandle.open_time_ms, timeframe_ms)
    candle_rows = (
        select(
            MarketCandle.market_symbol.label("market_symbol"),
            MarketCandle.base_symbol.label("base_symbol"),
            bucket_expr.label("bucket_open_time_ms"),
            MarketCandle.open.label("open"),
            MarketCandle.high.label("high"),
            MarketCandle.low.label("low"),
            MarketCandle.close.label("close"),
            MarketCandle.vol.label("vol"),
            MarketCandle.vol_ccy.label("vol_ccy"),
            MarketCandle.vol_quote.label("vol_quote"),
            MarketCandle.confirm.label("confirm"),
            func.row_number().over(
                partition_by=bucket_expr,
                order_by=MarketCandle.open_time_ms.asc(),
            ).label("row_number_asc"),
            func.row_number().over(
                partition_by=bucket_expr,
                order_by=MarketCandle.open_time_ms.desc(),
            ).label("row_number_desc"),
        )
        .where(
            MarketCandle.market_symbol == market_symbol,
            MarketCandle.timeframe == settings.historical_base_timeframe,
            MarketCandle.open_time_ms >= lookback_start_ms,
            MarketCandle.open_time_ms <= effective_end_time_ms,
        )
        .subquery()
    )

    first_open_expr = func.max(case((candle_rows.c.row_number_asc == 1, candle_rows.c.open), else_=None))
    last_close_expr = func.max(case((candle_rows.c.row_number_desc == 1, candle_rows.c.close), else_=None))
    aggregated_rows = db.execute(
        select(
            candle_rows.c.market_symbol.label("market_symbol"),
            func.max(candle_rows.c.base_symbol).label("base_symbol"),
            literal(normalized_timeframe).label("timeframe"),
            candle_rows.c.bucket_open_time_ms.label("open_time_ms"),
            first_open_expr.label("open"),
            func.max(candle_rows.c.high).label("high"),
            func.min(candle_rows.c.low).label("low"),
            last_close_expr.label("close"),
            func.sum(candle_rows.c.vol).label("vol"),
            func.sum(candle_rows.c.vol_ccy).label("vol_ccy"),
            func.sum(candle_rows.c.vol_quote).label("vol_quote"),
            func.min(case((candle_rows.c.confirm.is_(True), 1), else_=0)).label("confirm_int"),
            literal("aggregated").label("source"),
        )
        .group_by(candle_rows.c.market_symbol, candle_rows.c.bucket_open_time_ms)
        .order_by(desc(candle_rows.c.bucket_open_time_ms))
        .limit(limit)
    ).all()
    return [_serialize_aggregated_candle_row(row) for row in reversed(aggregated_rows)]



def aggregate_rows(rows: list[MarketCandle], timeframe: str) -> list[dict[str, Any]]:
    if not rows:
        return []
    timeframe_ms = timeframe_to_ms(timeframe)
    buckets: dict[int, dict[str, Any]] = {}
    for row in rows:
        bucket_ms = bucket_open_time_ms(row.open_time_ms, timeframe_ms)
        current = buckets.get(bucket_ms)
        if current is None:
            buckets[bucket_ms] = {
                "market_symbol": row.market_symbol,
                "base_symbol": row.base_symbol,
                "timeframe": timeframe,
                "open_time_ms": bucket_ms,
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "vol": row.vol,
                "vol_ccy": row.vol_ccy,
                "vol_quote": row.vol_quote,
                "confirm": row.confirm,
                "source": "aggregated",
            }
            continue
        current["high"] = max(current["high"], row.high)
        current["low"] = min(current["low"], row.low)
        current["close"] = row.close
        current["vol"] += row.vol
        current["vol_ccy"] = (current["vol_ccy"] or 0.0) + (row.vol_ccy or 0.0)
        current["vol_quote"] = (current["vol_quote"] or 0.0) + (row.vol_quote or 0.0)
    return [buckets[key] for key in sorted(buckets)]



def serialize_candle(row: MarketCandle) -> dict[str, Any]:
    return {
        "market_symbol": row.market_symbol,
        "base_symbol": row.base_symbol,
        "timeframe": row.timeframe,
        "open_time_ms": row.open_time_ms,
        "open": row.open,
        "high": row.high,
        "low": row.low,
        "close": row.close,
        "vol": row.vol,
        "vol_ccy": row.vol_ccy,
        "vol_quote": row.vol_quote,
        "confirm": row.confirm,
        "source": row.source,
    }



def build_market_snapshot(
    db: Session,
    as_of: datetime,
    limit: int | None = None,
    allowed_market_symbols: set[str] | None = None,
) -> dict[str, Any]:
    as_of_ms = datetime_to_ms(as_of)
    start_ms = as_of_ms - (24 * 60 * 60_000)
    base_query = select(
        MarketCandle.market_symbol.label("market_symbol"),
        MarketCandle.base_symbol.label("base_symbol"),
        MarketCandle.open_time_ms.label("open_time_ms"),
        MarketCandle.open.label("open"),
        MarketCandle.close.label("close"),
        MarketCandle.is_old_contract.label("is_old_contract"),
        func.coalesce(MarketCandle.vol_quote, MarketCandle.close * MarketCandle.vol).label("volume_quote"),
        func.row_number().over(
            partition_by=MarketCandle.market_symbol,
            order_by=MarketCandle.open_time_ms.asc(),
        ).label("row_number_asc"),
        func.row_number().over(
            partition_by=MarketCandle.market_symbol,
            order_by=MarketCandle.open_time_ms.desc(),
        ).label("row_number_desc"),
    ).where(
        MarketCandle.timeframe == settings.historical_base_timeframe,
        MarketCandle.open_time_ms >= start_ms,
        MarketCandle.open_time_ms <= as_of_ms,
    )
    if allowed_market_symbols is not None:
        if not allowed_market_symbols:
            return {
                "market_candidates": [],
                "source": "historical_db",
                "as_of_ms": as_of_ms,
            }
        base_query = base_query.where(MarketCandle.market_symbol.in_(sorted(allowed_market_symbols)))
    windowed_rows = base_query.subquery()

    first_open_expr = func.max(case((windowed_rows.c.row_number_asc == 1, windowed_rows.c.open), else_=None))
    last_close_expr = func.max(case((windowed_rows.c.row_number_desc == 1, windowed_rows.c.close), else_=None))
    last_open_time_expr = func.max(case((windowed_rows.c.row_number_desc == 1, windowed_rows.c.open_time_ms), else_=None))
    last_old_contract_expr = func.max(
        case(
            (
                windowed_rows.c.row_number_desc == 1,
                case((windowed_rows.c.is_old_contract.is_(True), 1), else_=0),
            ),
            else_=0,
        )
    )
    volume_expr = func.sum(windowed_rows.c.volume_quote)
    change_expr = (last_close_expr - first_open_expr) / func.nullif(first_open_expr, 0.0)

    selected_rows = db.execute(
        select(
            windowed_rows.c.market_symbol.label("symbol"),
            func.max(windowed_rows.c.base_symbol).label("base_symbol"),
            first_open_expr.label("first_open"),
            last_close_expr.label("last_price"),
            change_expr.label("change_24h_pct"),
            volume_expr.label("volume_24h_usd"),
            last_old_contract_expr.label("is_old_contract"),
            last_open_time_expr.label("as_of_ms"),
        )
        .group_by(windowed_rows.c.market_symbol)
        .order_by(desc(volume_expr), desc(func.abs(change_expr)))
        .limit(limit or settings.market_scan_limit_default)
    ).all()

    candidates = [
        {
            "symbol": row.symbol,
            "base_symbol": row.base_symbol,
            "last_price": round(float(row.last_price), 8),
            "change_24h_pct": round(float(row.change_24h_pct), 4),
            "volume_24h_usd": round(float(row.volume_24h_usd), 2),
            "funding_rate": 0.0,
            "open_interest_change_24h_pct": 0.0,
            "is_old_contract": bool(row.is_old_contract),
            "as_of_ms": int(row.as_of_ms),
        }
        for row in selected_rows
        if row.first_open not in {None, 0}
        and row.last_price is not None
        and row.volume_24h_usd is not None
        and row.as_of_ms is not None
    ]
    return {
        "market_candidates": candidates,
        "source": "historical_db",
        "as_of_ms": as_of_ms,
    }



def get_market_data_coverage_ranges(
    db: Session,
    *,
    timeframe: str | None = None,
) -> list[tuple[datetime, datetime]]:
    effective_timeframe = timeframe or settings.historical_base_timeframe
    gap_threshold_ms = timeframe_to_ms(effective_timeframe)
    distinct_open_times = (
        select(MarketCandle.open_time_ms.label("open_time_ms"))
        .where(MarketCandle.timeframe == effective_timeframe)
        .group_by(MarketCandle.open_time_ms)
        .order_by(MarketCandle.open_time_ms.asc())
        .subquery()
    )
    ordered_open_times = select(
        distinct_open_times.c.open_time_ms.label("open_time_ms"),
        func.lag(distinct_open_times.c.open_time_ms)
        .over(order_by=distinct_open_times.c.open_time_ms.asc())
        .label("previous_open_time_ms"),
    ).subquery()
    range_break_expr = case(
        (ordered_open_times.c.previous_open_time_ms.is_(None), 0),
        ((ordered_open_times.c.open_time_ms - ordered_open_times.c.previous_open_time_ms) > gap_threshold_ms, 1),
        else_=0,
    )
    grouped_ranges = select(
        ordered_open_times.c.open_time_ms.label("open_time_ms"),
        func.sum(range_break_expr).over(order_by=ordered_open_times.c.open_time_ms.asc()).label("range_group"),
    ).subquery()
    range_rows = db.execute(
        select(
            func.min(grouped_ranges.c.open_time_ms).label("start_ms"),
            func.max(grouped_ranges.c.open_time_ms).label("end_ms"),
        )
        .group_by(grouped_ranges.c.range_group)
        .order_by(func.min(grouped_ranges.c.open_time_ms).asc())
    ).all()
    if not range_rows:
        return []
    return [(ms_to_datetime(row.start_ms), ms_to_datetime(row.end_ms)) for row in range_rows]



def get_market_overview_coverage_ranges(
    db: Session,
    *,
    timeframe: str | None = None,
) -> list[tuple[datetime, datetime]]:
    effective_timeframe = timeframe or settings.historical_base_timeframe
    state = _load_market_overview_state(db, effective_timeframe)
    if state is None or not (state.coverage_ranges_json or []):
        state_payload = recompute_market_overview_state(
            db,
            timeframe=effective_timeframe,
            force=True,
            force_coverage_bootstrap=True,
        )
        return _range_payload_to_datetimes(state_payload.get("coverage_ranges") or [])
    return _range_payload_to_datetimes(state.coverage_ranges_json or [])



def get_market_data_coverage(db: Session) -> tuple[datetime | None, datetime | None]:
    coverage_ranges = get_market_overview_coverage_ranges(db)
    if not coverage_ranges:
        return None, None

    return max(
        coverage_ranges,
        key=lambda item: (
            datetime_to_ms(item[1]) - datetime_to_ms(item[0]),
            datetime_to_ms(item[1]),
        ),
    )



def has_market_data(db: Session) -> bool:
    return db.scalar(select(func.count()).select_from(MarketCandle)) > 0



def invalidate_market_overview_cache() -> None:
    global _OVERVIEW_CACHE_AT_MONOTONIC, _OVERVIEW_CACHE_PAYLOAD
    with _OVERVIEW_CACHE_LOCK:
        _OVERVIEW_CACHE_PAYLOAD = None
        _OVERVIEW_CACHE_AT_MONOTONIC = 0.0



def update_market_overview_state_for_open_times(
    db: Session,
    open_times_ms: Sequence[int],
    *,
    timeframe: str | None = None,
    force_rebuild: bool = False,
) -> dict[str, Any] | None:
    effective_timeframe = timeframe or settings.historical_base_timeframe
    unique_times = sorted({int(item) for item in open_times_ms})
    state = _load_market_overview_state(db, effective_timeframe)
    if state is None:
        if unique_times:
            return recompute_market_overview_state(
                db,
                timeframe=effective_timeframe,
                force=True,
                force_coverage_bootstrap=True,
            )
        return None

    if unique_times:
        merged_ranges = _merge_range_payloads(
            state.coverage_ranges_json or [],
            _build_range_payload_from_open_times(unique_times, timeframe_to_ms(effective_timeframe)),
            timeframe_to_ms(effective_timeframe),
        )
        state.coverage_ranges_json = merged_ranges
        state.coverage_start_ms, state.coverage_end_ms = _select_primary_range_window_ms(merged_ranges)
        db.add(state)
        db.commit()
        db.refresh(state)
        invalidate_market_overview_cache()

    if force_rebuild:
        return recompute_market_overview_state(db, timeframe=effective_timeframe, force=True)

    if _state_age_seconds(state) >= settings.market_overview_rebuild_dedupe_seconds:
        return recompute_market_overview_state(db, timeframe=effective_timeframe, force=True)
    return _serialize_market_overview_state(state)



def recompute_market_overview_state(
    db: Session,
    *,
    timeframe: str | None = None,
    force: bool = False,
    force_coverage_bootstrap: bool = False,
    latest_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from app.services.market_data_sync import (
        build_market_sync_gate_status,
        get_csv_ingestion_backlog,
        get_latest_market_coverage_snapshot,
        serialize_csv_ingestion_job,
    )

    effective_timeframe = timeframe or settings.historical_base_timeframe
    state = _load_market_overview_state(db, effective_timeframe)
    if state is not None and not force and not force_coverage_bootstrap:
        if _state_age_seconds(state) < settings.market_overview_rebuild_dedupe_seconds:
            return _serialize_market_overview_state(state)

    if state is None:
        state = MarketOverviewState(
            id=new_id("moview"),
            timeframe=effective_timeframe,
            created_at=utc_now(),
        )

    if force_coverage_bootstrap or not (state.coverage_ranges_json or []):
        coverage_ranges_payload = _serialize_coverage_ranges(get_market_data_coverage_ranges(db, timeframe=effective_timeframe))
    else:
        coverage_ranges_payload = _normalize_range_payloads(state.coverage_ranges_json or [])
    coverage_start_ms, coverage_end_ms = _select_primary_range_window_ms(coverage_ranges_payload)

    latest_snapshot_payload = latest_snapshot if latest_snapshot is not None else (get_latest_market_coverage_snapshot(db) or {})
    build_market_sync_gate_status(latest_snapshot_payload or None)

    sync_states = db.scalars(
        select(MarketSyncState)
        .where(MarketSyncState.timeframe == effective_timeframe)
        .order_by(MarketSyncState.base_symbol.asc())
    ).all()
    recent_jobs = db.scalars(
        select(CsvIngestionJob).order_by(CsvIngestionJob.requested_at.desc(), CsvIngestionJob.id.desc()).limit(10)
    ).all()
    ingest_backlog = get_csv_ingestion_backlog(db)

    state.timeframe = effective_timeframe
    state.total_candles_estimate = _estimate_total_candles(db)
    state.total_symbols = len(sync_states)
    state.coverage_start_ms = coverage_start_ms
    state.coverage_end_ms = coverage_end_ms
    state.coverage_ranges_json = coverage_ranges_payload
    state.bootstrap_pending_count = db.scalar(
        select(func.count())
        .select_from(MarketInstrument)
        .where(MarketInstrument.bootstrap_status != "ready")
    ) or 0
    state.backfill_lag_symbol_count = sum(
        1 for sync_state in sync_states if (sync_state.notes_json or {}).get("backfill_pending")
    )
    state.tier1_freshness_ms_p95 = _freshness_p95_ms([item for item in sync_states if item.priority_tier == "tier1"])
    state.tier2_freshness_ms_p95 = _freshness_p95_ms([item for item in sync_states if item.priority_tier == "tier2"])
    state.failed_sync_count = sum(1 for sync_state in sync_states if sync_state.status == "failed")
    state.skipped_sync_count = sum(1 for sync_state in sync_states if sync_state.status == "skipped")
    state.ingest_backlog_json = ingest_backlog
    state.recent_csv_jobs_json = [serialize_csv_ingestion_job(job) for job in recent_jobs]
    state.source_snapshot_id = str(latest_snapshot_payload.get("id")) if latest_snapshot_payload else None
    state.rebuilt_at = utc_now()
    db.add(state)
    db.commit()
    db.refresh(state)
    invalidate_market_overview_cache()
    return _serialize_market_overview_state(state)



def get_market_overview(db: Session) -> dict[str, Any]:
    cached_payload = _get_cached_market_overview_payload()
    if cached_payload is not None:
        return cached_payload

    acquired_refresh = _OVERVIEW_REFRESH_LOCK.acquire(blocking=False)
    if not acquired_refresh:
        cached_payload = _get_cached_market_overview_payload(ignore_ttl=True)
        if cached_payload is not None:
            return cached_payload
        _OVERVIEW_REFRESH_LOCK.acquire()
        acquired_refresh = True

    try:
        cached_payload = _get_cached_market_overview_payload()
        if cached_payload is not None:
            return cached_payload
        payload = _load_market_overview_payload(db)
        _store_cached_market_overview_payload(payload)
        return copy.deepcopy(payload)
    except Exception:
        cached_payload = _get_cached_market_overview_payload(ignore_ttl=True)
        if cached_payload is not None:
            return cached_payload
        raise
    finally:
        if acquired_refresh:
            _OVERVIEW_REFRESH_LOCK.release()



def list_market_symbols(db: Session) -> list[str]:
    rows = db.scalars(
        select(MarketCandle.market_symbol).distinct().order_by(MarketCandle.market_symbol.asc())
    ).all()
    return list(rows)



def get_market_sync_status(db: Session) -> dict[str, Any]:
    from app.services.market_data_sync import (
        build_market_sync_gate_status,
        get_csv_ingestion_backlog,
        get_latest_market_coverage_snapshot,
    )

    latest_snapshot = get_latest_market_coverage_snapshot(db)
    gate_status = build_market_sync_gate_status(latest_snapshot)
    recent_attempts = db.scalars(
        select(MarketSyncState)
        .where(MarketSyncState.last_error.is_not(None))
        .order_by(MarketSyncState.updated_at.desc())
        .limit(10)
    ).all()
    return {
        **gate_status,
        "ingest_backlog": get_csv_ingestion_backlog(db),
        "latest_snapshot": latest_snapshot or {},
        "recent_errors": [
            {
                "base_symbol": state.base_symbol,
                "priority_tier": state.priority_tier,
                "last_error": state.last_error,
                "retry_count": state.retry_count,
                "last_sync_completed_at_ms": datetime_to_ms(state.last_sync_completed_at)
                if state.last_sync_completed_at
                else None,
            }
            for state in recent_attempts
        ],
    }



def list_market_universe(db: Session) -> list[dict[str, Any]]:
    instruments = db.scalars(
        select(MarketInstrument).order_by(MarketInstrument.priority_tier.asc(), MarketInstrument.instrument_id.asc())
    ).all()
    states = {
        state.base_symbol: state
        for state in db.scalars(select(MarketSyncState)).all()
    }
    return [
        {
            "instrument_id": instrument.instrument_id,
            "base_symbol": instrument.base_symbol,
            "quote_asset": instrument.quote_asset,
            "instrument_type": instrument.instrument_type,
            "lifecycle_status": instrument.lifecycle_status,
            "priority_tier": instrument.priority_tier,
            "bootstrap_status": instrument.bootstrap_status,
            "last_trade_price": instrument.last_trade_price,
            "volume_24h_usd": instrument.volume_24h_usd,
            "discovered_at_ms": datetime_to_ms(instrument.discovered_at),
            "last_seen_active_at_ms": datetime_to_ms(instrument.last_seen_active_at) if instrument.last_seen_active_at else None,
            "delisted_at_ms": datetime_to_ms(instrument.delisted_at) if instrument.delisted_at else None,
            "sync_state": {
                "status": states[instrument.instrument_id].status,
                "last_synced_open_time_ms": states[instrument.instrument_id].last_synced_open_time_ms,
                "fresh_coverage_end_ms": states[instrument.instrument_id].fresh_coverage_end_ms,
                "next_sync_due_at_ms": datetime_to_ms(states[instrument.instrument_id].next_sync_due_at)
                if states[instrument.instrument_id].next_sync_due_at
                else None,
                "retry_count": states[instrument.instrument_id].retry_count,
                "last_error": states[instrument.instrument_id].last_error,
            }
            if instrument.instrument_id in states
            else None,
        }
        for instrument in instruments
    ]



def _load_market_overview_payload(db: Session) -> dict[str, Any]:
    from app.services.market_data_sync import build_market_sync_gate_status, get_latest_market_coverage_snapshot

    state = _load_market_overview_state(db, settings.historical_base_timeframe)
    if state is None:
        state_payload = recompute_market_overview_state(
            db,
            force=True,
            force_coverage_bootstrap=True,
        )
    elif _state_age_seconds(state) >= settings.market_overview_max_staleness_seconds:
        state_payload = recompute_market_overview_state(db, force=True)
    else:
        state_payload = _serialize_market_overview_state(state)

    latest_snapshot = get_latest_market_coverage_snapshot(db)
    market_sync = build_market_sync_gate_status(latest_snapshot)
    return {
        "historical_data_dir": str(settings.historical_data_dir),
        "base_timeframe": settings.historical_base_timeframe,
        "total_candles": int(state_payload.get("total_candles") or 0),
        "total_symbols": int(state_payload.get("total_symbols") or 0),
        "coverage_start_ms": state_payload.get("coverage_start_ms"),
        "coverage_end_ms": state_payload.get("coverage_end_ms"),
        "coverage_ranges": state_payload.get("coverage_ranges") or [],
        "recent_csv_jobs": state_payload.get("recent_csv_jobs") or [],
        "ingest_backlog": state_payload.get("ingest_backlog") or {},
        "sync_cursor_counts": state_payload.get("sync_cursor_counts") or {"total": 0, "failed": 0, "skipped": 0},
        "tier1_freshness_ms_p95": state_payload.get("tier1_freshness_ms_p95"),
        "tier2_freshness_ms_p95": state_payload.get("tier2_freshness_ms_p95"),
        "bootstrap_pending_count": int(state_payload.get("bootstrap_pending_count") or 0),
        "backfill_lag_symbol_count": int(state_payload.get("backfill_lag_symbol_count") or 0),
        "market_sync": market_sync,
        "latest_coverage_snapshot": latest_snapshot or {},
    }



def _serialize_market_overview_state(state: MarketOverviewState) -> dict[str, Any]:
    return {
        "timeframe": state.timeframe,
        "total_candles": int(state.total_candles_estimate or 0),
        "total_symbols": int(state.total_symbols or 0),
        "coverage_start_ms": state.coverage_start_ms,
        "coverage_end_ms": state.coverage_end_ms,
        "coverage_ranges": _normalize_range_payloads(state.coverage_ranges_json or []),
        "recent_csv_jobs": state.recent_csv_jobs_json or [],
        "ingest_backlog": state.ingest_backlog_json or {},
        "sync_cursor_counts": {
            "total": int(state.total_symbols or 0),
            "failed": int(state.failed_sync_count or 0),
            "skipped": int(state.skipped_sync_count or 0),
        },
        "tier1_freshness_ms_p95": state.tier1_freshness_ms_p95,
        "tier2_freshness_ms_p95": state.tier2_freshness_ms_p95,
        "bootstrap_pending_count": int(state.bootstrap_pending_count or 0),
        "backfill_lag_symbol_count": int(state.backfill_lag_symbol_count or 0),
        "source_snapshot_id": state.source_snapshot_id,
        "rebuilt_at_ms": datetime_to_ms(state.rebuilt_at),
    }



def _load_market_overview_state(db: Session, timeframe: str) -> MarketOverviewState | None:
    return db.scalar(
        select(MarketOverviewState)
        .where(MarketOverviewState.timeframe == timeframe)
        .limit(1)
    )



def _estimate_total_candles(db: Session) -> int:
    dialect_name = (db.bind.dialect.name if db.bind is not None else "").lower()
    if dialect_name != "postgresql":
        return int(db.scalar(select(func.count()).select_from(MarketCandle)) or 0)
    estimated = db.execute(
        text(
            """
            SELECT COALESCE(SUM(child.reltuples)::bigint, 0)
            FROM pg_class parent
            JOIN pg_inherits inherit ON inherit.inhparent = parent.oid
            JOIN pg_class child ON child.oid = inherit.inhrelid
            WHERE parent.relname = 'market_candles'
            """
        )
    ).scalar_one()
    return int(estimated or 0)



def _freshness_p95_ms(states: list[MarketSyncState]) -> int | None:
    values = []
    now_ms = datetime_to_ms(utc_now())
    for state in states:
        if state.last_sync_completed_at is None:
            continue
        values.append(max(now_ms - datetime_to_ms(state.last_sync_completed_at), 0))
    if not values:
        return None
    values.sort()
    index = max(int(len(values) * 0.95) - 1, 0)
    return values[index]



def _normalize_range_payloads(ranges: Sequence[dict[str, Any]]) -> list[dict[str, int]]:
    normalized = []
    for item in ranges:
        start_ms = item.get("start_ms")
        end_ms = item.get("end_ms")
        if start_ms is None or end_ms is None:
            continue
        start_value = int(start_ms)
        end_value = int(end_ms)
        if end_value < start_value:
            continue
        normalized.append({"start_ms": start_value, "end_ms": end_value})
    normalized.sort(key=lambda item: (item["start_ms"], item["end_ms"]))
    return normalized



def _serialize_coverage_ranges(ranges: Sequence[tuple[datetime, datetime]]) -> list[dict[str, int]]:
    return [
        {"start_ms": datetime_to_ms(start), "end_ms": datetime_to_ms(end)}
        for start, end in ranges
    ]



def _range_payload_to_datetimes(ranges: Sequence[dict[str, Any]]) -> list[tuple[datetime, datetime]]:
    return [
        (ms_to_datetime(int(item["start_ms"])), ms_to_datetime(int(item["end_ms"])))
        for item in _normalize_range_payloads(ranges)
    ]



def _build_range_payload_from_open_times(open_times_ms: Sequence[int], gap_threshold_ms: int) -> list[dict[str, int]]:
    if not open_times_ms:
        return []
    sorted_times = sorted({int(item) for item in open_times_ms})
    start_ms = sorted_times[0]
    previous_ms = sorted_times[0]
    ranges: list[dict[str, int]] = []
    for current_ms in sorted_times[1:]:
        if current_ms - previous_ms > gap_threshold_ms:
            ranges.append({"start_ms": start_ms, "end_ms": previous_ms})
            start_ms = current_ms
        previous_ms = current_ms
    ranges.append({"start_ms": start_ms, "end_ms": previous_ms})
    return ranges



def _merge_range_payloads(
    existing_ranges: Sequence[dict[str, Any]],
    new_ranges: Sequence[dict[str, Any]],
    gap_threshold_ms: int,
) -> list[dict[str, int]]:
    merged_source = _normalize_range_payloads(existing_ranges) + _normalize_range_payloads(new_ranges)
    if not merged_source:
        return []
    merged_source.sort(key=lambda item: (item["start_ms"], item["end_ms"]))
    merged_ranges = [dict(merged_source[0])]
    for current in merged_source[1:]:
        last = merged_ranges[-1]
        if current["start_ms"] - last["end_ms"] <= gap_threshold_ms:
            last["end_ms"] = max(last["end_ms"], current["end_ms"])
            continue
        merged_ranges.append(dict(current))
    return merged_ranges



def _select_primary_range_window_ms(ranges: Sequence[dict[str, Any]]) -> tuple[int | None, int | None]:
    normalized = _normalize_range_payloads(ranges)
    if not normalized:
        return None, None
    best_range = max(
        normalized,
        key=lambda item: ((item["end_ms"] - item["start_ms"]), item["end_ms"]),
    )
    return best_range["start_ms"], best_range["end_ms"]



def _state_age_seconds(state: MarketOverviewState) -> float:
    rebuilt_at = state.rebuilt_at
    if rebuilt_at.tzinfo is None:
        rebuilt_at = rebuilt_at.replace(tzinfo=utc_now().tzinfo)
    return max((utc_now() - rebuilt_at).total_seconds(), 0.0)



def _get_cached_market_overview_payload(*, ignore_ttl: bool = False) -> dict[str, Any] | None:
    with _OVERVIEW_CACHE_LOCK:
        if _OVERVIEW_CACHE_PAYLOAD is None:
            return None
        if not ignore_ttl:
            age_seconds = time.monotonic() - _OVERVIEW_CACHE_AT_MONOTONIC
            if age_seconds >= settings.market_overview_cache_ttl_seconds:
                return None
        return copy.deepcopy(_OVERVIEW_CACHE_PAYLOAD)



def _store_cached_market_overview_payload(payload: dict[str, Any]) -> None:
    global _OVERVIEW_CACHE_AT_MONOTONIC, _OVERVIEW_CACHE_PAYLOAD
    with _OVERVIEW_CACHE_LOCK:
        _OVERVIEW_CACHE_PAYLOAD = copy.deepcopy(payload)
        _OVERVIEW_CACHE_AT_MONOTONIC = time.monotonic()



def _bucket_expr(open_time_column, timeframe_ms: int):
    return open_time_column - (open_time_column % timeframe_ms)



def _serialize_aggregated_candle_row(row) -> dict[str, Any]:
    return {
        "market_symbol": row.market_symbol,
        "base_symbol": row.base_symbol,
        "timeframe": row.timeframe,
        "open_time_ms": int(row.open_time_ms),
        "open": float(row.open),
        "high": float(row.high),
        "low": float(row.low),
        "close": float(row.close),
        "vol": float(row.vol),
        "vol_ccy": float(row.vol_ccy) if row.vol_ccy is not None else None,
        "vol_quote": float(row.vol_quote) if row.vol_quote is not None else None,
        "confirm": bool(row.confirm_int),
        "source": row.source,
    }
