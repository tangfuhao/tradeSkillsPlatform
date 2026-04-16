from __future__ import annotations

from app.models import BacktestRun, LiveSignal, LiveTask, RunTrace, Skill
from app.services.execution_lifecycle import (
    backtest_available_actions,
    build_progress_payload,
    last_activity_at_ms,
    live_runtime_available_actions,
    strategy_available_actions,
)
from app.services.utils import datetime_to_ms


TRACE_RUNTIME_METRICS_KEY = "_runtime_metrics"
LEGACY_TRACE_EXECUTION_TIMING_KEY = "_execution_timing"


def skill_to_dict(skill: Skill, *, has_active_live_runtime: bool = False, active_live_task_id: str | None = None) -> dict:
    envelope = _public_skill_envelope(skill.envelope_json)
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
        "immutable": True,
        "available_actions": strategy_available_actions(
            validation_status=skill.validation_status,
            has_active_live_runtime=has_active_live_runtime,
        ),
        "raw_text": skill.raw_text,
        "active_live_task_id": active_live_task_id,
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
        "progress": build_progress_payload(
            total_steps=run.total_trigger_count,
            completed_steps=run.completed_trigger_count,
            last_processed_trace_index=run.last_processed_trace_index,
            last_processed_trigger_time_ms=run.last_processed_trigger_time_ms,
        ),
        "pending_action": run.control_requested,
        "available_actions": [] if run.control_requested else backtest_available_actions(run.status),
        "last_activity_at_ms": last_activity_at_ms(
            run.created_at,
            run.updated_at,
            extra_ms=run.last_processed_trigger_time_ms,
        ),
        "summary": run.summary_json,
        "last_runtime_error": run.last_runtime_error_json,
        "error_message": run.error_message,
        "created_at_ms": datetime_to_ms(run.created_at),
        "updated_at_ms": datetime_to_ms(run.updated_at),
    }


def trace_to_dict(trace: RunTrace) -> dict:
    execution_detail = trace.execution_detail
    decision = dict(trace.decision_json or {})
    execution_timing, execution_breakdown, llm_rounds, recovery = _extract_trace_runtime_metrics(decision)
    return {
        "id": trace.id,
        "trace_index": trace.trace_index,
        "trigger_time_ms": datetime_to_ms(trace.trigger_time),
        "reasoning_summary": trace.reasoning_summary,
        "decision": decision,
        "execution_timing": execution_timing,
        "execution_breakdown": execution_breakdown,
        "llm_rounds": llm_rounds,
        "recovery": recovery,
        "tool_calls": trace.tool_calls_json or [],
        "portfolio_before": execution_detail.portfolio_before_json if execution_detail else None,
        "portfolio_after": execution_detail.portfolio_after_json if execution_detail else None,
        "fills": execution_detail.fills_json if execution_detail else [],
    }


def live_task_to_dict(task: LiveTask) -> dict:
    last_triggered_at_ms = datetime_to_ms(task.last_triggered_at) if task.last_triggered_at else None
    return {
        "id": task.id,
        "skill_id": task.skill_id,
        "status": task.status,
        "cadence": task.cadence,
        "cadence_seconds": task.cadence_seconds,
        "available_actions": live_runtime_available_actions(task.status),
        "last_activity_at_ms": last_activity_at_ms(task.created_at, task.updated_at, extra_ms=last_triggered_at_ms),
        "last_triggered_at_ms": last_triggered_at_ms,
        "last_completed_slot_as_of_ms": task.last_completed_slot_as_of_ms,
        "created_at_ms": datetime_to_ms(task.created_at),
        "updated_at_ms": datetime_to_ms(task.updated_at),
    }



def live_signal_to_dict(signal: LiveSignal) -> dict:
    raw_signal = signal.signal_json or {}
    decision = raw_signal.get("decision") if isinstance(raw_signal, dict) else None
    decision_payload = decision if isinstance(decision, dict) else {}
    normalized_signal = {
        **decision_payload,
        "action": decision_payload.get("action"),
        "symbol": decision_payload.get("symbol"),
        "direction": decision_payload.get("direction"),
        "size_pct": decision_payload.get("size_pct"),
        "reason": decision_payload.get("reason"),
        "reasoning_summary": raw_signal.get("reasoning_summary") if isinstance(raw_signal, dict) else None,
        "provider": raw_signal.get("provider") if isinstance(raw_signal, dict) else None,
        "error_message": raw_signal.get("error_message") if isinstance(raw_signal, dict) else None,
        "execution_time_ms": raw_signal.get("execution_time_ms") if isinstance(raw_signal, dict) else None,
        "trigger_origin": raw_signal.get("trigger_origin") if isinstance(raw_signal, dict) else None,
        "portfolio_before": raw_signal.get("portfolio_before") if isinstance(raw_signal, dict) else None,
        "portfolio_after": raw_signal.get("portfolio_after") if isinstance(raw_signal, dict) else None,
        "fills": raw_signal.get("fills") if isinstance(raw_signal, dict) else [],
        "coverage": raw_signal.get("coverage") if isinstance(raw_signal, dict) else None,
        "execution_timing": raw_signal.get("execution_timing") if isinstance(raw_signal, dict) else None,
        "execution_breakdown": raw_signal.get("execution_breakdown") if isinstance(raw_signal, dict) else None,
        "llm_rounds": raw_signal.get("llm_rounds") if isinstance(raw_signal, dict) else [],
        "recovery": raw_signal.get("recovery") if isinstance(raw_signal, dict) else None,
    }
    return {
        "id": signal.id,
        "live_task_id": signal.live_task_id,
        "trigger_time_ms": datetime_to_ms(signal.trigger_time),
        "delivery_status": signal.delivery_status,
        "signal": normalized_signal,
        "created_at_ms": datetime_to_ms(signal.created_at),
    }


def _public_skill_envelope(raw_envelope: dict | None) -> dict:
    envelope = dict(raw_envelope or {})
    envelope.pop("runtime_modes", None)
    return envelope


def _extract_trace_runtime_metrics(decision: dict) -> tuple[dict | None, dict | None, list[dict], dict | None]:
    runtime_metrics = decision.pop(TRACE_RUNTIME_METRICS_KEY, None)
    execution_timing = None
    execution_breakdown = None
    llm_rounds: list[dict] = []
    recovery = None

    if isinstance(runtime_metrics, dict):
        candidate_execution_timing = runtime_metrics.get("execution_timing")
        if isinstance(candidate_execution_timing, dict):
            execution_timing = candidate_execution_timing
        candidate_execution_breakdown = runtime_metrics.get("execution_breakdown")
        if isinstance(candidate_execution_breakdown, dict):
            execution_breakdown = candidate_execution_breakdown
        candidate_llm_rounds = runtime_metrics.get("llm_rounds")
        if isinstance(candidate_llm_rounds, list):
            llm_rounds = [item for item in candidate_llm_rounds if isinstance(item, dict)]
        candidate_recovery = runtime_metrics.get("recovery")
        if isinstance(candidate_recovery, dict):
            recovery = candidate_recovery

    legacy_execution_timing = decision.pop(LEGACY_TRACE_EXECUTION_TIMING_KEY, None)
    if execution_timing is None and isinstance(legacy_execution_timing, dict):
        execution_timing = legacy_execution_timing

    return execution_timing, execution_breakdown, llm_rounds, recovery
