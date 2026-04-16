from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, replace
from typing import Any, Callable

from app.core.config import settings
from app.core.database import SessionLocal
from app.runtime.market_sync_queue import build_market_sync_queue
from app.services.market_data_sync import (
    MarketSyncSweepResult,
    compute_live_sync_cutoff,
    get_latest_market_coverage_snapshot,
    sync_incremental_okx_history,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MarketSyncLoopSnapshot:
    market_sync_loop_running: bool = False
    last_sync_started_at_ms: int | None = None
    last_sync_completed_at_ms: int | None = None
    last_sync_status: str | None = None
    last_sync_error: str | None = None
    last_successful_sync_completed_at_ms: int | None = None
    last_successful_coverage_end_ms: int | None = None
    universe_active_count: int = 0
    fresh_symbol_count: int = 0
    coverage_ratio: float = 0.0
    degraded: bool = False
    snapshot_age_ms: int | None = None
    blocked_reason: str | None = None
    missing_symbol_count: int = 0
    universe_version: int | None = None


class MarketSyncLoopManager:
    def __init__(
        self,
        *,
        session_factory: Callable[[], Any] = SessionLocal,
        interval_seconds: float | None = None,
        sync_runner: Callable[[Any], MarketSyncSweepResult] | None = None,
        dispatcher: Callable[[int], list[dict[str, Any]]] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._interval_seconds = interval_seconds or settings.market_sync_loop_interval_seconds
        self._sync_runner = sync_runner or self._default_sync_runner
        self._dispatcher = dispatcher or self._default_dispatcher
        self._state_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._snapshot = MarketSyncLoopSnapshot()

    def start(self) -> None:
        if settings.market_sync_queue_enabled:
            with self._state_lock:
                self._snapshot = replace(self._snapshot, market_sync_loop_running=False)
            return
        with self._state_lock:
            if self._snapshot.market_sync_loop_running:
                return
            self._stop_event.clear()
            self._snapshot = replace(self._snapshot, market_sync_loop_running=True)
            self._thread = threading.Thread(
                target=self._run_loop,
                name="market-sync-loop",
                daemon=True,
            )
            self._thread.start()

    def shutdown(self) -> None:
        if settings.market_sync_queue_enabled:
            with self._state_lock:
                self._snapshot = replace(self._snapshot, market_sync_loop_running=False)
            return
        with self._state_lock:
            if not self._snapshot.market_sync_loop_running:
                return
            thread = self._thread
            self._stop_event.set()
            self._snapshot = replace(self._snapshot, market_sync_loop_running=False)
        if thread is not None:
            thread.join(timeout=max(self._interval_seconds, 1.0) + 5.0)

    def get_snapshot(self) -> MarketSyncLoopSnapshot:
        if settings.market_sync_queue_enabled:
            try:
                queue = build_market_sync_queue()
                heartbeat = queue.read_heartbeat()
                queue.close()
            except Exception:
                logger.exception("Failed to read market sync worker heartbeat.")
                with self._state_lock:
                    return replace(self._snapshot, market_sync_loop_running=False, last_sync_status="failed")
            with self._state_lock:
                if heartbeat is None:
                    return replace(self._snapshot, market_sync_loop_running=False)
                external_snapshot = replace(
                    self._snapshot,
                    market_sync_loop_running=True,
                    last_sync_started_at_ms=heartbeat.get("last_sync_started_at_ms"),
                    last_sync_completed_at_ms=heartbeat.get("last_sync_completed_at_ms"),
                    last_sync_status=heartbeat.get("last_sync_status"),
                    last_sync_error=heartbeat.get("last_sync_error"),
                    last_successful_sync_completed_at_ms=heartbeat.get("last_successful_sync_completed_at_ms"),
                    last_successful_coverage_end_ms=heartbeat.get("last_successful_coverage_end_ms"),
                    universe_active_count=int(heartbeat.get("universe_active_count") or 0),
                    fresh_symbol_count=int(heartbeat.get("fresh_symbol_count") or 0),
                    coverage_ratio=float(heartbeat.get("coverage_ratio") or 0.0),
                    degraded=bool(heartbeat.get("degraded") or False),
                    snapshot_age_ms=heartbeat.get("snapshot_age_ms"),
                    blocked_reason=heartbeat.get("blocked_reason"),
                    missing_symbol_count=int(heartbeat.get("missing_symbol_count") or 0),
                    universe_version=heartbeat.get("universe_version"),
                )
                self._snapshot = external_snapshot
                return replace(self._snapshot)
        with self._state_lock:
            return replace(self._snapshot)

    def record_sync_result(self, result: MarketSyncSweepResult) -> MarketSyncLoopSnapshot:
        with self._state_lock:
            next_snapshot = replace(
                self._snapshot,
                last_sync_started_at_ms=result.started_at_ms,
                last_sync_completed_at_ms=result.completed_at_ms,
                last_sync_status=result.status,
                last_sync_error=result.error_message,
            )
            if result.is_healthy():
                next_snapshot = replace(
                    next_snapshot,
                    last_successful_sync_completed_at_ms=result.completed_at_ms,
                    last_successful_coverage_end_ms=result.coverage_end_ms_after,
                )
            next_snapshot = replace(
                next_snapshot,
                universe_active_count=result.universe_active_count,
                fresh_symbol_count=result.fresh_symbol_count,
                coverage_ratio=result.coverage_ratio,
                degraded=result.degraded,
                snapshot_age_ms=result.snapshot_age_ms,
                blocked_reason=result.blocked_reason,
                missing_symbol_count=result.missing_symbol_count,
                universe_version=result.universe_version,
            )
            self._snapshot = next_snapshot
            return replace(self._snapshot)

    def run_cycle_once(self) -> MarketSyncSweepResult:
        result = self._run_sync_cycle()
        self.record_sync_result(result)
        if result.is_dispatchable() and result.coverage_end_ms_after is not None:
            try:
                dispatch_results = self._dispatcher(result.coverage_end_ms_after)
                logger.info(
                    "Market sync dispatch finished for coverage_end_ms=%s tasks=%s",
                    result.coverage_end_ms_after,
                    len(dispatch_results),
                )
            except Exception:
                logger.exception("Market sync dispatch failed after a successful sync sweep.")
        return result

    def dispatch_current_coverage(self) -> list[dict[str, Any]]:
        with self._session_factory() as db:
            snapshot = get_latest_market_coverage_snapshot(db)
        if snapshot is None or snapshot.get("dispatch_as_of_ms") is None:
            return []
        return self._dispatcher(int(snapshot["dispatch_as_of_ms"]))

    def _run_loop(self) -> None:
        while not self._stop_event.wait(self._interval_seconds):
            try:
                self.run_cycle_once()
            except Exception:
                logger.exception("Market sync loop cycle failed unexpectedly.")

    @staticmethod
    def _default_sync_runner(db: Any) -> MarketSyncSweepResult:
        return sync_incremental_okx_history(db, cutoff=compute_live_sync_cutoff())

    @staticmethod
    def _default_dispatcher(coverage_end_ms: int) -> list[dict[str, Any]]:
        from app.services.live_service import dispatch_sync_driven_live_tasks

        return dispatch_sync_driven_live_tasks(coverage_end_ms)

    def _run_sync_cycle(self) -> MarketSyncSweepResult:
        with self._session_factory() as db:
            return self._sync_runner(db)


market_sync_loop_manager = MarketSyncLoopManager()
