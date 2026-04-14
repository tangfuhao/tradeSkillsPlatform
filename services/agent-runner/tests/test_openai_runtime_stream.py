from __future__ import annotations

import unittest
import json

from runner.config import settings
from runner.services.openai_runtime import _stream_response_round


class _FakeStreamingResponse:
    def __init__(self, events: list[dict], request_log: list[dict]) -> None:
        self._events = events
        self._request_log = request_log

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def iter_lines(self):
        for event in self._events:
            yield f"data: {json.dumps(event, ensure_ascii=False)}"
        yield "data: [DONE]"


class _FakeStreamingResponsesAPI:
    def __init__(self, events: list[dict], request_log: list[dict]) -> None:
        self._events = events
        self._request_log = request_log

    def create(self, **kwargs):
        self._request_log.append(kwargs)
        return _FakeStreamingResponse(self._events, self._request_log)


class _FakeResponsesAPI:
    def __init__(self, events: list[dict], request_log: list[dict]) -> None:
        self.with_streaming_response = _FakeStreamingResponsesAPI(events, request_log)


class _FakeClient:
    def __init__(self, events: list[dict], request_log: list[dict]) -> None:
        self.responses = _FakeResponsesAPI(events, request_log)


class OpenAIRuntimeStreamTests(unittest.TestCase):
    def test_stream_round_normalizes_azure_model_and_collects_text(self) -> None:
        request_log: list[dict] = []
        client = _FakeClient(
            events=[
                {
                    "type": "response.output_text.delta",
                    "item_id": "msg_1",
                    "content_index": 0,
                    "delta": '{"decision":{"action":"skip","reason":"no setup"}}',
                },
                {
                    "type": "response.output_item.done",
                    "item": {
                        "id": "msg_1",
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": '{"decision":{"action":"skip","reason":"no setup"}}'}
                        ],
                    },
                },
            ],
            request_log=request_log,
        )

        original_model = settings.openai_model
        try:
            settings.openai_model = "az/gpt-5.4"
            result = _stream_response_round(
                client,
                conversation_items=[{"type": "message", "role": "user", "content": []}],
            )
        finally:
            settings.openai_model = original_model

        self.assertEqual(result.output_text, '{"decision":{"action":"skip","reason":"no setup"}}')
        self.assertEqual(result.function_calls, [])
        self.assertEqual(request_log[0]["model"], "gpt-5.4")
        self.assertTrue(request_log[0]["stream"])

    def test_stream_round_normalizes_novita_prefix_for_compat_gateway(self) -> None:
        request_log: list[dict] = []
        client = _FakeClient(
            events=[
                {
                    "type": "response.output_text.delta",
                    "item_id": "msg_1",
                    "content_index": 0,
                    "delta": '{"decision":{"action":"skip","reason":"compat route"}}',
                },
            ],
            request_log=request_log,
        )

        original_model = settings.openai_model
        original_novita_base_url = settings.novita_base_url
        try:
            settings.openai_model = "pa/gpt-5.4"
            settings.novita_base_url = "https://cc.macaron.xin/openai/v1"
            _stream_response_round(
                client,
                conversation_items=[{"type": "message", "role": "user", "content": []}],
            )
        finally:
            settings.openai_model = original_model
            settings.novita_base_url = original_novita_base_url

        self.assertEqual(request_log[0]["model"], "gpt-5.4")
        self.assertTrue(request_log[0]["stream"])

    def test_stream_round_collects_function_calls(self) -> None:
        request_log: list[dict] = []
        client = _FakeClient(
            events=[
                {
                    "type": "response.output_item.added",
                    "item": {
                        "id": "fc_1",
                        "type": "function_call",
                        "call_id": "call_123",
                        "name": "scan_market",
                    },
                },
                {
                    "type": "response.function_call_arguments.delta",
                    "item_id": "fc_1",
                    "call_id": "call_123",
                    "delta": '{"top_n":',
                },
                {
                    "type": "response.function_call_arguments.done",
                    "item_id": "fc_1",
                    "arguments": '{"top_n": 5}',
                },
                {
                    "type": "response.output_item.done",
                    "item": {
                        "id": "fc_1",
                        "type": "function_call",
                        "call_id": "call_123",
                        "name": "scan_market",
                        "arguments": '{"top_n": 5}',
                    },
                },
            ],
            request_log=request_log,
        )

        result = _stream_response_round(
            client,
            conversation_items=[{"type": "message", "role": "user", "content": []}],
        )

        self.assertEqual(len(result.function_calls), 1)
        self.assertEqual(result.function_calls[0]["name"], "scan_market")
        self.assertEqual(result.function_calls[0]["call_id"], "call_123")
        self.assertEqual(result.function_calls[0]["arguments"], '{"top_n": 5}')


if __name__ == "__main__":
    unittest.main()
