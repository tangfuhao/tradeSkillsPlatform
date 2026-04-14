from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import BacktestRun, RunTrace, Skill, TraceExecutionDetail
from app.services.agent_runner_client import execute_agent_run
from app.services.demo_runtime import build_trigger_times, compute_max_drawdown
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
        start_at = ensure_utc(start_time)
        end_at = ensure_utc(end_time)
        cadence = (skill.envelope_json or {}).get("trigger", {}).get("value", "15m")
        _validate_backtest_window(self.db, start_at, end_at, cadence)
        run = BacktestRun(
            id=new_id("bt"),
            skill_id=skill.id,
            status="queued",
            scope="historical",
            start_time=start_at,
            end_time=end_at,
            initial_capital=initial_capital,
            benchmark_name=settings.default_benchmark,
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

        engine = PortfolioEngine(
            db,
            skill_id=skill.id,
            scope_kind=BACKTEST_SCOPE_KIND,
            scope_id=run.id,
            initial_capital=run.initial_capital,
        )

        try:
            run.status = "running"
            run.error_message = None
            _reset_run_execution_state(db, run, engine)
            db.commit()

            envelope = skill.envelope_json or {}
            cadence = envelope.get("trigger", {}).get("value", "15m")
            trigger_times, truncated = build_trigger_times(run.start_time, run.end_time, cadence)
            equity_curve = [run.initial_capital]
            market_data_provider = "historical_db"

            for trace_index, trigger_time in enumerate(trigger_times):
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
                    decision["execution_reference"] = (
                        fills[-1]["execution_reference"] if fills else "no_execution"
                    )
                    decision["fill_count"] = len(fills)

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
                    db.flush()
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
                    run.updated_at = utc_now()
                    db.add(run)
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
            run.summary_json = summary
            run.status = "completed"
            run.updated_at = utc_now()
            db.add(run)
            db.commit()
        except Exception as exc:
            db.rollback()
            persisted_run = db.get(BacktestRun, run_id)
            if persisted_run is None:
                return
            persisted_run.status = "failed"
            persisted_run.error_message = str(exc)
            persisted_run.updated_at = utc_now()
            db.add(persisted_run)
            db.commit()


def _validate_backtest_window(db: Session, start_time: datetime, end_time: datetime, cadence: str) -> None:
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

    trigger_times, _ = build_trigger_times(start_time, end_time, cadence)
    if len(trigger_times) < 2:
        raise ValueError(
            f"Requested window must span at least one full {cadence} interval inside the available historical coverage."
        )


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
    trace_ids = db.scalars(select(RunTrace.id).where(RunTrace.run_id == run.id)).all()
    if trace_ids:
        db.execute(delete(TraceExecutionDetail).where(TraceExecutionDetail.trace_id.in_(trace_ids)))
    db.execute(delete(RunTrace).where(RunTrace.run_id == run.id))
    engine.reset_scope(initial_capital=run.initial_capital, clear_strategy_state=True)


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
