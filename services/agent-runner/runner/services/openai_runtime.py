from __future__ import annotations

import io
import json
import math
import statistics
import time
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

from runner.config import settings
from runner.schemas import (
    AgentDecision,
    ExecuteRunRequest,
    ExecuteRunResponse,
    ExecutionBreakdown,
    ExecutionTiming,
    LlmRoundSummary,
    RiskTarget,
    ToolCallSummary,
)
from runner.services.model_routing import get_responses_client
from runner.services.responses_payload_builder import build_responses_request_payload
from runner.services.runtime_errors import build_stream_event_error
from runner.services.tool_gateway_client import ToolGatewayClient


DEFAULT_STOP_LOSS_PCT = 0.02
DEFAULT_TAKE_PROFIT_PCT = 0.10


@dataclass(slots=True)
class StreamRoundResult:
    output_text: str
    output_items: list[dict[str, Any]]
    function_calls: list[dict[str, Any]]
    execution_timing: ExecutionTiming
    result_type: str


@dataclass(slots=True)
class TimingCheckpoint:
    started_at_ms: int
    started_monotonic_ns: int


@dataclass(slots=True)
class OpenAIToolDecisionEngine:
    provider: str = "openai-tools"

    def execute(self, payload: ExecuteRunRequest) -> ExecuteRunResponse:
        run_timing = _start_timing()
        runtime = ToolRuntime(payload)
        conversation_items = _build_prompt_input_items(payload)
        tool_summaries: list[ToolCallSummary] = []
        llm_rounds: list[LlmRoundSummary] = []
        client = get_responses_client(settings.openai_model)

        for _ in range(settings.openai_max_tool_rounds):
            round_result = _stream_response_round(
                client,
                conversation_items=conversation_items,
                request_kind="execute",
            )
            llm_rounds.append(_build_llm_round_summary(len(llm_rounds) + 1, round_result))
            if round_result.function_calls:
                function_outputs: list[dict[str, Any]] = []
                for call in round_result.function_calls:
                    call_name = str(call.get("name") or "")
                    raw_arguments = str(call.get("arguments") or "{}")
                    arguments = _parse_json_object(raw_arguments)
                    tool_timing = _start_timing()
                    result = runtime.execute_tool(call_name, arguments)
                    tool_summaries.append(
                        ToolCallSummary(
                            tool_name=call_name,
                            arguments=arguments,
                            status=result.get("status", "executed"),
                            execution_timing=_finish_timing(tool_timing),
                        )
                    )
                    function_outputs.append(
                        {
                            "type": "function_call_output",
                            "call_id": call.get("call_id"),
                            "output": json.dumps(result.get("content", {}), ensure_ascii=False),
                        }
                    )
                conversation_items.extend(round_result.output_items)
                conversation_items.extend(function_outputs)
                continue

            try:
                final_payload = _parse_final_payload(round_result.output_text)
            except ValueError:
                return _fallback_non_json_response(
                    runtime,
                    tool_summaries=tool_summaries,
                    raw_output=round_result.output_text,
                    provider=self.provider,
                    execution_timing=_finish_timing(run_timing),
                    llm_rounds=llm_rounds,
                )
            decision_payload = final_payload.get("decision", final_payload)
            reasoning_summary = final_payload.get("reasoning_summary") or _default_reasoning_summary(tool_summaries)
            decision = _sanitize_decision(payload, runtime, decision_payload)
            execution_timing = _finish_timing(run_timing)
            return ExecuteRunResponse(
                decision=decision,
                reasoning_summary=reasoning_summary,
                tool_calls=tool_summaries,
                provider=self.provider,
                execution_timing=execution_timing,
                execution_breakdown=_build_execution_breakdown(execution_timing, tool_summaries, llm_rounds),
                llm_rounds=llm_rounds,
            )

        raise RuntimeError("LLM tool loop exceeded the configured maximum number of rounds.")


@dataclass(slots=True)
class ToolRuntime:
    payload: ExecuteRunRequest
    pending_state_patch: dict[str, Any] = field(default_factory=dict)
    staged_decision: dict[str, Any] = field(default_factory=dict)
    gateway_client: ToolGatewayClient = field(init=False)

    def __post_init__(self) -> None:
        self.gateway_client = ToolGatewayClient(self.payload)

    def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "scan_market":
            return self._scan_market(arguments)
        if tool_name == "get_portfolio_state":
            return self._get_portfolio_state()
        if tool_name == "get_strategy_state":
            return self._get_strategy_state()
        if tool_name == "save_strategy_state":
            return self._save_strategy_state(arguments)
        if tool_name == "get_market_metadata":
            return self._get_market_metadata(arguments)
        if tool_name == "get_candles":
            return self._get_candles(arguments)
        if tool_name == "compute_indicators":
            return self._compute_indicators(arguments)
        if tool_name == "get_funding_rate":
            return self._get_funding_rate(arguments)
        if tool_name == "get_open_interest":
            return self._get_open_interest(arguments)
        if tool_name == "python_exec":
            return self._python_exec(arguments)
        if tool_name in {"simulate_order", "emit_signal"}:
            return self._stage_trade_intent(tool_name, arguments)
        return {
            "status": "unsupported",
            "content": {"error": f"Unsupported tool: {tool_name}"},
        }

    def _scan_market(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.gateway_client.execute("scan_market", arguments)

    def _get_portfolio_state(self) -> dict[str, Any]:
        return self.gateway_client.execute("get_portfolio_state", {})

    def _compute_indicators(self, arguments: dict[str, Any]) -> dict[str, Any]:
        market_symbol = self._resolve_market_symbol(arguments.get("market_symbol")) or ""
        timeframe = str(arguments.get("timeframe") or "").strip().lower()
        limit = max(1, min(int(arguments.get("limit", 120) or 120), 240))
        candles = self._load_candles(market_symbol, timeframe, limit)
        if not candles:
            return {
                "status": "not_available",
                "content": {
                    "error": f"No candles available via tool gateway for {market_symbol} {timeframe}",
                },
            }
        selected = candles[-limit:] if limit is not None else candles
        closes = [float(item["close"]) for item in selected]
        results: dict[str, Any] = {}
        for period in arguments.get("ema_periods") or []:
            results[f"ema_{int(period)}"] = _ema(closes, int(period))
        for period in arguments.get("sma_periods") or []:
            results[f"sma_{int(period)}"] = _sma(closes, int(period))
        for period in arguments.get("rsi_periods") or []:
            results[f"rsi_{int(period)}"] = _rsi(closes, int(period))
        for period in arguments.get("atr_periods") or []:
            results[f"atr_{int(period)}"] = _atr(selected, int(period))
        return {
            "status": "ok",
            "content": {
                "market_symbol": market_symbol,
                "timeframe": timeframe,
                "count": len(selected),
                "indicators": results,
            },
        }

    def _get_strategy_state(self) -> dict[str, Any]:
        response = self.gateway_client.execute("get_strategy_state", {})
        merged = dict((response.get("content") or {}).get("strategy_state", {}))
        merged.update(self.pending_state_patch)
        return {"status": "ok", "content": {"strategy_state": merged}}

    def _save_strategy_state(self, arguments: dict[str, Any]) -> dict[str, Any]:
        patch = arguments.get("patch") or {}
        if not isinstance(patch, dict):
            return {"status": "error", "content": {"error": "patch must be an object"}}
        self.pending_state_patch.update(patch)
        preview = self._get_strategy_state()
        return {
            "status": "staged",
            "content": {
                "strategy_state": (preview.get("content") or {}).get("strategy_state", {}),
                "pending_state_patch": dict(self.pending_state_patch),
            },
        }

    def _get_market_metadata(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request_arguments = dict(arguments)
        if request_arguments.get("market_symbol"):
            request_arguments["market_symbol"] = self._resolve_market_symbol(request_arguments.get("market_symbol"))
        return self.gateway_client.execute("get_market_metadata", request_arguments)

    def _get_candles(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request_arguments = dict(arguments)
        if request_arguments.get("market_symbol"):
            request_arguments["market_symbol"] = self._resolve_market_symbol(request_arguments.get("market_symbol"))
        return self.gateway_client.execute("get_candles", request_arguments)

    def _get_funding_rate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request_arguments = dict(arguments)
        if request_arguments.get("market_symbol"):
            request_arguments["market_symbol"] = self._resolve_market_symbol(request_arguments.get("market_symbol"))
        return self.gateway_client.execute("get_funding_rate", request_arguments)

    def _get_open_interest(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request_arguments = dict(arguments)
        if request_arguments.get("market_symbol"):
            request_arguments["market_symbol"] = self._resolve_market_symbol(request_arguments.get("market_symbol"))
        return self.gateway_client.execute("get_open_interest", request_arguments)

    def _python_exec(self, arguments: dict[str, Any]) -> dict[str, Any]:
        code = str(arguments.get("code") or "")
        if not code.strip():
            return {"status": "error", "content": {"error": "code is required"}}
        if len(code) > 6000:
            return {"status": "error", "content": {"error": "code is too long"}}

        stdout = io.StringIO()
        env = self._python_env()
        locals_dict: dict[str, Any] = {}
        try:
            with redirect_stdout(stdout):
                exec(code, env, locals_dict)
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "error",
                "content": {
                    "error": str(exc),
                    "stdout": stdout.getvalue(),
                },
            }

        return {
            "status": "ok",
            "content": {
                "stdout": stdout.getvalue(),
                "result": _make_json_safe(locals_dict.get("result")),
            },
        }

    def _stage_trade_intent(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        request_arguments = dict(arguments)
        if request_arguments.get("symbol"):
            request_arguments["symbol"] = self._resolve_market_symbol(request_arguments.get("symbol")) or request_arguments.get("symbol")
        response = self.gateway_client.execute(tool_name, request_arguments)
        staged = dict((response.get("content") or {}).get("staged_decision", {}))
        self.staged_decision.update({key: value for key, value in staged.items() if value is not None})
        return {"status": response.get("status", "staged"), "content": {"staged_decision": dict(self.staged_decision)}}

    def _candidate_for(self, market_symbol: str | None) -> dict[str, Any] | None:
        if not market_symbol:
            return None
        normalized = self._resolve_market_symbol(market_symbol) or market_symbol.upper()
        for item in self.payload.context.get("market_candidates", []):
            if str(item.get("symbol") or "").upper() == normalized:
                return item
        return None

    def _python_env(self) -> dict[str, Any]:
        safe_builtins = {
            "abs": abs,
            "all": all,
            "any": any,
            "bool": bool,
            "dict": dict,
            "enumerate": enumerate,
            "float": float,
            "int": int,
            "len": len,
            "list": list,
            "max": max,
            "min": min,
            "print": print,
            "range": range,
            "round": round,
            "set": set,
            "sorted": sorted,
            "str": str,
            "sum": sum,
            "tuple": tuple,
            "zip": zip,
        }
        return {
            "__builtins__": safe_builtins,
            "math": math,
            "statistics": statistics,
            "json": json,
            "load_candles": self._load_candles,
            "ema": _ema,
            "sma": _sma,
            "rsi": _rsi,
            "atr": _atr,
        }

    def _load_candles(self, market_symbol: str, timeframe: str, limit: int | None = None) -> list[dict[str, Any]]:
        symbol = self._resolve_market_symbol(market_symbol) or market_symbol.strip().upper()
        tf = timeframe.strip().lower()
        response = self.gateway_client.execute(
            "get_candles",
            {
                "market_symbol": symbol,
                "timeframe": tf,
                "limit": int(limit or 200),
            },
        )
        if response.get("status") != "ok":
            return []
        candles = list((response.get("content") or {}).get("candles", []))
        if limit is not None:
            return candles[-int(limit) :]
        return candles

    def _resolve_market_symbol(self, raw_symbol: Any) -> str | None:
        if raw_symbol is None:
            return None
        symbol = str(raw_symbol).strip().upper()
        if not symbol:
            return None
        candidate_symbols = {
            str(item.get("symbol") or "").upper()
            for item in self.payload.context.get("market_candidates", [])
            if item.get("symbol")
        }
        universe = candidate_symbols
        if symbol in universe:
            return symbol
        if not symbol.endswith("-USDT-SWAP"):
            expanded = f"{symbol}-USDT-SWAP"
            if expanded in universe:
                return expanded
            symbol = expanded
        for candidate in universe:
            if candidate.startswith(f"{symbol}-") or candidate.startswith(symbol):
                return candidate
        return symbol


def _build_prompt_text(payload: ExecuteRunRequest) -> str:
    market_candidates = payload.context.get("market_candidates", [])[:8]
    compact_candidates = [
        {
            "symbol": item.get("symbol"),
            "last_price": item.get("last_price"),
            "change_24h_pct": item.get("change_24h_pct"),
            "volume_24h_usd": item.get("volume_24h_usd"),
            "funding_rate": item.get("funding_rate"),
            "open_interest_change_24h_pct": item.get("open_interest_change_24h_pct"),
            "is_old_contract": item.get("is_old_contract"),
        }
        for item in market_candidates
    ]
    tool_gateway = payload.context.get("tool_gateway", {}) if isinstance(payload.context, dict) else {}
    portfolio_summary = payload.context.get("portfolio_summary", {}) if isinstance(payload.context, dict) else {}
    return (
        "You are running one trigger cycle for a trading Skill.\n\n"
        f"Mode: {payload.mode}\n"
        f"Trigger time (UTC): {payload.trigger_time.isoformat()}\n"
        f"Trigger time ms: {payload.trigger_time_ms}\n"
        f"Skill title: {payload.skill_title or payload.skill_id or 'Unnamed Skill'}\n\n"
        "Skill text:\n"
        f"{payload.skill_text}\n\n"
        "Extracted envelope:\n"
        f"{json.dumps(payload.envelope, ensure_ascii=False)}\n\n"
        "Current compact market scan context:\n"
        f"{json.dumps(compact_candidates, ensure_ascii=False)}\n\n"
        "Tool gateway summary:\n"
        f"{json.dumps({
            'enabled': bool(tool_gateway),
            'as_of_ms': payload.context.get('as_of_ms'),
            'provider': payload.context.get('provider') or payload.context.get('source'),
            'market_candidate_count': len(payload.context.get('market_candidates', [])),
            'trace_index': tool_gateway.get('trace_index'),
        }, ensure_ascii=False)}\n\n"
        "Current portfolio hint:\n"
        f"{json.dumps(portfolio_summary, ensure_ascii=False)}"
    )


def _build_prompt_input_items(payload: ExecuteRunRequest) -> list[dict[str, Any]]:
    return [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": _build_prompt_text(payload)}],
        }
    ]


def _system_prompt() -> str:
    return (
        "You are the execution runtime for a natural-language trading Skill. "
        "Your job is to read the Skill, inspect tool data, and return one structured trade decision for this trigger.\n\n"
        "Rules:\n"
        "1. Use tools to inspect market context before finalizing a decision. Prefer scan_market, get_portfolio_state, get_strategy_state, and compute_indicators. Use get_candles only when you truly need raw bars. Use python_exec only for custom calculations that the built-in tools cannot cover.\n"
        "2. Respect the risk contract. Do not exceed max_position_pct. If a setup is unclear, choose skip or watch.\n"
        "3. If the Skill is short-biased, prefer sell direction when opening a position.\n"
        "4. If there are existing positions, unrealized PnL, or partial exits to consider, call get_portfolio_state before deciding whether to hold, reduce, or close.\n"
        "5. stop_loss and take_profit are metadata only in v1; they do not auto-trigger. The engine executes close_position or reduce_position only when you explicitly choose them.\n"
        "6. When open_position is chosen, include stop_loss and take_profit as {\"type\": \"price_pct\", \"value\": number}.\n"
        "7. close_position closes the full current position for the symbol and ignores size_pct. reduce_position uses size_pct as a ratio of the current position size, not of account equity.\n"
        "8. If you call save_strategy_state, the final decision.state_patch should still include the relevant patch.\n"
        "9. Final answer must be JSON only, with this shape:\n"
        "{\n"
        '  "reasoning_summary": "short summary of the execution plan and why the final decision was made",\n'
        '  "decision": {\n'
        '    "action": "skip|watch|open_position|close_position|reduce_position|hold",\n'
        '    "symbol": "... or null",\n'
        '    "direction": "buy|sell|null",\n'
        '    "size_pct": 0.0,\n'
        '    "reason": "...",\n'
        '    "stop_loss": {"type": "price_pct", "value": 0.02} or null,\n'
        '    "take_profit": {"type": "price_pct", "value": 0.10} or null,\n'
        '    "state_patch": {}\n'
        "  }\n"
        "}\n"
        "10. Keep tool usage minimal. In most cases you should finish within 3 to 4 tool calls.\n"
        "11. If you use python_exec, do not write import statements. Use the built-in helpers instead.\n"
        "12. Do not include markdown code fences in the final answer.\n"
        "13. This runtime is used for backtests, paper trading, and user-authorized live execution. "
        "Do not refuse solely because the request involves market analysis or a simulated trade decision."
    )


def _tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": "scan_market",
            "description": "Return the current ranked market candidates available for this trigger.",
            "parameters": {
                "type": "object",
                "properties": {
                    "top_n": {"type": "integer", "minimum": 1, "maximum": 20},
                    "sort_by": {"type": "string"},
                },
            },
        },
        {
            "type": "function",
            "name": "get_portfolio_state",
            "description": "Read the official execution-scoped portfolio, including cash, equity, realized and unrealized PnL, open positions, and recent fills.",
            "parameters": {"type": "object", "properties": {}},
        },
        {
            "type": "function",
            "name": "get_strategy_state",
            "description": "Read the externalized strategy state for this Skill.",
            "parameters": {"type": "object", "properties": {}},
        },
        {
            "type": "function",
            "name": "save_strategy_state",
            "description": "Stage a partial strategy state patch that should be persisted after this trigger completes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patch": {"type": "object"},
                },
                "required": ["patch"],
            },
        },
        {
            "type": "function",
            "name": "get_market_metadata",
            "description": "Inspect metadata about a candidate symbol and the remote tool-gateway context for this run.",
            "parameters": {
                "type": "object",
                "properties": {
                    "market_symbol": {"type": "string"},
                },
            },
        },
        {
            "type": "function",
            "name": "get_candles",
            "description": "Fetch OHLCV candles for a symbol and timeframe through the remote Tool Gateway. Prefer compute_indicators for EMA, RSI, ATR, or SMA unless you really need raw bars.",
            "parameters": {
                "type": "object",
                "properties": {
                    "market_symbol": {"type": "string"},
                    "timeframe": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                },
                "required": ["market_symbol", "timeframe"],
            },
        },
        {
            "type": "function",
            "name": "compute_indicators",
            "description": "Compute common technical indicators from candles fetched through the Tool Gateway. Prefer this over python_exec for EMA, SMA, RSI, or ATR.",
            "parameters": {
                "type": "object",
                "properties": {
                    "market_symbol": {"type": "string"},
                    "timeframe": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 240},
                    "ema_periods": {"type": "array", "items": {"type": "integer"}},
                    "sma_periods": {"type": "array", "items": {"type": "integer"}},
                    "rsi_periods": {"type": "array", "items": {"type": "integer"}},
                    "atr_periods": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["market_symbol", "timeframe"],
            },
        },
        {
            "type": "function",
            "name": "get_funding_rate",
            "description": "Return the currently available funding-rate snapshot for a candidate symbol.",
            "parameters": {
                "type": "object",
                "properties": {
                    "market_symbol": {"type": "string"},
                },
                "required": ["market_symbol"],
            },
        },
        {
            "type": "function",
            "name": "get_open_interest",
            "description": "Return the currently available open-interest change snapshot for a candidate symbol.",
            "parameters": {
                "type": "object",
                "properties": {
                    "market_symbol": {"type": "string"},
                },
                "required": ["market_symbol"],
            },
        },
        {
            "type": "function",
            "name": "python_exec",
            "description": (
                "Run a small pure-Python calculation with helper functions load_candles(symbol, timeframe, limit=None), "
                "ema(values, period), sma(values, period), rsi(values, period), atr(candles, period). "
                "Do not use import statements. Set a variable named result if you want structured output."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "code": {"type": "string"},
                },
                "required": ["code"],
            },
        },
        {
            "type": "function",
            "name": "simulate_order",
            "description": "Stage a simulated trade intent before producing the final structured decision.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "symbol": {"type": "string"},
                    "direction": {"type": "string"},
                    "size_pct": {"type": "number"},
                    "reason": {"type": "string"},
                    "stop_loss_pct": {"type": "number"},
                    "take_profit_pct": {"type": "number"},
                },
            },
        },
        {
            "type": "function",
            "name": "emit_signal",
            "description": "Stage a structured live signal intent before producing the final response.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "symbol": {"type": "string"},
                    "direction": {"type": "string"},
                    "size_pct": {"type": "number"},
                    "reason": {"type": "string"},
                    "stop_loss_pct": {"type": "number"},
                    "take_profit_pct": {"type": "number"},
                },
            },
        },
    ]


def _stream_response_round(
    client: OpenAI,
    *,
    conversation_items: list[dict[str, Any]],
    system_prompt: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    request_kind: str = "default",
) -> StreamRoundResult:
    if settings.openai_wire_api != "responses":
        raise RuntimeError(f"Unsupported wire API: {settings.openai_wire_api}")

    request_payload = build_responses_request_payload(
        model_name=settings.openai_model,
        conversation_items=conversation_items,
        system_prompt=_system_prompt() if system_prompt is None else system_prompt,
        tools=_tool_definitions() if tools is None else tools,
        stream=True,
        request_kind=request_kind,
    )

    output_text_parts: list[str] = []
    output_items: list[dict[str, Any]] = []
    function_calls_by_item_id: dict[str, dict[str, Any]] = {}
    message_text_keys: set[str] = set()
    finalized_output_item_ids: set[str] = set()
    round_timing = _start_timing()

    with client.responses.with_streaming_response.create(**request_payload) as response:
        for line in response.iter_lines():
            if not line or not line.startswith("data: "):
                continue
            payload = line[6:].strip()
            if not payload or payload == "[DONE]":
                continue
            event = json.loads(payload)
            event_type = str(_event_field(event, "type") or "")
            if event_type == "response.output_item.added":
                item = _event_field(event, "item")
                item_dict = _to_dict(item)
                if item_dict.get("type") == "function_call":
                    item_id = str(item_dict.get("id") or "")
                    if item_id:
                        function_calls_by_item_id[item_id] = item_dict
                continue

            if event_type == "response.function_call_arguments.delta":
                item_id = str(_event_field(event, "item_id") or "")
                delta = str(_event_field(event, "delta") or "")
                if not item_id or not delta:
                    continue
                call = function_calls_by_item_id.setdefault(item_id, {"type": "function_call", "id": item_id, "arguments": ""})
                call["arguments"] = f"{call.get('arguments', '')}{delta}"
                call_id = str(_event_field(event, "call_id") or "")
                if call_id:
                    call["call_id"] = call_id
                continue

            if event_type == "response.function_call_arguments.done":
                item_id = str(_event_field(event, "item_id") or "")
                if not item_id:
                    continue
                call = function_calls_by_item_id.setdefault(item_id, {"type": "function_call", "id": item_id})
                arguments = str(_event_field(event, "arguments") or "")
                if arguments:
                    call["arguments"] = arguments
                continue

            if event_type == "response.output_text.delta":
                delta = str(_event_field(event, "delta") or "")
                if not delta:
                    continue
                item_id = str(_event_field(event, "item_id") or "")
                content_index = _event_field(event, "content_index")
                if item_id and content_index is not None:
                    message_text_keys.add(f"{item_id}:{content_index}")
                output_text_parts.append(delta)
                continue

            if event_type == "response.output_text.done":
                text = str(_event_field(event, "text") or "")
                if not text:
                    continue
                item_id = str(_event_field(event, "item_id") or "")
                content_index = _event_field(event, "content_index")
                if item_id and content_index is not None and f"{item_id}:{content_index}" in message_text_keys:
                    continue
                output_text_parts.append(text)
                continue

            if event_type == "response.output_item.done":
                item = _event_field(event, "item")
                item_dict = _to_dict(item)
                item_id = str(item_dict.get("id") or "")
                item_type = str(item_dict.get("type") or "")
                if item_type == "function_call":
                    merged = dict(function_calls_by_item_id.get(item_id, {}))
                    merged.update(item_dict)
                    if item_id:
                        function_calls_by_item_id[item_id] = merged
                    if not item_id or item_id not in finalized_output_item_ids:
                        output_items.append(merged)
                        if item_id:
                            finalized_output_item_ids.add(item_id)
                    continue

                if item_type == "message":
                    if not item_id or item_id not in finalized_output_item_ids:
                        output_items.append(item_dict)
                        if item_id:
                            finalized_output_item_ids.add(item_id)
                    for index, part in enumerate(item_dict.get("content") or []):
                        if not isinstance(part, dict):
                            continue
                        if part.get("type") != "output_text":
                            continue
                        text = str(part.get("text") or "")
                        if not text:
                            continue
                        if item_id and f"{item_id}:{index}" in message_text_keys:
                            continue
                        output_text_parts.append(text)
                    continue

            if event_type == "error":
                raise build_stream_event_error(_event_field(event, "error"))

    function_calls = [item for item in output_items if item.get("type") == "function_call"]
    output_text = "".join(output_text_parts).strip()
    if function_calls or output_text:
        result_type = "tool_calls" if function_calls else "final_output"
        return StreamRoundResult(
            output_text=output_text,
            output_items=output_items,
            function_calls=function_calls,
            execution_timing=_finish_timing(round_timing),
            result_type=result_type,
        )
    raise RuntimeError("Responses API stream ended without assistant text or function calls.")


def _event_field(event: Any, field_name: str) -> Any:
    if isinstance(event, dict):
        return event.get(field_name)
    return getattr(event, field_name, None)


def _to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(exclude_none=True)
    return {}


def _parse_final_payload(content: str) -> dict[str, Any]:
    parsed = _parse_json_object(content)
    if not isinstance(parsed, dict):
        raise ValueError("Final model response must be a JSON object.")
    return parsed


def _parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def _fallback_non_json_response(
    runtime: ToolRuntime,
    *,
    tool_summaries: list[ToolCallSummary],
    raw_output: str,
    provider: str,
    execution_timing: ExecutionTiming,
    llm_rounds: list[LlmRoundSummary],
) -> ExecuteRunResponse:
    snippet = _compact_model_output(raw_output)
    decision_reason = (
        "Model returned an unstructured final response; execution falls back to skip."
        if not snippet
        else f"Model returned an unstructured final response ({snippet}); execution falls back to skip."
    )
    reasoning_summary = (
        "Model returned non-JSON final output after tool execution, so the runtime failed closed to `skip`."
    )
    return ExecuteRunResponse(
        decision=AgentDecision(
            action="skip",
            symbol=None,
            direction=None,
            size_pct=0.0,
            reason=decision_reason,
            state_patch=dict(runtime.pending_state_patch),
        ),
        reasoning_summary=reasoning_summary,
        tool_calls=tool_summaries,
        provider=provider,
        execution_timing=execution_timing,
        execution_breakdown=_build_execution_breakdown(execution_timing, tool_summaries, llm_rounds),
        llm_rounds=llm_rounds,
    )


def _compact_model_output(raw_output: str, *, limit: int = 160) -> str:
    compact = " ".join(str(raw_output or "").split())
    if not compact:
        return ""
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 3]}..."


def _start_timing() -> TimingCheckpoint:
    return TimingCheckpoint(
        started_at_ms=time.time_ns() // 1_000_000,
        started_monotonic_ns=time.monotonic_ns(),
    )


def _finish_timing(checkpoint: TimingCheckpoint) -> ExecutionTiming:
    completed_at_ms = time.time_ns() // 1_000_000
    duration_ms = max(0, (time.monotonic_ns() - checkpoint.started_monotonic_ns) // 1_000_000)
    return ExecutionTiming(
        started_at_ms=checkpoint.started_at_ms,
        completed_at_ms=max(completed_at_ms, checkpoint.started_at_ms),
        duration_ms=duration_ms,
    )


def _build_llm_round_summary(round_index: int, round_result: StreamRoundResult) -> LlmRoundSummary:
    return LlmRoundSummary(
        round_index=round_index,
        started_at_ms=round_result.execution_timing.started_at_ms,
        completed_at_ms=round_result.execution_timing.completed_at_ms,
        llm_round_duration_ms=round_result.execution_timing.duration_ms,
        tool_call_count=len(round_result.function_calls),
        result_type=round_result.result_type,
    )


def _build_execution_breakdown(
    execution_timing: ExecutionTiming,
    tool_summaries: list[ToolCallSummary],
    llm_rounds: list[LlmRoundSummary],
) -> ExecutionBreakdown:
    tool_execution_total_ms = sum(
        max(0, int(call.execution_timing.duration_ms))
        for call in tool_summaries
        if call.execution_timing is not None
    )
    llm_wait_total_ms = sum(max(0, int(round_summary.llm_round_duration_ms)) for round_summary in llm_rounds)
    other_overhead_ms = max(
        0,
        int(execution_timing.duration_ms) - tool_execution_total_ms - llm_wait_total_ms,
    )
    return ExecutionBreakdown(
        tool_execution_total_ms=tool_execution_total_ms,
        llm_wait_total_ms=llm_wait_total_ms,
        other_overhead_ms=other_overhead_ms,
    )


def _sanitize_decision(payload: ExecuteRunRequest, runtime: ToolRuntime, decision_payload: dict[str, Any]) -> AgentDecision:
    merged = dict(runtime.staged_decision)
    merged.update(decision_payload or {})
    action = str(merged.get("action") or "skip")
    direction = merged.get("direction")
    if action == "open_position" and not direction:
        direction = _preferred_direction(payload.skill_text)

    risk_contract = payload.envelope.get("risk_contract", {}) if isinstance(payload.envelope, dict) else {}
    max_position_pct = float(risk_contract.get("max_position_pct", 0.10) or 0.10)
    size_pct = float(merged.get("size_pct", 0.0) or 0.0)
    if action == "open_position":
        size_pct = max(0.0, min(size_pct, max_position_pct))
    elif action == "reduce_position":
        size_pct = max(0.0, min(size_pct, 1.0))
    else:
        size_pct = 0.0 if action in {"close_position", "skip", "watch", "hold"} else max(0.0, size_pct)

    symbol = merged.get("symbol")
    if isinstance(symbol, str):
        symbol = symbol.strip().upper() or None

    state_patch = dict(runtime.pending_state_patch)
    final_patch = merged.get("state_patch") or {}
    if isinstance(final_patch, dict):
        state_patch.update(final_patch)
    state_patch.setdefault("last_action", action)
    state_patch.setdefault("last_mode", payload.mode)
    if symbol:
        state_patch.setdefault("focus_symbol", symbol)

    stop_loss = _coerce_risk_target(merged.get("stop_loss"))
    take_profit = _coerce_risk_target(merged.get("take_profit"))
    if action == "open_position" and stop_loss is None:
        stop_loss = RiskTarget(type="price_pct", value=DEFAULT_STOP_LOSS_PCT)
    if action == "open_position" and take_profit is None:
        take_profit = RiskTarget(type="price_pct", value=DEFAULT_TAKE_PROFIT_PCT)

    if action in {"skip", "watch", "hold"}:
        size_pct = 0.0
        direction = None
        if action == "skip":
            symbol = None
    elif action == "close_position":
        size_pct = 0.0
        direction = None
    elif action == "reduce_position":
        direction = None

    return AgentDecision(
        action=action,
        symbol=symbol,
        direction=direction,
        size_pct=round(size_pct, 4),
        reason=str(merged.get("reason") or "No explicit reason was returned by the model."),
        stop_loss=stop_loss,
        take_profit=take_profit,
        state_patch=state_patch,
    )


def _coerce_risk_target(value: Any) -> RiskTarget | None:
    if value is None or value == "" or value == 0:
        return None
    if isinstance(value, RiskTarget):
        return value
    if isinstance(value, (int, float)):
        return RiskTarget(type="price_pct", value=float(value))
    if isinstance(value, dict):
        target_type = str(value.get("type") or "price_pct")
        target_value = float(value.get("value"))
        return RiskTarget(type=target_type, value=target_value)
    return None


def _preferred_direction(skill_text: str) -> str:
    lowered = skill_text.lower()
    if any(token in lowered for token in ["short", "sell", "做空"]):
        return "sell"
    return "buy"


def _default_reasoning_summary(tool_calls: list[ToolCallSummary]) -> str:
    if not tool_calls:
        return "The runtime produced a structured decision without additional tool calls."
    ordered = ", ".join(call.tool_name for call in tool_calls)
    return f"The runtime inspected tools in this order: {ordered}."


def _make_json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _make_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_make_json_safe(item) for item in value]
    return str(value)


def _sma(values: list[float], period: int) -> float | None:
    if period <= 0 or not values:
        return None
    window = values[-period:] if len(values) >= period else values
    return sum(window) / len(window)


def _ema(values: list[float], period: int) -> float | None:
    if period <= 0 or not values:
        return None
    if len(values) < period:
        return sum(values) / len(values)
    multiplier = 2 / (period + 1)
    ema_value = sum(values[:period]) / period
    for value in values[period:]:
        ema_value = (value - ema_value) * multiplier + ema_value
    return ema_value


def _rsi(values: list[float], period: int = 14) -> float | None:
    if period <= 0 or len(values) < 2:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(values[:-1], values[1:]):
        change = current - previous
        gains.append(max(change, 0.0))
        losses.append(abs(min(change, 0.0)))
    effective_period = min(period, len(gains))
    avg_gain = sum(gains[:effective_period]) / effective_period
    avg_loss = sum(losses[:effective_period]) / effective_period
    for gain, loss in zip(gains[effective_period:], losses[effective_period:]):
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _atr(candles: list[dict[str, Any]], period: int = 14) -> float | None:
    if period <= 0 or len(candles) < 2:
        return None
    true_ranges: list[float] = []
    previous_close: float | None = None
    for candle in candles:
        high = float(candle["high"])
        low = float(candle["low"])
        if previous_close is None:
            true_ranges.append(high - low)
        else:
            true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
        previous_close = float(candle["close"])
    effective_period = min(period, len(true_ranges))
    if effective_period <= 0:
        return None
    if len(true_ranges) < period:
        return sum(true_ranges) / len(true_ranges)
    return _ema(true_ranges, effective_period)
