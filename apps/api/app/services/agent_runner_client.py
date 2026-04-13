from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings


def execute_agent_run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        response = httpx.post(
            f"{settings.agent_runner_base_url}/v1/runs/execute",
            json=payload,
            timeout=settings.agent_runner_timeout_seconds,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        return _build_fallback_response(payload, str(exc))


def _build_fallback_response(payload: dict[str, Any], error_message: str) -> dict[str, Any]:
    candidates = payload.get("context", {}).get("market_candidates", [])
    decision = {
        "action": "skip",
        "symbol": None,
        "direction": None,
        "size_pct": 0.0,
        "reason": "No market candidate passed the local fallback threshold.",
        "stop_loss": None,
        "take_profit": None,
        "state_patch": {},
    }
    if candidates:
        hottest = max(candidates, key=lambda item: item.get("change_24h_pct", 0.0))
        if hottest.get("change_24h_pct", 0.0) >= 0.18:
            decision = {
                "action": "open_position",
                "symbol": hottest.get("symbol"),
                "direction": "sell",
                "size_pct": 0.10,
                "reason": "Fallback engine detected an overheated market candidate and opened a demo short.",
                "stop_loss": {"type": "price_pct", "value": 0.02},
                "take_profit": {"type": "price_pct", "value": 0.10},
                "state_patch": {"focus_symbol": hottest.get("symbol"), "last_action": "open_position"},
            }
        else:
            decision = {
                "action": "watch",
                "symbol": hottest.get("symbol"),
                "direction": None,
                "size_pct": 0.0,
                "reason": "Fallback engine found a candidate but not enough heat for a demo entry.",
                "stop_loss": None,
                "take_profit": None,
                "state_patch": {"focus_symbol": hottest.get("symbol"), "last_action": "watch"},
            }
    return {
        "decision": decision,
        "reasoning_summary": f"Agent Runner fallback was used because the HTTP call failed: {error_message}",
        "tool_calls": [
            {"tool_name": "scan_market", "arguments": {"mode": payload.get("mode")}, "status": "fallback"},
            {"tool_name": "get_strategy_state", "arguments": {"skill_id": payload.get("skill_id")}, "status": "fallback"},
        ],
        "provider": "local-fallback",
    }
