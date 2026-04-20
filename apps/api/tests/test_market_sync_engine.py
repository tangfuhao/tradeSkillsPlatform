from __future__ import annotations

import json
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import CsvIngestionJob, MarketCandle, MarketInstrument, MarketSyncState
from app.runtime.market_sync_loop import MarketSyncLoopManager
from app.services.market_data_store import (
    aggregate_rows,
    build_market_snapshot,
    fetch_candles,
    get_market_overview,
    get_market_sync_status,
    invalidate_market_overview_cache,
    list_market_universe,
    recompute_market_overview_state,
    update_market_overview_state_for_open_times,
)
from app.services.market_data_sync import (
    discover_local_csv_ingestion_jobs,
    get_fresh_market_symbols_for_dispatch,
    recompute_market_coverage_snapshot,
    run_pending_csv_ingestion_jobs,
    run_csv_ingestion_job,
)
from app.services.utils import datetime_to_ms, new_id, utc_now


class MarketSyncEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
        self.session_factory = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, future=True)
        Base.metadata.create_all(self.engine)
        invalidate_market_overview_cache()

    def tearDown(self) -> None:
        invalidate_market_overview_cache()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _seed_symbol(
        self,
        db,
        *,
        symbol: str,
        priority_tier: str,
        lifecycle_status: str = "active",
        bootstrap_status: str = "ready",
        fresh_coverage_end_ms: int | None,
        last_sync_completed_at: datetime | None = None,
        notes: dict | None = None,
    ) -> None:
        instrument = MarketInstrument(
            id=new_id("inst"),
            exchange="okx",
            instrument_id=symbol,
            base_symbol=symbol,
            quote_asset="USDT",
            instrument_type="SWAP",
            lifecycle_status=lifecycle_status,
            priority_tier=priority_tier,
            bootstrap_status=bootstrap_status,
            discovered_at=utc_now(),
            last_seen_active_at=utc_now(),
        )
        state = MarketSyncState(
            id=new_id("syncstate"),
            exchange="okx",
            base_symbol=symbol,
            timeframe="1m",
            lifecycle_status=lifecycle_status,
            priority_tier=priority_tier,
            status="completed" if fresh_coverage_end_ms is not None else "pending",
            fresh_coverage_end_ms=fresh_coverage_end_ms,
            last_synced_open_time_ms=fresh_coverage_end_ms,
            last_sync_completed_at=last_sync_completed_at,
            next_sync_due_at=utc_now() + timedelta(minutes=1),
            notes_json=notes or {},
        )
        db.add_all([instrument, state])

    def _seed_candle(
        self,
        db,
        *,
        open_time: datetime,
        market_symbol: str = "BTC-USDT-SWAP",
        source: str = "csv",
        open_price: float = 100.0,
        high_price: float = 101.0,
        low_price: float = 99.0,
        close_price: float = 100.5,
        vol: float = 1.0,
        vol_ccy: float | None = 1.0,
        vol_quote: float | None = 100.5,
        is_old_contract: bool = False,
    ) -> None:
        open_time_ms = datetime_to_ms(open_time)
        db.add(
            MarketCandle(
                exchange="okx",
                market_symbol=market_symbol,
                base_symbol=market_symbol,
                quote_asset="USDT",
                instrument_type="SWAP",
                timeframe="1m",
                open_time_ms=open_time_ms,
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                vol=vol,
                vol_ccy=vol_ccy,
                vol_quote=vol_quote,
                confirm=True,
                is_old_contract=is_old_contract,
                source=source,
            )
        )

    def test_coverage_snapshot_allows_degraded_dispatch_when_tier1_complete(self) -> None:
        dispatch_ms = int(datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc).timestamp() * 1000)
        with self.session_factory() as db:
            self._seed_symbol(db, symbol="BTC-USDT-SWAP", priority_tier="tier1", fresh_coverage_end_ms=dispatch_ms)
            for idx in range(18):
                self._seed_symbol(
                    db,
                    symbol=f"ALT{idx}-USDT-SWAP",
                    priority_tier="tier2",
                    fresh_coverage_end_ms=dispatch_ms,
                )
            self._seed_symbol(
                db,
                symbol="MISS-USDT-SWAP",
                priority_tier="tier2",
                fresh_coverage_end_ms=None,
            )
            db.commit()

            snapshot = recompute_market_coverage_snapshot(db, universe_version=123)
            gate = get_market_sync_status(db)
            fresh_symbols = get_fresh_market_symbols_for_dispatch(db, dispatch_ms)

        self.assertEqual(snapshot["dispatch_as_of_ms"], dispatch_ms)
        self.assertTrue(snapshot["degraded"])
        self.assertGreaterEqual(snapshot["coverage_ratio"], 0.95)
        self.assertEqual(gate["status"], "degraded")
        self.assertIn("BTC-USDT-SWAP", fresh_symbols)
        self.assertNotIn("MISS-USDT-SWAP", fresh_symbols)

    def test_coverage_snapshot_blocks_when_tier1_is_missing(self) -> None:
        dispatch_ms = int(datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc).timestamp() * 1000)
        with self.session_factory() as db:
            self._seed_symbol(db, symbol="BTC-USDT-SWAP", priority_tier="tier1", fresh_coverage_end_ms=None)
            for idx in range(19):
                self._seed_symbol(
                    db,
                    symbol=f"ALT{idx}-USDT-SWAP",
                    priority_tier="tier2",
                    fresh_coverage_end_ms=dispatch_ms,
                )
            db.commit()

            snapshot = recompute_market_coverage_snapshot(db, universe_version=456)
            gate = get_market_sync_status(db)

        self.assertIsNone(snapshot["dispatch_as_of_ms"])
        self.assertEqual(snapshot["blocked_reason"], "tier1_incomplete")
        self.assertEqual(gate["status"], "blocked")

    def test_market_overview_and_universe_expose_new_sync_fields(self) -> None:
        now = utc_now()
        dispatch_ms = datetime_to_ms(now) - 60_000
        with self.session_factory() as db:
            self._seed_symbol(
                db,
                symbol="BTC-USDT-SWAP",
                priority_tier="tier1",
                fresh_coverage_end_ms=dispatch_ms,
                last_sync_completed_at=now - timedelta(seconds=30),
            )
            self._seed_symbol(
                db,
                symbol="SOL-USDT-SWAP",
                priority_tier="tier2",
                bootstrap_status="pending",
                fresh_coverage_end_ms=None,
                last_sync_completed_at=now - timedelta(minutes=5),
                notes={"backfill_pending": True},
            )
            db.commit()
            recompute_market_coverage_snapshot(db, universe_version=789)
            overview = get_market_overview(db)
            universe = list_market_universe(db)

        self.assertIn("market_sync", overview)
        self.assertIn("latest_coverage_snapshot", overview)
        self.assertEqual(overview["bootstrap_pending_count"], 1)
        self.assertEqual(overview["backfill_lag_symbol_count"], 1)
        self.assertEqual(overview["sync_cursor_counts"]["total"], 2)
        self.assertEqual(overview["sync_cursor_counts"]["failed"], 0)
        self.assertEqual(overview["sync_cursor_counts"]["skipped"], 0)
        self.assertEqual(len(universe), 2)
        self.assertTrue(any(item["sync_state"] for item in universe))

    def test_market_sync_loop_manager_reads_external_worker_heartbeat(self) -> None:
        manager = MarketSyncLoopManager(session_factory=self.session_factory)

        class FakeQueue:
            def read_heartbeat(self):
                return {
                    "market_sync_loop_running": True,
                    "last_sync_started_at_ms": 10,
                    "last_sync_completed_at_ms": 20,
                    "last_sync_status": "succeeded",
                    "last_sync_error": None,
                    "last_successful_sync_completed_at_ms": 20,
                    "last_successful_coverage_end_ms": 30,
                    "universe_active_count": 100,
                    "fresh_symbol_count": 97,
                    "coverage_ratio": 0.97,
                    "degraded": True,
                    "snapshot_age_ms": 55,
                    "blocked_reason": None,
                    "missing_symbol_count": 3,
                    "universe_version": 12345,
                }

            def close(self):
                return None

        with (
            patch("app.runtime.market_sync_loop.settings.market_sync_queue_enabled", True),
            patch("app.runtime.market_sync_loop.build_market_sync_queue", return_value=FakeQueue()),
        ):
            snapshot = manager.get_snapshot()

        self.assertTrue(snapshot.market_sync_loop_running)
        self.assertEqual(snapshot.last_successful_coverage_end_ms, 30)
        self.assertEqual(snapshot.universe_active_count, 100)
        self.assertTrue(snapshot.degraded)

    def test_market_overview_uses_contiguous_coverage_ranges(self) -> None:
        with self.session_factory() as db:
            for minute in range(6):
                self._seed_candle(
                    db,
                    open_time=datetime(2023, 7, 1, 0, minute, tzinfo=timezone.utc),
                )
            for minute in range(3):
                self._seed_candle(
                    db,
                    open_time=datetime(2026, 4, 16, 0, minute, tzinfo=timezone.utc),
                    market_symbol="DOGE-USDT-SWAP",
                    source="okx_history_api",
                )
            db.commit()

            overview = get_market_overview(db)

        self.assertEqual(len(overview["coverage_ranges"]), 2)
        self.assertEqual(
            overview["coverage_ranges"][0],
            {
                "start_ms": datetime_to_ms(datetime(2023, 7, 1, 0, 0, tzinfo=timezone.utc)),
                "end_ms": datetime_to_ms(datetime(2023, 7, 1, 0, 5, tzinfo=timezone.utc)),
            },
        )
        self.assertEqual(
            overview["coverage_ranges"][1],
            {
                "start_ms": datetime_to_ms(datetime(2026, 4, 16, 0, 0, tzinfo=timezone.utc)),
                "end_ms": datetime_to_ms(datetime(2026, 4, 16, 0, 2, tzinfo=timezone.utc)),
            },
        )
        self.assertEqual(overview["coverage_start_ms"], overview["coverage_ranges"][0]["start_ms"])
        self.assertEqual(overview["coverage_end_ms"], overview["coverage_ranges"][0]["end_ms"])

    def test_market_overview_state_merges_bridged_ranges_incrementally(self) -> None:
        with self.session_factory() as db:
            for minute in (0, 1, 4, 5):
                self._seed_candle(
                    db,
                    open_time=datetime(2024, 1, 1, 0, minute, tzinfo=timezone.utc),
                )
            db.commit()
            recompute_market_overview_state(db, force=True, force_coverage_bootstrap=True)

            for minute in (2, 3):
                self._seed_candle(
                    db,
                    open_time=datetime(2024, 1, 1, 0, minute, tzinfo=timezone.utc),
                )
            db.commit()
            update_market_overview_state_for_open_times(
                db,
                [
                    datetime_to_ms(datetime(2024, 1, 1, 0, 3, tzinfo=timezone.utc)),
                    datetime_to_ms(datetime(2024, 1, 1, 0, 2, tzinfo=timezone.utc)),
                ],
                force_rebuild=True,
            )
            overview = get_market_overview(db)

        self.assertEqual(
            overview["coverage_ranges"],
            [
                {
                    "start_ms": datetime_to_ms(datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)),
                    "end_ms": datetime_to_ms(datetime(2024, 1, 1, 0, 5, tzinfo=timezone.utc)),
                }
            ],
        )
        self.assertEqual(overview["coverage_start_ms"], overview["coverage_ranges"][0]["start_ms"])
        self.assertEqual(overview["coverage_end_ms"], overview["coverage_ranges"][0]["end_ms"])

    def test_market_overview_reads_precomputed_state_without_rescanning_candles(self) -> None:
        snapshot = {
            "id": "covsnap_test",
            "active_symbol_count": 1,
            "fresh_symbol_count": 1,
            "tier1_symbol_count": 1,
            "tier1_fresh_symbol_count": 1,
            "coverage_ratio": 1.0,
            "dispatch_as_of_ms": datetime_to_ms(datetime(2024, 1, 1, 0, 2, tzinfo=timezone.utc)),
            "degraded": False,
            "blocked_reason": None,
            "missing_symbol_count": 0,
            "missing_symbols_sample": [],
            "universe_version": 1,
            "created_at_ms": datetime_to_ms(datetime(2024, 1, 1, 0, 3, tzinfo=timezone.utc)),
        }
        with self.session_factory() as db:
            self._seed_symbol(
                db,
                symbol="BTC-USDT-SWAP",
                priority_tier="tier1",
                fresh_coverage_end_ms=snapshot["dispatch_as_of_ms"],
                last_sync_completed_at=datetime(2024, 1, 1, 0, 3, tzinfo=timezone.utc),
            )
            for minute in range(3):
                self._seed_candle(
                    db,
                    open_time=datetime(2024, 1, 1, 0, minute, tzinfo=timezone.utc),
                )
            db.commit()
            recompute_market_overview_state(db, force=True, force_coverage_bootstrap=True, latest_snapshot=snapshot)
            invalidate_market_overview_cache()

            with (
                patch("app.services.market_data_store.get_market_data_coverage_ranges", side_effect=AssertionError("unexpected candle rescan")),
                patch("app.services.market_data_sync.get_latest_market_coverage_snapshot", return_value=snapshot) as latest_snapshot_mock,
            ):
                overview = get_market_overview(db)

        self.assertEqual(latest_snapshot_mock.call_count, 1)
        self.assertEqual(len(overview["coverage_ranges"]), 1)
        self.assertEqual(overview["coverage_end_ms"], snapshot["dispatch_as_of_ms"])

    def test_fetch_candles_aggregated_timeframe_matches_python_parity(self) -> None:
        end_time = datetime(2024, 1, 1, 12, 19, tzinfo=timezone.utc)
        with self.session_factory() as db:
            for minute in range(20):
                base_price = 100.0 + minute
                self._seed_candle(
                    db,
                    open_time=datetime(2024, 1, 1, 12, minute, tzinfo=timezone.utc),
                    market_symbol="BTC-USDT-SWAP",
                    open_price=base_price,
                    high_price=base_price + 2.0,
                    low_price=base_price - 1.0,
                    close_price=base_price + 0.5,
                    vol=1.0 + minute,
                    vol_ccy=2.0 + minute,
                    vol_quote=3.0 + minute,
                )
            db.commit()

            raw_rows = db.query(MarketCandle).order_by(MarketCandle.open_time_ms.asc()).all()
            expected = aggregate_rows(raw_rows, "15m")[-2:]
            actual = fetch_candles(
                db,
                market_symbol="BTC-USDT-SWAP",
                timeframe="15m",
                limit=2,
                end_time=end_time,
            )

        self.assertEqual(actual, expected)

    def test_build_market_snapshot_returns_ranked_sql_candidates(self) -> None:
        as_of = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        with self.session_factory() as db:
            for minute in range(3):
                self._seed_candle(
                    db,
                    open_time=as_of - timedelta(minutes=30 - minute),
                    market_symbol="BTC-USDT-SWAP",
                    open_price=100.0,
                    high_price=110.0,
                    low_price=99.0,
                    close_price=105.0 + minute,
                    vol=10.0,
                    vol_quote=1000.0 + minute,
                )
                self._seed_candle(
                    db,
                    open_time=as_of - timedelta(minutes=30 - minute),
                    market_symbol="ETH-USDT-SWAP",
                    open_price=50.0,
                    high_price=55.0,
                    low_price=49.0,
                    close_price=51.0 + minute,
                    vol=2.0,
                    vol_quote=100.0 + minute,
                )
            db.commit()

            snapshot = build_market_snapshot(db, as_of, limit=1)

        self.assertEqual(len(snapshot["market_candidates"]), 1)
        self.assertEqual(snapshot["market_candidates"][0]["symbol"], "BTC-USDT-SWAP")
        self.assertGreater(snapshot["market_candidates"][0]["volume_24h_usd"], 3000)
        self.assertGreater(snapshot["market_candidates"][0]["change_24h_pct"], 0)

    def test_csv_ingestion_discovery_creates_backlog_without_inserting_rows(self) -> None:
        csv_content = (
            "instrument_name,open_time,open,high,low,close,vol,vol_ccy,vol_quote,confirm\n"
            "BTC-USDT-SWAP,1713225600000,1,2,0.5,1.5,10,10,15,1\n"
        )
        with TemporaryDirectory() as tmpdir, self.session_factory() as db:
            csv_path = Path(tmpdir) / "allswap-candlesticks-test.csv"
            csv_path.write_text(csv_content, encoding="utf-8")

            with (
                patch("app.services.market_data_sync.settings.historical_data_dir", Path(tmpdir)),
                patch("app.services.market_data_sync.settings.historical_csv_glob", "allswap-candlesticks-*.csv"),
                patch("app.services.market_data_store.settings.historical_data_dir", Path(tmpdir)),
            ):
                discovery = discover_local_csv_ingestion_jobs(db)
                duplicate_discovery = discover_local_csv_ingestion_jobs(db)
                overview = get_market_overview(db)

            self.assertEqual(discovery["discovered_count"], 1)
            self.assertEqual(duplicate_discovery["discovered_count"], 0)
            self.assertEqual(overview["ingest_backlog"]["pending_count"], 1)
            self.assertEqual(len(overview["recent_csv_jobs"]), 1)
            self.assertEqual(overview["recent_csv_jobs"][0]["status"], "pending")
            self.assertEqual(db.query(CsvIngestionJob).count(), 1)
            self.assertEqual(db.query(MarketCandle).count(), 0)

    def test_run_pending_csv_ingestion_jobs_imports_rows_and_updates_backlog(self) -> None:
        csv_content = (
            "instrument_name,open_time,open,high,low,close,vol,vol_ccy,vol_quote,confirm\n"
            "BTC-USDT-SWAP,1713225600000,1,2,0.5,1.5,10,10,15,1\n"
            "ETH-USDT-SWAP,1713225660000,2,3,1.5,2.5,11,11,16,0\n"
        )
        with TemporaryDirectory() as tmpdir, self.session_factory() as db:
            csv_path = Path(tmpdir) / "allswap-candlesticks-run.csv"
            csv_path.write_text(csv_content, encoding="utf-8")

            with (
                patch("app.services.market_data_sync.settings.historical_data_dir", Path(tmpdir)),
                patch("app.services.market_data_sync.settings.historical_csv_glob", "allswap-candlesticks-*.csv"),
                patch("app.services.market_data_store.settings.historical_data_dir", Path(tmpdir)),
            ):
                discover_local_csv_ingestion_jobs(db)
                run_result = run_pending_csv_ingestion_jobs(db, limit=1, runner_id="test-runner", discover=False)
                overview = get_market_overview(db)

            self.assertEqual(run_result["completed_count"], 1)
            self.assertEqual(run_result["failed_count"], 0)
            self.assertEqual(len(run_result["jobs"]), 1)
            self.assertEqual(run_result["jobs"][0]["runner_id"], "test-runner")
            self.assertEqual(run_result["jobs"][0]["rows_seen"], 2)
            self.assertEqual(run_result["jobs"][0]["rows_staged"], 1)
            self.assertEqual(run_result["jobs"][0]["rows_inserted"], 1)
            self.assertEqual(run_result["jobs"][0]["rows_filtered"], 1)
            self.assertEqual(overview["ingest_backlog"]["pending_count"], 0)
            self.assertEqual(overview["ingest_backlog"]["completed_count"], 1)
            self.assertEqual(db.query(MarketCandle).count(), 1)

    def test_run_csv_ingestion_job_skips_duplicate_work_when_job_already_running(self) -> None:
        csv_content = (
            "instrument_name,open_time,open,high,low,close,vol,vol_ccy,vol_quote,confirm\n"
            "BTC-USDT-SWAP,1713225600000,1,2,0.5,1.5,10,10,15,1\n"
        )
        with TemporaryDirectory() as tmpdir, self.session_factory() as db:
            csv_path = Path(tmpdir) / "allswap-candlesticks-running.csv"
            csv_path.write_text(csv_content, encoding="utf-8")

            with (
                patch("app.services.market_data_sync.settings.historical_data_dir", Path(tmpdir)),
                patch("app.services.market_data_sync.settings.historical_csv_glob", "allswap-candlesticks-*.csv"),
            ):
                discovery = discover_local_csv_ingestion_jobs(db)
                job_id = discovery["jobs"][0]["id"]
                job = db.get(CsvIngestionJob, job_id)
                assert job is not None
                job.status = "running"
                job.runner_id = "other-runner"
                db.add(job)
                db.commit()

                with patch("app.services.market_data_sync._ingest_csv_file") as ingest_mock:
                    result = run_csv_ingestion_job(db, job_id, runner_id="second-runner")

            self.assertEqual(result["status"], "running")
            self.assertEqual(result["runner_id"], "other-runner")
            ingest_mock.assert_not_called()

    def test_runtime_storage_health_reports_unsupported_sqlite_without_import_crash(self) -> None:
        script = """
import json
import os
import sys

sys.path.insert(0, "apps/api")
os.environ["TRADE_SKILLS_DATABASE_URL"] = "sqlite:////tmp/tradeskills-health.db"

from app.core.schema import inspect_runtime_storage

print(json.dumps(inspect_runtime_storage()))
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd="/Users/fuhao/Documents/hackson/tradeSkills",
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "unsupported_engine")
        self.assertEqual(payload["backend"], "sqlite")


if __name__ == "__main__":
    unittest.main()
