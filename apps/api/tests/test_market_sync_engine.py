from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import MarketCandle, MarketInstrument, MarketSyncState
from app.runtime.market_sync_loop import MarketSyncLoopManager
from app.services.market_data_store import get_market_overview, get_market_sync_status, list_market_universe
from app.services.market_data_sync import get_fresh_market_symbols_for_dispatch, recompute_market_coverage_snapshot
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

    def tearDown(self) -> None:
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

    def _seed_candle(self, db, *, open_time: datetime, market_symbol: str = "BTC-USDT-SWAP", source: str = "csv") -> None:
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
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.5,
                vol=1.0,
                vol_ccy=1.0,
                vol_quote=100.5,
                confirm=True,
                is_old_contract=False,
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


if __name__ == "__main__":
    unittest.main()
