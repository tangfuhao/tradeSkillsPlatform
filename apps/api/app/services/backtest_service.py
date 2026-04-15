from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import BacktestRun, RunTrace, Skill
from app.services.agent_runner_client import execute_agent_run
from app.services.demo_runtime import build_trigger_times, compute_max_drawdown
from app.services.execution_cleanup import delete_backtest_run
from app.services.execution_lifecycle import (
    BACKTEST_STATUS_COMPLETED,
    BACKTEST_STATUS_FAILED,
    BACKTEST_STATUS_PAUSED,
    BACKTEST_STATUS_QUEUED,
    BACKTEST_STATUS_RUNNING,
    BACKTEST_STATUS_STOPPED,
    BACKTEST_STATUS_STOPPING,
)
from app.services.market_data_store import get_market_data_coverage
from app.services.portfolio_engine import BACKTEST_SCOPE_KIND, PortfolioEngine
from app.services.serializers import backtest_to_dict, trace_to_dict
from app.services.utils import datetime_to_ms, ensure_utc, new_id, utc_now
from app.tool_gateway.demo_gateway import build_market_snapshot_for_backtest


class BacktestService:
    def __init__(self, db: Session):
        self.db = db

    def create_run(self, skill_id: str, start_time, end_time, initial_capital: float) -> dict:
        skill = self.db.get(Skill, skill_id)
        if skill is None:
            raise LookupError("Skill not found.")
        if skill.validation_status != "passed":
            raise ValueError("Only validated strategies can start backtests.")
        start_at = ensure_utc(start_time)
        end_at = ensure_utc(end_time)
        cadence = (skill.envelope_json or {}).get("trigger", {}).get("value", "15m")
        trigger_times, _ = _validate_backtest_window(self.db, start_at, end_at, cadence)
        run = BacktestRun(
            id=new_id("bt"),
            skill_id=skill.id,
            status=BACKTEST_STATUS_QUEUED,
            scope="historical",
            start_time=start_at,
            end_time=end_at,
            initial_capital=initial_capital,
            benchmark_name=settings.default_benchmark,
            total_trigger_count=len(trigger_times),
            completed_trigger_count=0,
            control_requested=None,
            last_processed_trace_index=None,
            last_processed_trigger_time_ms=None,
        )
        self.db.add(run)
        engine = PortfolioEngine(
            self.db,
            skill_id=skill.id,
            scope_kind=BACKTEST_SCOPE_KIND,
            scope_id=run.id,
            initial_capital=initial_capital,
        )
        engine.ensure_book(initial_capital=initial_capital)
        engine.ensure_strategy_state()
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

    def get_portfolio(self, run_id: str) -> dict[str, Any]:
        run = self.db.get(BacktestRun, run_id)
        if run is None:
            raise LookupError("Backtest run not found.")
        engine = PortfolioEngine(
            self.db,
            skill_id=run.skill_id,
            scope_kind=BACKTEST_SCOPE_KIND,
            scope_id=run.id,
            initial_capital=run.initial_capital,
        )
        return engine.get_portfolio_state()

    def control_run(self, run_id: str, action: str) -> tuple[dict[str, Any], bool]:
        run = self.db.get(BacktestRun, run_id)
        if run is None:
            raise LookupError("Backtest run not found.")

        normalized = action.strip().lower()
        should_enqueue = False

        if normalized == "pause":
            if run.status == BACKTEST_STATUS_QUEUED:
                run.status = BACKTEST_STATUS_PAUSED
                run.control_requested = None
            elif run.status == BACKTEST_STATUS_RUNNING:
                run.control_requested = "pause"
            else:
                raise ValueError(f"Cannot pause a backtest in status '{run.status}'.")
        elif normalized == "resume":
            if run.status not in {BACKTEST_STATUS_PAUSED, BACKTEST_STATUS_FAILED}:
                raise ValueError(f"Cannot resume a backtest in status '{run.status}'.")
            if run.status == BACKTEST_STATUS_PAUSED and run.completed_trigger_count >= run.total_trigger_count > 0:
                raise ValueError("Backtest has already completed.")
            skill = self.db.get(Skill, run.skill_id)
            if skill is None:
                raise LookupError("Skill missing for backtest run.")
            run.status = BACKTEST_STATUS_RUNNING
            run.control_requested = None
            run.error_message = None
            should_enqueue = True
        elif normalized == "stop":
            if run.status == BACKTEST_STATUS_QUEUED:
                run.status = BACKTEST_STATUS_STOPPED
                run.control_requested = None
            elif run.status == BACKTEST_STATUS_RUNNING:
                run.status = BACKTEST_STATUS_STOPPING
                run.control_requested = None
            elif run.status == BACKTEST_STATUS_PAUSED:
                run.status = BACKTEST_STATUS_STOPPED
                run.control_requested = None
            else:
                raise ValueError(f"Cannot stop a backtest in status '{run.status}'.")
        else:
            raise ValueError(f"Unsupported backtest action '{action}'.")

        run.updated_at = utc_now()
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return backtest_to_dict(run), should_enqueue

    def delete_run(self, run_id: str) -> None:
        run = self.db.get(BacktestRun, run_id)
        if run is None:
            raise LookupError("Backtest run not found.")
        if run.status in {BACKTEST_STATUS_QUEUED, BACKTEST_STATUS_RUNNING, BACKTEST_STATUS_STOPPING}:
            raise ValueError("Stop or pause the backtest before deleting it.")
        delete_backtest_run(self.db, run)
        self.db.commit()



def execute_backtest_job(run_id: str) -> None:
    with SessionLocal() as db:
        run = db.get(BacktestRun, run_id)
        if run is None or run.status not in {BACKTEST_STATUS_QUEUED, BACKTEST_STATUS_RUNNING}:
            return
        skill = db.get(Skill, run.skill_id)
        if skill is None:
            _mark_run_failed(db, run_id, "Skill missing for backtest run.")
            return

        engine = PortfolioEngine(
            db,
            skill_id=skill.id,
            scope_kind=BACKTEST_SCOPE_KIND,
            scope_id=run.id,
            initial_capital=run.initial_capital,
        )

        try:
            envelope = skill.envelope_json or {}
            cadence = envelope.get("trigger", {}).get("value", "15m")
            trigger_times, truncated = build_trigger_times(run.start_time, run.end_time, cadence)
            run.total_trigger_count = len(trigger_times)
            run.status = BACKTEST_STATUS_RUNNING
            run.error_message = None
            db.add(run)

            if run.completed_trigger_count == 0:
                _reset_run_execution_state(db, run, engine)
            db.commit()

            equity_curve = _load_existing_equity_curve(db, run_id, run.initial_capital)
            market_data_provider = "historical_db"

            for trace_index in range(int(run.completed_trigger_count or 0), len(trigger_times)):
                persisted_run = db.get(BacktestRun, run_id)
                if persisted_run is None:
                    return
                if persisted_run.status == BACKTEST_STATUS_STOPPING:
                    persisted_run.status = BACKTEST_STATUS_STOPPED
                    persisted_run.updated_at = utc_now()
                    db.add(persisted_run)
                    db.commit()
                    return
                if persisted_run.control_requested == "pause":
                    persisted_run.status = BACKTEST_STATUS_PAUSED
                    persisted_run.control_requested = None
                    persisted_run.updated_at = utc_now()
                    db.add(persisted_run)
                    db.commit()
                    return
                if persisted_run.status in {BACKTEST_STATUS_PAUSED, BACKTEST_STATUS_STOPPED, BACKTEST_STATUS_FAILED}:
                    return

                trigger_time = trigger_times[trace_index]
                try:
                    market_snapshot = build_market_snapshot_for_backtest(db, trigger_time, trace_index)
                    market_data_provider = market_snapshot.get("provider", market_data_provider)
                    if not market_snapshot.get("market_candidates"):
                        raise RuntimeError(
                            market_snapshot.get("error")
                            or f"No historical market snapshot is available as of {trigger_time.isoformat()}."
                        )

                    portfolio_before, before_mark_prices = engine.mark_to_market(trigger_time)
                    db.commit()

                    payload = {
                        "skill_id": skill.id,
                        "skill_title": skill.title,
                        "mode": "backtest",
                        "trigger_time_ms": datetime_to_ms(trigger_time),
                        "skill_text": skill.raw_text,
                        "envelope": envelope,
                        "context": {
                            **market_snapshot,
                            "as_of_ms": datetime_to_ms(trigger_time),
                            "portfolio_summary": _portfolio_hint(portfolio_before),
                            "tool_gateway": _build_tool_gateway_context(
                                skill_id=skill.id,
                                scope_kind=BACKTEST_SCOPE_KIND,
                                scope_id=run.id,
                                mode="backtest",
                                trigger_time_ms=datetime_to_ms(trigger_time),
                                as_of_ms=datetime_to_ms(trigger_time),
                                trace_index=trace_index,
                            ),
                        },
                    }
                    agent_response = execute_agent_run(payload)
                    decision = dict(agent_response["decision"])
                    state_patch = decision.get("state_patch") or {}
                    if state_patch:
                        engine.save_strategy_state(state_patch)

                    portfolio_after, fills, after_mark_prices = engine.apply_decision(
                        decision,
                        trigger_time=trigger_time,
                        trace_index=trace_index,
                    )
                    decision["execution_reference"] = fills[-1]["execution_reference"] if fills else "no_execution"
                    decision["fill_count"] = len(fills)
                    persisted_decision = dict(decision)
                    execution_timing = agent_response.get("execution_timing")
                    if isinstance(execution_timing, dict):
                        persisted_decision["_execution_timing"] = execution_timing

                    trace = RunTrace(
                        id=new_id("trace"),
                        run_id=run.id,
                        mode="backtest",
                        trace_index=trace_index,
                        trigger_time=trigger_time,
                        decision_json=persisted_decision,
                        reasoning_summary=agent_response["reasoning_summary"],
                        tool_calls_json=agent_response["tool_calls"],
                    )
                    db.add(trace)
                    db.flush()
                    from app.models import TraceExecutionDetail

                    db.add(
                        TraceExecutionDetail(
                            id=new_id("ted"),
                            trace_id=trace.id,
                            portfolio_before_json=portfolio_before,
                            portfolio_after_json=portfolio_after,
                            fills_json=fills,
                            mark_prices_json=after_mark_prices or before_mark_prices,
                        )
                    )

                    persisted_run = db.get(BacktestRun, run_id)
                    if persisted_run is None:
                        return
                    persisted_run.completed_trigger_count = trace_index + 1
                    persisted_run.last_processed_trace_index = trace_index
                    persisted_run.last_processed_trigger_time_ms = datetime_to_ms(trigger_time)
                    persisted_run.updated_at = utc_now()
                    db.add(persisted_run)
                    db.commit()
                    equity_curve.append(float((portfolio_after.get("account") or {}).get("equity", run.initial_capital)))
                except Exception as exc:
                    db.rollback()
                    raise RuntimeError(
                        f"Backtest step {trace_index + 1} at {trigger_time.isoformat()} failed: {exc}"
                    ) from exc

            final_portfolio, _ = engine.mark_to_market(run.end_time)
            stats = engine.closed_trade_stats()
            summary = _build_backtest_summary(
                final_portfolio=final_portfolio,
                market_data_provider=market_data_provider,
                benchmark_name=settings.default_benchmark,
                benchmark_return_pct=round(min(0.18, 0.01 + len(trigger_times) * 0.0025), 4),
                max_drawdown_pct=compute_max_drawdown(equity_curve + [final_portfolio["account"]["equity"]]),
                replay_steps=len(trigger_times),
                truncated=truncated,
                closed_trade_count=int(stats["closed_trade_count"]),
                win_rate=float(stats["win_rate"]),
            )
            persisted_run = db.get(BacktestRun, run_id)
            if persisted_run is None:
                return
            persisted_run.summary_json = summary
            persisted_run.status = BACKTEST_STATUS_COMPLETED
            persisted_run.control_requested = None
            persisted_run.completed_trigger_count = len(trigger_times)
            persisted_run.last_processed_trace_index = len(trigger_times) - 1 if trigger_times else None
            persisted_run.last_processed_trigger_time_ms = datetime_to_ms(trigger_times[-1]) if trigger_times else None
            persisted_run.updated_at = utc_now()
            db.add(persisted_run)
            db.commit()
        except Exception as exc:
            db.rollback()
            _mark_run_failed(db, run_id, str(exc))



def _mark_run_failed(db: Session, run_id: str, message: str) -> None:
    persisted_run = db.get(BacktestRun, run_id)
    if persisted_run is None:
        return
    persisted_run.status = BACKTEST_STATUS_FAILED
    persisted_run.control_requested = None
    persisted_run.error_message = message
    persisted_run.updated_at = utc_now()
    db.add(persisted_run)
    db.commit()



def _validate_backtest_window(db: Session, start_time: datetime, end_time: datetime, cadence: str) -> tuple[list[datetime], bool]:
    if end_time <= start_time:
        raise ValueError("end_time must be later than start_time")

    coverage_start, coverage_end = get_market_data_coverage(db)
    if coverage_start is None or coverage_end is None:
        raise ValueError("No local historical market data is available. Import CSV data before creating a backtest.")

    if start_time < coverage_start or end_time > coverage_end:
        raise ValueError(
            "Requested window "
            f"{start_time.isoformat()} -> {end_time.isoformat()} is outside local historical coverage "
            f"{coverage_start.isoformat()} -> {coverage_end.isoformat()}."
        )

    trigger_times, truncated = build_trigger_times(start_time, end_time, cadence)
    if len(trigger_times) < 2:
        raise ValueError(
            f"Requested window must span at least one full {cadence} interval inside the available historical coverage."
        )
    return trigger_times, truncated



def _build_tool_gateway_context(
    *,
    skill_id: str,
    scope_kind: str,
    scope_id: str,
    mode: str,
    trigger_time_ms: int,
    as_of_ms: int,
    trace_index: int | None,
) -> dict[str, Any]:
    return {
        "base_url": f"{settings.tool_gateway_base_url.rstrip('/')}{settings.api_prefix}/internal/tool-gateway",
        "execute_url": f"{settings.tool_gateway_base_url.rstrip('/')}{settings.api_prefix}/internal/tool-gateway/execute",
        "shared_secret": settings.tool_gateway_shared_secret,
        "skill_id": skill_id,
        "scope_kind": scope_kind,
        "scope_id": scope_id,
        "mode": mode,
        "trigger_time_ms": trigger_time_ms,
        "as_of_ms": as_of_ms,
        "trace_index": trace_index,
    }



def _reset_run_execution_state(db: Session, run: BacktestRun, engine: PortfolioEngine) -> None:
    from app.models import TraceExecutionDetail
    from app.services.execution_cleanup import delete_execution_scope_state

    trace_ids = db.scalars(select(RunTrace.id).where(RunTrace.run_id == run.id)).all()
    if trace_ids:
        db.query(TraceExecutionDetail).filter(TraceExecutionDetail.trace_id.in_(trace_ids)).delete(synchronize_session=False)
    db.query(RunTrace).filter(RunTrace.run_id == run.id).delete(synchronize_session=False)
    delete_execution_scope_state(db, scope_kind=BACKTEST_SCOPE_KIND, scope_id=run.id)
    engine.ensure_book(initial_capital=run.initial_capital)
    engine.ensure_strategy_state()
    engine.reset_scope(initial_capital=run.initial_capital, clear_strategy_state=True)
    run.completed_trigger_count = 0
    run.control_requested = None
    run.last_processed_trace_index = None
    run.last_processed_trigger_time_ms = None
    run.summary_json = None
    run.error_message = None
    db.add(run)



def _load_existing_equity_curve(db: Session, run_id: str, initial_capital: float) -> list[float]:
    traces = db.scalars(
        select(RunTrace).where(RunTrace.run_id == run_id).order_by(RunTrace.trace_index.asc())
    ).all()
    if not traces:
        return [initial_capital]

    curve = [initial_capital]
    for trace in traces:
        execution_detail = trace.execution_detail
        portfolio_after = execution_detail.portfolio_after_json if execution_detail else None
        equity = float(((portfolio_after or {}).get("account") or {}).get("equity", initial_capital))
        curve.append(equity)
    return curve



def _portfolio_hint(portfolio: dict[str, Any]) -> dict[str, Any]:
    account = portfolio.get("account") or {}
    positions = portfolio.get("positions") or []
    return {
        "equity": account.get("equity"),
        "realized_pnl": account.get("realized_pnl"),
        "unrealized_pnl": account.get("unrealized_pnl"),
        "open_position_count": len(positions),
        "symbols": [item.get("symbol") for item in positions[:5]],
    }



def _build_backtest_summary(
    *,
    final_portfolio: dict[str, Any],
    market_data_provider: str,
    benchmark_name: str,
    benchmark_return_pct: float,
    max_drawdown_pct: float,
    replay_steps: int,
    truncated: bool,
    closed_trade_count: int,
    win_rate: float,
) -> dict[str, Any]:
    account = final_portfolio.get("account") or {}
    positions = final_portfolio.get("positions") or []
    realized_pnl = round(float(account.get("realized_pnl", 0.0) or 0.0), 2)
    unrealized_pnl_end = round(float(account.get("unrealized_pnl", 0.0) or 0.0), 2)
    final_equity = round(float(account.get("equity", 0.0) or 0.0), 2)
    initial_capital = float(account.get("initial_capital", 0.0) or 0.0)
    net_pnl = round(realized_pnl + unrealized_pnl_end, 2)
    total_return_pct = round(float(account.get("total_return_pct", 0.0) or 0.0), 4)
    return {
        "realized_pnl": realized_pnl,
        "unrealized_pnl_end": unrealized_pnl_end,
        "net_pnl": net_pnl,
        "total_return_pct": total_return_pct,
        "benchmark_return_pct": benchmark_return_pct,
        "benchmark_name": benchmark_name,
        "excess_return_pct": round(total_return_pct - benchmark_return_pct, 4),
        "max_drawdown_pct": max_drawdown_pct,
        "closed_trade_count": closed_trade_count,
        "trade_count": closed_trade_count,
        "win_rate": win_rate,
        "open_positions_end": len(positions),
        "fees_paid": 0.0,
        "final_equity": final_equity,
        "initial_capital": round(initial_capital, 2),
        "assumptions": [
            f"market snapshot provider: {market_data_provider}",
            "Execution uses historical 1m close prices only; fees, slippage, and funding are not deducted.",
            "Open positions are marked to market at end_time and are not force-closed.",
        ],
        "replay_steps": replay_steps,
        "truncated_replay": truncated,
    }
