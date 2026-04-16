from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import MarketCandle
from app.services.market_data_store import build_market_snapshot, fetch_candles
from app.services.portfolio_engine import PortfolioEngine
from app.services.utils import ensure_utc, new_id
from app.tool_gateway.market_handlers import (
    handle_get_candles,
    handle_get_funding_rate,
    handle_get_open_interest,
    handle_market_metadata,
    handle_scan_market,
)
from app.tool_gateway.portfolio_handlers import handle_get_portfolio_state
from app.tool_gateway.signal_handlers import handle_signal_intent
from app.tool_gateway.state_handlers import handle_get_strategy_state, handle_save_strategy_state


def build_market_snapshot_for_backtest(db: Session, as_of: datetime, step_index: int) -> dict[str, Any]:
    del step_index
    return _build_strict_snapshot(db, as_of)


def build_market_snapshot_for_live(
    db: Session,
    as_of: datetime | None = None,
    allowed_market_symbols: set[str] | None = None,
) -> dict[str, Any]:
    if as_of is not None:
        return _build_strict_snapshot(db, as_of, allowed_market_symbols=allowed_market_symbols)

    latest_open_time_ms = db.scalar(select(func.max(MarketCandle.open_time_ms)).select_from(MarketCandle))
    if latest_open_time_ms is None:
        return {
            "market_candidates": [],
            "provider": "historical_db",
            "as_of_ms": None,
            "error": "No historical market data is available. Import CSV data first.",
        }
    resolved_as_of = datetime.fromtimestamp(latest_open_time_ms / 1000, tz=timezone.utc)
    return _build_strict_snapshot(db, resolved_as_of, allowed_market_symbols=allowed_market_symbols)


def get_strategy_state(db: Session, *, skill_id: str, scope_kind: str, scope_id: str) -> dict[str, Any]:
    engine = PortfolioEngine(db, skill_id=skill_id, scope_kind=scope_kind, scope_id=scope_id)
    state = engine.get_strategy_state()
    db.commit()
    return state


def save_strategy_state(
    db: Session,
    *,
    skill_id: str,
    scope_kind: str,
    scope_id: str,
    patch: dict[str, Any],
) -> dict[str, Any]:
    engine = PortfolioEngine(db, skill_id=skill_id, scope_kind=scope_kind, scope_id=scope_id)
    state = engine.save_strategy_state(patch)
    db.commit()
    return state


def get_candles_tool(db: Session, market_symbol: str, timeframe: str, limit: int, end_time: datetime | None = None) -> list[dict[str, Any]]:
    return fetch_candles(db, market_symbol=market_symbol, timeframe=timeframe, limit=limit, end_time=end_time)


def execute_tool_gateway_request(
    db: Session,
    *,
    tool_name: str,
    skill_id: str,
    scope_kind: str,
    scope_id: str,
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
        return handle_get_strategy_state(
            db,
            skill_id=skill_id,
            scope_kind=scope_kind,
            scope_id=scope_id,
        )

    if tool_name == "get_portfolio_state":
        return handle_get_portfolio_state(
            db,
            skill_id=skill_id,
            scope_kind=scope_kind,
            scope_id=scope_id,
            as_of=effective_as_of,
        )

    if tool_name == "save_strategy_state":
        return handle_save_strategy_state(
            db,
            skill_id=skill_id,
            scope_kind=scope_kind,
            scope_id=scope_id,
            patch=arguments.get("patch") or {},
        )

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
            limit=max(1, min(int(arguments.get("limit", 80) or 80), 240)),
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


def build_market_snapshot_for_tool_request(db: Session, as_of: datetime, step_index: int) -> dict[str, Any]:
    del step_index
    return _build_strict_snapshot(db, as_of)


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


def _build_strict_snapshot(
    db: Session,
    as_of: datetime,
    *,
    allowed_market_symbols: set[str] | None = None,
) -> dict[str, Any]:
    normalized_as_of = ensure_utc(as_of)
    snapshot = build_market_snapshot(db, normalized_as_of, allowed_market_symbols=allowed_market_symbols)
    snapshot["provider"] = "historical_db"
    if snapshot["market_candidates"]:
        return snapshot
    snapshot["error"] = f"No historical market snapshot is available as of {normalized_as_of.isoformat()}."
    return snapshot
