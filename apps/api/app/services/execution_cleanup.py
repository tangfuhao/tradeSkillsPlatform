from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    BacktestRun,
    ExecutionStrategyState,
    LiveSignal,
    LiveTask,
    PortfolioBook,
    PortfolioFill,
    PortfolioPosition,
    RunTrace,
    Skill,
    StrategyState,
    TraceExecutionDetail,
)
from app.runtime.scheduler import scheduler_manager
from app.services.execution_lifecycle import BACKTEST_BUSY_STATUSES


def delete_execution_scope_state(db: Session, *, scope_kind: str, scope_id: str) -> None:
    book_ids = db.scalars(
        select(PortfolioBook.id).where(
            PortfolioBook.scope_kind == scope_kind,
            PortfolioBook.scope_id == scope_id,
        )
    ).all()
    if book_ids:
        db.execute(delete(PortfolioFill).where(PortfolioFill.book_id.in_(book_ids)))
        db.execute(delete(PortfolioPosition).where(PortfolioPosition.book_id.in_(book_ids)))
    db.execute(
        delete(PortfolioBook).where(
            PortfolioBook.scope_kind == scope_kind,
            PortfolioBook.scope_id == scope_id,
        )
    )
    db.execute(
        delete(ExecutionStrategyState).where(
            ExecutionStrategyState.scope_kind == scope_kind,
            ExecutionStrategyState.scope_id == scope_id,
        )
    )


def delete_backtest_run(db: Session, run: BacktestRun) -> None:
    trace_ids = db.scalars(select(RunTrace.id).where(RunTrace.run_id == run.id)).all()
    if trace_ids:
        db.execute(delete(TraceExecutionDetail).where(TraceExecutionDetail.trace_id.in_(trace_ids)))
    db.execute(delete(RunTrace).where(RunTrace.run_id == run.id))
    delete_execution_scope_state(db, scope_kind="backtest_run", scope_id=run.id)
    db.delete(run)


def delete_live_task(db: Session, task: LiveTask) -> None:
    scheduler_manager.unschedule_live_task(task.id)
    db.execute(delete(LiveSignal).where(LiveSignal.live_task_id == task.id))
    delete_execution_scope_state(db, scope_kind="live_task", scope_id=task.id)
    db.delete(task)


def delete_strategy_cascade(db: Session, skill: Skill) -> None:
    blocking_runs = db.scalars(
        select(BacktestRun).where(
            BacktestRun.skill_id == skill.id,
            BacktestRun.status.in_(BACKTEST_BUSY_STATUSES),
        )
    ).all()
    if blocking_runs:
        raise ValueError("Stop or finish in-progress backtests before deleting this strategy.")

    runs = db.scalars(select(BacktestRun).where(BacktestRun.skill_id == skill.id)).all()
    for run in runs:
        delete_backtest_run(db, run)

    tasks = db.scalars(select(LiveTask).where(LiveTask.skill_id == skill.id)).all()
    for task in tasks:
        delete_live_task(db, task)

    book_ids = db.scalars(select(PortfolioBook.id).where(PortfolioBook.skill_id == skill.id)).all()
    if book_ids:
        db.execute(delete(PortfolioFill).where(PortfolioFill.book_id.in_(book_ids)))
        db.execute(delete(PortfolioPosition).where(PortfolioPosition.book_id.in_(book_ids)))
    db.execute(delete(PortfolioBook).where(PortfolioBook.skill_id == skill.id))
    db.execute(delete(ExecutionStrategyState).where(ExecutionStrategyState.skill_id == skill.id))
    db.execute(delete(StrategyState).where(StrategyState.skill_id == skill.id))
    db.delete(skill)
