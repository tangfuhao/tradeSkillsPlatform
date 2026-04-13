from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runner.config import settings
from runner.schemas import AgentDecision, ExecuteRunRequest, ExecuteRunResponse, RiskTarget, ToolCallSummary
from runner.services.openai_runtime import OpenAIToolDecisionEngine


@dataclass(slots=True)
class HeuristicFallbackDecisionEngine:
    provider: str = "heuristic-fallback"

    def execute(self, payload: ExecuteRunRequest) -> ExecuteRunResponse:
        candidates = payload.context.get("market_candidates", [])
        state = payload.context.get("strategy_state", {})
        risk_contract = payload.envelope.get("risk_contract", {})
        max_position_pct = float(risk_contract.get("max_position_pct", 0.10) or 0.10)
        stop_loss = float(risk_contract.get("stop_loss_pct", 0.02) or 0.02)
        take_profit = float(risk_contract.get("take_profit_pct", 0.10) or 0.10)
        skill_text = payload.skill_text.lower()
        preferred_direction = "sell" if any(token in skill_text for token in ["short", "sell", "做空"]) else "buy"
        tool_calls = _build_tool_calls(payload)

        if not candidates:
            return ExecuteRunResponse(
                decision=AgentDecision(
                    action="skip",
                    reason="No market candidates were provided to the Agent Runner.",
                    size_pct=0.0,
                ),
                reasoning_summary="The fallback engine skipped because the tool context had no market candidates.",
                tool_calls=tool_calls,
                provider=self.provider,
            )

        hottest = max(candidates, key=_candidate_score)
        heat_score = _candidate_score(hottest)
        if heat_score >= 0.22:
            decision = AgentDecision(
                action="open_position",
                symbol=hottest.get("symbol"),
                direction=preferred_direction,
                size_pct=min(max_position_pct, 0.10),
                reason=(
                    f"{hottest.get('symbol')} shows an overheated short-term move, elevated speculative flow, "
                    "and enough liquidity for a fallback signal."
                ),
                stop_loss=RiskTarget(type="price_pct", value=stop_loss),
                take_profit=RiskTarget(type="price_pct", value=take_profit),
                state_patch={
                    "focus_symbol": hottest.get("symbol"),
                    "last_action": "open_position",
                    "last_mode": payload.mode,
                },
            )
            reasoning_summary = (
                "The fallback engine selected the hottest candidate, verified that the heat score cleared the "
                "entry threshold, and opened a position under the Skill risk cap."
            )
        elif heat_score >= 0.14:
            decision = AgentDecision(
                action="watch",
                symbol=hottest.get("symbol"),
                size_pct=0.0,
                reason="The candidate is interesting but still below the fallback entry threshold.",
                state_patch={
                    "focus_symbol": hottest.get("symbol"),
                    "last_action": "watch",
                    "previous_focus_symbol": state.get("focus_symbol"),
                    "last_mode": payload.mode,
                },
            )
            reasoning_summary = "The fallback engine kept the best candidate on watch and waited for stronger confirmation."
        else:
            decision = AgentDecision(
                action="skip",
                size_pct=0.0,
                reason="Current market context does not justify a signal under the fallback thresholds.",
                state_patch={"last_action": "skip", "last_mode": payload.mode},
            )
            reasoning_summary = "The fallback engine skipped because no candidate cleared the watch threshold."

        return ExecuteRunResponse(
            decision=decision,
            reasoning_summary=reasoning_summary,
            tool_calls=tool_calls,
            provider=self.provider,
        )


@dataclass(slots=True)
class ResilientDecisionEngine:
    primary: OpenAIToolDecisionEngine
    fallback: HeuristicFallbackDecisionEngine

    def execute(self, payload: ExecuteRunRequest) -> ExecuteRunResponse:
        try:
            return self.primary.execute(payload)
        except Exception as exc:  # noqa: BLE001
            fallback_response = self.fallback.execute(payload)
            return ExecuteRunResponse(
                decision=fallback_response.decision,
                reasoning_summary=(
                    f"LLM runtime failed and fallback engine was used instead: {exc}. "
                    f"{fallback_response.reasoning_summary}"
                ),
                tool_calls=fallback_response.tool_calls,
                provider=f"{self.primary.provider}:fallback",
            )


def _candidate_score(item: dict[str, Any]) -> float:
    return round(
        float(item.get("change_24h_pct", 0.0))
        + float(item.get("open_interest_change_24h_pct", 0.0)) * 0.55
        + max(float(item.get("funding_rate", 0.0)) * 20, 0.0),
        4,
    )


def _build_tool_calls(payload: ExecuteRunRequest) -> list[ToolCallSummary]:
    required_tools = payload.envelope.get("tool_contract", {}).get("required_tools", [])
    calls: list[ToolCallSummary] = []
    for tool_name in required_tools:
        if tool_name == "simulate_order" and payload.mode != "backtest":
            continue
        if tool_name == "emit_signal" and payload.mode != "live_signal":
            continue
        calls.append(
            ToolCallSummary(
                tool_name=tool_name,
                arguments={
                    "mode": payload.mode,
                    "trigger_time": payload.trigger_time.isoformat(),
                },
                status="fallback-planned",
            )
        )
    return calls


def get_engine() -> ResilientDecisionEngine:
    fallback = HeuristicFallbackDecisionEngine()
    primary = OpenAIToolDecisionEngine(provider=settings.provider)
    return ResilientDecisionEngine(primary=primary, fallback=fallback)
