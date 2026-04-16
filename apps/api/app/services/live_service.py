from __future__ import annotations

from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import LiveSignal, LiveTask, Skill
from app.runtime.live_execution_locks import release_live_task_execution, try_acquire_live_task_execution
from app.services.agent_run_recovery import AgentRunAborted, AgentRunRecoveryError, execute_agent_run_with_recovery
from app.services.demo_runtime import cadence_to_seconds
from app.services.execution_cleanup import delete_live_task
from app.services.execution_lifecycle import LIVE_RUNTIME_OWNING_STATUSES, LIVE_STATUS_ACTIVE, LIVE_STATUS_PAUSED, LIVE_STATUS_STOPPED
from app.services.portfolio_engine import DEFAULT_LIVE_INITIAL_CAPITAL, LIVE_SCOPE_KIND, PortfolioEngine
from app.services.serializers import live_signal_to_dict, live_task_to_dict
from app.services.utils import datetime_to_ms, ms_to_datetime, new_id, utc_now
from app.tool_gateway.demo_gateway import build_market_snapshot_for_live


HEALTHY_SYNC_STATUSES = {"succeeded", "no_advance"}


class LiveTaskOwnershipError(ValueError):
    def __init__(self, *, skill_id: str, existing_task_id: str, existing_status: str) -> None:
        super().__init__(f"Skill already owns a live runtime: {existing_task_id}")
        self.skill_id = skill_id
        self.existing_task_id = existing_task_id
        self.existing_status = existing_status


class LiveTaskTriggerRejectedError(ValueError):
    pass


class LiveTaskConflictError(LiveTaskTriggerRejectedError):
    pass


class LiveTaskService:
    def __init__(self, db: Session):
        self.db = db

    def create_task(self, skill_id: str) -> dict[str, Any]:
        skill = self.db.get(Skill, skill_id)
        if skill is None:
            raise LookupError("Skill not found.")
        if skill.validation_status != "passed":
            raise ValueError("Only validated strategies can start live runtimes.")
        existing_task = self.db.scalar(
            select(LiveTask).where(
                LiveTask.skill_id == skill.id,
                LiveTask.status.in_(LIVE_RUNTIME_OWNING_STATUSES),
            )
        )
        if existing_task is not None:
            raise LiveTaskOwnershipError(
                skill_id=skill.id,
                existing_task_id=existing_task.id,
                existing_status=existing_task.status,
            )
        cadence = (skill.envelope_json or {}).get("trigger", {}).get("value", "15m")
        task = LiveTask(
            id=new_id("live"),
            skill_id=skill.id,
            cadence=cadence,
            cadence_seconds=cadence_to_seconds(cadence),
            status=LIVE_STATUS_ACTIVE,
        )
        self.db.add(task)
        engine = PortfolioEngine(
            self.db,
            skill_id=skill.id,
            scope_kind=LIVE_SCOPE_KIND,
            scope_id=task.id,
            initial_capital=DEFAULT_LIVE_INITIAL_CAPITAL,
        )
        engine.ensure_book(initial_capital=DEFAULT_LIVE_INITIAL_CAPITAL)
        engine.ensure_strategy_state()
        self.db.commit()
        self.db.refresh(task)
        return live_task_to_dict(task)

    def list_tasks(self) -> list[dict[str, Any]]:
        tasks = self.db.scalars(select(LiveTask).order_by(LiveTask.created_at.desc())).all()
        return [live_task_to_dict(task) for task in tasks]

    def list_signals(self, live_task_id: str | None = None) -> list[dict[str, Any]]:
        query = select(LiveSignal).order_by(LiveSignal.created_at.desc())
        if live_task_id:
            query = query.where(LiveSignal.live_task_id == live_task_id)
        signals = self.db.scalars(query).all()
        return [live_signal_to_dict(signal) for signal in signals]

    def get_portfolio(self, task_id: str) -> dict[str, Any]:
        task = self.db.get(LiveTask, task_id)
        if task is None:
            raise LookupError("Live task not found.")
        engine = PortfolioEngine(
            self.db,
            skill_id=task.skill_id,
            scope_kind=LIVE_SCOPE_KIND,
            scope_id=task.id,
            initial_capital=DEFAULT_LIVE_INITIAL_CAPITAL,
        )
        return engine.get_portfolio_state()

    def control_task(self, task_id: str, action: str) -> dict[str, Any]:
        task = self.db.get(LiveTask, task_id)
        if task is None:
            raise LookupError("Live task not found.")

        normalized = action.strip().lower()
        if normalized == "pause":
            if task.status != LIVE_STATUS_ACTIVE:
                raise ValueError(f"Cannot pause a live runtime in status '{task.status}'.")
            task.status = LIVE_STATUS_PAUSED
        elif normalized == "resume":
            if task.status != LIVE_STATUS_PAUSED:
                raise ValueError(f"Cannot resume a live runtime in status '{task.status}'.")
            task.status = LIVE_STATUS_ACTIVE
        elif normalized == "stop":
            if task.status not in {LIVE_STATUS_ACTIVE, LIVE_STATUS_PAUSED}:
                raise ValueError(f"Cannot stop a live runtime in status '{task.status}'.")
            task.status = LIVE_STATUS_STOPPED
        else:
            raise ValueError(f"Unsupported live runtime action '{action}'.")

        task.updated_at = utc_now()
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return live_task_to_dict(task)

    def delete_task(self, task_id: str) -> None:
        task = self.db.get(LiveTask, task_id)
        if task is None:
            raise LookupError("Live task not found.")
        delete_live_task(self.db, task)
        self.db.commit()



def execute_live_task(
    task_id: str,
    *,
    slot_as_of_ms: int | None = None,
    trigger_origin: str = "manual",
    conflict_policy: Literal["skip", "raise"] = "skip",
    raise_on_reject: bool = False,
) -> dict[str, Any] | None:
    lock = try_acquire_live_task_execution(task_id)
    if lock is None:
        if conflict_policy == "raise":
            raise LiveTaskConflictError("Live task is already executing.")
        return None

    try:
        with SessionLocal() as db:
            task = db.get(LiveTask, task_id)
            if task is None:
                if raise_on_reject:
                    raise LookupError("Live task not found.")
                return None
            if task.status != LIVE_STATUS_ACTIVE:
                if raise_on_reject:
                    raise LiveTaskTriggerRejectedError("Live task is not active.")
                return None
            skill = db.get(Skill, task.skill_id)
            if skill is None:
                if raise_on_reject:
                    raise LookupError("Skill not found.")
                return None

            effective_slot_as_of_ms = slot_as_of_ms
            if effective_slot_as_of_ms is None:
                market_snapshot = build_market_snapshot_for_live(db)
                effective_slot_as_of_ms = _resolve_slot_as_of_ms(task, market_snapshot)
            if effective_slot_as_of_ms is None:
                if raise_on_reject:
                    raise LiveTaskTriggerRejectedError("No executable live slot is pending.")
                return None
            if (
                task.last_completed_slot_as_of_ms is not None
                and effective_slot_as_of_ms <= task.last_completed_slot_as_of_ms
            ):
                if raise_on_reject:
                    raise LiveTaskTriggerRejectedError("No executable live slot is pending.")
                return None

            trigger_time = utc_now()
            task.last_triggered_at = trigger_time
            engine = PortfolioEngine(
                db,
                skill_id=skill.id,
                scope_kind=LIVE_SCOPE_KIND,
                scope_id=task.id,
                initial_capital=DEFAULT_LIVE_INITIAL_CAPITAL,
            )
            slot_as_of = ms_to_datetime(effective_slot_as_of_ms)

            try:
                market_snapshot = build_market_snapshot_for_live(db, as_of=slot_as_of)
                snapshot_error = market_snapshot.get("error") if isinstance(market_snapshot, dict) else None
                if not market_snapshot.get("market_candidates"):
                    raise RuntimeError(
                        str(snapshot_error or "No historical market snapshot is available for live execution.")
                    )
                portfolio_before, _ = engine.mark_to_market(slot_as_of)
                db.commit()

                payload = {
                    "skill_id": skill.id,
                    "skill_title": skill.title,
                    "mode": "live_signal",
                    "trigger_time_ms": datetime_to_ms(trigger_time),
                    "skill_text": skill.raw_text,
                    "envelope": skill.envelope_json or {},
                    "context": {
                        **market_snapshot,
                        "as_of_ms": effective_slot_as_of_ms,
                        "portfolio_summary": _portfolio_hint(portfolio_before),
                        "tool_gateway": _build_tool_gateway_context(
                            skill_id=skill.id,
                            scope_kind=LIVE_SCOPE_KIND,
                            scope_id=task.id,
                            mode="live_signal",
                            trigger_time_ms=datetime_to_ms(trigger_time),
                            as_of_ms=effective_slot_as_of_ms,
                            trace_index=None,
                        ),
                    },
                }
                agent_response, recovery = execute_agent_run_with_recovery(
                    payload,
                    mode="live_signal",
                    should_abort=lambda: _live_retry_should_abort(db, task_id),
                )
                decision = dict(agent_response["decision"])
                state_patch = decision.get("state_patch") or {}
                portfolio_after, fills, _ = engine.apply_decision(
                    decision,
                    trigger_time=slot_as_of,
                    trace_index=None,
                )
                if state_patch:
                    engine.save_strategy_state(state_patch)
                signal = LiveSignal(
                    id=new_id("sig"),
                    live_task_id=task.id,
                    trigger_time=trigger_time,
                    delivery_status="stored",
                    signal_json={
                        "decision": {
                            **decision,
                            "execution_reference": fills[-1]["execution_reference"] if fills else "no_execution",
                            "fill_count": len(fills),
                        },
                        "reasoning_summary": agent_response["reasoning_summary"],
                        "provider": agent_response["provider"],
                        "execution_time_ms": effective_slot_as_of_ms,
                        "trigger_origin": trigger_origin,
                        "execution_timing": agent_response.get("execution_timing"),
                        "execution_breakdown": agent_response.get("execution_breakdown"),
                        "llm_rounds": agent_response.get("llm_rounds"),
                        "portfolio_before": portfolio_before,
                        "portfolio_after": portfolio_after,
                        "fills": fills,
                        "recovery": recovery,
                    },
                )
                task.last_completed_slot_as_of_ms = effective_slot_as_of_ms
                db.add(signal)
                db.add(task)
                db.commit()
            except AgentRunAborted:
                db.rollback()
                return None if _live_retry_should_abort(db, task_id) else None
            except AgentRunRecoveryError as exc:
                db.rollback()
                task = db.get(LiveTask, task_id)
                if task is None:
                    return None
                signal = _build_failed_live_signal(
                    task=task,
                    trigger_time=trigger_time,
                    slot_as_of_ms=effective_slot_as_of_ms,
                    trigger_origin=trigger_origin,
                    error_message=str(exc),
                    recovery=exc.recovery_payload(),
                )
                db.add(signal)
                db.add(task)
                db.commit()
            except Exception as exc:
                db.rollback()
                task = db.get(LiveTask, task_id)
                if task is None:
                    return None
                signal = _build_failed_live_signal(
                    task=task,
                    trigger_time=trigger_time,
                    slot_as_of_ms=effective_slot_as_of_ms,
                    trigger_origin=trigger_origin,
                    error_message=str(exc),
                    recovery={
                        "attempt_count": 1,
                        "recovered": False,
                        "retry_count": 0,
                        "retryable": False,
                        "final_error": {
                            "message": str(exc),
                            "error_type": "live_runtime_error",
                            "source": "live_runtime",
                            "retryable": False,
                            "last_http_status": None,
                            "upstream_status": None,
                            "retry_after_seconds": None,
                            "code": None,
                        },
                    },
                )
                db.add(signal)
                db.add(task)
                db.commit()

            db.refresh(signal)
            return live_signal_to_dict(signal)
    finally:
        release_live_task_execution(lock)



def dispatch_sync_driven_live_tasks(coverage_end_ms: int) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        tasks = db.scalars(
            select(LiveTask)
            .where(LiveTask.status == LIVE_STATUS_ACTIVE)
            .order_by(LiveTask.created_at.asc())
        ).all()
        candidates = [
            (task.id, pending_slot)
            for task in tasks
            if (pending_slot := compute_pending_slot_as_of_ms(task, coverage_end_ms)) is not None
        ]

    results: list[dict[str, Any]] = []
    for task_id, pending_slot in candidates:
        signal = execute_live_task(
            task_id,
            slot_as_of_ms=pending_slot,
            trigger_origin="sync_loop",
            conflict_policy="skip",
            raise_on_reject=False,
        )
        results.append(
            {
                "task_id": task_id,
                "slot_as_of_ms": pending_slot,
                "executed": signal is not None,
                "signal_id": signal.get("id") if signal else None,
                "delivery_status": signal.get("delivery_status") if signal else None,
            }
        )
    return results



def trigger_live_task_manually(task_id: str) -> dict[str, Any]:
    with SessionLocal() as db:
        task = db.get(LiveTask, task_id)
        if task is None:
            raise LookupError("Live task not found.")
        if task.status != LIVE_STATUS_ACTIVE:
            raise LiveTaskTriggerRejectedError("Live task is not active.")

        sync_snapshot = get_live_sync_gate_snapshot()
        if not sync_snapshot.market_sync_loop_running:
            raise LiveTaskTriggerRejectedError("Live sync loop is not running.")
        if sync_snapshot.last_sync_status not in HEALTHY_SYNC_STATUSES:
            raise LiveTaskTriggerRejectedError("Live sync state is unhealthy.")
        if sync_snapshot.last_successful_sync_completed_at_ms is None:
            raise LiveTaskTriggerRejectedError("No successful live sync has completed yet.")
        if _sync_snapshot_is_stale(sync_snapshot.last_successful_sync_completed_at_ms):
            raise LiveTaskTriggerRejectedError("Live sync state is stale.")
        coverage_end_ms = sync_snapshot.last_successful_coverage_end_ms
        if coverage_end_ms is None:
            raise LiveTaskTriggerRejectedError("No synced market coverage is available yet.")

        pending_slot = compute_pending_slot_as_of_ms(task, coverage_end_ms)
        if pending_slot is None:
            raise LiveTaskTriggerRejectedError("No executable live slot is pending.")

    signal = execute_live_task(
        task_id,
        slot_as_of_ms=pending_slot,
        trigger_origin="manual",
        conflict_policy="raise",
        raise_on_reject=True,
    )
    if signal is None:
        raise LiveTaskTriggerRejectedError("Live task execution was aborted.")
    return signal



def compute_latest_slot_as_of_ms(cadence_seconds: int, coverage_end_ms: int | None) -> int | None:
    if coverage_end_ms is None or cadence_seconds <= 0:
        return None
    step_ms = cadence_seconds * 1000
    return (coverage_end_ms // step_ms) * step_ms



def compute_pending_slot_as_of_ms(task: LiveTask, coverage_end_ms: int | None) -> int | None:
    latest_slot_as_of_ms = compute_latest_slot_as_of_ms(task.cadence_seconds, coverage_end_ms)
    if latest_slot_as_of_ms is None:
        return None
    if task.last_completed_slot_as_of_ms is not None and latest_slot_as_of_ms <= task.last_completed_slot_as_of_ms:
        return None
    return latest_slot_as_of_ms



def get_live_sync_gate_snapshot() -> Any:
    from app.runtime.market_sync_loop import market_sync_loop_manager

    return market_sync_loop_manager.get_snapshot()



def _resolve_slot_as_of_ms(task: LiveTask, market_snapshot: dict[str, Any]) -> int | None:
    raw_value = market_snapshot.get("as_of_ms")
    if not isinstance(raw_value, int):
        return None
    return compute_latest_slot_as_of_ms(task.cadence_seconds, raw_value)



def _build_failed_live_signal(
    *,
    task: LiveTask,
    trigger_time,
    slot_as_of_ms: int,
    trigger_origin: str,
    error_message: str,
    recovery: dict[str, Any],
) -> LiveSignal:
    return LiveSignal(
        id=new_id("sig"),
        live_task_id=task.id,
        trigger_time=trigger_time,
        delivery_status="failed",
        signal_json={
            "error_message": error_message,
            "provider": settings.agent_runner_base_url,
            "mode": "live_signal",
            "execution_time_ms": slot_as_of_ms,
            "trigger_origin": trigger_origin,
            "execution_scope": {"scope_kind": LIVE_SCOPE_KIND, "scope_id": task.id},
            "recovery": recovery,
        },
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



def _live_retry_should_abort(db: Session, task_id: str) -> bool:
    db.expire_all()
    task = db.get(LiveTask, task_id)
    return task is None or task.status != LIVE_STATUS_ACTIVE



def _sync_snapshot_is_stale(last_successful_sync_completed_at_ms: int) -> bool:
    freshness_ms = int(settings.live_data_freshness_seconds * 1000)
    now_ms = datetime_to_ms(utc_now())
    return now_ms - last_successful_sync_completed_at_ms > freshness_ms
