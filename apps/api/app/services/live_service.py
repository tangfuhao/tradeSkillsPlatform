from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import LiveSignal, LiveTask, Skill
from app.services.agent_run_recovery import AgentRunAborted, AgentRunRecoveryError, execute_agent_run_with_recovery
from app.services.demo_runtime import cadence_to_seconds
from app.services.execution_cleanup import delete_live_task
from app.services.execution_lifecycle import LIVE_RUNTIME_OWNING_STATUSES, LIVE_STATUS_ACTIVE, LIVE_STATUS_PAUSED, LIVE_STATUS_STOPPED
from app.services.portfolio_engine import DEFAULT_LIVE_INITIAL_CAPITAL, LIVE_SCOPE_KIND, PortfolioEngine
from app.services.serializers import live_signal_to_dict, live_task_to_dict
from app.services.utils import datetime_to_ms, ms_to_datetime, new_id, utc_now
from app.tool_gateway.demo_gateway import build_market_snapshot_for_live


class LiveTaskOwnershipError(ValueError):
    def __init__(self, *, skill_id: str, existing_task_id: str, existing_status: str) -> None:
        super().__init__(f"Skill already owns a live runtime: {existing_task_id}")
        self.skill_id = skill_id
        self.existing_task_id = existing_task_id
        self.existing_status = existing_status


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

    def control_task(self, task_id: str, action: str) -> tuple[dict[str, Any], str | None]:
        task = self.db.get(LiveTask, task_id)
        if task is None:
            raise LookupError("Live task not found.")

        normalized = action.strip().lower()
        scheduler_effect: str | None = None

        if normalized == "pause":
            if task.status != LIVE_STATUS_ACTIVE:
                raise ValueError(f"Cannot pause a live runtime in status '{task.status}'.")
            task.status = LIVE_STATUS_PAUSED
            scheduler_effect = "unschedule"
        elif normalized == "resume":
            if task.status != LIVE_STATUS_PAUSED:
                raise ValueError(f"Cannot resume a live runtime in status '{task.status}'.")
            task.status = LIVE_STATUS_ACTIVE
            scheduler_effect = "schedule"
        elif normalized == "stop":
            if task.status not in {LIVE_STATUS_ACTIVE, LIVE_STATUS_PAUSED}:
                raise ValueError(f"Cannot stop a live runtime in status '{task.status}'.")
            task.status = LIVE_STATUS_STOPPED
            scheduler_effect = "unschedule"
        else:
            raise ValueError(f"Unsupported live runtime action '{action}'.")

        task.updated_at = utc_now()
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return live_task_to_dict(task), scheduler_effect

    def delete_task(self, task_id: str) -> None:
        task = self.db.get(LiveTask, task_id)
        if task is None:
            raise LookupError("Live task not found.")
        delete_live_task(self.db, task)
        self.db.commit()



def execute_live_task(task_id: str) -> dict[str, Any] | None:
    with SessionLocal() as db:
        task = db.get(LiveTask, task_id)
        if task is None or task.status != LIVE_STATUS_ACTIVE:
            return None
        skill = db.get(Skill, task.skill_id)
        if skill is None:
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

        try:
            market_snapshot = build_market_snapshot_for_live(db)
            snapshot_error = market_snapshot.get("error") if isinstance(market_snapshot, dict) else None
            if not market_snapshot.get("market_candidates"):
                raise RuntimeError(
                    str(snapshot_error or "No historical market snapshot is available for live execution.")
                )
            snapshot_as_of = _resolve_snapshot_as_of(market_snapshot, trigger_time)
            portfolio_before, _ = engine.mark_to_market(snapshot_as_of)
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
                    "as_of_ms": datetime_to_ms(snapshot_as_of),
                    "portfolio_summary": _portfolio_hint(portfolio_before),
                    "tool_gateway": _build_tool_gateway_context(
                        skill_id=skill.id,
                        scope_kind=LIVE_SCOPE_KIND,
                        scope_id=task.id,
                        mode="live_signal",
                        trigger_time_ms=datetime_to_ms(trigger_time),
                        as_of_ms=datetime_to_ms(snapshot_as_of),
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
                trigger_time=snapshot_as_of,
                trace_index=None,
            )
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
                    "execution_time_ms": datetime_to_ms(snapshot_as_of),
                    "execution_timing": agent_response.get("execution_timing"),
                    "execution_breakdown": agent_response.get("execution_breakdown"),
                    "llm_rounds": agent_response.get("llm_rounds"),
                    "portfolio_before": portfolio_before,
                    "portfolio_after": portfolio_after,
                    "fills": fills,
                    "recovery": recovery,
                },
            )
            if state_patch:
                engine.save_strategy_state(state_patch)
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
            signal = LiveSignal(
                id=new_id("sig"),
                live_task_id=task.id,
                trigger_time=trigger_time,
                delivery_status="failed",
                signal_json={
                    "error_message": str(exc),
                    "provider": settings.agent_runner_base_url,
                    "mode": "live_signal",
                    "execution_scope": {"scope_kind": LIVE_SCOPE_KIND, "scope_id": task.id},
                    "recovery": exc.recovery_payload(),
                },
            )
            db.add(signal)
            db.add(task)
            db.commit()
        except Exception as exc:
            db.rollback()
            task = db.get(LiveTask, task_id)
            if task is None:
                return None
            signal = LiveSignal(
                id=new_id("sig"),
                live_task_id=task.id,
                trigger_time=trigger_time,
                delivery_status="failed",
                signal_json={
                    "error_message": str(exc),
                    "provider": settings.agent_runner_base_url,
                    "mode": "live_signal",
                    "execution_scope": {"scope_kind": LIVE_SCOPE_KIND, "scope_id": task.id},
                    "recovery": {
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
                },
            )
            db.add(signal)
            db.add(task)
            db.commit()

        db.refresh(signal)
        return live_signal_to_dict(signal)



def _resolve_snapshot_as_of(market_snapshot: dict[str, Any], fallback) -> Any:
    raw_value = market_snapshot.get("as_of_ms")
    if isinstance(raw_value, int):
        return ms_to_datetime(raw_value)
    return fallback



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
