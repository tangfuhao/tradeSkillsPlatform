from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, text
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
    execution_strategy_states: Mapped[list[ExecutionStrategyState]] = relationship(back_populates="skill")
    portfolio_books: Mapped[list[PortfolioBook]] = relationship(back_populates="skill")


class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    __table_args__ = (
        Index("ix_backtest_run_status_claim", "status", "claim_expires_at"),
        Index("ix_backtest_run_claim_owner", "claim_owner"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    scope: Mapped[str] = mapped_column(String(32), default="historical")
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    initial_capital: Mapped[float] = mapped_column(Float)
    benchmark_name: Mapped[str] = mapped_column(String(128), default="market_passive_reference")
    total_trigger_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_trigger_count: Mapped[int] = mapped_column(Integer, default=0)
    control_requested: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_processed_trace_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_processed_trigger_time_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    claim_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claim_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    claim_acquired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claim_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    run_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    last_runtime_error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    skill: Mapped[Skill] = relationship(back_populates="backtests")
    traces: Mapped[list[RunTrace]] = relationship(back_populates="run")

    __mapper_args__ = {
        "version_id_col": revision,
    }


class RunTrace(Base):
    __tablename__ = "run_traces"
    __table_args__ = (
        UniqueConstraint("run_id", "trace_index", name="uq_run_trace_run_index"),
        Index("ix_run_trace_run_created", "run_id", "created_at"),
    )

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
    execution_detail: Mapped[TraceExecutionDetail | None] = relationship(back_populates="trace", uselist=False)


class LiveTask(Base):
    __tablename__ = "live_tasks"
    __table_args__ = (
        Index("ix_live_task_status_claim", "status", "execution_claim_expires_at"),
        Index("ix_live_task_claim_owner", "execution_claim_owner"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    cadence: Mapped[str] = mapped_column(String(16))
    cadence_seconds: Mapped[int] = mapped_column(Integer)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_completed_slot_as_of_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_claimed_slot_as_of_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    execution_claim_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    execution_claim_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    execution_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    execution_claim_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    skill: Mapped[Skill] = relationship(back_populates="live_tasks")
    signals: Mapped[list[LiveSignal]] = relationship(back_populates="live_task")

    __mapper_args__ = {
        "version_id_col": revision,
    }


class LiveSignal(Base):
    __tablename__ = "live_signals"
    __table_args__ = (
        UniqueConstraint("live_task_id", "execution_time_ms", name="uq_live_signal_task_slot"),
        Index("ix_live_signal_task_created", "live_task_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    live_task_id: Mapped[str] = mapped_column(ForeignKey("live_tasks.id"), index=True)
    trigger_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    execution_time_ms: Mapped[int] = mapped_column(BigInteger, index=True)
    dispatch_as_of_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    trigger_origin: Mapped[str] = mapped_column(String(32), default="manual")
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


class ExecutionStrategyState(Base):
    __tablename__ = "execution_strategy_states"
    __table_args__ = (
        UniqueConstraint("scope_kind", "scope_id", name="uq_execution_strategy_state_scope"),
        Index("ix_execution_strategy_state_skill_scope", "skill_id", "scope_kind", "scope_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id"), index=True)
    scope_kind: Mapped[str] = mapped_column(String(32), index=True)
    scope_id: Mapped[str] = mapped_column(String(32), index=True)
    state_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    skill: Mapped[Skill] = relationship(back_populates="execution_strategy_states")


class PortfolioBook(Base):
    __tablename__ = "portfolio_books"
    __table_args__ = (
        UniqueConstraint("scope_kind", "scope_id", name="uq_portfolio_book_scope"),
        Index("ix_portfolio_book_skill_scope", "skill_id", "scope_kind", "scope_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id"), index=True)
    scope_kind: Mapped[str] = mapped_column(String(32), index=True)
    scope_id: Mapped[str] = mapped_column(String(32), index=True)
    initial_capital: Mapped[float] = mapped_column(Float)
    cash_balance: Mapped[float] = mapped_column(Float)
    equity: Mapped[float] = mapped_column(Float)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    last_mark_time_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    skill: Mapped[Skill] = relationship(back_populates="portfolio_books")
    positions: Mapped[list[PortfolioPosition]] = relationship(back_populates="book")
    fills: Mapped[list[PortfolioFill]] = relationship(back_populates="book")


class PortfolioPosition(Base):
    __tablename__ = "portfolio_positions"
    __table_args__ = (
        UniqueConstraint("book_id", "market_symbol", name="uq_portfolio_position_book_symbol"),
        Index("ix_portfolio_position_book_symbol", "book_id", "market_symbol"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("portfolio_books.id"), index=True)
    market_symbol: Mapped[str] = mapped_column(String(128), index=True)
    direction: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[float] = mapped_column(Float)
    avg_entry_price: Mapped[float] = mapped_column(Float)
    mark_price: Mapped[float] = mapped_column(Float, default=0.0)
    position_notional: Mapped[float] = mapped_column(Float, default=0.0)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    unrealized_pnl_pct: Mapped[float] = mapped_column(Float, default=0.0)
    cycle_realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    stop_loss_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    take_profit_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    opened_at_ms: Mapped[int] = mapped_column(BigInteger)
    updated_at_ms: Mapped[int] = mapped_column(BigInteger)

    book: Mapped[PortfolioBook] = relationship(back_populates="positions")


class PortfolioFill(Base):
    __tablename__ = "portfolio_fills"
    __table_args__ = (
        Index("ix_portfolio_fill_book_time", "book_id", "trigger_time_ms"),
        Index("ix_portfolio_fill_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("portfolio_books.id"), index=True)
    market_symbol: Mapped[str] = mapped_column(String(128), index=True)
    action: Mapped[str] = mapped_column(String(32))
    side: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    notional: Mapped[float] = mapped_column(Float)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    closed_trade_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    closed_trade_win: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    trigger_time_ms: Mapped[int] = mapped_column(BigInteger, index=True)
    trace_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    execution_reference: Mapped[str] = mapped_column(String(64), default="portfolio_book_fill")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    book: Mapped[PortfolioBook] = relationship(back_populates="fills")


class TraceExecutionDetail(Base):
    __tablename__ = "trace_execution_details"
    __table_args__ = (
        UniqueConstraint("trace_id", name="uq_trace_execution_detail_trace"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    trace_id: Mapped[str] = mapped_column(ForeignKey("run_traces.id"), index=True)
    portfolio_before_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    portfolio_after_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    fills_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    mark_prices_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    trace: Mapped[RunTrace] = relationship(back_populates="execution_detail")


class MarketCandle(Base):
    __tablename__ = "market_candles"
    __table_args__ = (
        Index("ix_market_candle_partition_lookup", "open_time_ms"),
        Index("ix_market_candle_timeframe_open_time", "timeframe", "open_time_ms"),
        Index("ix_market_candle_symbol_time", "market_symbol", "timeframe", "open_time_ms"),
        Index("ix_market_candle_base_time", "base_symbol", "timeframe", "open_time_ms"),
        {"postgresql_partition_by": "RANGE (open_time_ms)"},
    )

    exchange: Mapped[str] = mapped_column(String(16), primary_key=True, default="okx", index=True)
    market_symbol: Mapped[str] = mapped_column(String(128), primary_key=True, index=True)
    base_symbol: Mapped[str] = mapped_column(String(64), index=True)
    quote_asset: Mapped[str] = mapped_column(String(16), default="USDT")
    instrument_type: Mapped[str] = mapped_column(String(16), default="SWAP")
    timeframe: Mapped[str] = mapped_column(String(16), primary_key=True, default="1m")
    open_time_ms: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
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
    __table_args__ = (
        Index("ix_csv_ingestion_job_requested", "requested_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_path: Mapped[str] = mapped_column(String(512))
    source_fingerprint: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    runner_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    rows_seen: Mapped[int] = mapped_column(Integer, default=0)
    rows_staged: Mapped[int] = mapped_column(Integer, default=0)
    rows_inserted: Mapped[int] = mapped_column(Integer, default=0)
    rows_filtered: Mapped[int] = mapped_column(Integer, default=0)
    coverage_start_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    coverage_end_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    notes_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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


class MarketInstrument(Base):
    __tablename__ = "market_instruments"
    __table_args__ = (
        UniqueConstraint("exchange", "instrument_id", name="uq_market_instrument"),
        Index("ix_market_instrument_lifecycle_tier", "lifecycle_status", "priority_tier"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    exchange: Mapped[str] = mapped_column(String(16), default="okx", index=True)
    instrument_id: Mapped[str] = mapped_column(String(128), index=True)
    base_symbol: Mapped[str] = mapped_column(String(64), index=True)
    quote_asset: Mapped[str] = mapped_column(String(16), default="USDT")
    instrument_type: Mapped[str] = mapped_column(String(16), default="SWAP")
    lifecycle_status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    priority_tier: Mapped[str] = mapped_column(String(16), default="tier2", index=True)
    bootstrap_status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    last_trade_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume_24h_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_seen_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delisted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    missed_refresh_count: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class MarketSyncState(Base):
    __tablename__ = "market_sync_states"
    __table_args__ = (
        UniqueConstraint("exchange", "base_symbol", "timeframe", name="uq_market_sync_state_symbol"),
        Index("ix_market_sync_state_due", "lifecycle_status", "priority_tier", "next_sync_due_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    exchange: Mapped[str] = mapped_column(String(16), default="okx", index=True)
    base_symbol: Mapped[str] = mapped_column(String(64), index=True)
    timeframe: Mapped[str] = mapped_column(String(16), default="1m")
    lifecycle_status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    priority_tier: Mapped[str] = mapped_column(String(16), default="tier2", index=True)
    last_synced_open_time_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    fresh_coverage_end_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    next_sync_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_sync_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class MarketSyncAttempt(Base):
    __tablename__ = "market_sync_attempts"
    __table_args__ = (
        Index("ix_market_sync_attempt_symbol_started", "base_symbol", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    exchange: Mapped[str] = mapped_column(String(16), default="okx", index=True)
    base_symbol: Mapped[str] = mapped_column(String(64), index=True)
    timeframe: Mapped[str] = mapped_column(String(16), default="1m")
    queue_name: Mapped[str] = mapped_column(String(32), default="symbol-sync-normal", index=True)
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    retryable: Mapped[bool] = mapped_column(Boolean, default=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    inserted_rows: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MarketCoverageSnapshot(Base):
    __tablename__ = "market_coverage_snapshots"
    __table_args__ = (
        Index("ix_market_coverage_snapshot_created", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    active_symbol_count: Mapped[int] = mapped_column(Integer, default=0)
    fresh_symbol_count: Mapped[int] = mapped_column(Integer, default=0)
    tier1_symbol_count: Mapped[int] = mapped_column(Integer, default=0)
    tier1_fresh_symbol_count: Mapped[int] = mapped_column(Integer, default=0)
    coverage_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    dispatch_as_of_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)
    blocked_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    universe_version: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    missing_symbol_count: Mapped[int] = mapped_column(Integer, default=0)
    missing_symbols_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    notes_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MarketOverviewState(Base):
    __tablename__ = "market_overview_states"
    __table_args__ = (
        UniqueConstraint("timeframe", name="uq_market_overview_state_timeframe"),
        Index("ix_market_overview_state_rebuilt", "rebuilt_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(16), default="1m")
    total_candles_estimate: Mapped[int] = mapped_column(BigInteger, default=0)
    total_symbols: Mapped[int] = mapped_column(Integer, default=0)
    coverage_start_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    coverage_end_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    coverage_ranges_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    bootstrap_pending_count: Mapped[int] = mapped_column(Integer, default=0)
    backfill_lag_symbol_count: Mapped[int] = mapped_column(Integer, default=0)
    tier1_freshness_ms_p95: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    tier2_freshness_ms_p95: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    failed_sync_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_sync_count: Mapped[int] = mapped_column(Integer, default=0)
    ingest_backlog_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    recent_csv_jobs_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    source_snapshot_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rebuilt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
