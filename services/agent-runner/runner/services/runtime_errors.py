from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from runner.schemas import RunnerErrorDetail


@dataclass(slots=True)
class RunnerExecutionError(RuntimeError):
    status_code: int
    detail: RunnerErrorDetail

    def __post_init__(self) -> None:
        RuntimeError.__init__(self, self.detail.message)


def to_http_exception(exc: Exception) -> HTTPException:
    if isinstance(exc, RunnerExecutionError):
        return HTTPException(status_code=exc.status_code, detail=exc.detail.model_dump(exclude_none=True))
    detail = classify_exception(exc)
    return HTTPException(status_code=detail.status_code, detail=detail.detail.model_dump(exclude_none=True))


@dataclass(frozen=True, slots=True)
class ClassifiedRunnerError:
    status_code: int
    detail: RunnerErrorDetail


def classify_exception(exc: Exception) -> ClassifiedRunnerError:
    class_name = exc.__class__.__name__
    if class_name == "APITimeoutError":
        return ClassifiedRunnerError(
            status_code=504,
            detail=RunnerErrorDetail(
                retryable=True,
                source="openai",
                error_type="upstream_timeout",
                message="The upstream model request timed out.",
            ),
        )
    if class_name == "APIConnectionError":
        return ClassifiedRunnerError(
            status_code=503,
            detail=RunnerErrorDetail(
                retryable=True,
                source="openai",
                error_type="upstream_connection_error",
                message=_clean_message(exc, fallback="The upstream model endpoint was temporarily unreachable."),
            ),
        )

    if class_name in {"APIStatusError", "RateLimitError"}:
        response = getattr(exc, "response", None)
        response_status = _coerce_int(getattr(exc, "status_code", None)) or _coerce_int(
            getattr(response, "status_code", None)
        )
        body = _extract_json_body(response)
        error_body = body.get("error") if isinstance(body.get("error"), dict) else body
        code = _clean_optional_text(error_body.get("code")) or _clean_optional_text(error_body.get("type"))
        message = _clean_optional_text(error_body.get("message")) or _clean_message(
            exc,
            fallback="The upstream model request failed.",
        )
        retry_after = _parse_retry_after(getattr(response, "headers", None))
        retryable = bool(response_status == 429 or (response_status is not None and response_status >= 500))
        return ClassifiedRunnerError(
            status_code=429 if response_status == 429 else (503 if retryable else 500),
            detail=RunnerErrorDetail(
                retryable=retryable,
                source="openai",
                error_type=code or _default_status_error_type(response_status),
                message=message,
                upstream_status=response_status,
                retry_after_seconds=retry_after,
                code=code,
            ),
        )

    return ClassifiedRunnerError(
        status_code=500,
        detail=RunnerErrorDetail(
            retryable=False,
            source="runner",
            error_type="runner_internal_error",
            message=_clean_message(exc, fallback="The Agent Runner failed unexpectedly."),
        ),
    )


def build_stream_event_error(error: Any) -> RunnerExecutionError:
    payload = error if isinstance(error, dict) else {}
    raw_type = _clean_optional_text(payload.get("type")) or "responses_api_error"
    code = _clean_optional_text(payload.get("code")) or raw_type
    message = _clean_optional_text(payload.get("message")) or "Responses API stream failed."
    headers = payload.get("headers") if isinstance(payload.get("headers"), dict) else None
    retry_after = _parse_retry_after(headers)
    upstream_status = 429 if code == "too_many_requests" or raw_type == "too_many_requests" else None
    retryable = bool(upstream_status == 429 or raw_type in {"server_error", "internal_error", "rate_limit_exceeded"})
    status_code = 429 if upstream_status == 429 else (503 if retryable else 500)
    return RunnerExecutionError(
        status_code=status_code,
        detail=RunnerErrorDetail(
            retryable=retryable,
            source="responses_api",
            error_type=raw_type,
            message=message,
            upstream_status=upstream_status,
            retry_after_seconds=retry_after,
            code=code,
        ),
    )


def _extract_json_body(response: Any) -> dict[str, Any]:
    if response is None:
        return {}
    json_method = getattr(response, "json", None)
    if not callable(json_method):
        return {}
    try:
        body = json_method()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _clean_optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _clean_message(exc: Exception, *, fallback: str) -> str:
    message = str(exc).strip()
    return message or fallback


def _parse_retry_after(headers: Any) -> float | None:
    if not headers:
        return None
    if isinstance(headers, dict):
        raw_value = headers.get("retry-after") or headers.get("Retry-After")
    else:
        raw_value = getattr(headers, "get", lambda *_args, **_kwargs: None)("retry-after")
        if raw_value is None:
            raw_value = getattr(headers, "get", lambda *_args, **_kwargs: None)("Retry-After")
    if raw_value is None:
        return None
    try:
        parsed = float(str(raw_value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _default_status_error_type(status_code: int | None) -> str:
    if status_code == 429:
        return "too_many_requests"
    if status_code is None:
        return "upstream_status_error"
    return f"upstream_http_{status_code}"
