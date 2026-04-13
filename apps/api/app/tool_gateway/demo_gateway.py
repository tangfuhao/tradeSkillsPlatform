from __future__ import annotations
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import MarketCandle, StrategyState
from app.services.market_data_store import build_market_snapshot, fetch_candles, has_market_data
from app.services.utils import ensure_utc, new_id, utc_now


FALLBACK_SYMBOLS = [
    "DOGE-USDT-SWAP",
    "WIF-USDT-SWAP",
    "SOL-USDT-SWAP",
    "PEPE-USDT-SWAP",
]


def build_market_snapshot_for_backtest(db: Session, as_of: datetime, step_index: int) -> dict[str, Any]:
    if has_market_data(db):
        snapshot = build_market_snapshot(db, as_of)
        if snapshot["market_candidates"]:
            snapshot["provider"] = "historical_db"
            return snapshot
    return _build_fallback_snapshot(step_index)


def build_market_snapshot_for_live(db: Session) -> dict[str, Any]:
    latest_open_time_ms = db.scalar(select(func.max(MarketCandle.open_time_ms)).select_from(MarketCandle))
    if latest_open_time_ms is not None:
        as_of = datetime.fromtimestamp(latest_open_time_ms / 1000, tz=timezone.utc)
        snapshot = build_market_snapshot(db, as_of)
        if snapshot["market_candidates"]:
            snapshot["provider"] = "historical_db"
            return snapshot
    return _build_fallback_snapshot(0)


def get_strategy_state(db: Session, skill_id: str) -> dict[str, Any]:
    state = db.scalar(select(StrategyState).where(StrategyState.skill_id == skill_id))
    if state is None:
        state = StrategyState(id=new_id("state"), skill_id=skill_id, state_json={})
        db.add(state)
        db.commit()
        db.refresh(state)
    return state.state_json or {}


def save_strategy_state(db: Session, skill_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    state = db.scalar(select(StrategyState).where(StrategyState.skill_id == skill_id))
    if state is None:
        state = StrategyState(id=new_id("state"), skill_id=skill_id, state_json={})
        db.add(state)
        db.flush()
    next_state = dict(state.state_json or {})
    next_state.update(patch)
    state.state_json = next_state
    db.commit()
    db.refresh(state)
    return next_state


def get_candles_tool(db: Session, market_symbol: str, timeframe: str, limit: int, end_time: datetime | None = None) -> list[dict[str, Any]]:
    return fetch_candles(db, market_symbol=market_symbol, timeframe=timeframe, limit=limit, end_time=end_time)


def execute_tool_gateway_request(
    db: Session,
    *,
    tool_name: str,
    skill_id: str,
    mode: str,
    trigger_time: datetime,
    arguments: dict[str, Any],
    as_of: datetime | None = None,
    trace_index: int | None = None,
) -> dict[str, Any]:
    effective_as_of = ensure_utc(as_of or trigger_time)

    if tool_name == "scan_market":
        snapshot = build_market_snapshot_for_tool_request(db, effective_as_of, trace_index or 0)
        top_n = max(1, min(int(arguments.get("top_n", 8) or 8), 20))
        requested_sort = str(arguments.get("sort_by", "volume_24h_usd") or "volume_24h_usd")
        sort_aliases = {
            "change_pct": "change_24h_pct",
            "price_change": "change_24h_pct",
            "change_24h": "change_24h_pct",
            "volume": "volume_24h_usd",
            "oi_change": "open_interest_change_24h_pct",
            "open_interest": "open_interest_change_24h_pct",
            "funding": "funding_rate",
            "rank": "volume_24h_usd",
        }
        sort_by = sort_aliases.get(requested_sort, requested_sort)
        candidates = list(snapshot.get("market_candidates", []))
        candidates.sort(key=lambda item: float(item.get(sort_by, 0.0) or 0.0), reverse=True)
        return {
            "status": "ok",
            "content": {
                "count": len(candidates[:top_n]),
                "candidates": candidates[:top_n],
                "source": snapshot.get("provider") or snapshot.get("source"),
                "as_of": snapshot.get("as_of"),
            },
        }

    if tool_name == "get_strategy_state":
        return {
            "status": "ok",
            "content": {
                "strategy_state": get_strategy_state(db, skill_id),
            },
        }

    if tool_name == "save_strategy_state":
        patch = arguments.get("patch") or {}
        if not isinstance(patch, dict):
            return {"status": "error", "content": {"error": "patch must be an object"}}
        return {
            "status": "ok",
            "content": {
                "strategy_state": save_strategy_state(db, skill_id, patch),
            },
        }

    if tool_name == "get_market_metadata":
        resolved_symbol = _resolve_market_symbol_for_gateway(db, arguments.get("market_symbol"))
        snapshot = build_market_snapshot_for_tool_request(db, effective_as_of, trace_index or 0)
        candidate = _candidate_from_snapshot(snapshot, resolved_symbol)
        return {
            "status": "ok",
            "content": {
                "market_symbol": resolved_symbol,
                "candidate": candidate,
                "as_of": snapshot.get("as_of"),
                "source": snapshot.get("provider") or snapshot.get("source"),
                "mode": mode,
            },
        }

    if tool_name == "get_candles":
        resolved_symbol = _resolve_market_symbol_for_gateway(db, arguments.get("market_symbol"))
        timeframe = str(arguments.get("timeframe") or "").strip().lower()
        limit = max(1, min(int(arguments.get("limit", 80) or 80), 200))
        rows = fetch_candles(
            db,
            market_symbol=resolved_symbol,
            timeframe=timeframe,
            limit=limit,
            end_time=effective_as_of,
        )
        if not rows:
            return {
                "status": "not_available",
                "content": {
                    "error": f"No candles found for {resolved_symbol} {timeframe}",
                    "market_symbol": resolved_symbol,
                    "timeframe": timeframe,
                    "as_of": effective_as_of.isoformat(),
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
                        "open_time": row["open_time"].isoformat() if hasattr(row["open_time"], "isoformat") else row["open_time"],
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

    if tool_name in {"get_funding_rate", "get_open_interest"}:
        resolved_symbol = _resolve_market_symbol_for_gateway(db, arguments.get("market_symbol"))
        snapshot = build_market_snapshot_for_tool_request(db, effective_as_of, trace_index or 0)
        candidate = _candidate_from_snapshot(snapshot, resolved_symbol)
        if tool_name == "get_funding_rate":
            return {
                "status": "ok" if candidate else "not_available",
                "content": {
                    "market_symbol": resolved_symbol,
                    "funding_rate": float(candidate.get("funding_rate", 0.0) or 0.0) if candidate else None,
                },
            }
        return {
            "status": "ok" if candidate else "not_available",
            "content": {
                "market_symbol": resolved_symbol,
                "open_interest_change_24h_pct": float(candidate.get("open_interest_change_24h_pct", 0.0) or 0.0)
                if candidate
                else None,
            },
        }

    return {"status": "unsupported", "content": {"error": f"Unsupported tool: {tool_name}"}}


def _build_fallback_snapshot(step_index: int) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for offset, symbol in enumerate(FALLBACK_SYMBOLS):
        signal_index = step_index + (offset * 2)
        change_24h_pct = round(0.05 + ((signal_index * 7) % 24) / 100.0, 4)
        funding_rate = round(0.0003 + ((signal_index * 3) % 8) / 10000.0, 5)
        open_interest_change_24h_pct = round(0.03 + ((signal_index * 5) % 14) / 100.0, 4)
        volume_24h_usd = 15_000_000 + ((signal_index * 13) % 25) * 2_500_000
        last_price = round(0.25 + offset * 0.18 + signal_index * 0.01, 4)
        candidates.append(
            {
                "symbol": symbol,
                "base_symbol": symbol,
                "last_price": last_price,
                "change_24h_pct": change_24h_pct,
                "volume_24h_usd": volume_24h_usd,
                "funding_rate": funding_rate,
                "open_interest_change_24h_pct": open_interest_change_24h_pct,
                "is_old_contract": False,
            }
        )
    return {"market_candidates": candidates, "provider": "synthetic_fallback", "as_of": utc_now().isoformat()}


def build_market_snapshot_for_tool_request(db: Session, as_of: datetime, step_index: int) -> dict[str, Any]:
    if has_market_data(db):
        snapshot = build_market_snapshot(db, as_of)
        if snapshot["market_candidates"]:
            snapshot["provider"] = "historical_db"
            return snapshot
    return _build_fallback_snapshot(step_index)


def _candidate_from_snapshot(snapshot: dict[str, Any], market_symbol: str | None) -> dict[str, Any] | None:
    if not market_symbol:
        return None
    normalized = market_symbol.upper()
    for item in snapshot.get("market_candidates", []):
        if str(item.get("symbol") or "").upper() == normalized:
            return item
    return None


def _resolve_market_symbol_for_gateway(db: Session, raw_symbol: Any) -> str:
    symbol = str(raw_symbol or "").strip().upper()
    if not symbol:
        return ""

    exact_match = db.scalar(
        select(MarketCandle.market_symbol).where(MarketCandle.market_symbol == symbol).limit(1)
    )
    if exact_match:
        return exact_match

    base_symbol = symbol
    if "#OLD#" in base_symbol:
        base_symbol = base_symbol.split("#OLD#")[0]
    if not base_symbol.endswith("-USDT-SWAP"):
        base_symbol = f"{base_symbol}-USDT-SWAP"

    direct_match = db.scalar(
        select(MarketCandle.market_symbol).where(MarketCandle.market_symbol == base_symbol).limit(1)
    )
    if direct_match:
        return direct_match

    related_match = db.scalar(
        select(MarketCandle.market_symbol)
        .where(MarketCandle.base_symbol == base_symbol)
        .order_by(MarketCandle.is_old_contract.asc(), MarketCandle.open_time_ms.desc())
        .limit(1)
    )
    if related_match:
        return related_match

    return base_symbol
