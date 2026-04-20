from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from unittest.mock import patch

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.database import Base, bulk_operation_session
from app.models import BacktestRun, LiveSignal, LiveTask, Skill, TraceExecutionDetail
from app.services.backtest_service import BacktestService, execute_backtest_job
from app.services.execution_lifecycle import BACKTEST_STATUS_RUNNING, LIVE_STATUS_ACTIVE
from app.services.live_service import LiveTaskService, execute_live_task
from app.services.market_data_store import build_market_snapshot, fetch_candles, get_market_data_coverage_ranges
from app.services.market_data_sync import insert_candle_batch
from app.services.partitioning import ensure_market_candle_partitions


class PostgreSQLRuntimeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        url = make_url(settings.database_url)
        if url.get_backend_name() != "postgresql":
            raise unittest.SkipTest("PostgreSQL integration tests require a PostgreSQL runtime database.")

        cls.schema = f"itest_{uuid4().hex[:10]}"
        try:
            cls.admin_engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
            with cls.admin_engine.begin() as connection:
                connection.execute(text(f"CREATE SCHEMA {cls.schema}"))
            cls.engine = create_engine(
                settings.database_url,
                future=True,
                pool_pre_ping=True,
                connect_args={"options": f"-c search_path={cls.schema}"},
            )
            Base.metadata.create_all(cls.engine)
            cls.session_factory = sessionmaker(bind=cls.engine, autoflush=False, autocommit=False, future=True)
            with cls.session_factory() as db:
                ensure_market_candle_partitions(db, months_back=48, months_ahead=3)
        except SQLAlchemyError as exc:  # pragma: no cover - environment specific
            raise unittest.SkipTest(f"PostgreSQL integration tests could not initialize: {exc}") from exc

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "engine"):
            cls.engine.dispose()
        if hasattr(cls, "admin_engine"):
            with cls.admin_engine.begin() as connection:
                connection.execute(text(f"DROP SCHEMA IF EXISTS {cls.schema} CASCADE"))
            cls.admin_engine.dispose()
        super().tearDownClass()

    def setUp(self) -> None:
        self._truncate_all_tables()

    def _truncate_all_tables(self) -> None:
        table_names = ", ".join(table.name for table in reversed(Base.metadata.sorted_tables))
        with self.session_factory() as db:
            db.execute(text(f"TRUNCATE TABLE {table_names} CASCADE"))
            db.commit()

    def create_skill(self, *, title: str = "Momentum Skill", cadence: str = "15m") -> Skill:
        with self.session_factory() as db:
            skill = Skill(
                id=self.make_id("skill"),
                title=title,
                raw_text=f"# {title}\n\nRun every {cadence}.",
                source_hash=f"sha256:{uuid4().hex}",
                validation_status="passed",
                envelope_json={"trigger": {"value": cadence}},
                validation_errors_json=[],
                validation_warnings_json=[],
            )
            db.add(skill)
            db.commit()
            db.refresh(skill)
            return skill

    def make_id(self, prefix: str) -> str:
        return f"{prefix}-{uuid4().hex[:10]}"

    def count_rows(self, model, *criteria) -> int:
        with self.session_factory() as db:
            query = select(func.count()).select_from(model)
            if criteria:
                query = query.where(*criteria)
            return int(db.scalar(query) or 0)

    def test_market_candle_stage_insert_and_sql_reads_on_postgresql(self) -> None:
        start_time = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        batch = []
        for offset in range(600):
            open_time = start_time + timedelta(minutes=offset)
            open_price = 100.0 + offset
            batch.append(
                {
                    "exchange": "okx",
                    "market_symbol": "BTC-USDT-SWAP",
                    "base_symbol": "BTC-USDT-SWAP",
                    "quote_asset": "USDT",
                    "instrument_type": "SWAP",
                    "timeframe": "1m",
                    "open_time_ms": int(open_time.timestamp() * 1000),
                    "open": open_price,
                    "high": open_price + 1.0,
                    "low": open_price - 1.0,
                    "close": open_price + 0.5,
                    "vol": 1.0,
                    "vol_ccy": 1.0,
                    "vol_quote": open_price + 0.5,
                    "confirm": True,
                    "is_old_contract": False,
                    "source": "migration_test",
                    "created_at": open_time,
                    "updated_at": open_time,
                }
            )

        with self.session_factory() as db:
            inserted = insert_candle_batch(db, batch)
            self.assertEqual(inserted, 600)

        with self.session_factory() as db:
            candles = fetch_candles(
                db,
                market_symbol="BTC-USDT-SWAP",
                timeframe="15m",
                limit=2,
                end_time=start_time + timedelta(minutes=599),
            )
            self.assertEqual(len(candles), 2)
            self.assertTrue(all(item["timeframe"] == "15m" for item in candles))
            self.assertTrue(all(item["source"] == "aggregated" for item in candles))
            self.assertEqual(candles[-1]["open_time_ms"], int((start_time + timedelta(minutes=585)).timestamp() * 1000))

            snapshot = build_market_snapshot(db, as_of=start_time + timedelta(minutes=599), limit=5)
            self.assertEqual(snapshot["source"], "historical_db")
            self.assertEqual(snapshot["market_candidates"][0]["symbol"], "BTC-USDT-SWAP")

            coverage_ranges = get_market_data_coverage_ranges(db)
            self.assertEqual(len(coverage_ranges), 1)
            self.assertEqual(int(coverage_ranges[0][0].timestamp() * 1000), int(start_time.timestamp() * 1000))

    def test_bulk_operation_session_overrides_low_statement_timeout(self) -> None:
        with self.session_factory() as db:
            db.execute(text("SET LOCAL statement_timeout = 10"))
            with bulk_operation_session(db):
                db.execute(text("SELECT pg_sleep(0.05)"))
            db.rollback()

    def test_live_slot_claim_is_idempotent_on_postgresql(self) -> None:
        skill = self.create_skill(title="Live PG Idempotency")
        response_payload = {
            "decision": {"action": "skip"},
            "reasoning_summary": "Keep the current position.",
            "tool_calls": [],
            "provider": "mock-runner",
        }

        with self.session_factory() as db:
            task_id = LiveTaskService(db).create_task(skill.id)["id"]

        with (
            patch("app.services.live_service.SessionLocal", self.session_factory),
            patch(
                "app.services.live_service.build_market_snapshot_for_live",
                return_value={"market_candidates": [{"symbol": "BTC-USDT-SWAP"}], "provider": "mock-provider"},
            ),
            patch(
                "app.services.live_service.execute_agent_run_with_recovery",
                return_value=(response_payload, {"attempt_count": 1, "recovered": False, "retry_count": 0}),
            ),
        ):
            first_signal = execute_live_task(task_id, slot_as_of_ms=1_710_010_000_000, raise_on_reject=True)
            second_signal = execute_live_task(task_id, slot_as_of_ms=1_710_010_000_000, raise_on_reject=True)

        self.assertIsNotNone(first_signal)
        self.assertIsNotNone(second_signal)
        assert first_signal is not None and second_signal is not None
        self.assertEqual(first_signal["id"], second_signal["id"])
        self.assertEqual(self.count_rows(LiveSignal, LiveSignal.live_task_id == task_id), 1)

        with self.session_factory() as db:
            task = db.get(LiveTask, task_id)
            self.assertIsNotNone(task)
            assert task is not None
            self.assertEqual(task.status, LIVE_STATUS_ACTIVE)
            self.assertEqual(task.last_completed_slot_as_of_ms, 1_710_010_000_000)

    def test_backtest_revision_conflict_is_enforced_on_postgresql(self) -> None:
        skill = self.create_skill(title="Backtest PG Revision Guard")
        start_time = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        end_time = start_time + timedelta(minutes=30)
        trigger_times = [start_time, start_time + timedelta(minutes=15)]

        with (
            patch(
                "app.services.backtest_service.get_market_overview_coverage_ranges",
                return_value=[(start_time - timedelta(days=1), end_time + timedelta(days=1))],
            ),
            patch("app.services.backtest_service.build_trigger_times", return_value=(trigger_times, False)),
        ):
            with self.session_factory() as db:
                created = BacktestService(db).create_run(skill.id, start_time, end_time, 10_000.0)
                run_id = created["id"]
                revision = created["revision"]

        with self.session_factory() as db:
            paused, _ = BacktestService(db).control_run(run_id, "pause", expected_revision=revision)
            self.assertEqual(paused["status"], "paused")

        with self.session_factory() as db:
            with self.assertRaisesRegex(ValueError, "revision conflict"):
                BacktestService(db).control_run(run_id, "resume", expected_revision=revision)

    def test_backtest_claim_guard_prevents_duplicate_worker_pickup_on_postgresql(self) -> None:
        skill = self.create_skill(title="Backtest PG Claim Guard")
        start_time = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        end_time = start_time + timedelta(minutes=30)
        trigger_times = [start_time, start_time + timedelta(minutes=15)]

        with (
            patch(
                "app.services.backtest_service.get_market_overview_coverage_ranges",
                return_value=[(start_time - timedelta(days=1), end_time + timedelta(days=1))],
            ),
            patch("app.services.backtest_service.build_trigger_times", return_value=(trigger_times, False)),
            patch("app.services.backtest_service.SessionLocal", self.session_factory),
        ):
            with self.session_factory() as db:
                run_id = BacktestService(db).create_run(skill.id, start_time, end_time, 10_000.0)["id"]
                run = db.get(BacktestRun, run_id)
                self.assertIsNotNone(run)
                assert run is not None
                run.status = BACKTEST_STATUS_RUNNING
                run.claim_owner = "other-worker"
                run.claim_token = "busy-claim"
                run.claim_acquired_at = datetime.now(timezone.utc)
                run.claim_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
                db.add(run)
                db.commit()

            execute_backtest_job(run_id)

        self.assertEqual(self.count_rows(TraceExecutionDetail), 0)
        self.assertEqual(self.count_rows(BacktestRun, BacktestRun.id == run_id), 1)


if __name__ == "__main__":
    unittest.main()
