from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.portfolio_engine import PortfolioEngine


def handle_get_strategy_state(
    db: Session,
    *,
    skill_id: str,
    scope_kind: str,
    scope_id: str,
) -> dict[str, Any]:
    engine = PortfolioEngine(
        db,
        skill_id=skill_id,
        scope_kind=scope_kind,
        scope_id=scope_id,
    )
    state = engine.get_strategy_state()
    db.commit()
    return {
        "status": "ok",
        "content": {
            "strategy_state": state,
        },
    }


def handle_save_strategy_state(
    db: Session,
    *,
    skill_id: str,
    scope_kind: str,
    scope_id: str,
    patch: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(patch, dict):
        return {"status": "error", "content": {"error": "patch must be an object"}}
    engine = PortfolioEngine(
        db,
        skill_id=skill_id,
        scope_kind=scope_kind,
        scope_id=scope_id,
    )
    state = engine.save_strategy_state(patch)
    db.commit()
    return {
        "status": "ok",
        "content": {
            "strategy_state": state,
        },
    }
