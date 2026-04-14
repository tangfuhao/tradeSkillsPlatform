from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import ExecutionStrategyState, MarketCandle, PortfolioBook, PortfolioFill, PortfolioPosition
from app.services.market_data_store import fetch_candles
from app.services.utils import datetime_to_ms, ensure_utc, new_id


BACKTEST_SCOPE_KIND = "backtest_run"
LIVE_SCOPE_KIND = "live_task"
DEFAULT_LIVE_INITIAL_CAPITAL = 10_000.0

POSITION_EPSILON = 1e-10
DEFAULT_RECENT_FILL_LIMIT = 5


class PortfolioEngine:
    def __init__(
        self,
        db: Session,
        *,
        skill_id: str,
        scope_kind: str,
        scope_id: str,
        initial_capital: float | None = None,
    ) -> None:
        self.db = db
        self.skill_id = skill_id
        self.scope_kind = scope_kind
        self.scope_id = scope_id
        self.initial_capital = initial_capital

    def ensure_strategy_state(self) -> ExecutionStrategyState:
        state = self.db.scalar(
            select(ExecutionStrategyState).where(
                ExecutionStrategyState.scope_kind == self.scope_kind,
                ExecutionStrategyState.scope_id == self.scope_id,
            )
        )
        if state is None:
            state = ExecutionStrategyState(
                id=new_id("estate"),
                skill_id=self.skill_id,
                scope_kind=self.scope_kind,
                scope_id=self.scope_id,
                state_json={},
            )
            self.db.add(state)
            self.db.flush()
        return state

    def get_strategy_state(self) -> dict[str, Any]:
        return dict(self.ensure_strategy_state().state_json or {})

    def save_strategy_state(self, patch: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(patch, dict):
            raise ValueError("patch must be an object")
        state = self.ensure_strategy_state()
        next_state = dict(state.state_json or {})
        next_state.update(patch)
        state.state_json = next_state
        self.db.add(state)
        self.db.flush()
        return next_state

    def ensure_book(self, initial_capital: float | None = None) -> PortfolioBook:
        book = self.db.scalar(
            select(PortfolioBook).where(
                PortfolioBook.scope_kind == self.scope_kind,
                PortfolioBook.scope_id == self.scope_id,
            )
        )
        if book is None:
            book = PortfolioBook(
                id=new_id("book"),
                skill_id=self.skill_id,
                scope_kind=self.scope_kind,
                scope_id=self.scope_id,
                initial_capital=float(initial_capital or self.initial_capital or DEFAULT_LIVE_INITIAL_CAPITAL),
                cash_balance=float(initial_capital or self.initial_capital or DEFAULT_LIVE_INITIAL_CAPITAL),
                equity=float(initial_capital or self.initial_capital or DEFAULT_LIVE_INITIAL_CAPITAL),
                realized_pnl=0.0,
                unrealized_pnl=0.0,
                last_mark_time_ms=None,
            )
            self.db.add(book)
            self.db.flush()
        return book

    def reset_scope(self, initial_capital: float | None = None, *, clear_strategy_state: bool = True) -> PortfolioBook:
        book = self.ensure_book(initial_capital=initial_capital)
        self.db.execute(delete(PortfolioFill).where(PortfolioFill.book_id == book.id))
        self.db.execute(delete(PortfolioPosition).where(PortfolioPosition.book_id == book.id))
        capital = float(initial_capital or book.initial_capital or self.initial_capital or DEFAULT_LIVE_INITIAL_CAPITAL)
        book.initial_capital = capital
        book.cash_balance = capital
        book.equity = capital
        book.realized_pnl = 0.0
        book.unrealized_pnl = 0.0
        book.last_mark_time_ms = None
        self.db.add(book)
        if clear_strategy_state:
            state = self.ensure_strategy_state()
            state.state_json = {}
            self.db.add(state)
        self.db.flush()
        return book

    def get_portfolio_state(self, *, as_of: datetime | None = None, recent_fill_limit: int = DEFAULT_RECENT_FILL_LIMIT) -> dict[str, Any]:
        if as_of is not None:
            snapshot, _ = self.mark_to_market(as_of, recent_fill_limit=recent_fill_limit)
            return snapshot
        return self._snapshot(self.ensure_book(), recent_fill_limit=recent_fill_limit)

    def mark_to_market(
        self,
        as_of: datetime,
        *,
        recent_fill_limit: int = DEFAULT_RECENT_FILL_LIMIT,
    ) -> tuple[dict[str, Any], dict[str, float]]:
        book = self.ensure_book()
        as_of_utc = ensure_utc(as_of)
        as_of_ms = datetime_to_ms(as_of_utc)
        positions = self._positions(book.id)
        mark_prices: dict[str, float] = {}
        total_position_value = 0.0
        total_unrealized = 0.0

        for position in positions:
            mark_price = self._require_market_price(position.market_symbol, as_of_utc)
            position.mark_price = mark_price
            position.position_notional = position.quantity * mark_price
            position.unrealized_pnl = _realized_pnl(
                direction=position.direction,
                entry_price=position.avg_entry_price,
                exit_price=mark_price,
                quantity=position.quantity,
            )
            denominator = position.avg_entry_price * position.quantity
            position.unrealized_pnl_pct = round(position.unrealized_pnl / denominator, 6) if denominator > 0 else 0.0
            position.updated_at_ms = as_of_ms
            mark_prices[position.market_symbol] = mark_price
            total_unrealized += position.unrealized_pnl
            total_position_value += _position_market_value(
                direction=position.direction,
                quantity=position.quantity,
                mark_price=mark_price,
            )
            self.db.add(position)

        book.unrealized_pnl = total_unrealized
        book.equity = book.cash_balance + total_position_value
        book.last_mark_time_ms = as_of_ms
        self.db.add(book)
        self.db.flush()
        return self._snapshot(book, recent_fill_limit=recent_fill_limit), mark_prices

    def apply_decision(
        self,
        decision: dict[str, Any],
        *,
        trigger_time: datetime,
        trace_index: int | None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, float]]:
        book = self.ensure_book()
        trigger_time_utc = ensure_utc(trigger_time)
        trigger_time_ms = datetime_to_ms(trigger_time_utc)
        action = str(decision.get("action") or "skip").strip()

        if action in {"skip", "watch", "hold"}:
            snapshot, mark_prices = self.mark_to_market(trigger_time_utc)
            return snapshot, [], mark_prices

        raw_symbol = decision.get("symbol")
        market_symbol = self._resolve_market_symbol(raw_symbol)
        if not market_symbol:
            raise RuntimeError(f"{action} requires a market symbol.")

        fills: list[PortfolioFill] = []
        position = self._position(book.id, market_symbol)
        execution_price = self._require_market_price(market_symbol, trigger_time_utc)
        stop_loss = _normalize_metadata(decision.get("stop_loss"))
        take_profit = _normalize_metadata(decision.get("take_profit"))

        if action == "open_position":
            direction = str(decision.get("direction") or "").strip().lower()
            if direction not in {"buy", "sell"}:
                raise RuntimeError("open_position requires direction=buy or direction=sell.")
            size_pct = float(decision.get("size_pct", 0.0) or 0.0)
            if size_pct <= 0:
                raise RuntimeError("open_position requires size_pct > 0.")
            if book.equity <= 0:
                raise RuntimeError("Current equity must be positive before opening a position.")
            order_notional = book.equity * size_pct
            order_quantity = order_notional / execution_price
            if order_quantity <= POSITION_EPSILON:
                raise RuntimeError("open_position order quantity is too small to execute.")

            if position is not None and position.direction != direction:
                fills.append(
                    self._close_position(
                        book=book,
                        position=position,
                        quantity=position.quantity,
                        execution_price=execution_price,
                        trigger_time_ms=trigger_time_ms,
                        trace_index=trace_index,
                        action="close_position",
                    )
                )
                position = None

            fills.append(
                self._open_position(
                    book=book,
                    market_symbol=market_symbol,
                    direction=direction,
                    quantity=order_quantity,
                    execution_price=execution_price,
                    trigger_time_ms=trigger_time_ms,
                    trace_index=trace_index,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                )
            )
        elif action == "close_position":
            if position is None or position.quantity <= POSITION_EPSILON:
                raise RuntimeError(f"close_position requested for {market_symbol}, but no open position exists.")
            fills.append(
                self._close_position(
                    book=book,
                    position=position,
                    quantity=position.quantity,
                    execution_price=execution_price,
                    trigger_time_ms=trigger_time_ms,
                    trace_index=trace_index,
                    action="close_position",
                )
            )
        elif action == "reduce_position":
            if position is None or position.quantity <= POSITION_EPSILON:
                raise RuntimeError(f"reduce_position requested for {market_symbol}, but no open position exists.")
            reduce_ratio = float(decision.get("size_pct", 0.0) or 0.0)
            if reduce_ratio <= 0 or reduce_ratio > 1:
                raise RuntimeError("reduce_position requires size_pct within (0, 1].")
            reduce_quantity = position.quantity * reduce_ratio
            fills.append(
                self._close_position(
                    book=book,
                    position=position,
                    quantity=reduce_quantity,
                    execution_price=execution_price,
                    trigger_time_ms=trigger_time_ms,
                    trace_index=trace_index,
                    action="reduce_position",
                )
            )
        else:
            raise RuntimeError(f"Unsupported decision action: {action}")

        snapshot, mark_prices = self.mark_to_market(trigger_time_utc)
        return snapshot, [self.serialize_fill(fill) for fill in fills], mark_prices

    def closed_trade_stats(self) -> dict[str, float | int]:
        book = self.ensure_book()
        fills = self.db.scalars(
            select(PortfolioFill)
            .where(PortfolioFill.book_id == book.id, PortfolioFill.closed_trade_pnl.is_not(None))
            .order_by(PortfolioFill.created_at.asc())
        ).all()
        count = len(fills)
        wins = sum(1 for fill in fills if bool(fill.closed_trade_win))
        return {
            "closed_trade_count": count,
            "win_rate": round((wins / count), 4) if count else 0.0,
        }

    def serialize_fill(self, fill: PortfolioFill) -> dict[str, Any]:
        return {
            "id": fill.id,
            "symbol": fill.market_symbol,
            "action": fill.action,
            "side": fill.side,
            "quantity": round(fill.quantity, 8),
            "price": round(fill.price, 8),
            "notional": round(fill.notional, 8),
            "realized_pnl": round(fill.realized_pnl, 8),
            "closed_trade_pnl": round(fill.closed_trade_pnl, 8) if fill.closed_trade_pnl is not None else None,
            "closed_trade_win": fill.closed_trade_win,
            "trigger_time_ms": fill.trigger_time_ms,
            "trace_index": fill.trace_index,
            "execution_reference": fill.execution_reference,
        }

    def _snapshot(self, book: PortfolioBook, *, recent_fill_limit: int) -> dict[str, Any]:
        positions = self._positions(book.id)
        recent_fills = self.db.scalars(
            select(PortfolioFill)
            .where(PortfolioFill.book_id == book.id)
            .order_by(PortfolioFill.trigger_time_ms.desc(), PortfolioFill.created_at.desc())
            .limit(recent_fill_limit)
        ).all()
        return {
            "scope_kind": self.scope_kind,
            "scope_id": self.scope_id,
            "skill_id": self.skill_id,
            "account": {
                "initial_capital": round(book.initial_capital, 8),
                "cash_balance": round(book.cash_balance, 8),
                "equity": round(book.equity, 8),
                "realized_pnl": round(book.realized_pnl, 8),
                "unrealized_pnl": round(book.unrealized_pnl, 8),
                "total_return_pct": round(
                    (book.equity - book.initial_capital) / book.initial_capital,
                    6,
                )
                if book.initial_capital > 0
                else 0.0,
                "last_mark_time_ms": book.last_mark_time_ms,
            },
            "positions": [
                {
                    "symbol": position.market_symbol,
                    "direction": position.direction,
                    "quantity": round(position.quantity, 8),
                    "avg_entry_price": round(position.avg_entry_price, 8),
                    "mark_price": round(position.mark_price, 8),
                    "position_notional": round(position.position_notional, 8),
                    "unrealized_pnl": round(position.unrealized_pnl, 8),
                    "unrealized_pnl_pct": round(position.unrealized_pnl_pct, 6),
                    "stop_loss": position.stop_loss_json,
                    "take_profit": position.take_profit_json,
                    "opened_at_ms": position.opened_at_ms,
                    "updated_at_ms": position.updated_at_ms,
                }
                for position in positions
            ],
            "recent_fills": [self.serialize_fill(fill) for fill in recent_fills],
        }

    def _positions(self, book_id: str) -> list[PortfolioPosition]:
        return self.db.scalars(
            select(PortfolioPosition)
            .where(PortfolioPosition.book_id == book_id)
            .order_by(PortfolioPosition.market_symbol.asc())
        ).all()

    def _position(self, book_id: str, market_symbol: str) -> PortfolioPosition | None:
        return self.db.scalar(
            select(PortfolioPosition).where(
                PortfolioPosition.book_id == book_id,
                PortfolioPosition.market_symbol == market_symbol,
            )
        )

    def _open_position(
        self,
        *,
        book: PortfolioBook,
        market_symbol: str,
        direction: str,
        quantity: float,
        execution_price: float,
        trigger_time_ms: int,
        trace_index: int | None,
        stop_loss: dict[str, Any] | None,
        take_profit: dict[str, Any] | None,
    ) -> PortfolioFill:
        notional = quantity * execution_price
        if direction == "buy":
            book.cash_balance -= notional
        else:
            book.cash_balance += notional

        position = self._position(book.id, market_symbol)
        if position is None:
            position = PortfolioPosition(
                id=new_id("pos"),
                book_id=book.id,
                market_symbol=market_symbol,
                direction=direction,
                quantity=quantity,
                avg_entry_price=execution_price,
                mark_price=execution_price,
                position_notional=notional,
                unrealized_pnl=0.0,
                unrealized_pnl_pct=0.0,
                cycle_realized_pnl=0.0,
                stop_loss_json=stop_loss,
                take_profit_json=take_profit,
                opened_at_ms=trigger_time_ms,
                updated_at_ms=trigger_time_ms,
            )
        else:
            total_quantity = position.quantity + quantity
            if position.direction != direction:
                raise RuntimeError(f"Cannot add to {market_symbol}: existing direction conflicts with open_position.")
            position.avg_entry_price = (
                (position.avg_entry_price * position.quantity) + (execution_price * quantity)
            ) / total_quantity
            position.quantity = total_quantity
            position.mark_price = execution_price
            position.position_notional = total_quantity * execution_price
            position.updated_at_ms = trigger_time_ms
            if stop_loss is not None:
                position.stop_loss_json = stop_loss
            if take_profit is not None:
                position.take_profit_json = take_profit

        fill = PortfolioFill(
            id=new_id("fill"),
            book_id=book.id,
            market_symbol=market_symbol,
            action="open_position",
            side=direction,
            quantity=quantity,
            price=execution_price,
            notional=notional,
            realized_pnl=0.0,
            closed_trade_pnl=None,
            closed_trade_win=None,
            trigger_time_ms=trigger_time_ms,
            trace_index=trace_index,
            execution_reference="portfolio_book_fill",
        )
        self.db.add(book)
        self.db.add(position)
        self.db.add(fill)
        self.db.flush()
        return fill

    def _close_position(
        self,
        *,
        book: PortfolioBook,
        position: PortfolioPosition,
        quantity: float,
        execution_price: float,
        trigger_time_ms: int,
        trace_index: int | None,
        action: str,
    ) -> PortfolioFill:
        if quantity <= POSITION_EPSILON:
            raise RuntimeError(f"{action} quantity is too small to execute for {position.market_symbol}.")
        if quantity - position.quantity > POSITION_EPSILON:
            raise RuntimeError(
                f"{action} requested {quantity} {position.market_symbol}, exceeding current position size {position.quantity}."
            )

        side = "sell" if position.direction == "buy" else "buy"
        notional = quantity * execution_price
        if side == "sell":
            book.cash_balance += notional
        else:
            book.cash_balance -= notional

        realized_pnl = _realized_pnl(
            direction=position.direction,
            entry_price=position.avg_entry_price,
            exit_price=execution_price,
            quantity=quantity,
        )
        book.realized_pnl += realized_pnl
        position.cycle_realized_pnl += realized_pnl

        remaining_quantity = position.quantity - quantity
        closed_trade_pnl: float | None = None
        closed_trade_win: bool | None = None

        if remaining_quantity <= POSITION_EPSILON:
            closed_trade_pnl = position.cycle_realized_pnl
            closed_trade_win = closed_trade_pnl > 0
            self.db.delete(position)
        else:
            position.quantity = remaining_quantity
            position.updated_at_ms = trigger_time_ms
            self.db.add(position)

        fill = PortfolioFill(
            id=new_id("fill"),
            book_id=book.id,
            market_symbol=position.market_symbol,
            action=action,
            side=side,
            quantity=quantity,
            price=execution_price,
            notional=notional,
            realized_pnl=realized_pnl,
            closed_trade_pnl=closed_trade_pnl,
            closed_trade_win=closed_trade_win,
            trigger_time_ms=trigger_time_ms,
            trace_index=trace_index,
            execution_reference="portfolio_book_fill",
        )
        self.db.add(book)
        self.db.add(fill)
        self.db.flush()
        return fill

    def _require_market_price(self, market_symbol: str, as_of: datetime) -> float:
        candles = fetch_candles(
            self.db,
            market_symbol=market_symbol,
            timeframe="1m",
            limit=1,
            end_time=ensure_utc(as_of),
        )
        if not candles:
            raise RuntimeError(f"No historical 1m close is available for {market_symbol} at {ensure_utc(as_of).isoformat()}.")
        price = float(candles[-1]["close"])
        if price <= 0:
            raise RuntimeError(f"Historical 1m close must be positive for {market_symbol}.")
        return price

    def _resolve_market_symbol(self, raw_symbol: Any) -> str:
        symbol = str(raw_symbol or "").strip().upper()
        if not symbol:
            return ""
        exact_match = self.db.scalar(
            select(MarketCandle.market_symbol).where(MarketCandle.market_symbol == symbol).limit(1)
        )
        if exact_match:
            return exact_match

        base_symbol = symbol.split("#OLD#")[0]
        if not base_symbol.endswith("-USDT-SWAP"):
            base_symbol = f"{base_symbol}-USDT-SWAP"

        direct_match = self.db.scalar(
            select(MarketCandle.market_symbol).where(MarketCandle.market_symbol == base_symbol).limit(1)
        )
        if direct_match:
            return direct_match

        related_match = self.db.scalar(
            select(MarketCandle.market_symbol)
            .where(MarketCandle.base_symbol == base_symbol)
            .order_by(MarketCandle.is_old_contract.asc(), MarketCandle.open_time_ms.desc())
            .limit(1)
        )
        return related_match or base_symbol


def _realized_pnl(*, direction: str, entry_price: float, exit_price: float, quantity: float) -> float:
    if direction == "buy":
        return (exit_price - entry_price) * quantity
    return (entry_price - exit_price) * quantity


def _position_market_value(*, direction: str, quantity: float, mark_price: float) -> float:
    signed_quantity = quantity if direction == "buy" else -quantity
    return signed_quantity * mark_price


def _normalize_metadata(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return dict(value)
    return None
