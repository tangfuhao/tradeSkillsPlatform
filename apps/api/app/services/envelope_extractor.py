from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ExtractionResult:
    envelope: dict[str, Any]
    errors: list[str]
    warnings: list[str]


def extract_skill_envelope(skill_text: str, title_override: str | None = None) -> ExtractionResult:
    title = title_override or _extract_title(skill_text)
    cadence = _extract_cadence(skill_text)
    errors: list[str] = []
    warnings: list[str] = []

    if not title:
        errors.append("Skill title could not be identified.")
    if not cadence:
        errors.append("Execution cadence could not be identified. Include phrases like 'Every 15 minutes' or '每 15 分钟'.")
    if not _contains_ai_reasoning(skill_text):
        errors.append("Skill must include an identifiable AI reasoning step.")
    if not _contains_risk_control(skill_text):
        errors.append("Skill must include explicit stop-loss or risk-control guidance.")

    if errors:
        return ExtractionResult(envelope={}, errors=errors, warnings=warnings)

    required_tools = _detect_required_tools(skill_text)
    optional_tools = ["get_market_metadata"]
    needs_market_scan = "scan_market" in required_tools
    needs_python = "python_exec" in required_tools
    market_context = {
        "venue": _extract_venue(skill_text),
        "instrument_type": "swap" if _mentions_swap(skill_text) else "spot",
        "quote_asset": "USDT",
        "scan_scope": "all_usdt_swaps" if _mentions_swap(skill_text) else "named_symbols_only",
        "supports_short": _supports_short(skill_text),
    }
    risk_contract = {
        "max_position_pct": _extract_pct(skill_text, default=0.10, keywords=["position", "equity", "资金", "仓位"]),
        "requires_stop_loss": True,
        "max_daily_loss_pct": _extract_pct(skill_text, default=0.08, keywords=["daily", "drawdown", "回撤"]),
        "max_concurrent_positions": _extract_integer(skill_text, default=2, keywords=["concurrent", "同时", "最多"]),
        "allow_hedging": False,
    }
    envelope = {
        "schema_version": "skill_envelope.v1",
        "runtime_modes": ["backtest", "live_signal"],
        "trigger": {
            "type": "interval",
            "value": cadence,
            "timezone": "UTC",
            "trigger_on": "bar_close",
        },
        "market_context": market_context,
        "tool_contract": {
            "required_tools": required_tools,
            "optional_tools": optional_tools,
        },
        "output_contract": {
            "schema": "trade_signal_v1",
            "required_fields": [
                "action",
                "symbol",
                "direction",
                "size_pct",
                "reason",
            ],
        },
        "risk_contract": risk_contract,
        "state_contract": {
            "externalized": True,
            "read_tool": "get_strategy_state",
            "write_tool": "save_strategy_state",
        },
        "runtime_profile": {
            "needs_market_scan": needs_market_scan,
            "needs_python_sandbox": needs_python,
        },
        "extraction_notes": _build_notes(skill_text, market_context),
    }
    return ExtractionResult(envelope=envelope, errors=[], warnings=warnings)


def _extract_title(skill_text: str) -> str | None:
    for line in skill_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("# ")
    return None


def _extract_cadence(skill_text: str) -> str | None:
    patterns = [
        (re.compile(r"every\s+(\d+)\s*(minute|minutes|min|hour|hours|day|days|m|h|d)", re.IGNORECASE), _normalize_unit),
        (re.compile(r"每\s*(\d+)\s*(分钟|分|小时|天|m|h|d)", re.IGNORECASE), _normalize_cn_unit),
        (re.compile(r"\b(\d+)\s*([mhd])\b", re.IGNORECASE), lambda n, u: f"{n}{u.lower()}"),
    ]
    for pattern, formatter in patterns:
        match = pattern.search(skill_text)
        if match:
            return formatter(match.group(1), match.group(2))
    return None


def _normalize_unit(number: str, unit: str) -> str:
    lowered = unit.lower()
    if lowered.startswith("minute") or lowered == "min":
        return f"{number}m"
    if lowered.startswith("hour"):
        return f"{number}h"
    if lowered.startswith("day"):
        return f"{number}d"
    return f"{number}{lowered}"


def _normalize_cn_unit(number: str, unit: str) -> str:
    if unit in {"分钟", "分"}:
        return f"{number}m"
    if unit == "小时":
        return f"{number}h"
    if unit == "天":
        return f"{number}d"
    return f"{number}{unit.lower()}"


def _contains_ai_reasoning(skill_text: str) -> bool:
    lowered = skill_text.lower()
    keywords = ["ai", "reasoning", "reason", "综合判断", "推理", "判断"]
    return any(keyword in lowered for keyword in keywords)


def _contains_risk_control(skill_text: str) -> bool:
    lowered = skill_text.lower()
    keywords = ["risk", "stop loss", "stop-loss", "drawdown", "止损", "风控", "回撤", "仓位"]
    return any(keyword in lowered for keyword in keywords)


def _detect_required_tools(skill_text: str) -> list[str]:
    lowered = skill_text.lower()
    tools = {"get_strategy_state", "save_strategy_state"}
    if any(token in lowered for token in ["scan", "watchlist", "市场", "标的", "altcoin"]):
        tools.add("scan_market")
    if any(token in lowered for token in ["candle", "ohlcv", "ema", "rsi", "atr", "k线"]):
        tools.add("get_candles")
    if any(token in lowered for token in ["funding", "资金费率"]):
        tools.add("get_funding_rate")
    if any(token in lowered for token in ["open interest", "持仓量"]):
        tools.add("get_open_interest")
    if any(token in lowered for token in ["python", "script", "脚本"]):
        tools.add("python_exec")
    if any(token in lowered for token in ["notify", "signal", "telegram", "webhook", "通知"]):
        tools.add("emit_signal")
    if any(token in lowered for token in ["open", "close", "short", "long", "做空", "做多", "开仓", "平仓"]):
        tools.add("simulate_order")
    return sorted(tools)


def _extract_venue(skill_text: str) -> str:
    lowered = skill_text.lower()
    if "okx" in lowered or "okex" in lowered:
        return "okx"
    return "demo"


def _mentions_swap(skill_text: str) -> bool:
    lowered = skill_text.lower()
    return any(token in lowered for token in ["swap", "perpetual", "永续", "合约"])


def _supports_short(skill_text: str) -> bool:
    lowered = skill_text.lower()
    return any(token in lowered for token in ["short", "sell", "做空"])


def _extract_pct(skill_text: str, default: float, keywords: list[str]) -> float:
    for line in skill_text.splitlines():
        lowered = line.lower()
        if not any(keyword in lowered for keyword in keywords):
            continue
        match = re.search(r"(\d+(?:\.\d+)?)\s*%", line)
        if match:
            return round(float(match.group(1)) / 100.0, 4)
    return default


def _extract_integer(skill_text: str, default: int, keywords: list[str]) -> int:
    for line in skill_text.splitlines():
        lowered = line.lower()
        if not any(keyword in lowered for keyword in keywords):
            continue
        match = re.search(r"(\d+)", line)
        if match:
            return int(match.group(1))
    return default


def _build_notes(skill_text: str, market_context: dict[str, Any]) -> list[str]:
    notes = [
        "Envelope extracted from natural-language Skill text.",
        f"Detected venue: {market_context['venue']}.",
        f"Detected instrument type: {market_context['instrument_type']}.",
    ]
    if market_context["supports_short"]:
        notes.append("Skill appears to support short positioning.")
    return notes
