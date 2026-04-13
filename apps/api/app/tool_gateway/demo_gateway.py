from __future__ import annotations
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import MarketCandle, StrategyState
from app.services.market_data_store import build_market_snapshot, fetch_candles, has_market_data
from app.services.utils import ensure_utc, new_id, utc_now
from app.tool_gateway.market_handlers import (
    handle_get_candles,
    handle_get_funding_rate,
    handle_get_open_interest,
    handle_market_metadata,
    handle_scan_market,
)
from app.tool_gateway.signal_handlers import handle_signal_intent
from app.tool_gateway.state_handlers import handle_get_strategy_state, handle_save_strategy_state


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
        return handle_scan_market(
            db,
            as_of=effective_as_of,
            trace_index=trace_index,
            top_n=max(1, min(int(arguments.get("top_n", 8) or 8), 20)),
            sort_by=str(arguments.get("sort_by", "volume_24h_usd") or "volume_24h_usd"),
        )

    if tool_name == "get_strategy_state":
        return handle_get_strategy_state(db, skill_id=skill_id)

    if tool_name == "save_strategy_state":
        return handle_save_strategy_state(db, skill_id=skill_id, patch=arguments.get("patch") or {})

    if tool_name == "get_market_metadata":
        return handle_market_metadata(
            db,
            as_of=effective_as_of,
            trace_index=trace_index,
            market_symbol=str(arguments.get("market_symbol") or ""),
            mode=mode,
        )

    if tool_name == "get_candles":
        return handle_get_candles(
            db,
            as_of=effective_as_of,
            market_symbol=str(arguments.get("market_symbol") or ""),
            timeframe=str(arguments.get("timeframe") or "").strip().lower(),
            limit=max(1, min(int(arguments.get("limit", 80) or 80), 200)),
        )

    if tool_name in {"get_funding_rate", "get_open_interest"}:
        if tool_name == "get_funding_rate":
            return handle_get_funding_rate(
                db,
                as_of=effective_as_of,
                trace_index=trace_index,
                market_symbol=str(arguments.get("market_symbol") or ""),
            )
        return handle_get_open_interest(
            db,
            as_of=effective_as_of,
            trace_index=trace_index,
            market_symbol=str(arguments.get("market_symbol") or ""),
        )

    if tool_name in {"simulate_order", "emit_signal"}:
        return handle_signal_intent(
            tool_name=tool_name,
            action=arguments.get("action"),
            symbol=arguments.get("symbol"),
            direction=arguments.get("direction"),
            size_pct=float(arguments.get("size_pct", 0.0) or 0.0),
            reason=arguments.get("reason"),
            stop_loss_pct=arguments.get("stop_loss_pct"),
            take_profit_pct=arguments.get("take_profit_pct"),
        )

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


def candidate_from_snapshot(snapshot: dict[str, Any], market_symbol: str | None) -> dict[str, Any] | None:
    if not market_symbol:
        return None
    normalized = market_symbol.upper()
    for item in snapshot.get("market_candidates", []):
        if str(item.get("symbol") or "").upper() == normalized:
            return item
    return None


def resolve_market_symbol_for_gateway(db: Session, raw_symbol: Any) -> str:
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
