from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import CsvIngestionJob, MarketCandle, MarketInstrument, MarketSyncState
from app.services.utils import datetime_to_ms, ms_to_datetime, utc_now


def normalize_timeframe(value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError("timeframe is required")
    suffix = text[-1].lower()
    amount = int(text[:-1])
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
    lookback_start_ms = None
    if end_time_ms is not None:
        lookback_start_ms = end_time_ms - (timeframe_ms * max(limit, 1) * 2)
    query = select(MarketCandle).where(
        MarketCandle.market_symbol == market_symbol,
        MarketCandle.timeframe == settings.historical_base_timeframe,
    )
    if end_time_ms is not None:
        query = query.where(MarketCandle.open_time_ms <= end_time_ms)
    if lookback_start_ms is not None:
        query = query.where(MarketCandle.open_time_ms >= lookback_start_ms)
    rows = db.scalars(query.order_by(MarketCandle.open_time_ms.asc())).all()
    aggregated = aggregate_rows(rows, normalized_timeframe)
    return aggregated[-limit:]


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
    rows = db.scalars(
        select(MarketCandle).where(
            MarketCandle.timeframe == settings.historical_base_timeframe,
            MarketCandle.open_time_ms >= start_ms,
            MarketCandle.open_time_ms <= as_of_ms,
        ).order_by(MarketCandle.market_symbol.asc(), MarketCandle.open_time_ms.asc())
    ).all()
    grouped: dict[str, list[MarketCandle]] = defaultdict(list)
    for row in rows:
        grouped[row.market_symbol].append(row)

    candidates: list[dict[str, Any]] = []
    for market_symbol, symbol_rows in grouped.items():
        if allowed_market_symbols is not None and market_symbol not in allowed_market_symbols:
            continue
        if not symbol_rows:
            continue
        first = symbol_rows[0]
        last = symbol_rows[-1]
        if first.open <= 0:
            continue
        volume_24h_quote = sum((item.vol_quote if item.vol_quote is not None else item.close * item.vol) for item in symbol_rows)
        change_24h_pct = round((last.close - first.open) / first.open, 4)
        candidates.append(
            {
                "symbol": market_symbol,
                "base_symbol": last.base_symbol,
                "last_price": round(last.close, 8),
                "change_24h_pct": change_24h_pct,
                "volume_24h_usd": round(volume_24h_quote, 2),
                "funding_rate": 0.0,
                "open_interest_change_24h_pct": 0.0,
                "is_old_contract": last.is_old_contract,
                "as_of_ms": last.open_time_ms,
            }
        )
    candidates.sort(key=lambda item: (item["volume_24h_usd"], abs(item["change_24h_pct"])), reverse=True)
    selected = candidates[: limit or settings.market_scan_limit_default]
    return {
        "market_candidates": selected,
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
    open_times = db.scalars(
        select(MarketCandle.open_time_ms)
        .where(MarketCandle.timeframe == effective_timeframe)
        .distinct()
        .order_by(MarketCandle.open_time_ms.asc())
    ).all()
    if not open_times:
        return []

    coverage_ranges_ms: list[tuple[int, int]] = []
    range_start_ms = open_times[0]
    previous_ms = open_times[0]

    for current_ms in open_times[1:]:
        if current_ms - previous_ms > gap_threshold_ms:
            coverage_ranges_ms.append((range_start_ms, previous_ms))
            range_start_ms = current_ms
        previous_ms = current_ms

    coverage_ranges_ms.append((range_start_ms, previous_ms))
    return [(ms_to_datetime(start_ms), ms_to_datetime(end_ms)) for start_ms, end_ms in coverage_ranges_ms]


def get_market_data_coverage(db: Session) -> tuple[datetime | None, datetime | None]:
    coverage_ranges = get_market_data_coverage_ranges(db)
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


def get_market_overview(db: Session) -> dict[str, Any]:
    from app.services.market_data_sync import get_latest_market_coverage_snapshot, get_market_sync_gate_status

    total_candles = db.scalar(select(func.count()).select_from(MarketCandle)) or 0
    total_symbols = db.scalar(select(func.count(func.distinct(MarketCandle.market_symbol))).select_from(MarketCandle)) or 0
    coverage_ranges = get_market_data_coverage_ranges(db)
    coverage_start, coverage_end = get_market_data_coverage(db)
    jobs = db.scalars(select(CsvIngestionJob).order_by(CsvIngestionJob.started_at.desc()).limit(10)).all()
    sync_states = db.scalars(select(MarketSyncState).order_by(MarketSyncState.base_symbol.asc())).all()
    gate_status = get_market_sync_gate_status(db)
    latest_snapshot = get_latest_market_coverage_snapshot(db) or {}
    tier1_states = [state for state in sync_states if state.priority_tier == "tier1"]
    tier2_states = [state for state in sync_states if state.priority_tier == "tier2"]
    return {
        "historical_data_dir": str(settings.historical_data_dir),
        "base_timeframe": settings.historical_base_timeframe,
        "total_candles": total_candles,
        "total_symbols": total_symbols,
        "coverage_start_ms": datetime_to_ms(coverage_start) if coverage_start else None,
        "coverage_end_ms": datetime_to_ms(coverage_end) if coverage_end else None,
        "coverage_ranges": [
            {
                "start_ms": datetime_to_ms(range_start),
                "end_ms": datetime_to_ms(range_end),
            }
            for range_start, range_end in coverage_ranges
        ],
        "recent_csv_jobs": [
            {
                "id": job.id,
                "source_path": job.source_path,
                "status": job.status,
                "rows_seen": job.rows_seen,
                "rows_inserted": job.rows_inserted,
                "rows_filtered": job.rows_filtered,
                "coverage_start_ms": job.coverage_start_ms,
                "coverage_end_ms": job.coverage_end_ms,
                "completed_at_ms": datetime_to_ms(job.completed_at) if job.completed_at else None,
                "error_message": job.error_message,
            }
            for job in jobs
        ],
        "sync_cursors": [
            {
                "base_symbol": state.base_symbol,
                "timeframe": state.timeframe,
                "status": state.status,
                "last_synced_open_time_ms": state.last_synced_open_time_ms,
                "last_sync_completed_at_ms": datetime_to_ms(state.last_sync_completed_at)
                if state.last_sync_completed_at
                else None,
                "notes": state.notes_json or {},
            }
            for state in sync_states
        ],
        "tier1_freshness_ms_p95": _freshness_p95_ms(tier1_states),
        "tier2_freshness_ms_p95": _freshness_p95_ms(tier2_states),
        "bootstrap_pending_count": db.scalar(
            select(func.count()).select_from(MarketInstrument).where(MarketInstrument.bootstrap_status != "ready")
        )
        or 0,
        "backfill_lag_symbol_count": sum(1 for state in sync_states if (state.notes_json or {}).get("backfill_pending")),
        "market_sync": gate_status,
        "latest_coverage_snapshot": latest_snapshot,
    }


def list_market_symbols(db: Session) -> list[str]:
    rows = db.scalars(
        select(MarketCandle.market_symbol).distinct().order_by(MarketCandle.market_symbol.asc())
    ).all()
    return list(rows)


def get_market_sync_status(db: Session) -> dict[str, Any]:
    from app.services.market_data_sync import get_latest_market_coverage_snapshot, get_market_sync_gate_status

    gate_status = get_market_sync_gate_status(db)
    latest_snapshot = get_latest_market_coverage_snapshot(db) or {}
    recent_attempts = db.scalars(
        select(MarketSyncState).where(MarketSyncState.last_error.is_not(None)).order_by(MarketSyncState.updated_at.desc()).limit(10)
    ).all()
    return {
        **gate_status,
        "latest_snapshot": latest_snapshot,
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
    instruments = db.scalars(select(MarketInstrument).order_by(MarketInstrument.priority_tier.asc(), MarketInstrument.instrument_id.asc())).all()
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
