from __future__ import annotations

import json
import socket
import time
from typing import Any

from redis import Redis

from app.core.config import settings
from app.services.utils import datetime_to_ms, utc_now

QUEUE_UNIVERSE_REFRESH = "market-sync:queue:universe-refresh"
QUEUE_SYMBOL_SYNC_HIGH = "market-sync:queue:symbol-sync-high"
QUEUE_SYMBOL_SYNC_NORMAL = "market-sync:queue:symbol-sync-normal"
QUEUE_SYMBOL_SYNC_BACKFILL = "market-sync:queue:symbol-sync-backfill"
QUEUE_COVERAGE_AGGREGATE = "market-sync:queue:coverage-aggregate"
QUEUE_LIVE_DISPATCH = "market-sync:queue:live-dispatch"

QUEUE_PRIORITY = [
    QUEUE_SYMBOL_SYNC_HIGH,
    QUEUE_SYMBOL_SYNC_NORMAL,
    QUEUE_SYMBOL_SYNC_BACKFILL,
    QUEUE_COVERAGE_AGGREGATE,
    QUEUE_LIVE_DISPATCH,
    QUEUE_UNIVERSE_REFRESH,
]

HEARTBEAT_KEY = "market-sync:worker:heartbeat"
UNIVERSE_LOCK_KEY = "market-sync:singleton:universe-refresh"
SCHEDULER_LOCK_KEY = "market-sync:singleton:scheduler"
COVERAGE_LOCK_KEY = "market-sync:singleton:coverage-aggregate"
LIVE_DISPATCH_LOCK_KEY = "market-sync:singleton:live-dispatch"


class MarketSyncQueue:
    def __init__(self, redis_client: Redis | None = None) -> None:
        self._redis = redis_client or Redis.from_url(settings.market_sync_redis_url, decode_responses=True)

    @property
    def redis(self) -> Redis:
        return self._redis

    def enqueue(self, queue_name: str, payload: dict[str, Any], *, dedupe_key: str | None = None, ttl_seconds: int = 300) -> bool:
        if dedupe_key:
            dedupe_key_name = f"market-sync:dedupe:{dedupe_key}"
            if not self._redis.set(dedupe_key_name, "1", nx=True, ex=ttl_seconds):
                return False
        envelope = json.dumps(payload)
        self._redis.rpush(queue_name, envelope)
        return True

    def dequeue(self, timeout_seconds: int | float | None = None) -> tuple[str, dict[str, Any]] | None:
        timeout = int(timeout_seconds or settings.market_sync_worker_poll_seconds)
        item = self._redis.blpop(QUEUE_PRIORITY, timeout=timeout)
        if item is None:
            return None
        queue_name, raw_payload = item
        return queue_name, json.loads(raw_payload)

    def acquire_singleton(self, key: str, *, ttl_seconds: int) -> bool:
        return bool(self._redis.set(key, str(datetime_to_ms(utc_now())), nx=True, ex=ttl_seconds))

    def enqueue_universe_refresh(self) -> bool:
        return self.enqueue(
            QUEUE_UNIVERSE_REFRESH,
            {"job_type": "universe_refresh", "enqueued_at_ms": datetime_to_ms(utc_now())},
            dedupe_key="universe-refresh",
            ttl_seconds=max(int(settings.market_universe_refresh_interval_seconds), 1),
        )

    def enqueue_coverage_aggregate(self) -> bool:
        return self.enqueue(
            QUEUE_COVERAGE_AGGREGATE,
            {"job_type": "coverage_aggregate", "enqueued_at_ms": datetime_to_ms(utc_now())},
            dedupe_key="coverage-aggregate",
            ttl_seconds=15,
        )

    def enqueue_live_dispatch(self, dispatch_as_of_ms: int) -> bool:
        return self.enqueue(
            QUEUE_LIVE_DISPATCH,
            {
                "job_type": "live_dispatch",
                "dispatch_as_of_ms": dispatch_as_of_ms,
                "enqueued_at_ms": datetime_to_ms(utc_now()),
            },
            dedupe_key=f"live-dispatch:{dispatch_as_of_ms}",
            ttl_seconds=180,
        )

    def enqueue_symbol_sync(self, *, base_symbol: str, queue_name: str, priority_tier: str) -> bool:
        return self.enqueue(
            queue_name,
            {
                "job_type": "symbol_sync",
                "base_symbol": base_symbol,
                "priority_tier": priority_tier,
                "enqueued_at_ms": datetime_to_ms(utc_now()),
            },
            dedupe_key=f"symbol-sync:{base_symbol}",
            ttl_seconds=60,
        )

    def write_heartbeat(self, *, worker_id: str, payload: dict[str, Any]) -> None:
        heartbeat_payload = {
            "worker_id": worker_id,
            "heartbeat_at_ms": datetime_to_ms(utc_now()),
            **payload,
        }
        self._redis.set(
            HEARTBEAT_KEY,
            json.dumps(heartbeat_payload),
            ex=max(int(settings.market_sync_worker_heartbeat_ttl_seconds), 1),
        )

    def read_heartbeat(self) -> dict[str, Any] | None:
        payload = self._redis.get(HEARTBEAT_KEY)
        if not payload:
            return None
        return json.loads(payload)

    def close(self) -> None:
        try:
            self._redis.close()
        except Exception:
            pass


class MarketSyncQueueUnavailable:
    def __init__(self) -> None:
        self._worker_id = f"local-{socket.gethostname()}"

    def enqueue_universe_refresh(self) -> bool:
        return False

    def enqueue_coverage_aggregate(self) -> bool:
        return False

    def enqueue_live_dispatch(self, dispatch_as_of_ms: int) -> bool:
        del dispatch_as_of_ms
        return False

    def enqueue_symbol_sync(self, *, base_symbol: str, queue_name: str, priority_tier: str) -> bool:
        del base_symbol, queue_name, priority_tier
        return False

    def write_heartbeat(self, *, worker_id: str, payload: dict[str, Any]) -> None:
        del worker_id, payload

    def read_heartbeat(self) -> dict[str, Any] | None:
        return {
            "worker_id": self._worker_id,
            "heartbeat_at_ms": datetime_to_ms(utc_now()),
        }

    def acquire_singleton(self, key: str, *, ttl_seconds: int) -> bool:
        del key, ttl_seconds
        return True

    def close(self) -> None:
        return None


def build_market_sync_queue() -> MarketSyncQueue | MarketSyncQueueUnavailable:
    if not settings.market_sync_queue_enabled:
        return MarketSyncQueueUnavailable()
    return MarketSyncQueue()
