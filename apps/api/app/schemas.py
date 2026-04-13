from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class SkillCreateRequest(BaseModel):
    title: str | None = None
    skill_text: str = Field(min_length=20)


class SkillReviewUpdateRequest(BaseModel):
    review_status: Literal["preview_ready", "review_pending", "approved_full_window", "review_rejected"]


class SkillResponse(BaseModel):
    id: str
    title: str
    validation_status: str
    review_status: str
    source_hash: str
    envelope: dict[str, Any]
    validation_errors: list[str]
    validation_warnings: list[str]
    preview_window: dict[str, datetime]
    created_at: datetime
    updated_at: datetime


class BacktestCreateRequest(BaseModel):
    skill_id: str
    start_time: datetime
    end_time: datetime
    initial_capital: float = Field(default=10000.0, gt=0)


class TraceResponse(BaseModel):
    id: str
    trace_index: int
    trigger_time: datetime
    reasoning_summary: str
    decision: dict[str, Any]
    tool_calls: list[dict[str, Any]]


class BacktestResponse(BaseModel):
    id: str
    skill_id: str
    status: str
    scope: str
    benchmark_name: str
    start_time: datetime
    end_time: datetime
    initial_capital: float
    summary: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class LiveTaskCreateRequest(BaseModel):
    skill_id: str


class LiveTaskResponse(BaseModel):
    id: str
    skill_id: str
    status: str
    cadence: str
    cadence_seconds: int
    last_triggered_at: datetime | None
    created_at: datetime
    updated_at: datetime


class LiveSignalResponse(BaseModel):
    id: str
    live_task_id: str
    trigger_time: datetime
    delivery_status: str
    signal: dict[str, Any]
    created_at: datetime


class HealthResponse(BaseModel):
    name: str
    status: str
    database_url: str
    agent_runner_base_url: str
    scheduler_running: bool
    active_scheduler_jobs: int
    server_time: datetime


class MarketCandleResponse(BaseModel):
    market_symbol: str
    base_symbol: str
    timeframe: str
    open_time_ms: int
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    vol: float
    vol_ccy: float | None
    vol_quote: float | None
    confirm: bool
    source: str


class MarketOverviewResponse(BaseModel):
    historical_data_dir: str
    base_timeframe: str
    total_candles: int
    total_symbols: int
    coverage_start: str | None
    coverage_end: str | None
    recent_csv_jobs: list[dict[str, Any]]
    sync_cursors: list[dict[str, Any]]
