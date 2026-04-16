from __future__ import annotations

import threading


_TASK_LOCKS: dict[str, threading.Lock] = {}
_TASK_LOCKS_GUARD = threading.Lock()


def try_acquire_live_task_execution(task_id: str) -> threading.Lock | None:
    with _TASK_LOCKS_GUARD:
        lock = _TASK_LOCKS.setdefault(task_id, threading.Lock())
    if not lock.acquire(blocking=False):
        return None
    return lock


def release_live_task_execution(lock: threading.Lock | None) -> None:
    if lock is None:
        return
    lock.release()


def clear_live_task_execution_lock(task_id: str) -> None:
    with _TASK_LOCKS_GUARD:
        _TASK_LOCKS.pop(task_id, None)
