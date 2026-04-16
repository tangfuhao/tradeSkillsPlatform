from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import case, desc, func, literal, select
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
        if row.first_open not in {None, 0} and row.last_price is not None and row.volume_24h_usd is not None and row.as_of_ms is not None
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
        func.lag(distinct_open_times.c.open_time_ms).over(order_by=distinct_open_times.c.open_time_ms.asc()).label("previous_open_time_ms"),
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
    from app.services.market_data_sync import (
        get_csv_ingestion_backlog,
        get_latest_market_coverage_snapshot,
        get_market_sync_gate_status,
        serialize_csv_ingestion_job,
    )

    total_candles = db.scalar(select(func.count()).select_from(MarketCandle)) or 0
    total_symbols = db.scalar(select(func.count(func.distinct(MarketCandle.market_symbol))).select_from(MarketCandle)) or 0
    coverage_ranges = get_market_data_coverage_ranges(db)
    coverage_start, coverage_end = get_market_data_coverage(db)
    jobs = db.scalars(select(CsvIngestionJob).order_by(CsvIngestionJob.requested_at.desc()).limit(10)).all()
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
        "recent_csv_jobs": [serialize_csv_ingestion_job(job) for job in jobs],
        "ingest_backlog": get_csv_ingestion_backlog(db),
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
    from app.services.market_data_sync import (
        get_csv_ingestion_backlog,
        get_latest_market_coverage_snapshot,
        get_market_sync_gate_status,
    )

    gate_status = get_market_sync_gate_status(db)
    latest_snapshot = get_latest_market_coverage_snapshot(db) or {}
    recent_attempts = db.scalars(
        select(MarketSyncState).where(MarketSyncState.last_error.is_not(None)).order_by(MarketSyncState.updated_at.desc()).limit(10)
    ).all()
    return {
        **gate_status,
        "ingest_backlog": get_csv_ingestion_backlog(db),
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
