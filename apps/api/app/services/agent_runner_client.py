from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.services.internal_http import build_internal_http_client


def execute_agent_run(payload: dict[str, Any]) -> dict[str, Any]:
    return _post_runner_json("/v1/runs/execute", payload, operation="run execution")


def extract_skill_envelope_with_runner(payload: dict[str, Any]) -> dict[str, Any]:
    return _post_runner_json("/v1/skills/extract-envelope", payload, operation="envelope extraction")


def _post_runner_json(path: str, payload: dict[str, Any], *, operation: str) -> dict[str, Any]:
    try:
        with build_internal_http_client(timeout=settings.agent_runner_timeout_seconds) as client:
            response = client.post(
                f"{settings.agent_runner_base_url}{path}",
                json=payload,
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text.strip() or str(exc)
        raise RuntimeError(f"Agent Runner {operation} returned HTTP {exc.response.status_code}: {detail}") from exc
    except httpx.TimeoutException as exc:
        raise RuntimeError(
            "Agent Runner "
            f"{operation} timed out after {settings.agent_runner_timeout_seconds:.0f}s. "
            "Increase TRADE_SKILLS_AGENT_RUNNER_TIMEOUT_SECONDS or reduce the model latency budget."
        ) from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Agent Runner {operation} failed: {exc}") from exc

    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(f"Agent Runner {operation} returned a non-JSON response.") from exc
