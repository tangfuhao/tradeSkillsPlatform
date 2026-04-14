from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.services.market_data_store import fetch_candles
from app.services.utils import datetime_to_ms, ensure_utc


SORT_ALIASES = {
    "change_pct": "change_24h_pct",
    "price_change": "change_24h_pct",
    "change_24h": "change_24h_pct",
    "volume": "volume_24h_usd",
    "oi_change": "open_interest_change_24h_pct",
    "open_interest": "open_interest_change_24h_pct",
    "funding": "funding_rate",
    "rank": "volume_24h_usd",
}


def handle_scan_market(
    db: Session,
    *,
    as_of: datetime,
    trace_index: int | None,
    top_n: int,
    sort_by: str,
) -> dict[str, Any]:
    from app.tool_gateway.demo_gateway import build_market_snapshot_for_tool_request

    snapshot = build_market_snapshot_for_tool_request(db, ensure_utc(as_of), trace_index or 0)
    normalized_sort = SORT_ALIASES.get(sort_by, sort_by)
    candidates = list(snapshot.get("market_candidates", []))
    candidates.sort(key=lambda item: float(item.get(normalized_sort, 0.0) or 0.0), reverse=True)
    if not candidates:
        return {
            "status": "not_available",
            "content": {
                "count": 0,
                "candidates": [],
                "source": snapshot.get("provider") or snapshot.get("source"),
                "as_of_ms": snapshot.get("as_of_ms"),
                "error": snapshot.get("error") or f"No market candidates are available as of {datetime_to_ms(ensure_utc(as_of))}.",
            },
        }
    return {
        "status": "ok",
        "content": {
            "count": len(candidates[:top_n]),
            "candidates": candidates[:top_n],
            "source": snapshot.get("provider") or snapshot.get("source"),
            "as_of_ms": snapshot.get("as_of_ms"),
        },
    }


def handle_market_metadata(
    db: Session,
    *,
    as_of: datetime,
    trace_index: int | None,
    market_symbol: str,
    mode: str,
) -> dict[str, Any]:
    from app.tool_gateway.demo_gateway import build_market_snapshot_for_tool_request, candidate_from_snapshot, resolve_market_symbol_for_gateway

    resolved_symbol = resolve_market_symbol_for_gateway(db, market_symbol)
    snapshot = build_market_snapshot_for_tool_request(db, ensure_utc(as_of), trace_index or 0)
    candidate = candidate_from_snapshot(snapshot, resolved_symbol)
    if candidate is None:
        return {
            "status": "not_available",
            "content": {
                "market_symbol": resolved_symbol,
                "candidate": None,
                "as_of_ms": snapshot.get("as_of_ms"),
                "source": snapshot.get("provider") or snapshot.get("source"),
                "mode": mode,
                "error": snapshot.get("error") or f"No market metadata is available for {resolved_symbol}.",
            },
        }
    return {
        "status": "ok",
        "content": {
            "market_symbol": resolved_symbol,
            "candidate": candidate,
            "as_of_ms": snapshot.get("as_of_ms"),
            "source": snapshot.get("provider") or snapshot.get("source"),
            "mode": mode,
        },
    }


def handle_get_candles(
    db: Session,
    *,
    as_of: datetime,
    market_symbol: str,
    timeframe: str,
    limit: int,
) -> dict[str, Any]:
    from app.tool_gateway.demo_gateway import resolve_market_symbol_for_gateway

    resolved_symbol = resolve_market_symbol_for_gateway(db, market_symbol)
    rows = fetch_candles(
        db,
        market_symbol=resolved_symbol,
        timeframe=timeframe,
        limit=limit,
        end_time=ensure_utc(as_of),
    )
    if not rows:
        return {
            "status": "not_available",
            "content": {
                "error": f"No candles found for {resolved_symbol} {timeframe}",
                "market_symbol": resolved_symbol,
                "timeframe": timeframe,
                "as_of_ms": datetime_to_ms(ensure_utc(as_of)),
            },
        }

    close_values = [float(item["close"]) for item in rows]
    summary = {
        "count": len(rows),
        "latest_close": close_values[-1] if close_values else None,
        "window_change_pct": round((close_values[-1] - close_values[0]) / close_values[0], 4)
        if len(close_values) >= 2 and close_values[0] > 0
        else 0.0,
    }
    return {
        "status": "ok",
        "content": {
            "market_symbol": resolved_symbol,
            "timeframe": timeframe,
            "summary": summary,
            "candles": [
                {
                    "open_time_ms": row["open_time_ms"],
                    "open": row["open"],
                    "high": row["high"],
                    "low": row["low"],
                    "close": row["close"],
                    "vol": row["vol"],
                }
                for row in rows
            ],
        },
    }


def handle_get_funding_rate(
    db: Session,
    *,
    as_of: datetime,
    trace_index: int | None,
    market_symbol: str,
) -> dict[str, Any]:
    from app.tool_gateway.demo_gateway import build_market_snapshot_for_tool_request, candidate_from_snapshot, resolve_market_symbol_for_gateway

    resolved_symbol = resolve_market_symbol_for_gateway(db, market_symbol)
    snapshot = build_market_snapshot_for_tool_request(db, ensure_utc(as_of), trace_index or 0)
    candidate = candidate_from_snapshot(snapshot, resolved_symbol)
    return {
        "status": "ok" if candidate else "not_available",
        "content": {
            "market_symbol": resolved_symbol,
            "funding_rate": float(candidate.get("funding_rate", 0.0) or 0.0) if candidate else None,
        },
    }


def handle_get_open_interest(
    db: Session,
    *,
    as_of: datetime,
    trace_index: int | None,
    market_symbol: str,
) -> dict[str, Any]:
    from app.tool_gateway.demo_gateway import build_market_snapshot_for_tool_request, candidate_from_snapshot, resolve_market_symbol_for_gateway

    resolved_symbol = resolve_market_symbol_for_gateway(db, market_symbol)
    snapshot = build_market_snapshot_for_tool_request(db, ensure_utc(as_of), trace_index or 0)
    candidate = candidate_from_snapshot(snapshot, resolved_symbol)
    return {
        "status": "ok" if candidate else "not_available",
        "content": {
            "market_symbol": resolved_symbol,
            "open_interest_change_24h_pct": float(candidate.get("open_interest_change_24h_pct", 0.0) or 0.0)
            if candidate
            else None,
        },
    }
