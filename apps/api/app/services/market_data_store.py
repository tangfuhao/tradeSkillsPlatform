from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import CsvIngestionJob, MarketCandle, MarketSyncCursor
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
                "open_time": ms_to_datetime(bucket_ms),
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
        "open_time": ms_to_datetime(row.open_time_ms),
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


def build_market_snapshot(db: Session, as_of: datetime, limit: int | None = None) -> dict[str, Any]:
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
                "as_of": ms_to_datetime(last.open_time_ms).isoformat(),
            }
        )
    candidates.sort(key=lambda item: (item["volume_24h_usd"], abs(item["change_24h_pct"])), reverse=True)
    selected = candidates[: limit or settings.market_scan_limit_default]
    return {
        "market_candidates": selected,
        "source": "historical_db",
        "as_of": as_of.isoformat(),
    }


def has_market_data(db: Session) -> bool:
    return db.scalar(select(func.count()).select_from(MarketCandle)) > 0


def get_market_overview(db: Session) -> dict[str, Any]:
    total_candles = db.scalar(select(func.count()).select_from(MarketCandle)) or 0
    total_symbols = db.scalar(select(func.count(func.distinct(MarketCandle.market_symbol))).select_from(MarketCandle)) or 0
    min_max = db.execute(
        select(func.min(MarketCandle.open_time_ms), func.max(MarketCandle.open_time_ms))
    ).one()
    jobs = db.scalars(select(CsvIngestionJob).order_by(CsvIngestionJob.started_at.desc()).limit(10)).all()
    cursors = db.scalars(select(MarketSyncCursor).order_by(MarketSyncCursor.base_symbol.asc())).all()
    return {
        "historical_data_dir": str(settings.historical_data_dir),
        "base_timeframe": settings.historical_base_timeframe,
        "total_candles": total_candles,
        "total_symbols": total_symbols,
        "coverage_start": ms_to_datetime(min_max[0]).isoformat() if min_max[0] else None,
        "coverage_end": ms_to_datetime(min_max[1]).isoformat() if min_max[1] else None,
        "recent_csv_jobs": [
            {
                "id": job.id,
                "source_path": job.source_path,
                "status": job.status,
                "rows_seen": job.rows_seen,
                "rows_inserted": job.rows_inserted,
                "rows_filtered": job.rows_filtered,
                "coverage_start": ms_to_datetime(job.coverage_start_ms).isoformat() if job.coverage_start_ms else None,
                "coverage_end": ms_to_datetime(job.coverage_end_ms).isoformat() if job.coverage_end_ms else None,
                "completed_at": job.completed_at,
                "error_message": job.error_message,
            }
            for job in jobs
        ],
        "sync_cursors": [
            {
                "base_symbol": cursor.base_symbol,
                "timeframe": cursor.timeframe,
                "status": cursor.status,
                "last_synced_open_time_ms": cursor.last_synced_open_time_ms,
                "last_synced_open_time": ms_to_datetime(cursor.last_synced_open_time_ms).isoformat()
                if cursor.last_synced_open_time_ms
                else None,
                "last_sync_completed_at": cursor.last_sync_completed_at,
                "notes": cursor.notes_json or {},
            }
            for cursor in cursors
        ],
    }


def list_market_symbols(db: Session) -> list[str]:
    rows = db.scalars(
        select(MarketCandle.market_symbol).distinct().order_by(MarketCandle.market_symbol.asc())
    ).all()
    return list(rows)
