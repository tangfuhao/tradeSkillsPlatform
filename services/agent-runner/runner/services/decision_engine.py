from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runner.schemas import AgentDecision, ExecuteRunRequest, ExecuteRunResponse, RiskTarget, ToolCallSummary


@dataclass(slots=True)
class DemoDecisionEngine:
    provider: str = "demo-heuristic"

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
                reasoning_summary="The demo engine skipped because the tool context had no market candidates.",
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
                    "and enough liquidity for a demo signal."
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
                "The demo engine selected the hottest candidate, verified that the heat score cleared the "
                "entry threshold, and opened a position under the Skill risk cap."
            )
        elif heat_score >= 0.14:
            decision = AgentDecision(
                action="watch",
                symbol=hottest.get("symbol"),
                size_pct=0.0,
                reason="The candidate is interesting but still below the demo entry threshold.",
                state_patch={
                    "focus_symbol": hottest.get("symbol"),
                    "last_action": "watch",
                    "previous_focus_symbol": state.get("focus_symbol"),
                },
            )
            reasoning_summary = "The demo engine kept the best candidate on watch and waited for stronger confirmation."
        else:
            decision = AgentDecision(
                action="skip",
                size_pct=0.0,
                reason="Current market context does not justify a signal under the demo thresholds.",
                state_patch={"last_action": "skip"},
            )
            reasoning_summary = "The demo engine skipped because no candidate cleared the watch threshold."

        return ExecuteRunResponse(
            decision=decision,
            reasoning_summary=reasoning_summary,
            tool_calls=tool_calls,
            provider=self.provider,
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
                status="planned",
            )
        )
    return calls


def get_engine() -> DemoDecisionEngine:
    return DemoDecisionEngine()
