from __future__ import annotations

import unittest
from unittest.mock import patch

from runner.schemas import ExecuteRunRequest
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
    def test_execute_falls_back_to_skip_when_final_output_is_not_json(self) -> None:
        with patch("runner.services.openai_runtime.get_responses_client", return_value=object()):
            with patch(
                "runner.services.openai_runtime._stream_response_round",
                return_value=StreamRoundResult(
                    output_text="I'm sorry, but I cannot assist with that request.",
                    output_items=[],
                    function_calls=[],
                ),
            ):
                result = OpenAIToolDecisionEngine().execute(_request())

        self.assertEqual(result.decision.action, "skip")
        self.assertEqual(result.decision.size_pct, 0.0)
        self.assertIn("unstructured final response", result.decision.reason)
        self.assertIn("failed closed", result.reasoning_summary)


if __name__ == "__main__":
    unittest.main()
