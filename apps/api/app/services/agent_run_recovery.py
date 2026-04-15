from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any, Callable

from app.services.agent_runner_client import AgentRunnerRequestError, execute_agent_run


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int
    max_total_delay_seconds: float
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 20.0


BACKTEST_RETRY_POLICY = RetryPolicy(max_attempts=4, max_total_delay_seconds=90.0)
LIVE_RETRY_POLICY = RetryPolicy(max_attempts=3, max_total_delay_seconds=20.0)


class AgentRunAborted(RuntimeError):
    pass


@dataclass(slots=True)
class AgentRunRecoveryError(RuntimeError):
    attempt_count: int
    final_error: AgentRunnerRequestError

    def __post_init__(self) -> None:
        RuntimeError.__init__(self, str(self.final_error))

    @property
    def retryable(self) -> bool:
        return self.final_error.retryable

    def recovery_payload(self) -> dict[str, Any]:
        return {
            "attempt_count": self.attempt_count,
            "recovered": False,
            "retry_count": max(0, self.attempt_count - 1),
            "retryable": self.retryable,
            "final_error": self.final_error.to_public_dict(),
        }

    def backtest_runtime_error(self, *, failed_trace_index: int, trigger_time_ms: int) -> dict[str, Any]:
        return {
            "failed_trace_index": failed_trace_index,
            "trigger_time_ms": trigger_time_ms,
            "attempt_count": self.attempt_count,
            "retryable": self.retryable,
            "last_http_status": self.final_error.status_code,
            "error_type": self.final_error.error_type,
            "message": self.final_error.message,
            "source": self.final_error.source,
            "upstream_status": self.final_error.upstream_status,
            "retry_after_seconds": self.final_error.retry_after_seconds,
            "code": self.final_error.code,
        }


def execute_agent_run_with_recovery(
    payload: dict[str, Any],
    *,
    mode: str,
    should_abort: Callable[[], bool] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[dict[str, Any], dict[str, Any]]:
    policy = BACKTEST_RETRY_POLICY if mode == "backtest" else LIVE_RETRY_POLICY
    attempt_count = 0
    total_delay_seconds = 0.0

    while attempt_count < policy.max_attempts:
        if should_abort is not None and should_abort():
            raise AgentRunAborted("Agent execution aborted because the runtime is no longer active.")

        attempt_count += 1
        try:
            response = execute_agent_run(payload)
            return response, {
                "attempt_count": attempt_count,
                "recovered": attempt_count > 1,
                "retry_count": max(0, attempt_count - 1),
            }
        except AgentRunnerRequestError as exc:
            if not exc.retryable or attempt_count >= policy.max_attempts:
                raise AgentRunRecoveryError(attempt_count=attempt_count, final_error=exc) from exc

            delay_seconds = compute_retry_delay(
                policy=policy,
                attempt_count=attempt_count,
                retry_after_seconds=exc.retry_after_seconds,
                total_delay_seconds=total_delay_seconds,
            )
            if delay_seconds is None:
                raise AgentRunRecoveryError(attempt_count=attempt_count, final_error=exc) from exc

            if should_abort is not None and should_abort():
                raise AgentRunAborted("Agent execution aborted because the runtime is no longer active.") from exc

            sleep_fn(delay_seconds)
            total_delay_seconds += delay_seconds

    raise RuntimeError("Agent recovery loop exited unexpectedly.")


def compute_retry_delay(
    *,
    policy: RetryPolicy,
    attempt_count: int,
    retry_after_seconds: float | None,
    total_delay_seconds: float,
) -> float | None:
    remaining_budget = max(0.0, policy.max_total_delay_seconds - total_delay_seconds)
    if remaining_budget <= 0:
        return None

    if retry_after_seconds is not None:
        delay = min(max(retry_after_seconds, 0.0), policy.max_delay_seconds, remaining_budget)
        return delay if delay > 0 else None

    capped_delay = min(policy.base_delay_seconds * (2 ** max(0, attempt_count - 1)), policy.max_delay_seconds)
    delay = min(random.uniform(0.0, capped_delay), remaining_budget)
    return delay if delay > 0 else None
