from __future__ import annotations

import unittest
from types import SimpleNamespace

from runner.services.startup_preflight import collect_startup_preflight_errors


def _config(**overrides):
    base = {
        "openai_model": "pa/gpt-5.4",
        "openai_wire_api": "responses",
        "openai_api_key": "openai-key",
        "openai_base_url": "https://api.openai.com/v1",
        "azure_openai_api_key": "",
        "azure_openai_base_url": "",
        "azure_openai_api_version": "2025-04-01-preview",
        "novita_api_key": "novita-key",
        "novita_base_url": "https://api.novita.ai/openai/v1",
        "allow_compat_model_prefix_routing": False,
        "openai_reasoning_effort": "medium",
        "execute_reasoning_effort": None,
        "openai_timeout_seconds": 120.0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class StartupPreflightTests(unittest.TestCase):
    def test_preflight_accepts_supported_runtime_matrix(self) -> None:
        errors = collect_startup_preflight_errors(
            _config(),
            runtime_python=(3, 12),
            openai_version="1.77.0",
        )
        self.assertEqual(errors, [])

    def test_preflight_rejects_python_version_drift(self) -> None:
        errors = collect_startup_preflight_errors(
            _config(),
            runtime_python=(3, 14),
            openai_version="1.77.0",
        )
        self.assertTrue(any("Python 3.12.x" in item for item in errors))

    def test_preflight_rejects_openai_version_drift(self) -> None:
        errors = collect_startup_preflight_errors(
            _config(),
            runtime_python=(3, 12),
            openai_version="1.78.0",
        )
        self.assertTrue(any("openai==1.77.0" in item for item in errors))

    def test_preflight_blocks_prefixed_novita_model_on_non_official_base_url(self) -> None:
        errors = collect_startup_preflight_errors(
            _config(novita_base_url="https://compat.example.com/openai/v1"),
            runtime_python=(3, 12),
            openai_version="1.77.0",
        )
        self.assertTrue(any("Prefixed Novita models" in item for item in errors))

    def test_preflight_rejects_gpt54_high_reasoning_with_low_timeout(self) -> None:
        errors = collect_startup_preflight_errors(
            _config(openai_reasoning_effort="xhigh", openai_timeout_seconds=60.0),
            runtime_python=(3, 12),
            openai_version="1.77.0",
        )
        self.assertTrue(any("AGENT_RUNNER_OPENAI_TIMEOUT_SECONDS" in item for item in errors))

    def test_preflight_rejects_gpt54_high_execute_reasoning_with_low_timeout(self) -> None:
        errors = collect_startup_preflight_errors(
            _config(execute_reasoning_effort="xhigh", openai_timeout_seconds=60.0),
            runtime_python=(3, 12),
            openai_version="1.77.0",
        )
        self.assertTrue(any("AGENT_RUNNER_OPENAI_TIMEOUT_SECONDS" in item for item in errors))

    def test_preflight_allows_compat_gateway_only_when_explicitly_enabled(self) -> None:
        errors = collect_startup_preflight_errors(
            _config(
                novita_base_url="https://compat.example.com/openai/v1",
                allow_compat_model_prefix_routing=True,
            ),
            runtime_python=(3, 12),
            openai_version="1.77.0",
        )
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
