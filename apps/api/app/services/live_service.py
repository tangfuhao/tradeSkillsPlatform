from __future__ import annotations

import os
import socket
from datetime import timedelta
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import LiveSignal, LiveTask, Skill
from app.runtime.live_execution_locks import release_live_task_execution, try_acquire_live_task_execution
from app.services.agent_run_recovery import AgentRunAborted, AgentRunRecoveryError, execute_agent_run_with_recovery
from app.services.demo_runtime import cadence_to_seconds
from app.services.execution_cleanup import delete_live_task
from app.services.execution_lifecycle import LIVE_RUNTIME_OWNING_STATUSES, LIVE_STATUS_ACTIVE, LIVE_STATUS_PAUSED, LIVE_STATUS_STOPPED
from app.services.market_data_sync import get_fresh_market_symbols_for_dispatch, get_market_sync_gate_status
from app.services.portfolio_engine import DEFAULT_LIVE_INITIAL_CAPITAL, LIVE_SCOPE_KIND, PortfolioEngine
from app.services.serializers import live_signal_to_dict, live_task_to_dict
from app.services.utils import datetime_to_ms, ensure_utc, ms_to_datetime, new_id, utc_now
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

    def control_task(self, task_id: str, action: str, *, expected_revision: int | None = None) -> dict[str, Any]:
        task = self.db.scalar(select(LiveTask).where(LiveTask.id == task_id).with_for_update())
        if task is None:
            raise LookupError("Live task not found.")
        if expected_revision is not None and task.revision != expected_revision:
            raise ValueError(
                f"Live runtime revision conflict: expected {expected_revision}, current {task.revision}."
            )

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
        try:
            self.db.commit()
        except StaleDataError as exc:
            self.db.rollback()
            raise ValueError("Live runtime changed concurrently; refresh and retry.") from exc
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

            claim_outcome = _claim_live_task_slot(
                db,
                task_id=task_id,
                slot_as_of_ms=effective_slot_as_of_ms,
                conflict_policy=conflict_policy,
                raise_on_reject=raise_on_reject,
            )
            if claim_outcome.get("signal") is not None:
                return live_signal_to_dict(claim_outcome["signal"])
            claim_token = claim_outcome.get("claim_token")
            if claim_token is None:
                return None
            task = claim_outcome["task"]
            trigger_time = utc_now()
            engine = PortfolioEngine(
                db,
                skill_id=skill.id,
                scope_kind=LIVE_SCOPE_KIND,
                scope_id=task.id,
                initial_capital=DEFAULT_LIVE_INITIAL_CAPITAL,
            )
            slot_as_of = ms_to_datetime(effective_slot_as_of_ms)
            coverage_context = get_market_sync_gate_status(db)
            if coverage_context.get("dispatch_as_of_ms") is None:
                coverage_context = {
                    "status": "healthy",
                    "dispatch_as_of_ms": effective_slot_as_of_ms,
                    "coverage_ratio": 1.0,
                    "degraded": False,
                    "missing_symbol_count": 0,
                    "missing_symbols_sample": [],
                    "universe_version": None,
                }

            try:
                if (
                    coverage_context.get("status") in {"healthy", "degraded"}
                    and coverage_context.get("dispatch_as_of_ms") != effective_slot_as_of_ms
                ):
                    raise RuntimeError("Live dispatch coverage is no longer aligned with the pending slot.")
                fresh_symbols = get_fresh_market_symbols_for_dispatch(db, effective_slot_as_of_ms)
                if not fresh_symbols:
                    fresh_symbols = None
                watchlist = _extract_live_watchlist(skill)
                if watchlist and fresh_symbols is not None and not watchlist.issubset(fresh_symbols):
                    missing_watchlist = sorted(watchlist - fresh_symbols)
                    raise RuntimeError(
                        f"Live watchlist coverage is incomplete for {', '.join(missing_watchlist[:5])}."
                    )
                market_snapshot = build_market_snapshot_for_live(
                    db,
                    as_of=slot_as_of,
                    allowed_market_symbols=fresh_symbols,
                )
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
                        "dispatch_as_of_ms": coverage_context.get("dispatch_as_of_ms"),
                        "coverage_ratio": coverage_context.get("coverage_ratio"),
                        "degraded": coverage_context.get("degraded"),
                        "missing_symbol_count": coverage_context.get("missing_symbol_count"),
                        "missing_symbols_sample": coverage_context.get("missing_symbols_sample"),
                        "universe_version": coverage_context.get("universe_version"),
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
                    should_abort=lambda: _live_retry_should_abort(db, task_id, claim_token=claim_token),
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
                    execution_time_ms=effective_slot_as_of_ms,
                    dispatch_as_of_ms=coverage_context.get("dispatch_as_of_ms"),
                    trigger_origin=trigger_origin,
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
                        "coverage": {
                            "dispatch_as_of_ms": coverage_context.get("dispatch_as_of_ms"),
                            "coverage_ratio": coverage_context.get("coverage_ratio"),
                            "degraded": coverage_context.get("degraded"),
                            "missing_symbol_count": coverage_context.get("missing_symbol_count"),
                            "missing_symbols_sample": coverage_context.get("missing_symbols_sample"),
                            "universe_version": coverage_context.get("universe_version"),
                        },
                        "recovery": recovery,
                    },
                )
                signal = _finalize_live_task_signal(
                    db,
                    task_id=task.id,
                    claim_token=claim_token,
                    signal=signal,
                    slot_as_of_ms=effective_slot_as_of_ms,
                    mark_completed=True,
                )
                if signal is None:
                    return None
            except AgentRunAborted:
                db.rollback()
                _release_live_task_claim(db, task_id=task_id, claim_token=claim_token)
                return None if _live_retry_should_abort(db, task_id, claim_token=claim_token) else None
            except AgentRunRecoveryError as exc:
                db.rollback()
                task = db.get(LiveTask, task_id)
                if task is None:
                    return None
                signal = _build_failed_live_signal(
                    task=task,
                    trigger_time=trigger_time,
                    slot_as_of_ms=effective_slot_as_of_ms,
                    dispatch_as_of_ms=coverage_context.get("dispatch_as_of_ms"),
                    trigger_origin=trigger_origin,
                    error_message=str(exc),
                    recovery=exc.recovery_payload(),
                )
                signal = _finalize_live_task_signal(
                    db,
                    task_id=task.id,
                    claim_token=claim_token,
                    signal=signal,
                    slot_as_of_ms=effective_slot_as_of_ms,
                    mark_completed=False,
                )
                if signal is None:
                    return None
            except Exception as exc:
                db.rollback()
                task = db.get(LiveTask, task_id)
                if task is None:
                    return None
                signal = _build_failed_live_signal(
                    task=task,
                    trigger_time=trigger_time,
                    slot_as_of_ms=effective_slot_as_of_ms,
                    dispatch_as_of_ms=coverage_context.get("dispatch_as_of_ms"),
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
                signal = _finalize_live_task_signal(
                    db,
                    task_id=task.id,
                    claim_token=claim_token,
                    signal=signal,
                    slot_as_of_ms=effective_slot_as_of_ms,
                    mark_completed=False,
                )
                if signal is None:
                    return None

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
        gate_status = get_market_sync_gate_status(db)
        if gate_status.get("dispatch_as_of_ms") is None:
            coverage_end_ms = sync_snapshot.last_successful_coverage_end_ms
        else:
            if gate_status.get("status") not in {"healthy", "degraded"}:
                raise LiveTaskTriggerRejectedError("Live coverage gate is blocked.")
            coverage_end_ms = gate_status.get("dispatch_as_of_ms")
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
    dispatch_as_of_ms: int | None,
    trigger_origin: str,
    error_message: str,
    recovery: dict[str, Any],
) -> LiveSignal:
    return LiveSignal(
        id=new_id("sig"),
        live_task_id=task.id,
        trigger_time=trigger_time,
        execution_time_ms=slot_as_of_ms,
        dispatch_as_of_ms=dispatch_as_of_ms,
        trigger_origin=trigger_origin,
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


def _execution_owner() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"



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



def _extract_live_watchlist(skill: Skill) -> set[str]:
    envelope = skill.envelope_json or {}
    market_context = envelope.get("market_context") if isinstance(envelope, dict) else {}
    if not isinstance(market_context, dict):
        return set()
    raw_symbols = None
    for key in ("watchlist", "symbols", "named_symbols"):
        candidate = market_context.get(key)
        if isinstance(candidate, list):
            raw_symbols = candidate
            break
    if not raw_symbols:
        return set()
    watchlist: set[str] = set()
    for item in raw_symbols:
        symbol = str(item or "").strip().upper()
        if not symbol:
            continue
        if not symbol.endswith("-USDT-SWAP"):
            symbol = f"{symbol}-USDT-SWAP"
        watchlist.add(symbol)
    return watchlist


def _live_retry_should_abort(db: Session, task_id: str, *, claim_token: str | None = None) -> bool:
    db.expire_all()
    task = db.get(LiveTask, task_id)
    if task is None or task.status != LIVE_STATUS_ACTIVE:
        return True
    if claim_token is not None and task.execution_claim_token != claim_token:
        return True
    return False



def _sync_snapshot_is_stale(last_successful_sync_completed_at_ms: int) -> bool:
    freshness_ms = int(settings.live_data_freshness_seconds * 1000)
    now_ms = datetime_to_ms(utc_now())
    return now_ms - last_successful_sync_completed_at_ms > freshness_ms


def _claim_live_task_slot(
    db: Session,
    *,
    task_id: str,
    slot_as_of_ms: int,
    conflict_policy: Literal["skip", "raise"],
    raise_on_reject: bool,
) -> dict[str, Any]:
    task = db.scalar(select(LiveTask).where(LiveTask.id == task_id).with_for_update())
    if task is None:
        if raise_on_reject:
            raise LookupError("Live task not found.")
        return {}
    existing_signal = db.scalar(
        select(LiveSignal)
        .where(
            LiveSignal.live_task_id == task_id,
            LiveSignal.execution_time_ms == slot_as_of_ms,
        )
        .order_by(LiveSignal.created_at.desc())
    )
    if existing_signal is not None:
        return {"task": task, "signal": existing_signal, "claim_token": None}
    if task.status != LIVE_STATUS_ACTIVE:
        if raise_on_reject:
            raise LiveTaskTriggerRejectedError("Live task is not active.")
        return {}
    if task.last_completed_slot_as_of_ms is not None and slot_as_of_ms <= task.last_completed_slot_as_of_ms:
        if raise_on_reject:
            raise LiveTaskTriggerRejectedError("No executable live slot is pending.")
        return {}

    now = utc_now()
    if (
        task.execution_claim_token
        and task.last_claimed_slot_as_of_ms == slot_as_of_ms
        and task.execution_claim_expires_at is not None
        and ensure_utc(task.execution_claim_expires_at) > now
    ):
        if conflict_policy == "raise":
            raise LiveTaskConflictError("Live task slot is already claimed.")
        return {}

    claim_token = new_id("lclaim")
    task.last_triggered_at = now
    task.last_claimed_slot_as_of_ms = slot_as_of_ms
    task.execution_claim_owner = _execution_owner()
    task.execution_claim_token = claim_token
    task.execution_claimed_at = now
    task.execution_claim_expires_at = now + timedelta(seconds=settings.live_task_execution_claim_ttl_seconds)
    db.add(task)
    db.commit()
    db.refresh(task)
    return {"task": task, "signal": None, "claim_token": claim_token}


def _release_live_task_claim(db: Session, *, task_id: str, claim_token: str) -> None:
    task = db.scalar(select(LiveTask).where(LiveTask.id == task_id).with_for_update())
    if task is None or task.execution_claim_token != claim_token:
        db.rollback()
        return
    task.execution_claim_token = None
    task.execution_claim_owner = None
    task.execution_claimed_at = None
    task.execution_claim_expires_at = None
    db.add(task)
    db.commit()


def _finalize_live_task_signal(
    db: Session,
    *,
    task_id: str,
    claim_token: str,
    signal: LiveSignal,
    slot_as_of_ms: int,
    mark_completed: bool,
) -> LiveSignal | None:
    task = db.scalar(select(LiveTask).where(LiveTask.id == task_id).with_for_update())
    if task is None:
        db.rollback()
        return None
    if task.execution_claim_token != claim_token:
        db.rollback()
        existing_signal = db.scalar(
            select(LiveSignal)
            .where(
                LiveSignal.live_task_id == task_id,
                LiveSignal.execution_time_ms == slot_as_of_ms,
            )
            .order_by(LiveSignal.created_at.desc())
        )
        return existing_signal

    if mark_completed:
        task.last_completed_slot_as_of_ms = slot_as_of_ms
    task.execution_claim_token = None
    task.execution_claim_owner = None
    task.execution_claimed_at = None
    task.execution_claim_expires_at = None
    db.add(signal)
    db.add(task)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing_signal = db.scalar(
            select(LiveSignal)
            .where(
                LiveSignal.live_task_id == task_id,
                LiveSignal.execution_time_ms == slot_as_of_ms,
            )
            .order_by(LiveSignal.created_at.desc())
        )
        return existing_signal
    return signal
