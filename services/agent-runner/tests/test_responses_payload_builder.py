from __future__ import annotations

import unittest

from runner.config import settings
from runner.services.responses_payload_builder import build_responses_request_payload


class ResponsesPayloadBuilderTests(unittest.TestCase):
    def test_builder_uses_global_reasoning_for_default_requests(self) -> None:
        original_model = settings.openai_model
        original_novita_base_url = settings.novita_base_url
        try:
            settings.openai_model = "pa/gpt-5.4"
            settings.novita_base_url = "https://api.novita.ai/openai/v1"
            payload = build_responses_request_payload(
                model_name=settings.openai_model,
                conversation_items=[{"type": "message", "role": "user", "content": []}],
                system_prompt="system",
                tools=[],
                stream=True,
            )
        finally:
            settings.openai_model = original_model
            settings.novita_base_url = original_novita_base_url

        self.assertNotIn("temperature", payload)
        self.assertEqual(payload["model"], "pa/gpt-5.4")
        self.assertEqual(payload["reasoning"], {"effort": settings.openai_reasoning_effort})

    def test_builder_omits_reasoning_for_execute_requests_when_override_is_blank(self) -> None:
        original_execute_reasoning_effort = settings.execute_reasoning_effort
        try:
            settings.execute_reasoning_effort = ""
            payload = build_responses_request_payload(
                model_name="pa/gpt-5.4",
                conversation_items=[{"type": "message", "role": "user", "content": []}],
                system_prompt="system",
                tools=[],
                stream=True,
                request_kind="execute",
            )
        finally:
            settings.execute_reasoning_effort = original_execute_reasoning_effort

        self.assertNotIn("reasoning", payload)

    def test_builder_normalizes_prefixed_model_for_compat_route(self) -> None:
        original_novita_base_url = settings.novita_base_url
        try:
            settings.novita_base_url = "https://compat.example.com/openai/v1"
            payload = build_responses_request_payload(
                model_name="pa/gpt-5.4",
                conversation_items=[{"type": "message", "role": "user", "content": []}],
                system_prompt="",
                tools=[],
                stream=False,
            )
        finally:
            settings.novita_base_url = original_novita_base_url

        self.assertEqual(payload["model"], "gpt-5.4")
        self.assertFalse(payload["stream"])


if __name__ == "__main__":
    unittest.main()
