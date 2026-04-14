from __future__ import annotations

import unittest

from app.services.internal_http import build_internal_http_client


class InternalHTTPTests(unittest.TestCase):
    def test_internal_http_client_disables_env_proxy_discovery(self) -> None:
        with build_internal_http_client(timeout=1.0) as client:
            self.assertFalse(client.trust_env)


if __name__ == "__main__":
    unittest.main()
