from __future__ import annotations

import unittest
from unittest.mock import patch

from runner.schemas import ExecuteRunRequest, ExecutionTiming
from runner.services.openai_runtime import OpenAIToolDecisionEngine, StreamRoundResult


def _request() -> ExecuteRunRequest:
    return ExecuteRunRequest.model_validate(
        {
            "skill_id": "skill_test",
            "skill_title": "Test Skill",
            "mode": "backtest",
            "trigger_time_ms": 1689264000000,
            "skill_text": "01234567890123456789 simulated strategy text",
            "envelope": {},
            "context": {},
        }
    )


class OpenAIRuntimeExecuteTests(unittest.TestCase):
    def test_execute_records_round_and_tool_timing(self) -> None:
        rounds = [
            StreamRoundResult(
                output_text="",
                output_items=[],
                function_calls=[
                    {
                        "name": "scan_market",
                        "arguments": "{\"top_n\": 3}",
                        "call_id": "call_test_1",
                    }
                ],
                execution_timing=ExecutionTiming(
                    started_at_ms=1704067200000,
                    completed_at_ms=1704067201200,
                    duration_ms=1200,
                ),
                result_type="tool_calls",
            ),
            StreamRoundResult(
                output_text='{"decision":{"action":"skip","reason":"No setup."},"reasoning_summary":"Reviewed the scan results."}',
                output_items=[],
                function_calls=[],
                execution_timing=ExecutionTiming(
                    started_at_ms=1704067201200,
                    completed_at_ms=1704067202400,
                    duration_ms=1200,
                ),
                result_type="final_output",
            ),
        ]

        with patch("runner.services.openai_runtime.get_responses_client", return_value=object()):
            with patch("runner.services.openai_runtime._stream_response_round", side_effect=rounds):
                with patch(
                    "runner.services.openai_runtime.ToolRuntime.execute_tool",
                    return_value={"status": "ok", "content": {"market_candidates": []}},
                ):
                    result = OpenAIToolDecisionEngine().execute(_request())

        self.assertEqual(result.decision.action, "skip")
        self.assertEqual(result.tool_calls[0].tool_name, "scan_market")
        self.assertIsNotNone(result.tool_calls[0].execution_timing)
        self.assertIsNotNone(result.execution_timing)
        self.assertIsNotNone(result.execution_breakdown)
        self.assertEqual(len(result.llm_rounds), 2)
        assert result.tool_calls[0].execution_timing is not None
        assert result.execution_timing is not None
        assert result.execution_breakdown is not None
        self.assertGreaterEqual(result.tool_calls[0].execution_timing.duration_ms, 0)
        self.assertGreaterEqual(result.execution_timing.duration_ms, 0)
        self.assertEqual(result.execution_breakdown.llm_wait_total_ms, 2400)
        self.assertEqual(result.execution_breakdown.tool_execution_total_ms, result.tool_calls[0].execution_timing.duration_ms)
        self.assertGreaterEqual(result.execution_breakdown.other_overhead_ms, 0)
        self.assertLessEqual(
            result.tool_calls[0].execution_timing.started_at_ms,
            result.tool_calls[0].execution_timing.completed_at_ms,
        )
        self.assertLessEqual(result.execution_timing.started_at_ms, result.execution_timing.completed_at_ms)

    def test_execute_falls_back_to_skip_when_final_output_is_not_json(self) -> None:
        with patch("runner.services.openai_runtime.get_responses_client", return_value=object()):
            with patch(
                "runner.services.openai_runtime._stream_response_round",
                return_value=StreamRoundResult(
                    output_text="I'm sorry, but I cannot assist with that request.",
                    output_items=[],
                    function_calls=[],
                    execution_timing=ExecutionTiming(
                        started_at_ms=1704067200000,
                        completed_at_ms=1704067200500,
                        duration_ms=500,
                    ),
                    result_type="final_output",
                ),
            ):
                result = OpenAIToolDecisionEngine().execute(_request())

        self.assertEqual(result.decision.action, "skip")
        self.assertEqual(result.decision.size_pct, 0.0)
        self.assertIn("unstructured final response", result.decision.reason)
        self.assertIn("failed closed", result.reasoning_summary)
        self.assertIsNotNone(result.execution_timing)
        self.assertIsNotNone(result.execution_breakdown)
        self.assertEqual(len(result.llm_rounds), 1)
        assert result.execution_timing is not None
        assert result.execution_breakdown is not None
        self.assertGreaterEqual(result.execution_timing.duration_ms, 0)
        self.assertEqual(result.execution_breakdown.llm_wait_total_ms, 500)
        self.assertLessEqual(result.execution_timing.started_at_ms, result.execution_timing.completed_at_ms)


if __name__ == "__main__":
    unittest.main()
