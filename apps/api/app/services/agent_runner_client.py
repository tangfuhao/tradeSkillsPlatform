from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings
from app.services.internal_http import build_internal_http_client


@dataclass(frozen=True, slots=True)
class AgentRunnerErrorDetail:
    retryable: bool
    source: str
    error_type: str
    message: str
    upstream_status: int | None = None
    retry_after_seconds: float | None = None
    code: str | None = None


@dataclass(slots=True)
class AgentRunnerRequestError(RuntimeError):
    operation: str
    detail: AgentRunnerErrorDetail
    status_code: int | None = None

    def __post_init__(self) -> None:
        if self.status_code is not None:
            RuntimeError.__init__(
                self,
                f"Agent Runner {self.operation} returned HTTP {self.status_code}: {self.detail.message}",
            )
        else:
            RuntimeError.__init__(self, f"Agent Runner {self.operation} failed: {self.detail.message}")

    @property
    def retryable(self) -> bool:
        return self.detail.retryable

    @property
    def retry_after_seconds(self) -> float | None:
        return self.detail.retry_after_seconds

    @property
    def error_type(self) -> str:
        return self.detail.error_type

    @property
    def message(self) -> str:
        return self.detail.message

    @property
    def source(self) -> str:
        return self.detail.source

    @property
    def upstream_status(self) -> int | None:
        return self.detail.upstream_status

    @property
    def code(self) -> str | None:
        return self.detail.code

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "retryable": self.retryable,
            "source": self.source,
            "error_type": self.error_type,
            "message": self.message,
            "last_http_status": self.status_code,
            "upstream_status": self.upstream_status,
            "retry_after_seconds": self.retry_after_seconds,
            "code": self.code,
        }


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
        raise AgentRunnerRequestError(
            operation=operation,
            detail=_detail_from_http_status_error(exc),
            status_code=exc.response.status_code,
        ) from exc
    except httpx.TimeoutException as exc:
        raise AgentRunnerRequestError(
            operation=operation,
            detail=AgentRunnerErrorDetail(
                retryable=True,
                source="agent_runner",
                error_type="agent_runner_timeout",
                message=(
                    f"The Agent Runner {operation} timed out after "
                    f"{settings.agent_runner_timeout_seconds:.0f}s."
                ),
            ),
            status_code=504,
        ) from exc
    except httpx.HTTPError as exc:
        raise AgentRunnerRequestError(
            operation=operation,
            detail=AgentRunnerErrorDetail(
                retryable=True,
                source="agent_runner",
                error_type="agent_runner_connection_error",
                message=str(exc),
            ),
            status_code=503,
        ) from exc

    try:
        return response.json()
    except ValueError as exc:
        raise AgentRunnerRequestError(
            operation=operation,
            detail=AgentRunnerErrorDetail(
                retryable=False,
                source="agent_runner",
                error_type="agent_runner_non_json_response",
                message="Agent Runner returned a non-JSON response.",
            ),
            status_code=response.status_code,
        ) from exc


def _detail_from_http_status_error(exc: httpx.HTTPStatusError) -> AgentRunnerErrorDetail:
    response = exc.response
    structured_detail = _structured_detail_from_response(response)
    if structured_detail is not None:
        return structured_detail

    detail_text = response.text.strip() or str(exc)
    retry_after_seconds = _parse_retry_after(response.headers)
    retryable = response.status_code in {429, 502, 503, 504}
    return AgentRunnerErrorDetail(
        retryable=retryable,
        source="agent_runner",
        error_type=("too_many_requests" if response.status_code == 429 else f"agent_runner_http_{response.status_code}"),
        message=detail_text,
        upstream_status=response.status_code if retryable else None,
        retry_after_seconds=retry_after_seconds,
    )


def _structured_detail_from_response(response: httpx.Response) -> AgentRunnerErrorDetail | None:
    try:
        body = response.json()
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(body, dict):
        return None
    detail = body.get("detail")
    if not isinstance(detail, dict):
        return None
    message = str(detail.get("message") or response.text.strip() or f"HTTP {response.status_code}").strip()
    return AgentRunnerErrorDetail(
        retryable=bool(detail.get("retryable")),
        source=str(detail.get("source") or "agent_runner"),
        error_type=str(detail.get("error_type") or detail.get("code") or f"agent_runner_http_{response.status_code}"),
        message=message,
        upstream_status=_coerce_int(detail.get("upstream_status")),
        retry_after_seconds=_coerce_float(detail.get("retry_after_seconds")) or _parse_retry_after(response.headers),
        code=_clean_optional_text(detail.get("code")),
    )


def _parse_retry_after(headers: httpx.Headers) -> float | None:
    raw_value = headers.get("retry-after") or headers.get("Retry-After")
    return _coerce_float(raw_value)


def _clean_optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
