#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"

if VENV_PYTHON.exists() and Path(sys.executable).resolve() != VENV_PYTHON.resolve():
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), __file__, *sys.argv[1:]])

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.core.database import SessionLocal  # noqa: E402
from app.core.schema import inspect_runtime_storage  # noqa: E402
from app.services.partitioning import (  # noqa: E402
    ensure_market_candle_partitions,
    list_market_candle_partitions,
    prune_market_candle_partitions,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect and maintain the PostgreSQL runtime storage.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("health", help="Print runtime storage compatibility and pool diagnostics.")

    list_parser = subparsers.add_parser("partitions-list", help="List market_candles partitions.")
    list_parser.add_argument("--as-json", action="store_true", help="Return the partition list as a JSON object.")

    ensure_parser = subparsers.add_parser("partitions-ensure", help="Create or rebalance market_candles partitions.")
    ensure_parser.add_argument("--months-back", type=int, default=None, help="Months of historical partitions to keep.")
    ensure_parser.add_argument("--months-ahead", type=int, default=None, help="Months of future partitions to pre-create.")

    prune_parser = subparsers.add_parser("partitions-prune", help="Detach or drop old market_candles partitions.")
    prune_parser.add_argument(
        "--retention-months",
        type=int,
        default=None,
        help="Hot retention window in months before partitions are detached or dropped.",
    )
    prune_parser.add_argument(
        "--drop",
        action="store_true",
        help="Drop old partitions instead of detaching them from the parent table.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.command == "health":
        result: Any = inspect_runtime_storage()
    else:
        with SessionLocal() as db:
            if args.command == "partitions-list":
                partitions = list_market_candle_partitions(db)
                result = {"market_candle_partitions": partitions} if args.as_json else partitions
            elif args.command == "partitions-ensure":
                result = ensure_market_candle_partitions(
                    db,
                    months_back=args.months_back,
                    months_ahead=args.months_ahead,
                )
            else:
                result = prune_market_candle_partitions(
                    db,
                    retention_months=args.retention_months,
                    drop=args.drop,
                )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
