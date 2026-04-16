from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings


@dataclass(frozen=True, slots=True)
class MonthlyPartition:
    name: str
    start_ms: int
    end_ms: int


def ensure_market_candle_partitions(
    db: Session,
    *,
    months_back: int | None = None,
    months_ahead: int | None = None,
    anchor: datetime | None = None,
) -> dict[str, Any]:
    bind = db.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        return {
            "status": "skipped",
            "reason": "market candle partitions require PostgreSQL",
            "created": [],
            "partition_count": 0,
        }

    current = anchor or datetime.now(timezone.utc)
    partitions = _build_monthly_partitions(
        current,
        months_back=months_back if months_back is not None else settings.market_candle_partition_months_back,
        months_ahead=months_ahead if months_ahead is not None else settings.market_candle_partition_months_ahead,
    )

    created: list[str] = []
    for partition in partitions:
        db.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS {partition.name}
                PARTITION OF market_candles
                FOR VALUES FROM ({partition.start_ms}) TO ({partition.end_ms})
                """
            )
        )
        created.append(partition.name)

    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS market_candles_default
            PARTITION OF market_candles DEFAULT
            """
        )
    )
    db.commit()

    for partition in partitions:
        _rebalance_default_partition(db, partition)
    db.commit()

    return {
        "status": "ok",
        "created": created,
        "partition_count": len(list_market_candle_partitions(db)),
    }


def list_market_candle_partitions(db: Session) -> list[str]:
    bind = db.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        return []

    rows = db.execute(
        text(
            """
            SELECT child.relname
            FROM pg_inherits
            JOIN pg_class parent ON pg_inherits.inhparent = parent.oid
            JOIN pg_class child ON pg_inherits.inhrelid = child.oid
            WHERE parent.relname = 'market_candles'
            ORDER BY child.relname
            """
        )
    ).scalars()
    return list(rows)


def prune_market_candle_partitions(
    db: Session,
    *,
    retention_months: int | None = None,
    now: datetime | None = None,
    drop: bool = False,
) -> dict[str, Any]:
    bind = db.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        return {"status": "skipped", "reason": "market candle retention requires PostgreSQL", "affected": []}

    current = now or datetime.now(timezone.utc)
    cutoff_month = _add_months(datetime(current.year, current.month, 1, tzinfo=timezone.utc), -(retention_months or settings.market_candle_hot_retention_months))

    affected: list[str] = []
    for partition_name in list_market_candle_partitions(db):
        partition_start = _partition_start_from_name(partition_name)
        if partition_start is None or partition_start >= cutoff_month:
            continue
        affected.append(partition_name)
        if drop:
            db.execute(text(f"DROP TABLE IF EXISTS {partition_name}"))
        else:
            db.execute(text(f"ALTER TABLE market_candles DETACH PARTITION {partition_name}"))
    db.commit()

    return {
        "status": "ok",
        "affected": affected,
        "mode": "drop" if drop else "detach",
    }


def _rebalance_default_partition(db: Session, partition: MonthlyPartition) -> None:
    db.execute(
        text(
            f"""
            INSERT INTO market_candles
            SELECT *
            FROM market_candles_default
            WHERE open_time_ms >= {partition.start_ms}
              AND open_time_ms < {partition.end_ms}
            ON CONFLICT DO NOTHING
            """
        )
    )
    db.execute(
        text(
            f"""
            DELETE FROM market_candles_default
            WHERE open_time_ms >= {partition.start_ms}
              AND open_time_ms < {partition.end_ms}
            """
        )
    )


def _build_monthly_partitions(current: datetime, *, months_back: int, months_ahead: int) -> list[MonthlyPartition]:
    current_month = datetime(current.year, current.month, 1, tzinfo=timezone.utc)
    partitions: list[MonthlyPartition] = []
    total = months_back + months_ahead + 1

    for offset in range(-months_back, months_ahead + 1):
        month_start = _add_months(current_month, offset)
        month_end = _add_months(month_start, 1)
        partitions.append(
            MonthlyPartition(
                name=f"market_candles_{month_start.year:04d}{month_start.month:02d}",
                start_ms=int(month_start.timestamp() * 1000),
                end_ms=int(month_end.timestamp() * 1000),
            )
        )

    if len(partitions) != total:
        raise RuntimeError("failed to enumerate expected candle partitions")

    return partitions


def _add_months(value: datetime, offset: int) -> datetime:
    month_index = (value.year * 12 + (value.month - 1)) + offset
    year = month_index // 12
    month = (month_index % 12) + 1
    return datetime(year, month, 1, tzinfo=timezone.utc)


def _partition_start_from_name(name: str) -> datetime | None:
    if not name.startswith("market_candles_") or name == "market_candles_default":
        return None
    suffix = name.removeprefix("market_candles_")
    if len(suffix) != 6 or not suffix.isdigit():
        return None
    return datetime(int(suffix[:4]), int(suffix[4:6]), 1, tzinfo=timezone.utc)
