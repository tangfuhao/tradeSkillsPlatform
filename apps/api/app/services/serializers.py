from __future__ import annotations

from app.models import BacktestRun, LiveSignal, LiveTask, RunTrace, Skill
from app.services.utils import datetime_to_ms


def skill_to_dict(skill: Skill) -> dict:
    envelope = skill.envelope_json or {}
    extraction_meta = envelope.get("extraction_meta") if isinstance(envelope, dict) else {}
    extraction_method = str((extraction_meta or {}).get("method") or "rule_only")
    fallback_used = bool((extraction_meta or {}).get("fallback_used") or extraction_method == "llm_fallback")
    return {
        "id": skill.id,
        "title": skill.title,
        "validation_status": skill.validation_status,
        "source_hash": skill.source_hash,
        "envelope": envelope,
        "extraction_method": extraction_method,
        "fallback_used": fallback_used,
        "validation_errors": skill.validation_errors_json or [],
        "validation_warnings": skill.validation_warnings_json or [],
        "created_at_ms": datetime_to_ms(skill.created_at),
        "updated_at_ms": datetime_to_ms(skill.updated_at),
    }


def backtest_to_dict(run: BacktestRun) -> dict:
    return {
        "id": run.id,
        "skill_id": run.skill_id,
        "status": run.status,
        "scope": run.scope,
        "benchmark_name": run.benchmark_name,
        "start_time_ms": datetime_to_ms(run.start_time),
        "end_time_ms": datetime_to_ms(run.end_time),
        "initial_capital": run.initial_capital,
        "summary": run.summary_json,
        "error_message": run.error_message,
        "created_at_ms": datetime_to_ms(run.created_at),
        "updated_at_ms": datetime_to_ms(run.updated_at),
    }


def trace_to_dict(trace: RunTrace) -> dict:
    execution_detail = trace.execution_detail
    return {
        "id": trace.id,
        "trace_index": trace.trace_index,
        "trigger_time_ms": datetime_to_ms(trace.trigger_time),
        "reasoning_summary": trace.reasoning_summary,
        "decision": trace.decision_json or {},
        "tool_calls": trace.tool_calls_json or [],
        "portfolio_before": execution_detail.portfolio_before_json if execution_detail else None,
        "portfolio_after": execution_detail.portfolio_after_json if execution_detail else None,
        "fills": execution_detail.fills_json if execution_detail else [],
    }


def live_task_to_dict(task: LiveTask) -> dict:
    return {
        "id": task.id,
        "skill_id": task.skill_id,
        "status": task.status,
        "cadence": task.cadence,
        "cadence_seconds": task.cadence_seconds,
        "last_triggered_at_ms": datetime_to_ms(task.last_triggered_at) if task.last_triggered_at else None,
        "created_at_ms": datetime_to_ms(task.created_at),
        "updated_at_ms": datetime_to_ms(task.updated_at),
    }


def live_signal_to_dict(signal: LiveSignal) -> dict:
    return {
        "id": signal.id,
        "live_task_id": signal.live_task_id,
        "trigger_time_ms": datetime_to_ms(signal.trigger_time),
        "delivery_status": signal.delivery_status,
        "signal": signal.signal_json or {},
        "created_at_ms": datetime_to_ms(signal.created_at),
    }
