from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

from app.services.utils import ensure_utc


MAX_REPLAY_STEPS = 48


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


def compute_demo_trade_return(step_index: int, direction: str | None) -> float:
    cycle = [0.014, -0.009, 0.018, 0.011, -0.006, 0.016]
    base = cycle[step_index % len(cycle)]
    if direction == "buy":
        return round(base * 0.8, 4)
    return round(base, 4)


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
