from __future__ import annotations

import httpx


def build_internal_http_client(*, timeout: float) -> httpx.Client:
    # Internal service-to-service traffic must bypass system proxy discovery.
    return httpx.Client(timeout=timeout, trust_env=False)
