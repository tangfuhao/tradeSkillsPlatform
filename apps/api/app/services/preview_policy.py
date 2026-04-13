from __future__ import annotations

from datetime import datetime, timedelta

from app.core.config import settings
from app.services.utils import ensure_utc, utc_now


def get_preview_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    current = ensure_utc(now or utc_now())
    start = current - timedelta(days=settings.preview_window_days)
    return start, current


def determine_scope(review_status: str, start_time: datetime, end_time: datetime) -> str:
    validate_window(review_status, start_time, end_time)
    return "approved" if review_status == "approved_full_window" else "preview"


def validate_window(review_status: str, start_time: datetime, end_time: datetime) -> None:
    start = ensure_utc(start_time)
    end = ensure_utc(end_time)
    if end <= start:
        raise ValueError("end_time must be later than start_time")
    if review_status == "approved_full_window":
        return
    preview_start, preview_end = get_preview_window()
    if start < preview_start or end > preview_end:
        raise ValueError(
            "Requested window exceeds preview scope. Approve the Skill for a larger history window first."
        )
