#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_ROOT = REPO_ROOT / "services" / "agent-runner"
if str(RUNNER_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNNER_ROOT))

from runner.config import settings  # noqa: E402
from runner.services.model_routing import get_responses_client  # noqa: E402
from runner.services.responses_payload_builder import build_responses_request_payload  # noqa: E402
from runner.services.startup_preflight import assert_startup_preflight  # noqa: E402


def main() -> int:
    assert_startup_preflight()
    client = get_responses_client(settings.openai_model)
    payload = build_responses_request_payload(
        model_name=settings.openai_model,
        conversation_items=[
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Reply with OK only."}],
            }
        ],
        system_prompt="",
        tools=[],
        stream=False,
    )
    response = client.responses.create(**payload)
    output_text = str(getattr(response, "output_text", "") or "").strip()
    print(f"provider_smoke_status=ok model={settings.openai_model}")
    print(f"provider_smoke_output={output_text}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"provider_smoke_status=error {exc}", file=sys.stderr)
        raise SystemExit(1)
