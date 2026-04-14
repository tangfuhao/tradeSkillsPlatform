from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.services.portfolio_engine import PortfolioEngine


def handle_get_portfolio_state(
    db: Session,
    *,
    skill_id: str,
    scope_kind: str,
    scope_id: str,
    as_of: datetime | None,
) -> dict[str, Any]:
    engine = PortfolioEngine(
        db,
        skill_id=skill_id,
        scope_kind=scope_kind,
        scope_id=scope_id,
    )
    portfolio = engine.get_portfolio_state(as_of=as_of)
    db.commit()
    return {
        "status": "ok",
        "content": {
            "portfolio": portfolio,
        },
    }
