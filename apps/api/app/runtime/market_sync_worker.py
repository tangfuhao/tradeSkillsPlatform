from __future__ import annotations

import logging
import socket
import time
from typing import Any

from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
from app.main import ensure_runtime_schema
from app.runtime.market_sync_queue import (
    COVERAGE_LOCK_KEY,
    LIVE_DISPATCH_LOCK_KEY,
    SCHEDULER_LOCK_KEY,
    UNIVERSE_LOCK_KEY,
    QUEUE_SYMBOL_SYNC_BACKFILL,
    QUEUE_SYMBOL_SYNC_HIGH,
    QUEUE_SYMBOL_SYNC_NORMAL,
    build_market_sync_queue,
)
from app.services.live_service import dispatch_sync_driven_live_tasks
from app.services.market_data_sync import (
    compute_live_sync_cutoff,
    get_market_sync_gate_status,
    get_previous_dispatch_as_of_ms,
    recompute_market_coverage_snapshot,
    refresh_market_universe,
    select_due_sync_states,
    sync_market_symbol,
)
from app.services.utils import datetime_to_ms, utc_now

logger = logging.getLogger(__name__)


class MarketSyncWorker:
    def __init__(self) -> None:
        self.queue = build_market_sync_queue()
        self.worker_id = f"market-sync-worker:{socket.gethostname()}:{int(time.time())}"
        self._last_status_payload: dict[str, Any] = {
            "last_sync_status": "idle",
            "last_sync_error": None,
        }
        self._last_universe_refresh_at_ms = 0

    def run_forever(self) -> None:
        logger.info("Starting market sync worker %s", self.worker_id)
        Base.metadata.create_all(bind=engine)
        ensure_runtime_schema()
        while True:
            try:
                self._scheduler_tick()
                item = self.queue.dequeue(timeout_seconds=settings.market_sync_worker_poll_seconds)
                if item is None:
                    self._write_heartbeat()
                    continue
                queue_name, payload = item
                self._handle_job(queue_name, payload)
                self._write_heartbeat()
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                logger.exception("Market sync worker loop failed: %s", exc)
                self._last_status_payload = {
                    **self._last_status_payload,
                    "last_sync_status": "failed",
                    "last_sync_error": str(exc),
                    "last_sync_completed_at_ms": datetime_to_ms(utc_now()),
                }
                self._write_heartbeat()
                time.sleep(max(settings.market_sync_worker_poll_seconds, 1.0))

    def _scheduler_tick(self) -> None:
        now = utc_now()
        now_ms = datetime_to_ms(now)
        if now_ms - self._last_universe_refresh_at_ms >= int(settings.market_universe_refresh_interval_seconds * 1000):
            if self.queue.acquire_singleton(UNIVERSE_LOCK_KEY, ttl_seconds=max(int(settings.market_universe_refresh_interval_seconds), 1)):
                self.queue.enqueue_universe_refresh()
                self._last_universe_refresh_at_ms = now_ms

        if not self.queue.acquire_singleton(SCHEDULER_LOCK_KEY, ttl_seconds=max(int(settings.market_sync_schedule_interval_seconds), 1)):
            return

        with SessionLocal() as db:
            due_states = select_due_sync_states(db, now=now)
        for state in due_states[: settings.market_sync_cycle_symbol_limit]:
            queue_name = _queue_name_for_tier(state.priority_tier)
            self.queue.enqueue_symbol_sync(
                base_symbol=state.base_symbol,
                queue_name=queue_name,
                priority_tier=state.priority_tier,
            )

    def _handle_job(self, queue_name: str, payload: dict[str, Any]) -> None:
        del queue_name
        job_type = payload.get("job_type")
        started_at_ms = datetime_to_ms(utc_now())
        if job_type == "universe_refresh":
            with SessionLocal() as db:
                refresh_market_universe(db, universe_version=started_at_ms)
            self.queue.enqueue_coverage_aggregate()
            self._last_status_payload = {
                **self._last_status_payload,
                "last_sync_started_at_ms": started_at_ms,
                "last_sync_completed_at_ms": datetime_to_ms(utc_now()),
                "last_sync_status": "succeeded",
                "last_sync_error": None,
            }
            return

        if job_type == "symbol_sync":
            base_symbol = str(payload.get("base_symbol") or "")
            if not base_symbol:
                return
            with SessionLocal() as db:
                result = sync_market_symbol(db, base_symbol, cutoff_ms=datetime_to_ms(compute_live_sync_cutoff()))
                gate_status = get_market_sync_gate_status(db)
            self.queue.enqueue_coverage_aggregate()
            self._last_status_payload = {
                **self._last_status_payload,
                "last_sync_started_at_ms": started_at_ms,
                "last_sync_completed_at_ms": datetime_to_ms(utc_now()),
                "last_sync_status": "succeeded" if result.get("status") == "completed" else "failed",
                "last_sync_error": (result.get("failure") or {}).get("message"),
                "last_successful_sync_completed_at_ms": datetime_to_ms(utc_now()) if result.get("status") == "completed" else self._last_status_payload.get("last_successful_sync_completed_at_ms"),
                "last_successful_coverage_end_ms": gate_status.get("dispatch_as_of_ms") or self._last_status_payload.get("last_successful_coverage_end_ms"),
            }
            return

        if job_type == "coverage_aggregate":
            if not self.queue.acquire_singleton(COVERAGE_LOCK_KEY, ttl_seconds=5):
                return
            with SessionLocal() as db:
                previous_dispatch_ms = get_previous_dispatch_as_of_ms(db)
                snapshot = recompute_market_coverage_snapshot(db, universe_version=started_at_ms)
            dispatch_as_of_ms = snapshot.get("dispatch_as_of_ms")
            if dispatch_as_of_ms is not None and dispatch_as_of_ms != previous_dispatch_ms:
                self.queue.enqueue_live_dispatch(int(dispatch_as_of_ms))
            self._last_status_payload = {
                **self._last_status_payload,
                "last_sync_started_at_ms": started_at_ms,
                "last_sync_completed_at_ms": datetime_to_ms(utc_now()),
                "last_sync_status": "succeeded" if dispatch_as_of_ms is not None else "blocked",
                "last_sync_error": snapshot.get("blocked_reason"),
                "last_successful_sync_completed_at_ms": datetime_to_ms(utc_now()) if dispatch_as_of_ms is not None else self._last_status_payload.get("last_successful_sync_completed_at_ms"),
                "last_successful_coverage_end_ms": dispatch_as_of_ms or self._last_status_payload.get("last_successful_coverage_end_ms"),
            }
            return

        if job_type == "live_dispatch":
            if not self.queue.acquire_singleton(LIVE_DISPATCH_LOCK_KEY, ttl_seconds=5):
                return
            dispatch_as_of_ms = int(payload.get("dispatch_as_of_ms") or 0)
            if dispatch_as_of_ms <= 0:
                return
            dispatch_sync_driven_live_tasks(dispatch_as_of_ms)
            self._last_status_payload = {
                **self._last_status_payload,
                "last_sync_started_at_ms": started_at_ms,
                "last_sync_completed_at_ms": datetime_to_ms(utc_now()),
                "last_sync_status": "succeeded",
                "last_sync_error": None,
                "last_successful_sync_completed_at_ms": datetime_to_ms(utc_now()),
                "last_successful_coverage_end_ms": dispatch_as_of_ms,
            }
            return

    def _write_heartbeat(self) -> None:
        with SessionLocal() as db:
            gate_status = get_market_sync_gate_status(db)
        self.queue.write_heartbeat(
            worker_id=self.worker_id,
            payload={
                **self._last_status_payload,
                "market_sync_loop_running": True,
                "universe_active_count": gate_status.get("universe_active_count", 0),
                "fresh_symbol_count": gate_status.get("fresh_symbol_count", 0),
                "coverage_ratio": gate_status.get("coverage_ratio", 0.0),
                "degraded": gate_status.get("degraded", False),
                "snapshot_age_ms": gate_status.get("snapshot_age_ms"),
                "blocked_reason": gate_status.get("blocked_reason"),
                "missing_symbol_count": gate_status.get("missing_symbol_count", 0),
                "universe_version": gate_status.get("universe_version"),
            },
        )


def _queue_name_for_tier(priority_tier: str) -> str:
    if priority_tier == "tier1":
        return QUEUE_SYMBOL_SYNC_HIGH
    if priority_tier == "tier2":
        return QUEUE_SYMBOL_SYNC_NORMAL
    return QUEUE_SYMBOL_SYNC_BACKFILL


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[market-sync-worker] %(message)s")
    worker = MarketSyncWorker()
    worker.run_forever()


if __name__ == "__main__":
    main()
