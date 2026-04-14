from __future__ import annotations

import unittest

from runner.config import settings
from runner.services.model_routing import get_responses_client_key, resolve_upstream_model_name


class ModelRoutingTests(unittest.TestCase):
    def test_resolve_upstream_model_name_strips_azure_prefix(self) -> None:
        self.assertEqual(resolve_upstream_model_name("az/gpt-5.4"), "gpt-5.4")

    def test_resolve_upstream_model_name_keeps_other_prefixes(self) -> None:
        original_base_url = settings.novita_base_url
        try:
            settings.novita_base_url = "https://api.novita.ai/openai/v1"
            self.assertEqual(resolve_upstream_model_name("pa/gpt-5.4"), "pa/gpt-5.4")
        finally:
            settings.novita_base_url = original_base_url

    def test_resolve_upstream_model_name_strips_novita_prefix_for_compat_gateway(self) -> None:
        original_base_url = settings.novita_base_url
        try:
            settings.novita_base_url = "https://cc.macaron.xin/openai/v1"
            self.assertEqual(resolve_upstream_model_name("pa/gpt-5.4"), "gpt-5.4")
        finally:
            settings.novita_base_url = original_base_url

    def test_get_responses_client_key_routes_azure_models(self) -> None:
        self.assertEqual(get_responses_client_key("az/gpt-5.4"), "azure_openai")

    def test_get_responses_client_key_routes_novita_models(self) -> None:
        self.assertEqual(get_responses_client_key("pa/gpt-5.4"), "novita")

    def test_get_responses_client_key_defaults_to_openai(self) -> None:
        self.assertEqual(get_responses_client_key("gpt-5.1-codex-mini"), "openai")


if __name__ == "__main__":
    unittest.main()
