from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from app.services.agent_run_recovery import AgentRunAborted, BACKTEST_RETRY_POLICY, compute_retry_delay, execute_agent_run_with_recovery
from app.services.agent_runner_client import (
    AgentRunnerErrorDetail,
    AgentRunnerRequestError,
    _detail_from_http_status_error,
)


class AgentRunRecoveryTests(unittest.TestCase):
    def test_structured_http_429_is_classified_as_transient(self) -> None:
        request = httpx.Request("POST", "http://runner/v1/runs/execute")
        response = httpx.Response(
            429,
            request=request,
            json={
                "detail": {
                    "retryable": True,
                    "source": "openai",
                    "error_type": "too_many_requests",
                    "message": "Too Many Requests",
                    "upstream_status": 429,
                    "retry_after_seconds": 6,
                }
            },
        )
        exc = httpx.HTTPStatusError("Too Many Requests", request=request, response=response)

        detail = _detail_from_http_status_error(exc)

        self.assertTrue(detail.retryable)
        self.assertEqual(detail.error_type, "too_many_requests")
        self.assertEqual(detail.upstream_status, 429)
        self.assertEqual(detail.retry_after_seconds, 6)

    def test_plain_http_400_is_not_retryable(self) -> None:
        request = httpx.Request("POST", "http://runner/v1/runs/execute")
        response = httpx.Response(400, request=request, text="bad request")
        exc = httpx.HTTPStatusError("bad request", request=request, response=response)

        detail = _detail_from_http_status_error(exc)

        self.assertFalse(detail.retryable)
        self.assertEqual(detail.error_type, "agent_runner_http_400")

    def test_compute_retry_delay_prefers_retry_after(self) -> None:
        delay = compute_retry_delay(
            policy=BACKTEST_RETRY_POLICY,
            attempt_count=1,
            retry_after_seconds=7,
            total_delay_seconds=0,
        )
        self.assertEqual(delay, 7)

    def test_execute_agent_run_with_recovery_retries_transient_failures(self) -> None:
        attempts = {"count": 0}

        def fake_execute(_payload):
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise AgentRunnerRequestError(
                    operation="run execution",
                    status_code=503,
                    detail=AgentRunnerErrorDetail(
                        retryable=True,
                        source="agent_runner",
                        error_type="upstream_http_503",
                        message="temporary outage",
                    ),
                )
            return {"decision": {"action": "skip"}}

        sleeps: list[float] = []
        with (
            patch("app.services.agent_run_recovery.execute_agent_run", side_effect=fake_execute),
            patch("app.services.agent_run_recovery.random.uniform", return_value=0.25),
        ):
            response, recovery = execute_agent_run_with_recovery({}, mode="backtest", sleep_fn=sleeps.append)

        self.assertEqual(attempts["count"], 3)
        self.assertEqual(response["decision"]["action"], "skip")
        self.assertEqual(recovery["attempt_count"], 3)
        self.assertTrue(recovery["recovered"])
        self.assertEqual(sleeps, [0.25, 0.25])

    def test_execute_agent_run_with_recovery_aborts_when_runtime_is_no_longer_active(self) -> None:
        def fake_execute(_payload):
            raise AgentRunnerRequestError(
                operation="run execution",
                status_code=503,
                detail=AgentRunnerErrorDetail(
                    retryable=True,
                    source="agent_runner",
                    error_type="upstream_http_503",
                    message="temporary outage",
                ),
            )

        with patch("app.services.agent_run_recovery.execute_agent_run", side_effect=fake_execute):
            with self.assertRaises(AgentRunAborted):
                execute_agent_run_with_recovery({}, mode="backtest", should_abort=lambda: True)


if __name__ == "__main__":
    unittest.main()
