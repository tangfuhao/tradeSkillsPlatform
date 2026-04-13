from __future__ import annotations

from typing import Any


def handle_signal_intent(
    *,
    tool_name: str,
    action: str | None,
    symbol: str | None,
    direction: str | None,
    size_pct: float,
    reason: str | None,
    stop_loss_pct: float | None,
    take_profit_pct: float | None,
) -> dict[str, Any]:
    staged = {
        "action": action or ("open_position" if tool_name == "simulate_order" else "watch"),
        "symbol": str(symbol).strip().upper() if symbol else None,
        "direction": direction,
        "size_pct": float(size_pct or 0.0),
        "reason": reason or f"Intent staged through {tool_name}.",
    }
    if stop_loss_pct is not None:
        staged["stop_loss"] = {"type": "price_pct", "value": float(stop_loss_pct)}
    if take_profit_pct is not None:
        staged["take_profit"] = {"type": "price_pct", "value": float(take_profit_pct)}
    return {
        "status": "staged",
        "content": {
            "staged_decision": {key: value for key, value in staged.items() if value is not None},
        },
    }
