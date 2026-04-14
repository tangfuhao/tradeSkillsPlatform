from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from runner.config import settings
from runner.schemas import ExecuteRunRequest
from runner.services.internal_http import build_internal_http_client


READ_ONLY_TOOLS = {
    "scan_market",
    "get_portfolio_state",
    "get_strategy_state",
    "get_market_metadata",
    "get_candles",
    "get_funding_rate",
    "get_open_interest",
}

TOOL_ENDPOINTS = {
    "scan_market": "/market/scan",
    "get_portfolio_state": "/portfolio/state",
    "get_market_metadata": "/market/metadata",
    "get_candles": "/market/candles",
    "get_funding_rate": "/market/funding-rate",
    "get_open_interest": "/market/open-interest",
    "get_strategy_state": "/state/get",
    "save_strategy_state": "/state/save",
    "simulate_order": "/signal/simulate-order",
    "emit_signal": "/signal/emit",
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
            "skill_id": self._gateway_context().get("skill_id") or self.payload.skill_id,
            "scope_kind": self._gateway_context().get("scope_kind"),
            "scope_id": self._gateway_context().get("scope_id"),
            "mode": self._gateway_context().get("mode") or self.payload.mode,
            "trigger_time_ms": self._gateway_context().get("trigger_time_ms") or self.payload.trigger_time_ms,
            "as_of_ms": self._gateway_context().get("as_of_ms") or self.payload.context.get("as_of_ms"),
            "trace_index": self._gateway_context().get("trace_index"),
        }
        request_payload.update(arguments)
        headers = {"Content-Type": "application/json"}
        shared_secret = self._gateway_context().get("shared_secret") or ""
        if shared_secret:
            headers["X-Tool-Gateway-Secret"] = shared_secret

        try:
            with build_internal_http_client(timeout=settings.tool_gateway_timeout_seconds) as client:
                response = client.post(
                    self._endpoint_url(tool_name),
                    json=request_payload,
                    headers=headers,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = _extract_error_detail(exc.response)
            raise RuntimeError(
                f"Tool Gateway {tool_name} failed with HTTP {exc.response.status_code}: {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Tool Gateway {tool_name} request failed: {exc}") from exc
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

    def _endpoint_url(self, tool_name: str) -> str:
        compatibility_execute_url = str(self._gateway_context().get("execute_url") or "").strip()
        base_url = str(self._gateway_context().get("base_url") or "").strip()
        if not base_url and compatibility_execute_url:
            return compatibility_execute_url
        if not base_url:
            raise RuntimeError("Tool gateway base_url is required in payload.context.tool_gateway.")
        suffix = TOOL_ENDPOINTS.get(tool_name)
        if not suffix:
            raise RuntimeError(f"No Tool Gateway endpoint is configured for tool: {tool_name}")
        return f"{base_url.rstrip('/')}{suffix}"

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


def _extract_error_detail(response: httpx.Response) -> str:
    body = response.text.strip()
    if not body:
        return response.reason_phrase or "request failed"
    try:
        parsed = response.json()
    except ValueError:
        return body

    detail = parsed.get("detail")
    if isinstance(detail, str) and detail.strip():
        return detail
    if isinstance(detail, list):
        messages: list[str] = []
        for item in detail:
            if isinstance(item, dict):
                location = item.get("loc")
                loc_text = ".".join(str(part) for part in location) if isinstance(location, list) else None
                msg = str(item.get("msg") or "").strip()
                if loc_text and msg:
                    messages.append(f"{loc_text}: {msg}")
                elif msg:
                    messages.append(msg)
        if messages:
            return "; ".join(messages)
    return body
