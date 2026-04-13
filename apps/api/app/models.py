from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Skill(Base):
    __tablename__ = "skills"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    raw_text: Mapped[str] = mapped_column(Text())
    source_hash: Mapped[str] = mapped_column(String(128), index=True)
    validation_status: Mapped[str] = mapped_column(String(32), default="pending")
    review_status: Mapped[str] = mapped_column(String(32), default="pending_validation")
    envelope_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    validation_errors_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    validation_warnings_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    backtests: Mapped[list[BacktestRun]] = relationship(back_populates="skill")
    live_tasks: Mapped[list[LiveTask]] = relationship(back_populates="skill")
    strategy_state: Mapped[StrategyState | None] = relationship(back_populates="skill", uselist=False)


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    scope: Mapped[str] = mapped_column(String(32), default="preview")
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    initial_capital: Mapped[float] = mapped_column(Float)
    benchmark_name: Mapped[str] = mapped_column(String(128), default="market_passive_reference")
    summary_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    skill: Mapped[Skill] = relationship(back_populates="backtests")
    traces: Mapped[list[RunTrace]] = relationship(back_populates="run")


class RunTrace(Base):
    __tablename__ = "run_traces"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("backtest_runs.id"), index=True)
    mode: Mapped[str] = mapped_column(String(32), default="backtest")
    trace_index: Mapped[int] = mapped_column(Integer)
    trigger_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decision_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reasoning_summary: Mapped[str] = mapped_column(Text())
    tool_calls_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    run: Mapped[BacktestRun] = relationship(back_populates="traces")


class LiveTask(Base):
    __tablename__ = "live_tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    cadence: Mapped[str] = mapped_column(String(16))
    cadence_seconds: Mapped[int] = mapped_column(Integer)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    skill: Mapped[Skill] = relationship(back_populates="live_tasks")
    signals: Mapped[list[LiveSignal]] = relationship(back_populates="live_task")


class LiveSignal(Base):
    __tablename__ = "live_signals"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    live_task_id: Mapped[str] = mapped_column(ForeignKey("live_tasks.id"), index=True)
    trigger_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    signal_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    delivery_status: Mapped[str] = mapped_column(String(32), default="stored")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    live_task: Mapped[LiveTask] = relationship(back_populates="signals")


class StrategyState(Base):
    __tablename__ = "strategy_states"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id"), unique=True, index=True)
    state_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    skill: Mapped[Skill] = relationship(back_populates="strategy_state")


class MarketCandle(Base):
    __tablename__ = "market_candles"
    __table_args__ = (
        UniqueConstraint("exchange", "market_symbol", "timeframe", "open_time_ms", name="uq_market_candle"),
        Index("ix_market_candle_symbol_time", "market_symbol", "timeframe", "open_time_ms"),
        Index("ix_market_candle_base_time", "base_symbol", "timeframe", "open_time_ms"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exchange: Mapped[str] = mapped_column(String(16), default="okx", index=True)
    market_symbol: Mapped[str] = mapped_column(String(128), index=True)
    base_symbol: Mapped[str] = mapped_column(String(64), index=True)
    quote_asset: Mapped[str] = mapped_column(String(16), default="USDT")
    instrument_type: Mapped[str] = mapped_column(String(16), default="SWAP")
    timeframe: Mapped[str] = mapped_column(String(16), default="1m")
    open_time_ms: Mapped[int] = mapped_column(BigInteger, index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    vol: Mapped[float] = mapped_column(Float)
    vol_ccy: Mapped[float | None] = mapped_column(Float, nullable=True)
    vol_quote: Mapped[float | None] = mapped_column(Float, nullable=True)
    confirm: Mapped[bool] = mapped_column(Boolean, default=True)
    is_old_contract: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(32), default="csv")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class CsvIngestionJob(Base):
    __tablename__ = "csv_ingestion_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_path: Mapped[str] = mapped_column(String(512))
    source_fingerprint: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    rows_seen: Mapped[int] = mapped_column(Integer, default=0)
    rows_inserted: Mapped[int] = mapped_column(Integer, default=0)
    rows_filtered: Mapped[int] = mapped_column(Integer, default=0)
    coverage_start_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    coverage_end_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    notes_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MarketSyncCursor(Base):
    __tablename__ = "market_sync_cursors"
    __table_args__ = (
        UniqueConstraint("exchange", "base_symbol", "timeframe", "source_kind", name="uq_market_sync_cursor"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    exchange: Mapped[str] = mapped_column(String(16), default="okx", index=True)
    base_symbol: Mapped[str] = mapped_column(String(64), index=True)
    timeframe: Mapped[str] = mapped_column(String(16), default="1m")
    source_kind: Mapped[str] = mapped_column(String(32), default="okx_history_api")
    last_synced_open_time_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    notes_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_sync_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
