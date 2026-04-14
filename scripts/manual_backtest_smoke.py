#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_WINDOW_MINUTES = 30
DEFAULT_TIMEOUT_SECONDS = 180
DEFAULT_POLL_SECONDS = 2.0
DEFAULT_INITIAL_CAPITAL = 10_000.0

SMOKE_SKILL_TITLE = "Manual Backtest Smoke Skill"
SMOKE_SKILL_TEXT = """# Manual Backtest Smoke Skill

## Cadence
Run every 15m.

## Workflow
1. Scan the OKX USDT swap market and inspect liquid movers.
2. Compute 15m EMA20, EMA60, RSI14, and ATR14 for one candidate before deciding.
3. Read the strategy state so the run exercises state access.
4. If the setup is unclear, return skip. If RSI is elevated and price is above EMA20 and EMA60, you may open a 5% short with a 2% stop loss and a 4% take profit.
5. Return a structured decision every cycle and never invent market data.
"""


def _request(method: str, url: str, payload: dict | None = None) -> dict | list:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed with HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{method} {url} failed: {exc}") from exc


def _find_run(api_base_url: str, run_id: str) -> dict:
    runs = _request("GET", f"{api_base_url}/api/v1/backtests")
    if not isinstance(runs, list):
        raise RuntimeError("Backtest list response is not a list.")
    for run in runs:
        if isinstance(run, dict) and run.get("id") == run_id:
            return run
    raise RuntimeError(f"Backtest {run_id} was not found in list response.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a one-off short-window historical backtest smoke check against the local API."
    )
    parser.add_argument("--api-base-url", default=DEFAULT_API_BASE_URL)
    parser.add_argument("--window-minutes", type=int, default=DEFAULT_WINDOW_MINUTES)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)
    parser.add_argument("--initial-capital", type=float, default=DEFAULT_INITIAL_CAPITAL)
    parser.add_argument("--skill-id", default="")
    parser.add_argument("--start-ms", type=int, default=0)
    parser.add_argument("--title", default=SMOKE_SKILL_TITLE)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    overview = _request("GET", f"{args.api_base_url}/api/v1/market-data/overview")
    if not isinstance(overview, dict):
        raise RuntimeError("Market overview response is not an object.")

    coverage_start_ms = overview.get("coverage_start_ms")
    coverage_end_ms = overview.get("coverage_end_ms")
    if not isinstance(coverage_start_ms, int) or not isinstance(coverage_end_ms, int):
        raise RuntimeError("No historical market coverage is available.")

    start_ms = args.start_ms or coverage_start_ms
    end_ms = min(start_ms + args.window_minutes * 60_000, coverage_end_ms)
    if end_ms <= start_ms:
        raise RuntimeError("Smoke window is empty. Adjust --start-ms or --window-minutes.")

    skill_id = args.skill_id.strip()
    if not skill_id:
        created_skill = _request(
            "POST",
            f"{args.api_base_url}/api/v1/skills",
            {"title": args.title, "skill_text": SMOKE_SKILL_TEXT},
        )
        if not isinstance(created_skill, dict) or not created_skill.get("id"):
            raise RuntimeError("Skill creation did not return an id.")
        skill_id = str(created_skill["id"])
        print(f"created skill: {skill_id}")
    else:
        print(f"using skill: {skill_id}")

    created_run = _request(
        "POST",
        f"{args.api_base_url}/api/v1/backtests",
        {
            "skill_id": skill_id,
            "start_time_ms": start_ms,
            "end_time_ms": end_ms,
            "initial_capital": args.initial_capital,
        },
    )
    if not isinstance(created_run, dict) or not created_run.get("id"):
        raise RuntimeError("Backtest creation did not return an id.")

    run_id = str(created_run["id"])
    print(f"created backtest: {run_id}")
    print(f"window_ms: {start_ms} -> {end_ms}")

    deadline = time.time() + args.timeout_seconds
    terminal_statuses = {"completed", "failed"}
    run = created_run
    while time.time() < deadline:
        run = _find_run(args.api_base_url, run_id)
        status = str(run.get("status") or "")
        print(f"backtest status: {status}")
        if status in terminal_statuses:
            break
        time.sleep(args.poll_seconds)
    else:
        raise RuntimeError(f"Backtest {run_id} did not finish within {args.timeout_seconds} seconds.")

    traces = _request("GET", f"{args.api_base_url}/api/v1/backtests/{run_id}/traces")
    if not isinstance(traces, list):
        raise RuntimeError("Trace response is not a list.")
    if not traces:
        raise RuntimeError(f"Backtest {run_id} finished without any traces.")

    serialized = json.dumps({"run": run, "traces": traces}, ensure_ascii=False)
    for marker in ("synthetic_fallback", "synthetic_cycle"):
        if marker in serialized:
            raise RuntimeError(f"Backtest {run_id} unexpectedly contains deprecated marker: {marker}")

    if run.get("status") != "completed":
        raise RuntimeError(
            f"Backtest {run_id} finished with status={run.get('status')}: {run.get('error_message')}"
        )

    print(f"trace_count: {len(traces)}")
    print(f"summary: {json.dumps(run.get('summary'), ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"manual backtest smoke failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
