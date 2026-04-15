from __future__ import annotations

import unittest

from runner.services.runtime_errors import build_stream_event_error, classify_exception


class _FakeResponse:
    def __init__(self, *, status_code: int, body: dict, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}

    def json(self):
        return self._body


class APIStatusError(Exception):
    def __init__(self, *, status_code: int, body: dict, headers: dict[str, str] | None = None) -> None:
        super().__init__(body)
        self.status_code = status_code
        self.response = _FakeResponse(status_code=status_code, body=body, headers=headers)


class APITimeoutError(Exception):
    pass


class APIConnectionError(Exception):
    pass


class RuntimeErrorMappingTests(unittest.TestCase):
    def test_stream_too_many_requests_is_retryable(self) -> None:
        exc = build_stream_event_error(
            {
                "type": "too_many_requests",
                "code": "too_many_requests",
                "message": "Too Many Requests",
            }
        )

        self.assertEqual(exc.status_code, 429)
        self.assertTrue(exc.detail.retryable)
        self.assertEqual(exc.detail.error_type, "too_many_requests")
        self.assertEqual(exc.detail.upstream_status, 429)

    def test_timeout_is_classified_as_retryable(self) -> None:
        classified = classify_exception(APITimeoutError("timed out"))

        self.assertEqual(classified.status_code, 504)
        self.assertTrue(classified.detail.retryable)
        self.assertEqual(classified.detail.error_type, "upstream_timeout")

    def test_connection_error_is_classified_as_retryable(self) -> None:
        classified = classify_exception(APIConnectionError("connection reset"))

        self.assertEqual(classified.status_code, 503)
        self.assertTrue(classified.detail.retryable)
        self.assertEqual(classified.detail.error_type, "upstream_connection_error")

    def test_non_retryable_status_error_stays_permanent(self) -> None:
        classified = classify_exception(
            APIStatusError(
                status_code=400,
                body={"error": {"code": "invalid_request", "message": "Invalid request."}},
            )
        )

        self.assertEqual(classified.status_code, 500)
        self.assertFalse(classified.detail.retryable)
        self.assertEqual(classified.detail.error_type, "invalid_request")


if __name__ == "__main__":
    unittest.main()
