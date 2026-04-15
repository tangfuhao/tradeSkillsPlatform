from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from app.core.config import REPO_ROOT

SCHEMA_PATH = REPO_ROOT / "packages" / "shared-schemas" / "skill-envelope.schema.json"
DEFAULT_OPTIONAL_TOOLS = ["get_market_metadata"]
DEFAULT_OUTPUT_CONTRACT = {
    "schema": "trade_signal_v1",
    "required_fields": ["action", "symbol", "direction", "size_pct", "reason"],
}
DEFAULT_STATE_CONTRACT = {
    "externalized": True,
    "read_tool": "get_strategy_state",
    "write_tool": "save_strategy_state",
}
FIELD_ERROR_MESSAGES = {
    "title": "Skill title could not be identified.",
    "trigger.value": (
        "Execution cadence could not be identified. Include phrases like 'Every 15 minutes' or '每 15 分钟'."
    ),
    "ai_reasoning": "Skill must include an identifiable AI reasoning step.",
    "risk_control_guidance": "Skill must include explicit stop-loss or risk-control guidance.",
    "risk_contract.max_position_pct": "Skill must define a maximum position sizing rule with an explicit percentage.",
    "risk_contract.max_daily_loss_pct": "Skill must define a maximum daily loss or drawdown rule with an explicit percentage.",
    "risk_contract.max_concurrent_positions": "Skill must define a maximum concurrent positions limit.",
}


@dataclass(slots=True)
class RuleExtractionResult:
    title: str | None
    envelope: dict[str, Any]
    missing_fields: list[str]
    errors: list[str]
    warnings: list[str]
    has_ai_reasoning: bool
    has_risk_control_guidance: bool


@dataclass(slots=True)
class EnvelopeValidationResult:
    errors: list[str]
    warnings: list[str]


@lru_cache(maxsize=1)
def load_skill_envelope_schema() -> dict[str, Any]:
    return json.loads(Path(SCHEMA_PATH).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def get_skill_envelope_validator() -> Draft202012Validator:
    return Draft202012Validator(load_skill_envelope_schema())


def extract_skill_envelope_rule_based(skill_text: str, title_override: str | None = None) -> RuleExtractionResult:
    title = title_override or _extract_title(skill_text)
    cadence = _extract_cadence(skill_text)
    has_ai_reasoning = _contains_ai_reasoning(skill_text)
    has_risk_control_guidance = _contains_risk_control(skill_text)

    required_tools = _detect_required_tools(skill_text)
    market_context = _extract_market_context(skill_text)
    risk_contract = _extract_risk_contract(skill_text)
    envelope: dict[str, Any] = {
        "tool_contract": {
            "required_tools": required_tools,
        },
        "runtime_profile": {
            "needs_market_scan": "scan_market" in required_tools,
            "needs_python_sandbox": "python_exec" in required_tools,
        },
        "extraction_notes": _build_notes(market_context),
    }
    if cadence:
        envelope["trigger"] = {"value": cadence}
    if market_context:
        envelope["market_context"] = market_context
    if risk_contract:
        envelope["risk_contract"] = risk_contract

    missing_fields = collect_missing_fields(
        title=title,
        envelope=envelope,
        has_ai_reasoning=has_ai_reasoning,
        has_risk_control_guidance=has_risk_control_guidance,
    )
    return RuleExtractionResult(
        title=title,
        envelope=envelope,
        missing_fields=missing_fields,
        errors=errors_for_missing_fields(missing_fields),
        warnings=[],
        has_ai_reasoning=has_ai_reasoning,
        has_risk_control_guidance=has_risk_control_guidance,
    )


def collect_missing_fields(
    *,
    title: str | None,
    envelope: dict[str, Any],
    has_ai_reasoning: bool,
    has_risk_control_guidance: bool,
) -> list[str]:
    missing_fields: list[str] = []
    if not title:
        missing_fields.append("title")
    if not has_ai_reasoning:
        missing_fields.append("ai_reasoning")
    if not has_risk_control_guidance:
        missing_fields.append("risk_control_guidance")

    trigger = envelope.get("trigger") if isinstance(envelope, dict) else {}
    if not isinstance(trigger, dict) or not str(trigger.get("value") or "").strip():
        missing_fields.append("trigger.value")

    risk_contract = envelope.get("risk_contract") if isinstance(envelope, dict) else {}
    if not isinstance(risk_contract, dict):
        risk_contract = {}
    for field_name in (
        "risk_contract.max_position_pct",
        "risk_contract.max_daily_loss_pct",
        "risk_contract.max_concurrent_positions",
    ):
        field_key = field_name.split(".")[-1]
        value = risk_contract.get(field_key)
        if value is None:
            missing_fields.append(field_name)

    return missing_fields


def errors_for_missing_fields(missing_fields: list[str]) -> list[str]:
    return _dedupe_preserve_order([FIELD_ERROR_MESSAGES[field] for field in missing_fields if field in FIELD_ERROR_MESSAGES])


def merge_envelope_patch(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    _merge_missing_values(merged, patch)
    return merged


def apply_envelope_defaults(envelope: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(envelope)
    merged.setdefault("schema_version", "skill_envelope.v1")

    trigger = merged.setdefault("trigger", {})
    if isinstance(trigger, dict):
        trigger.setdefault("type", "interval")
        trigger.setdefault("timezone", "UTC")
        trigger.setdefault("trigger_on", "bar_close")

    tool_contract = merged.setdefault("tool_contract", {})
    if isinstance(tool_contract, dict):
        required_tools = list(tool_contract.get("required_tools") or [])
        if not required_tools:
            required_tools = ["get_strategy_state", "save_strategy_state"]
        else:
            required_tools = _dedupe_preserve_order(required_tools)
            for tool_name in ["get_strategy_state", "save_strategy_state"]:
                if tool_name not in required_tools:
                    required_tools.insert(0, tool_name)
            required_tools = _dedupe_preserve_order(required_tools)
        tool_contract["required_tools"] = required_tools
        tool_contract.setdefault("optional_tools", list(DEFAULT_OPTIONAL_TOOLS))

    merged.setdefault("output_contract", copy.deepcopy(DEFAULT_OUTPUT_CONTRACT))
    merged.setdefault("state_contract", copy.deepcopy(DEFAULT_STATE_CONTRACT))

    risk_contract = merged.setdefault("risk_contract", {})
    if isinstance(risk_contract, dict):
        risk_contract.setdefault("requires_stop_loss", True)
        risk_contract.setdefault("allow_hedging", False)

    runtime_profile = merged.setdefault("runtime_profile", {})
    if isinstance(runtime_profile, dict):
        required_tools = tool_contract.get("required_tools") if isinstance(tool_contract, dict) else []
        runtime_profile.setdefault("needs_market_scan", "scan_market" in (required_tools or []))
        runtime_profile.setdefault("needs_python_sandbox", "python_exec" in (required_tools or []))

    market_context = merged.get("market_context")
    if isinstance(market_context, dict):
        instrument_type = market_context.get("instrument_type")
        if instrument_type == "swap":
            market_context.setdefault("scan_scope", "all_usdt_swaps")
        elif instrument_type:
            market_context.setdefault("scan_scope", "named_symbols_only")

    notes = list(merged.get("extraction_notes") or [])
    if not notes:
        notes.append("Envelope extracted from natural-language Skill text.")
    merged["extraction_notes"] = _dedupe_preserve_order(notes)
    return merged


def validate_skill_envelope(envelope: dict[str, Any]) -> EnvelopeValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    for issue in sorted(get_skill_envelope_validator().iter_errors(envelope), key=lambda item: list(item.absolute_path)):
        errors.append(_format_jsonschema_error(issue))

    trigger = envelope.get("trigger") if isinstance(envelope, dict) else {}
    if not isinstance(trigger, dict) or not str(trigger.get("value") or "").strip():
        errors.append(FIELD_ERROR_MESSAGES["trigger.value"])

    risk_contract = envelope.get("risk_contract") if isinstance(envelope, dict) else {}
    if not isinstance(risk_contract, dict):
        risk_contract = {}
    for field_name in (
        "risk_contract.max_position_pct",
        "risk_contract.max_daily_loss_pct",
        "risk_contract.max_concurrent_positions",
    ):
        field_key = field_name.split(".")[-1]
        if risk_contract.get(field_key) is None:
            errors.append(FIELD_ERROR_MESSAGES[field_name])

    tool_contract = envelope.get("tool_contract") if isinstance(envelope, dict) else {}
    if not isinstance(tool_contract, dict) or not list(tool_contract.get("required_tools") or []):
        errors.append("Skill Envelope must include at least one required tool.")

    output_contract = envelope.get("output_contract") if isinstance(envelope, dict) else {}
    if not isinstance(output_contract, dict):
        errors.append("Skill Envelope must include an output contract.")

    state_contract = envelope.get("state_contract") if isinstance(envelope, dict) else {}
    if not isinstance(state_contract, dict):
        errors.append("Skill Envelope must include a state contract.")

    return EnvelopeValidationResult(
        errors=_dedupe_preserve_order(errors),
        warnings=_dedupe_preserve_order(warnings),
    )


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
    tools = ["get_strategy_state", "save_strategy_state"]
    if any(token in lowered for token in ["scan", "watchlist", "市场", "标的", "altcoin"]):
        tools.append("scan_market")
    if any(token in lowered for token in ["candle", "ohlcv", "ema", "rsi", "atr", "k线"]):
        tools.append("get_candles")
    if any(token in lowered for token in ["funding", "资金费率"]):
        tools.append("get_funding_rate")
    if any(token in lowered for token in ["open interest", "持仓量"]):
        tools.append("get_open_interest")
    if any(token in lowered for token in ["python", "script", "脚本"]):
        tools.append("python_exec")
    if any(token in lowered for token in ["notify", "signal", "telegram", "webhook", "通知"]):
        tools.append("emit_signal")
    if any(token in lowered for token in ["open", "close", "short", "long", "做空", "做多", "开仓", "平仓"]):
        tools.append("simulate_order")
    return _dedupe_preserve_order(tools)


def _extract_market_context(skill_text: str) -> dict[str, Any]:
    lowered = skill_text.lower()
    market_context: dict[str, Any] = {}
    if "okx" in lowered or "okex" in lowered:
        market_context["venue"] = "okx"
    if any(token in lowered for token in ["swap", "perpetual", "永续", "合约"]):
        market_context["instrument_type"] = "swap"
    elif "spot" in lowered or "现货" in lowered:
        market_context["instrument_type"] = "spot"
    quote_asset = _extract_quote_asset(skill_text)
    if quote_asset:
        market_context["quote_asset"] = quote_asset
    if any(token in lowered for token in ["short", "sell", "做空"]):
        market_context["supports_short"] = True
    elif any(token in lowered for token in ["long-only", "long only", "只做多", "做多"]):
        market_context["supports_short"] = False
    return market_context


def _extract_quote_asset(skill_text: str) -> str | None:
    upper_text = skill_text.upper()
    for asset in ("USDT", "USDC", "USD"):
        if asset in upper_text:
            return asset
    return None


def _extract_risk_contract(skill_text: str) -> dict[str, Any]:
    risk_contract: dict[str, Any] = {}
    max_position_pct = _extract_pct(skill_text, keywords=["position", "equity", "资金", "仓位"])
    if max_position_pct is not None:
        risk_contract["max_position_pct"] = max_position_pct
    max_daily_loss_pct = _extract_pct(skill_text, keywords=["daily", "drawdown", "回撤"])
    if max_daily_loss_pct is not None:
        risk_contract["max_daily_loss_pct"] = max_daily_loss_pct
    max_concurrent_positions = _extract_integer(skill_text, keywords=["concurrent", "同时", "最多"])
    if max_concurrent_positions is not None:
        risk_contract["max_concurrent_positions"] = max_concurrent_positions
    return risk_contract


def _extract_pct(skill_text: str, keywords: list[str]) -> float | None:
    for line in skill_text.splitlines():
        lowered = line.lower()
        if not any(keyword in lowered for keyword in keywords):
            continue
        for keyword in keywords:
            if keyword not in lowered:
                continue
            keyword_pattern = re.escape(keyword)
            after_keyword = re.search(rf"{keyword_pattern}[^0-9%]*(\d+(?:\.\d+)?)\s*%", lowered)
            if after_keyword:
                return round(float(after_keyword.group(1)) / 100.0, 4)
            before_keyword = re.search(rf"(\d+(?:\.\d+)?)\s*%[^\n%]*{keyword_pattern}", lowered)
            if before_keyword:
                return round(float(before_keyword.group(1)) / 100.0, 4)
        match = re.search(r"(\d+(?:\.\d+)?)\s*%", line)
        if match:
            return round(float(match.group(1)) / 100.0, 4)
    return None


def _extract_integer(skill_text: str, keywords: list[str]) -> int | None:
    for line in skill_text.splitlines():
        lowered = line.lower()
        if not any(keyword in lowered for keyword in keywords):
            continue
        for keyword in keywords:
            if keyword not in lowered:
                continue
            keyword_pattern = re.escape(keyword)
            after_keyword = re.search(rf"{keyword_pattern}[^0-9]*(\d+)", lowered)
            if after_keyword:
                return int(after_keyword.group(1))
            before_keyword = re.search(rf"(\d+)[^\n]*{keyword_pattern}", lowered)
            if before_keyword:
                return int(before_keyword.group(1))
        match = re.search(r"(\d+)", line)
        if match:
            return int(match.group(1))
    return None


def _build_notes(market_context: dict[str, Any]) -> list[str]:
    notes = ["Envelope extracted from natural-language Skill text."]
    if market_context.get("venue"):
        notes.append(f"Detected venue: {market_context['venue']}.")
    if market_context.get("instrument_type"):
        notes.append(f"Detected instrument type: {market_context['instrument_type']}.")
    if market_context.get("supports_short") is True:
        notes.append("Skill appears to support short positioning.")
    return notes


def _merge_missing_values(base: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, patch_value in patch.items():
        if key not in base or _is_empty_value(base[key]):
            base[key] = copy.deepcopy(patch_value)
            continue
        base_value = base[key]
        if isinstance(base_value, dict) and isinstance(patch_value, dict):
            _merge_missing_values(base_value, patch_value)
            continue
        if isinstance(base_value, list) and isinstance(patch_value, list):
            base[key] = _dedupe_preserve_order([*base_value, *patch_value])


def _is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict, tuple, set)):
        return not value
    return False


def _format_jsonschema_error(issue: Any) -> str:
    path = ".".join(str(part) for part in issue.absolute_path)
    if path:
        return f"Skill Envelope schema validation failed at {path}: {issue.message}"
    return f"Skill Envelope schema validation failed: {issue.message}"


def _dedupe_preserve_order(values: list[Any] | tuple[Any, ...] | Any) -> list[Any]:
    if not isinstance(values, (list, tuple)):
        values = [values]
    deduped: list[Any] = []
    seen: set[Any] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
