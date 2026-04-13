from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import LiveSignal, LiveTask, Skill
from app.services.agent_runner_client import execute_agent_run
from app.services.demo_runtime import cadence_to_seconds
from app.services.serializers import live_signal_to_dict, live_task_to_dict
from app.services.utils import new_id, utc_now
from app.tool_gateway.demo_gateway import (
    build_market_snapshot_for_live,
    save_strategy_state,
)


class LiveTaskService:
    def __init__(self, db: Session):
        self.db = db

    def create_task(self, skill_id: str) -> dict[str, Any]:
        skill = self.db.get(Skill, skill_id)
        if skill is None:
            raise LookupError("Skill not found.")
        cadence = (skill.envelope_json or {}).get("trigger", {}).get("value", "15m")
        task = LiveTask(
            id=new_id("live"),
            skill_id=skill.id,
            cadence=cadence,
            cadence_seconds=cadence_to_seconds(cadence),
            status="active",
        )
        self.db.add(task)
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


def execute_live_task(task_id: str) -> dict[str, Any] | None:
    with SessionLocal() as db:
        task = db.get(LiveTask, task_id)
        if task is None or task.status != "active":
            return None
        skill = db.get(Skill, task.skill_id)
        if skill is None:
            return None
        trigger_time = utc_now()
        market_snapshot = build_market_snapshot_for_live(db)
        snapshot_as_of = _resolve_snapshot_as_of(market_snapshot, trigger_time)
        payload = {
            "skill_id": skill.id,
            "skill_title": skill.title,
            "mode": "live_signal",
            "trigger_time": trigger_time.isoformat(),
            "skill_text": skill.raw_text,
            "envelope": skill.envelope_json or {},
            "context": {
                **market_snapshot,
                "as_of": snapshot_as_of.isoformat(),
                "tool_gateway": _build_tool_gateway_context(
                    skill_id=skill.id,
                    mode="live_signal",
                    trigger_time=trigger_time.isoformat(),
                    as_of=snapshot_as_of.isoformat(),
                    trace_index=None,
                ),
            },
        }
        agent_response = execute_agent_run(payload)
        decision = dict(agent_response["decision"])
        state_patch = decision.get("state_patch") or {}
        if state_patch:
            save_strategy_state(db, skill.id, state_patch)
        signal = LiveSignal(
            id=new_id("sig"),
            live_task_id=task.id,
            trigger_time=trigger_time,
            delivery_status="stored",
            signal_json={
                **decision,
                "reasoning_summary": agent_response["reasoning_summary"],
                "provider": agent_response["provider"],
            },
        )
        task.last_triggered_at = trigger_time
        db.add(signal)
        db.add(task)
        db.commit()
        db.refresh(signal)
        return live_signal_to_dict(signal)


def _resolve_snapshot_as_of(market_snapshot: dict[str, Any], fallback: datetime) -> datetime:
    raw_value = market_snapshot.get("as_of")
    if isinstance(raw_value, str):
        try:
            return datetime.fromisoformat(raw_value)
        except ValueError:
            return fallback
    return fallback


def _build_tool_gateway_context(
    *,
    skill_id: str,
    mode: str,
    trigger_time: str,
    as_of: str,
    trace_index: int | None,
) -> dict[str, Any]:
    return {
        "base_url": f"{settings.tool_gateway_base_url.rstrip('/')}{settings.api_prefix}/internal/tool-gateway",
        "execute_url": f"{settings.tool_gateway_base_url.rstrip('/')}{settings.api_prefix}/internal/tool-gateway/execute",
        "shared_secret": settings.tool_gateway_shared_secret,
        "skill_id": skill_id,
        "mode": mode,
        "trigger_time": trigger_time,
        "as_of": as_of,
        "trace_index": trace_index,
    }
