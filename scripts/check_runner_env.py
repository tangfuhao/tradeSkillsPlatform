#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_ROOT = REPO_ROOT / "services" / "agent-runner"
if str(RUNNER_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNNER_ROOT))

from runner.services.startup_preflight import assert_startup_preflight  # noqa: E402


def main() -> int:
    try:
        assert_startup_preflight()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print("Agent Runner environment check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
