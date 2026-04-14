from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

from app.services.utils import ensure_utc


# Keep replay bounds high enough to cover a full day of 15m bars in local dev.
MAX_REPLAY_STEPS = 512


def cadence_to_seconds(cadence: str) -> int:
    amount = int(cadence[:-1])
    unit = cadence[-1].lower()
    if unit == "m":
        return amount * 60
    if unit == "h":
        return amount * 60 * 60
    if unit == "d":
        return amount * 60 * 60 * 24
    raise ValueError(f"Unsupported cadence: {cadence}")


def build_trigger_times(start_time: datetime, end_time: datetime, cadence: str) -> tuple[list[datetime], bool]:
    start = ensure_utc(start_time)
    end = ensure_utc(end_time)
    step = timedelta(seconds=cadence_to_seconds(cadence))
    points: list[datetime] = []
    cursor = start
    while cursor <= end:
        points.append(cursor)
        cursor += step
        if len(points) >= MAX_REPLAY_STEPS:
            return points, True
    return points, False
def compute_max_drawdown(equity_curve: Iterable[float]) -> float:
    peak = 0.0
    max_drawdown = 0.0
    for equity in equity_curve:
        if equity > peak:
            peak = equity
        if peak <= 0:
            continue
        drawdown = (peak - equity) / peak
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    return round(max_drawdown, 4)
