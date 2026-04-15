from __future__ import annotations

from typing import Any

from runner.config import resolve_execute_reasoning_effort, settings
from runner.services.model_routing import resolve_model_route


def build_responses_request_payload(
    *,
    model_name: str,
    conversation_items: list[dict[str, Any]],
    system_prompt: str,
    tools: list[dict[str, Any]],
    stream: bool,
    request_kind: str = "default",
) -> dict[str, Any]:
    route = resolve_model_route(model_name)
    payload: dict[str, Any] = {
        "model": route.upstream_model_name,
        "input": conversation_items,
        "store": False,
        "stream": stream,
    }
    if system_prompt:
        payload["instructions"] = system_prompt
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    reasoning_effort = (
        resolve_execute_reasoning_effort()
        if request_kind == "execute"
        else str(settings.openai_reasoning_effort or "").strip() or None
    )
    if route.supports_reasoning and reasoning_effort:
        payload["reasoning"] = {"effort": reasoning_effort}
    if route.supports_temperature and settings.openai_temperature is not None:
        payload["temperature"] = settings.openai_temperature
    return payload
