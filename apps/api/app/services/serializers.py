from __future__ import annotations

from app.models import BacktestRun, LiveSignal, LiveTask, RunTrace, Skill
from app.services.preview_policy import get_preview_window


def skill_to_dict(skill: Skill) -> dict:
    preview_start, preview_end = get_preview_window()
    return {
        "id": skill.id,
        "title": skill.title,
        "validation_status": skill.validation_status,
        "review_status": skill.review_status,
        "source_hash": skill.source_hash,
        "envelope": skill.envelope_json or {},
        "validation_errors": skill.validation_errors_json or [],
        "validation_warnings": skill.validation_warnings_json or [],
        "preview_window": {
            "start": preview_start,
            "end": preview_end,
        },
        "created_at": skill.created_at,
        "updated_at": skill.updated_at,
    }


def backtest_to_dict(run: BacktestRun) -> dict:
    return {
        "id": run.id,
        "skill_id": run.skill_id,
        "status": run.status,
        "scope": run.scope,
        "benchmark_name": run.benchmark_name,
        "start_time": run.start_time,
        "end_time": run.end_time,
        "initial_capital": run.initial_capital,
        "summary": run.summary_json,
        "error_message": run.error_message,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


def trace_to_dict(trace: RunTrace) -> dict:
    return {
        "id": trace.id,
        "trace_index": trace.trace_index,
        "trigger_time": trace.trigger_time,
        "reasoning_summary": trace.reasoning_summary,
        "decision": trace.decision_json or {},
        "tool_calls": trace.tool_calls_json or [],
    }


def live_task_to_dict(task: LiveTask) -> dict:
    return {
        "id": task.id,
        "skill_id": task.skill_id,
        "status": task.status,
        "cadence": task.cadence,
        "cadence_seconds": task.cadence_seconds,
        "last_triggered_at": task.last_triggered_at,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def live_signal_to_dict(signal: LiveSignal) -> dict:
    return {
        "id": signal.id,
        "live_task_id": signal.live_task_id,
        "trigger_time": signal.trigger_time,
        "delivery_status": signal.delivery_status,
        "signal": signal.signal_json or {},
        "created_at": signal.created_at,
    }
