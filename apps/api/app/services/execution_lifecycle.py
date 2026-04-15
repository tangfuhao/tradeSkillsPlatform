from __future__ import annotations

from datetime import datetime

from app.services.utils import datetime_to_ms

BACKTEST_STATUS_QUEUED = "queued"
BACKTEST_STATUS_RUNNING = "running"
BACKTEST_STATUS_PAUSED = "paused"
BACKTEST_STATUS_STOPPING = "stopping"
BACKTEST_STATUS_STOPPED = "stopped"
BACKTEST_STATUS_COMPLETED = "completed"
BACKTEST_STATUS_FAILED = "failed"

LIVE_STATUS_ACTIVE = "active"
LIVE_STATUS_PAUSED = "paused"
LIVE_STATUS_STOPPED = "stopped"
LIVE_STATUS_FAILED = "failed"

BACKTEST_NON_TERMINAL_STATUSES = {
    BACKTEST_STATUS_QUEUED,
    BACKTEST_STATUS_RUNNING,
    BACKTEST_STATUS_PAUSED,
    BACKTEST_STATUS_STOPPING,
}
BACKTEST_BUSY_STATUSES = {
    BACKTEST_STATUS_QUEUED,
    BACKTEST_STATUS_RUNNING,
    BACKTEST_STATUS_STOPPING,
}
LIVE_RUNTIME_OWNING_STATUSES = {
    LIVE_STATUS_ACTIVE,
    LIVE_STATUS_PAUSED,
}


def backtest_available_actions(status: str) -> list[str]:
    if status in {BACKTEST_STATUS_QUEUED, BACKTEST_STATUS_RUNNING}:
        return ["pause", "stop"]
    if status == BACKTEST_STATUS_PAUSED:
        return ["resume", "stop", "delete"]
    if status == BACKTEST_STATUS_FAILED:
        return ["resume", "delete"]
    if status in {BACKTEST_STATUS_STOPPED, BACKTEST_STATUS_COMPLETED}:
        return ["delete"]
    return []


def live_runtime_available_actions(status: str) -> list[str]:
    if status == LIVE_STATUS_ACTIVE:
        return ["trigger", "pause", "stop", "delete"]
    if status == LIVE_STATUS_PAUSED:
        return ["resume", "stop", "delete"]
    if status in {LIVE_STATUS_STOPPED, LIVE_STATUS_FAILED}:
        return ["delete"]
    return []


def strategy_available_actions(*, validation_status: str, has_active_live_runtime: bool) -> list[str]:
    actions = ["delete"]
    if validation_status == "passed":
        actions.append("create_backtest")
        if not has_active_live_runtime:
            actions.append("create_live_task")
    return actions


def build_progress_payload(
    *,
    total_steps: int | None,
    completed_steps: int | None,
    last_processed_trace_index: int | None,
    last_processed_trigger_time_ms: int | None,
) -> dict[str, int | float | None]:
    total = int(total_steps or 0)
    completed = int(completed_steps or 0)
    percent = round((completed / total), 4) if total > 0 else 0.0
    return {
        "total_steps": total,
        "completed_steps": completed,
        "percent": percent,
        "last_processed_trace_index": last_processed_trace_index,
        "last_processed_trigger_time_ms": last_processed_trigger_time_ms,
    }


def last_activity_at_ms(*times: datetime | None, extra_ms: int | None = None) -> int | None:
    candidates = [datetime_to_ms(value) for value in times if value is not None]
    if extra_ms is not None:
        candidates.append(int(extra_ms))
    return max(candidates) if candidates else None
