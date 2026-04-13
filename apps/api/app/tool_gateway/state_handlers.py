from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

def handle_get_strategy_state(db: Session, *, skill_id: str) -> dict[str, Any]:
    from app.tool_gateway.demo_gateway import get_strategy_state

    return {
        "status": "ok",
        "content": {
            "strategy_state": get_strategy_state(db, skill_id),
        },
    }


def handle_save_strategy_state(db: Session, *, skill_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    from app.tool_gateway.demo_gateway import save_strategy_state

    if not isinstance(patch, dict):
        return {"status": "error", "content": {"error": "patch must be an object"}}
    return {
        "status": "ok",
        "content": {
            "strategy_state": save_strategy_state(db, skill_id, patch),
        },
    }
