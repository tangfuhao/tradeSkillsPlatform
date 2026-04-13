from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import MarketCandle, StrategyState
from app.services.market_data_store import build_market_snapshot, fetch_candles, has_market_data
from app.services.utils import new_id, utc_now


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
