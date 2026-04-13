from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import BacktestRun, RunTrace, Skill
from app.services.agent_runner_client import execute_agent_run
from app.services.demo_runtime import build_trigger_times, compute_demo_trade_return, compute_max_drawdown
from app.services.market_data_store import fetch_candles
from app.services.preview_policy import determine_scope
from app.services.serializers import backtest_to_dict, trace_to_dict
from app.services.utils import ensure_utc, new_id, utc_now
from app.tool_gateway.demo_gateway import build_market_snapshot_for_backtest, get_strategy_state, save_strategy_state


class BacktestService:
    def __init__(self, db: Session):
        self.db = db

    def create_run(self, skill_id: str, start_time, end_time, initial_capital: float) -> dict:
        skill = self.db.get(Skill, skill_id)
        if skill is None:
            raise LookupError("Skill not found.")
        start_at = ensure_utc(start_time)
        end_at = ensure_utc(end_time)
        scope = determine_scope(skill.review_status, start_at, end_at)
        run = BacktestRun(
            id=new_id("bt"),
            skill_id=skill.id,
            status="queued",
            scope=scope,
            start_time=start_at,
            end_time=end_at,
            initial_capital=initial_capital,
            benchmark_name=settings.default_benchmark,
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return backtest_to_dict(run)

    def list_runs(self) -> list[dict[str, Any]]:
        runs = self.db.scalars(select(BacktestRun).order_by(BacktestRun.created_at.desc())).all()
        return [backtest_to_dict(run) for run in runs]

    def get_run(self, run_id: str) -> dict:
        run = self.db.get(BacktestRun, run_id)
        if run is None:
            raise LookupError("Backtest run not found.")
        return backtest_to_dict(run)

    def get_traces(self, run_id: str) -> list[dict[str, Any]]:
        run = self.db.get(BacktestRun, run_id)
        if run is None:
            raise LookupError("Backtest run not found.")
        traces = self.db.scalars(
            select(RunTrace).where(RunTrace.run_id == run_id).order_by(RunTrace.trace_index.asc())
        ).all()
        return [trace_to_dict(trace) for trace in traces]


def execute_backtest_job(run_id: str) -> None:
    with SessionLocal() as db:
        run = db.get(BacktestRun, run_id)
        if run is None:
            return
        skill = db.get(Skill, run.skill_id)
        if skill is None:
            run.status = "failed"
            run.error_message = "Skill missing for backtest run."
            db.commit()
            return
        try:
            run.status = "running"
            run.error_message = None
            db.execute(delete(RunTrace).where(RunTrace.run_id == run.id))
            db.commit()

            envelope = skill.envelope_json or {}
            cadence = envelope.get("trigger", {}).get("value", "15m")
            trigger_times, truncated = build_trigger_times(run.start_time, run.end_time, cadence)
            equity = run.initial_capital
            equity_curve = [equity]
            trade_count = 0
            winning_trades = 0
            fees_paid = 0.0
            market_data_provider = "synthetic_fallback"

            for trace_index, trigger_time in enumerate(trigger_times):
                market_snapshot = build_market_snapshot_for_backtest(db, trigger_time, trace_index)
                market_data_provider = market_snapshot.get("provider", market_data_provider)
                strategy_state = get_strategy_state(db, skill.id)
                payload = {
                    "skill_id": skill.id,
                    "skill_title": skill.title,
                    "mode": "backtest",
                    "trigger_time": trigger_time.isoformat(),
                    "skill_text": skill.raw_text,
                    "envelope": envelope,
                    "context": {
                        **market_snapshot,
                        "strategy_state": strategy_state,
                        "as_of": trigger_time.isoformat(),
                    },
                }
                agent_response = execute_agent_run(payload)
                decision = dict(agent_response["decision"])
                state_patch = decision.get("state_patch") or {}
                if state_patch:
                    save_strategy_state(db, skill.id, state_patch)
                simulated_return_pct = 0.0
                execution_reference = "synthetic_cycle"
                if decision.get("action") == "open_position":
                    simulated_return_pct, execution_reference = _compute_trade_return_from_history(
                        db=db,
                        market_symbol=decision.get("symbol"),
                        direction=decision.get("direction"),
                        trigger_time=trigger_time,
                        exit_time=trigger_times[trace_index + 1] if trace_index + 1 < len(trigger_times) else trigger_time,
                        fallback_step_index=trace_index,
                    )
                    equity = round(equity * (1 + simulated_return_pct), 2)
                    trade_count += 1
                    fees_paid += 3.25
                    if simulated_return_pct > 0:
                        winning_trades += 1
                equity_curve.append(equity)
                decision["simulated_return_pct"] = simulated_return_pct
                decision["execution_reference"] = execution_reference
                trace = RunTrace(
                    id=new_id("trace"),
                    run_id=run.id,
                    mode="backtest",
                    trace_index=trace_index,
                    trigger_time=trigger_time,
                    decision_json=decision,
                    reasoning_summary=agent_response["reasoning_summary"],
                    tool_calls_json=agent_response["tool_calls"],
                )
                db.add(trace)
                db.commit()

            total_return_pct = round((equity - run.initial_capital) / run.initial_capital, 4)
            benchmark_return_pct = round(min(0.18, 0.01 + len(trigger_times) * 0.0025), 4)
            max_drawdown_pct = compute_max_drawdown(equity_curve)
            win_rate = round((winning_trades / trade_count), 4) if trade_count else 0.0
            run.summary_json = {
                "net_pnl": round(equity - run.initial_capital, 2),
                "total_return_pct": total_return_pct,
                "benchmark_return_pct": benchmark_return_pct,
                "excess_return_pct": round(total_return_pct - benchmark_return_pct, 4),
                "max_drawdown_pct": max_drawdown_pct,
                "trade_count": trade_count,
                "win_rate": win_rate,
                "fees_paid": round(fees_paid, 2),
                "final_equity": round(equity, 2),
                "assumptions": [
                    f"market snapshot provider: {market_data_provider}",
                    f"system benchmark default: {settings.default_benchmark}",
                    "1m historical bars are the source of truth when available; aggregated views are derived at query time",
                ],
                "replay_steps": len(trigger_times),
                "truncated_replay": truncated,
            }
            run.status = "completed"
            run.updated_at = utc_now()
            db.add(run)
            db.commit()
        except Exception as exc:
            run.status = "failed"
            run.error_message = str(exc)
            run.updated_at = utc_now()
            db.add(run)
            db.commit()


def _compute_trade_return_from_history(
    db: Session,
    market_symbol: str | None,
    direction: str | None,
    trigger_time,
    exit_time,
    fallback_step_index: int,
) -> tuple[float, str]:
    if market_symbol:
        entry_rows = fetch_candles(db, market_symbol=market_symbol, timeframe="1m", limit=1, end_time=trigger_time)
        exit_rows = fetch_candles(db, market_symbol=market_symbol, timeframe="1m", limit=1, end_time=exit_time)
        if entry_rows and exit_rows:
            entry_close = float(entry_rows[-1]["close"])
            exit_close = float(exit_rows[-1]["close"])
            if entry_close > 0:
                raw_return = (exit_close - entry_close) / entry_close
                if direction == "sell":
                    raw_return = -raw_return
                return round(raw_return, 4), "historical_bar_close"
    return compute_demo_trade_return(fallback_step_index, direction), "synthetic_cycle"
