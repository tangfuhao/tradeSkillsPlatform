from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


class ExecuteRunRequest(BaseModel):
    skill_id: str | None = None
    skill_title: str | None = None
    mode: Literal["backtest", "live_signal"]
    trigger_time_ms: int
    skill_text: str = Field(min_length=20)
    envelope: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)

    @property
    def trigger_time(self) -> datetime:
        return datetime.fromtimestamp(self.trigger_time_ms / 1000, tz=timezone.utc)


class SkillEnvelopeExtractRequest(BaseModel):
    skill_text: str = Field(min_length=20)
    title_override: str | None = None
    rule_envelope: dict[str, Any] = Field(default_factory=dict)
    rule_errors: list[str] = Field(default_factory=list)
    rule_warnings: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)


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


class ExecutionTiming(BaseModel):
    started_at_ms: int
    completed_at_ms: int
    duration_ms: int


class ExecutionBreakdown(BaseModel):
    tool_execution_total_ms: int = 0
    llm_wait_total_ms: int = 0
    other_overhead_ms: int = 0


class LlmRoundSummary(BaseModel):
    round_index: int
    started_at_ms: int
    completed_at_ms: int
    llm_round_duration_ms: int
    tool_call_count: int = 0
    result_type: Literal["tool_calls", "final_output"]


class ToolCallSummary(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    status: str = "planned"
    execution_timing: ExecutionTiming | None = None


class ExecuteRunResponse(BaseModel):
    decision: AgentDecision
    reasoning_summary: str
    tool_calls: list[ToolCallSummary]
    provider: str
    execution_timing: ExecutionTiming | None = None
    execution_breakdown: ExecutionBreakdown | None = None
    llm_rounds: list[LlmRoundSummary] = Field(default_factory=list)


class SkillEnvelopeExtractResponse(BaseModel):
    title: str | None = None
    envelope_patch: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    unresolved_fields: list[str] = Field(default_factory=list)
    reasoning_summary: str
    provider: str
