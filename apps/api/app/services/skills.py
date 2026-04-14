from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy.orm import Session

from app.models import Skill
from app.services.agent_runner_client import extract_skill_envelope_with_runner
from app.services.envelope_extractor import (
    apply_envelope_defaults,
    collect_missing_fields,
    errors_for_missing_fields,
    extract_skill_envelope_rule_based,
    merge_envelope_patch,
    validate_skill_envelope,
)
from app.services.serializers import skill_to_dict
from app.services.utils import new_id


def create_skill(db: Session, title: str | None, skill_text: str) -> dict:
    rule_result = extract_skill_envelope_rule_based(skill_text, title_override=title)
    base_title = title or rule_result.title
    fallback_used = bool(rule_result.missing_fields)
    fallback_response: dict[str, Any] | None = None

    merged_envelope = rule_result.envelope
    final_title = base_title
    final_warnings = list(rule_result.warnings)
    has_ai_reasoning = rule_result.has_ai_reasoning
    has_risk_control_guidance = rule_result.has_risk_control_guidance

    if fallback_used:
        try:
            fallback_response = extract_skill_envelope_with_runner(
                {
                    "skill_text": skill_text,
                    "title_override": title,
                    "rule_envelope": rule_result.envelope,
                    "rule_errors": rule_result.errors,
                    "rule_warnings": rule_result.warnings,
                    "missing_fields": rule_result.missing_fields,
                }
            )
        except RuntimeError as exc:
            raise ValueError(_build_fallback_failure_message(rule_result.errors, exc)) from exc

        merged_envelope = merge_envelope_patch(rule_result.envelope, _as_dict(fallback_response.get("envelope_patch")))
        response_title = str(fallback_response.get("title") or "").strip() or None
        final_title = final_title or response_title
        final_warnings = _dedupe_preserve_order(
            [
                *rule_result.warnings,
                *list(fallback_response.get("warnings") or []),
                "Rule extraction required LLM fallback before the Skill became executable.",
            ]
        )
        unresolved_fields = {str(item) for item in list(fallback_response.get("unresolved_fields") or [])}
        has_ai_reasoning = has_ai_reasoning or "ai_reasoning" not in unresolved_fields
        has_risk_control_guidance = has_risk_control_guidance or "risk_control_guidance" not in unresolved_fields

    envelope_with_defaults = apply_envelope_defaults(merged_envelope)
    missing_fields = collect_missing_fields(
        title=final_title,
        envelope=envelope_with_defaults,
        has_ai_reasoning=has_ai_reasoning,
        has_risk_control_guidance=has_risk_control_guidance,
    )
    validation = validate_skill_envelope(envelope_with_defaults)
    final_errors = _dedupe_preserve_order([*errors_for_missing_fields(missing_fields), *validation.errors])
    final_warnings = _dedupe_preserve_order([*final_warnings, *validation.warnings])
    if final_errors:
        raise ValueError("; ".join(final_errors))

    extraction_method = "llm_fallback" if fallback_used else "rule_only"
    provider = str((fallback_response or {}).get("provider") or "rule-based")
    reasoning_summary = str(
        (fallback_response or {}).get("reasoning_summary")
        or "Rule-based extraction satisfied the upload requirements without LLM fallback."
    )
    envelope_with_defaults["extraction_meta"] = {
        "method": extraction_method,
        "fallback_used": fallback_used,
        "provider": provider,
        "reasoning_summary": reasoning_summary,
        "rule_failure_reasons": list(rule_result.errors),
    }

    skill = Skill(
        id=new_id("skill"),
        title=final_title or skill_text.splitlines()[0].lstrip("# ").strip(),
        raw_text=skill_text,
        source_hash=f"sha256:{hashlib.sha256(skill_text.encode('utf-8')).hexdigest()}",
        validation_status="passed",
        envelope_json=envelope_with_defaults,
        validation_errors_json=[],
        validation_warnings_json=final_warnings,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill_to_dict(skill)


def _build_fallback_failure_message(rule_errors: list[str], exc: RuntimeError) -> str:
    combined = [*rule_errors, f"LLM fallback failed: {exc}"]
    return "; ".join(_dedupe_preserve_order(combined))


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
