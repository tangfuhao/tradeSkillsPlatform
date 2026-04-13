from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from runner.config import settings
from runner.schemas import ExecuteRunRequest


READ_ONLY_TOOLS = {
    "scan_market",
    "get_strategy_state",
    "get_market_metadata",
    "get_candles",
    "get_funding_rate",
    "get_open_interest",
}


@dataclass(slots=True)
class ToolGatewayClient:
    payload: ExecuteRunRequest
    cache: dict[str, dict[str, Any]] = field(default_factory=dict)

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        cache_key = self._cache_key(tool_name, arguments)
        if tool_name in READ_ONLY_TOOLS and cache_key in self.cache:
            return self.cache[cache_key]

        request_payload = {
            "tool_name": tool_name,
            "skill_id": self._gateway_context().get("skill_id") or self.payload.skill_id,
            "mode": self._gateway_context().get("mode") or self.payload.mode,
            "trigger_time": self._gateway_context().get("trigger_time") or self.payload.trigger_time.isoformat(),
            "as_of": self._gateway_context().get("as_of") or self.payload.context.get("as_of"),
            "trace_index": self._gateway_context().get("trace_index"),
            "arguments": arguments,
        }
        headers = {"Content-Type": "application/json"}
        shared_secret = self._gateway_context().get("shared_secret") or ""
        if shared_secret:
            headers["X-Tool-Gateway-Secret"] = shared_secret

        response = httpx.post(
            self._execute_url(),
            json=request_payload,
            headers=headers,
            timeout=settings.tool_gateway_timeout_seconds,
        )
        response.raise_for_status()
        result = response.json()

        if tool_name in READ_ONLY_TOOLS:
            self.cache[cache_key] = result
        elif tool_name == "save_strategy_state":
            state_cache_key = self._cache_key("get_strategy_state", {})
            self.cache[state_cache_key] = {
                "status": "ok",
                "content": {"strategy_state": (result.get("content") or {}).get("strategy_state", {})},
            }
        return result

    def _execute_url(self) -> str:
        gateway_context = self._gateway_context()
        execute_url = str(gateway_context.get("execute_url") or "").strip()
        if not execute_url:
            raise RuntimeError("Tool gateway execute_url is required in payload.context.tool_gateway.")
        return execute_url

    def _gateway_context(self) -> dict[str, Any]:
        raw = self.payload.context.get("tool_gateway", {})
        return raw if isinstance(raw, dict) else {}

    def _cache_key(self, tool_name: str, arguments: dict[str, Any]) -> str:
        normalized = json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)
        return f"{tool_name}:{normalized}"
