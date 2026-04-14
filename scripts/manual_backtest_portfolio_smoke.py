#!/usr/bin/env python3
from __future__ import annotations

from datetime import timedelta
import json
import sys

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import BacktestRun, MarketCandle, RunTrace, Skill
from app.services.backtest_service import BacktestService, execute_backtest_job
from app.services.market_data_store import fetch_candles, get_market_data_coverage
from app.services.utils import ensure_utc, new_id


SMOKE_SKILL_TEXT = """# Portfolio Engine Manual Smoke Skill

## Cadence
Run every 15m.

## Workflow
Use market data and official portfolio state to manage positions.
"""


def main() -> int:
    with SessionLocal() as db:
        coverage_start, coverage_end = get_market_data_coverage(db)
        if coverage_start is None or coverage_end is None:
            raise RuntimeError("No historical market coverage is available.")

        start_time = ensure_utc(coverage_start)
        end_time = min(ensure_utc(coverage_end), start_time + timedelta(minutes=30))

        market_symbol = db.scalar(
            select(MarketCandle.market_symbol)
            .where(MarketCandle.open_time_ms >= int(start_time.timestamp() * 1000))
            .order_by(MarketCandle.market_symbol.asc())
            .limit(1)
        )
        if not market_symbol:
            raise RuntimeError("No market symbol is available for the smoke run.")

        skill = Skill(
            id=new_id("skill"),
            title="Portfolio Engine Manual Smoke",
            raw_text=SMOKE_SKILL_TEXT,
            source_hash=new_id("hash"),
            validation_status="valid",
            review_status="compatible",
            envelope_json={
                "trigger": {"value": "15m"},
                "risk_contract": {"max_position_pct": 0.10},
            },
            validation_errors_json=[],
            validation_warnings_json=[],
        )
        db.add(skill)
        db.commit()

        service = BacktestService(db)
        run = service.create_run(
            skill_id=skill.id,
            start_time=start_time,
            end_time=end_time,
            initial_capital=10_000.0,
        )

    import app.services.backtest_service as backtest_module

    decisions = [
        {
            "action": "open_position",
            "symbol": market_symbol,
            "direction": "buy",
            "size_pct": 0.10,
            "reason": "Open the smoke long.",
            "stop_loss": {"type": "price_pct", "value": 0.02},
            "take_profit": {"type": "price_pct", "value": 0.04},
            "state_patch": {"phase": "opened"},
        },
        {
            "action": "hold",
            "symbol": market_symbol,
            "direction": None,
            "size_pct": 0.0,
            "reason": "Hold once.",
            "stop_loss": None,
            "take_profit": None,
            "state_patch": {"phase": "holding"},
        },
        {
            "action": "close_position",
            "symbol": market_symbol,
            "direction": None,
            "size_pct": 0.0,
            "reason": "Close the smoke long.",
            "stop_loss": None,
            "take_profit": None,
            "state_patch": {"phase": "closed"},
        },
    ]

    original_execute = backtest_module.execute_agent_run
    step = {"index": 0}

    def fake_execute_agent_run(payload: dict) -> dict:
        index = step["index"]
        if index >= len(decisions):
            raise RuntimeError(f"Unexpected extra agent invocation at step {index}.")
        decision = decisions[index]
        step["index"] += 1
        return {
            "decision": decision,
            "reasoning_summary": decision["reason"],
            "tool_calls": [
                {"tool_name": "get_portfolio_state", "arguments": {}, "status": "ok"},
                {"tool_name": "get_strategy_state", "arguments": {}, "status": "ok"},
            ],
            "provider": "manual-smoke",
        }

    backtest_module.execute_agent_run = fake_execute_agent_run
    try:
        execute_backtest_job(run["id"])
    finally:
        backtest_module.execute_agent_run = original_execute

    with SessionLocal() as db:
        persisted_run = db.get(BacktestRun, run["id"])
        if persisted_run is None:
            raise RuntimeError("Smoke backtest disappeared from the database.")
        if persisted_run.status != "completed":
            raise RuntimeError(
                f"Smoke backtest finished with status={persisted_run.status}: {persisted_run.error_message}"
            )

        traces = db.scalars(
            select(RunTrace).where(RunTrace.run_id == persisted_run.id).order_by(RunTrace.trace_index.asc())
        ).all()
        if len(traces) != 3:
            raise RuntimeError(f"Expected 3 traces, received {len(traces)}.")

        entry_candle = fetch_candles(db, market_symbol=market_symbol, timeframe="1m", limit=1, end_time=start_time)
        exit_candle = fetch_candles(db, market_symbol=market_symbol, timeframe="1m", limit=1, end_time=end_time)
        if not entry_candle or not exit_candle:
            raise RuntimeError("Missing entry/exit candles for smoke expectations.")

        entry_price = float(entry_candle[-1]["close"])
        exit_price = float(exit_candle[-1]["close"])
        quantity = (10_000.0 * 0.10) / entry_price
        expected_realized = round((exit_price - entry_price) * quantity, 2)
        expected_final_equity = round(10_000.0 + expected_realized, 2)

        summary = persisted_run.summary_json or {}
        if round(float(summary.get("realized_pnl", 0.0) or 0.0), 2) != expected_realized:
            raise RuntimeError(
                f"realized_pnl mismatch: expected {expected_realized}, got {summary.get('realized_pnl')}"
            )
        if round(float(summary.get("final_equity", 0.0) or 0.0), 2) != expected_final_equity:
            raise RuntimeError(
                f"final_equity mismatch: expected {expected_final_equity}, got {summary.get('final_equity')}"
            )
        if int(summary.get("closed_trade_count", 0) or 0) != 1:
            raise RuntimeError(f"Expected closed_trade_count=1, got {summary.get('closed_trade_count')}")
        if int(summary.get("open_positions_end", 0) or 0) != 0:
            raise RuntimeError(f"Expected open_positions_end=0, got {summary.get('open_positions_end')}")

        serialized = json.dumps(
            {
                "run": summary,
                "traces": [
                    {
                        "trace_index": trace.trace_index,
                        "decision": trace.decision_json,
                        "portfolio_before": trace.execution_detail.portfolio_before_json if trace.execution_detail else None,
                        "portfolio_after": trace.execution_detail.portfolio_after_json if trace.execution_detail else None,
                        "fills": trace.execution_detail.fills_json if trace.execution_detail else [],
                    }
                    for trace in traces
                ],
            },
            ensure_ascii=False,
        )
        for marker in ("synthetic_fallback", "synthetic_cycle"):
            if marker in serialized:
                raise RuntimeError(f"Unexpected deprecated marker in smoke output: {marker}")

        print(f"market_symbol: {market_symbol}")
        print(f"entry_price: {entry_price}")
        print(f"exit_price: {exit_price}")
        print(f"expected_realized: {expected_realized}")
        print(f"summary: {json.dumps(summary, ensure_ascii=False)}")
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"manual portfolio backtest smoke failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
