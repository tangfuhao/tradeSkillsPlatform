#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / 'apps' / 'api'
VENV_PYTHON = ROOT / '.venv' / 'bin' / 'python'

if VENV_PYTHON.exists() and Path(sys.executable).resolve() != VENV_PYTHON.resolve():
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), __file__, *sys.argv[1:]])

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.core.database import SessionLocal  # noqa: E402
from app.services.market_data_sync import (  # noqa: E402
    discover_local_csv_ingestion_jobs,
    list_csv_ingestion_jobs,
    run_csv_ingestion_job,
    run_pending_csv_ingestion_jobs,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Manage PostgreSQL-backed historical CSV ingest jobs.')
    subparsers = parser.add_subparsers(dest='command', required=True)

    subparsers.add_parser('discover', help='Scan the configured historical data directory and register pending CSV jobs.')

    list_parser = subparsers.add_parser('list', help='List recent CSV ingest jobs.')
    list_parser.add_argument('--status', dest='status_filter', default=None, help='Optional job status filter.')
    list_parser.add_argument('--limit', type=int, default=20, help='Maximum jobs to return (default: 20).')

    run_pending_parser = subparsers.add_parser('run-pending', help='Run pending CSV ingest jobs in request order.')
    run_pending_parser.add_argument('--limit', type=int, default=1, help='Maximum pending jobs to run (default: 1).')
    run_pending_parser.add_argument('--runner-id', default='cli-manual', help='Runner identifier recorded on the job.')
    run_pending_parser.add_argument(
        '--skip-discover',
        action='store_true',
        help='Do not scan for new CSV files before executing pending jobs.',
    )

    run_job_parser = subparsers.add_parser('run-job', help='Run one specific CSV ingest job by id.')
    run_job_parser.add_argument('job_id', help='CSV ingest job id to execute.')
    run_job_parser.add_argument('--runner-id', default='cli-manual', help='Runner identifier recorded on the job.')

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result: Any
    with SessionLocal() as db:
        if args.command == 'discover':
            result = discover_local_csv_ingestion_jobs(db)
        elif args.command == 'list':
            result = list_csv_ingestion_jobs(db, status=args.status_filter, limit=args.limit)
        elif args.command == 'run-pending':
            result = run_pending_csv_ingestion_jobs(
                db,
                limit=args.limit,
                runner_id=args.runner_id,
                discover=not args.skip_discover,
            )
        else:
            result = run_csv_ingestion_job(db, args.job_id, runner_id=args.runner_id)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
