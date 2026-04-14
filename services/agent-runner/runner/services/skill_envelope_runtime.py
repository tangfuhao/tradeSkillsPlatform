from __future__ import annotations

import json
from typing import Any

from runner.config import settings
from runner.schemas import SkillEnvelopeExtractRequest, SkillEnvelopeExtractResponse
from runner.services.model_routing import get_responses_client
from runner.services.openai_runtime import _parse_final_payload, _stream_response_round


class OpenAISkillEnvelopeExtractionEngine:
    provider: str = "openai-skill-envelope"

    def extract(self, payload: SkillEnvelopeExtractRequest) -> SkillEnvelopeExtractResponse:
        client = get_responses_client(settings.openai_model)
        round_result = _stream_response_round(
            client,
            conversation_items=_build_prompt_input_items(payload),
            system_prompt=_system_prompt(),
            tools=[],
        )
        try:
            final_payload = _parse_final_payload(round_result.output_text)
        except ValueError as exc:
            raise RuntimeError("Skill envelope extraction returned non-JSON final output.") from exc

        envelope_patch = final_payload.get("envelope_patch") or {}
        if not isinstance(envelope_patch, dict):
            raise RuntimeError("Skill envelope extraction must return an object in `envelope_patch`.")

        warnings = final_payload.get("warnings") or []
        if not isinstance(warnings, list):
            raise RuntimeError("Skill envelope extraction must return `warnings` as an array.")

        unresolved_fields = final_payload.get("unresolved_fields") or []
        if not isinstance(unresolved_fields, list):
            raise RuntimeError("Skill envelope extraction must return `unresolved_fields` as an array.")

        return SkillEnvelopeExtractResponse(
            title=_clean_optional_text(final_payload.get("title")),
            envelope_patch=envelope_patch,
            warnings=[str(item) for item in warnings],
            unresolved_fields=[str(item) for item in unresolved_fields],
            reasoning_summary=str(
                final_payload.get("reasoning_summary")
                or _default_reasoning_summary([str(item) for item in unresolved_fields])
            ),
            provider=self.provider,
        )


def _build_prompt_input_items(payload: SkillEnvelopeExtractRequest) -> list[dict[str, Any]]:
    return [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": _build_prompt_text(payload)}],
        }
    ]


def _build_prompt_text(payload: SkillEnvelopeExtractRequest) -> str:
    return (
        "Extract a conservative Skill Envelope patch from this trading Skill.\n\n"
        "Skill text:\n"
        f"{payload.skill_text}\n\n"
        "Rule envelope (authoritative when fields are already present):\n"
        f"{json.dumps(payload.rule_envelope, ensure_ascii=False)}\n\n"
        "Rule extraction errors:\n"
        f"{json.dumps(payload.rule_errors, ensure_ascii=False)}\n\n"
        "Rule extraction warnings:\n"
        f"{json.dumps(payload.rule_warnings, ensure_ascii=False)}\n\n"
        "Missing fields that still need attention:\n"
        f"{json.dumps(payload.missing_fields, ensure_ascii=False)}"
    )


def _system_prompt() -> str:
    return (
        "You extract a conservative runtime envelope patch from a natural-language trading Skill.\n\n"
        "Rules:\n"
        "1. Return JSON only. Do not include markdown code fences.\n"
        "2. Use only evidence from the Skill text and the supplied rule extraction context.\n"
        "3. Do not overwrite fields that already exist in `rule_envelope`; only fill missing data.\n"
        "4. Never invent a cadence if the Skill text does not explicitly support one.\n"
        "5. Never invent numeric hard risk limits such as max_position_pct, max_daily_loss_pct, or max_concurrent_positions.\n"
        "6. It is acceptable to normalize wording like '10 percent' into decimal values such as 0.10 when the number is explicit in the Skill text.\n"
        "7. If a field remains unsupported by the text, keep it out of `envelope_patch` and list it in `unresolved_fields`.\n"
        "8. `unresolved_fields` may include values like title, ai_reasoning, risk_control_guidance, trigger.value, risk_contract.max_position_pct, risk_contract.max_daily_loss_pct, risk_contract.max_concurrent_positions.\n"
        "9. Keep `warnings` short and factual.\n"
        "10. Output exactly this JSON shape:\n"
        "{\n"
        '  "title": "string or null",\n'
        '  "reasoning_summary": "short summary",\n'
        '  "envelope_patch": {},\n'
        '  "warnings": ["..."],\n'
        '  "unresolved_fields": ["..."]\n'
        "}"
    )


def _default_reasoning_summary(unresolved_fields: list[str]) -> str:
    if not unresolved_fields:
        return "The extractor resolved the remaining envelope gaps from the Skill text."
    unresolved = ", ".join(unresolved_fields)
    return f"The extractor filled only text-supported fields and left these unresolved: {unresolved}."


def _clean_optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
