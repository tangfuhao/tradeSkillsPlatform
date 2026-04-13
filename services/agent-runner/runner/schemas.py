from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ExecuteRunRequest(BaseModel):
    skill_id: str | None = None
    skill_title: str | None = None
    mode: Literal["backtest", "live_signal"]
    trigger_time: datetime
    skill_text: str = Field(min_length=20)
    envelope: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)


class RiskTarget(BaseModel):
    type: str
    value: float


class AgentDecision(BaseModel):
    action: Literal["skip", "watch", "open_position", "close_position", "reduce_position", "hold"]
    symbol: str | None = None
    direction: Literal["buy", "sell"] | None = None
    size_pct: float = 0.0
    reason: str
    stop_loss: RiskTarget | None = None
    take_profit: RiskTarget | None = None
    state_patch: dict[str, Any] = Field(default_factory=dict)


class ToolCallSummary(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    status: str = "planned"


class ExecuteRunResponse(BaseModel):
    decision: AgentDecision
    reasoning_summary: str
    tool_calls: list[ToolCallSummary]
    provider: str
