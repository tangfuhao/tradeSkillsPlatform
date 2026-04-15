from __future__ import annotations

import unittest
from unittest.mock import patch

from runner.schemas import ExecutionTiming, SkillEnvelopeExtractRequest
from runner.services.openai_runtime import StreamRoundResult
from runner.services.skill_envelope_runtime import OpenAISkillEnvelopeExtractionEngine, _system_prompt


def _request() -> SkillEnvelopeExtractRequest:
    return SkillEnvelopeExtractRequest.model_validate(
        {
            "skill_text": "01234567890123456789 Every 15 minutes. Use AI reasoning. Max position 10%. Max daily drawdown 8%. Max concurrent positions 2.",
            "title_override": None,
            "rule_envelope": {"trigger": {"value": "15m"}},
            "rule_errors": ["Skill title could not be identified."],
            "rule_warnings": [],
            "missing_fields": ["title"],
        }
    )


class SkillEnvelopeRuntimeTests(unittest.TestCase):
    def test_extract_returns_structured_patch_when_output_is_valid_json(self) -> None:
        with patch("runner.services.skill_envelope_runtime.get_responses_client", return_value=object()):
            with patch(
                "runner.services.skill_envelope_runtime._stream_response_round",
                return_value=StreamRoundResult(
                    output_text='{"title":"Recovered Title","reasoning_summary":"Recovered title from text.","envelope_patch":{},"warnings":[],"unresolved_fields":[]}',
                    output_items=[],
                    function_calls=[],
                    execution_timing=ExecutionTiming(
                        started_at_ms=1704067200000,
                        completed_at_ms=1704067200010,
                        duration_ms=10,
                    ),
                    result_type="final_output",
                ),
            ):
                result = OpenAISkillEnvelopeExtractionEngine().extract(_request())

        self.assertEqual(result.title, "Recovered Title")
        self.assertEqual(result.provider, "openai-skill-envelope")
        self.assertEqual(result.unresolved_fields, [])

    def test_extract_fails_closed_when_output_is_not_json(self) -> None:
        with patch("runner.services.skill_envelope_runtime.get_responses_client", return_value=object()):
            with patch(
                "runner.services.skill_envelope_runtime._stream_response_round",
                return_value=StreamRoundResult(
                    output_text="I think the title is obvious from the text.",
                    output_items=[],
                    function_calls=[],
                    execution_timing=ExecutionTiming(
                        started_at_ms=1704067200000,
                        completed_at_ms=1704067200010,
                        duration_ms=10,
                    ),
                    result_type="final_output",
                ),
            ):
                with self.assertRaises(RuntimeError) as exc_info:
                    OpenAISkillEnvelopeExtractionEngine().extract(_request())

        self.assertIn("non-JSON final output", str(exc_info.exception))

    def test_prompt_instructs_model_not_to_overwrite_rule_fields(self) -> None:
        prompt = _system_prompt()

        self.assertIn("Do not overwrite fields that already exist in `rule_envelope`", prompt)
        self.assertIn("Never invent a cadence", prompt)
        self.assertIn("Never invent numeric hard risk limits", prompt)


if __name__ == "__main__":
    unittest.main()
