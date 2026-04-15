from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import Skill
from app.services.serializers import skill_to_dict
from app.services.skills import create_skill


RULE_ONLY_SKILL = """# Momentum Breakout Skill

## Execution Cadence
Every 15 minutes.

## AI Reasoning
Use AI reasoning to judge whether the breakout is strong enough.

## Risk Control
- Max position size: 10%
- Max daily drawdown: 8%
- Max concurrent positions: 2
- Stop loss: 2%
"""

TITLE_FALLBACK_SKILL = """Momentum breakout setup for OKX swaps.

Run this workflow every 15 minutes.
Use AI reasoning to judge whether momentum still supports a follow-through trade.
Risk control: stop loss 2%, max position size 10%, max daily drawdown 8%, max concurrent positions 2.
"""

NO_CADENCE_SKILL = """# Missing Cadence Skill

## AI Reasoning
Use AI reasoning to decide whether to open a position.

## Risk Control
- Max position size: 10%
- Max daily drawdown: 8%
- Max concurrent positions: 2
- Stop loss: 2%
"""

MISSING_NUMERIC_RISK_SKILL = """# Missing Numeric Risk Skill

## Execution Cadence
Every 15 minutes.

## AI Reasoning
Use AI reasoning to judge whether the market is strong enough.

## Risk Control
Always use stop loss and keep risk controlled.
"""


class SkillCreationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, future=True)
        self.session_factory = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, future=True)
        Base.metadata.create_all(self.engine)
        self.db = self.session_factory()

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_create_skill_uses_rule_only_when_rule_extraction_is_complete(self) -> None:
        created = create_skill(self.db, None, RULE_ONLY_SKILL)

        self.assertEqual(created["extraction_method"], "rule_only")
        self.assertFalse(created["fallback_used"])
        self.assertEqual(created["envelope"]["trigger"]["value"], "15m")
        self.assertNotIn("runtime_modes", created["envelope"])

    def test_create_skill_uses_llm_fallback_without_overwriting_rule_fields(self) -> None:
        fallback_response = {
            "title": "LLM Generated Title",
            "envelope_patch": {
                "trigger": {"value": "1h"},
                "risk_contract": {
                    "max_position_pct": 0.25,
                    "max_daily_loss_pct": 0.15,
                    "max_concurrent_positions": 4,
                },
            },
            "warnings": ["Title inferred from body text."],
            "unresolved_fields": [],
            "reasoning_summary": "Filled the missing title from the first sentence.",
            "provider": "mock-runner",
        }
        with patch("app.services.skills.extract_skill_envelope_with_runner", return_value=fallback_response):
            created = create_skill(self.db, None, TITLE_FALLBACK_SKILL)

        self.assertEqual(created["title"], "LLM Generated Title")
        self.assertEqual(created["extraction_method"], "llm_fallback")
        self.assertTrue(created["fallback_used"])
        self.assertEqual(created["envelope"]["trigger"]["value"], "15m")
        self.assertIn("Rule extraction required LLM fallback", " ".join(created["validation_warnings"]))

    def test_create_skill_rejects_missing_cadence_when_fallback_cannot_resolve_it(self) -> None:
        fallback_response = {
            "title": None,
            "envelope_patch": {},
            "warnings": [],
            "unresolved_fields": ["trigger.value"],
            "reasoning_summary": "Cadence remained unresolved.",
            "provider": "mock-runner",
        }
        with patch("app.services.skills.extract_skill_envelope_with_runner", return_value=fallback_response):
            with self.assertRaises(ValueError) as exc_info:
                create_skill(self.db, None, NO_CADENCE_SKILL)

        self.assertIn("Execution cadence could not be identified", str(exc_info.exception))

    def test_create_skill_rejects_missing_numeric_risk_limits_after_fallback(self) -> None:
        fallback_response = {
            "title": None,
            "envelope_patch": {},
            "warnings": [],
            "unresolved_fields": [
                "risk_contract.max_position_pct",
                "risk_contract.max_daily_loss_pct",
                "risk_contract.max_concurrent_positions",
            ],
            "reasoning_summary": "The text does not provide explicit numeric hard limits.",
            "provider": "mock-runner",
        }
        with patch("app.services.skills.extract_skill_envelope_with_runner", return_value=fallback_response):
            with self.assertRaises(ValueError) as exc_info:
                create_skill(self.db, None, MISSING_NUMERIC_RISK_SKILL)

        error_text = str(exc_info.exception)
        self.assertIn("maximum position sizing rule", error_text)
        self.assertIn("maximum daily loss or drawdown", error_text)
        self.assertIn("maximum concurrent positions limit", error_text)

    def test_create_skill_surfaces_runner_failures_when_fallback_is_required(self) -> None:
        with patch(
            "app.services.skills.extract_skill_envelope_with_runner",
            side_effect=RuntimeError("runner unavailable"),
        ):
            with self.assertRaises(ValueError) as exc_info:
                create_skill(self.db, None, TITLE_FALLBACK_SKILL)

        self.assertIn("LLM fallback failed: runner unavailable", str(exc_info.exception))

    def test_create_skill_rejects_schema_invalid_envelope_patch(self) -> None:
        fallback_response = {
            "title": None,
            "envelope_patch": {
                "trigger": {"value": "15 minutes"},
                "risk_contract": {
                    "max_position_pct": 0.10,
                    "max_daily_loss_pct": 0.08,
                    "max_concurrent_positions": 2,
                },
            },
            "warnings": [],
            "unresolved_fields": [],
            "reasoning_summary": "Cadence wording was copied verbatim from the text.",
            "provider": "mock-runner",
        }
        with patch("app.services.skills.extract_skill_envelope_with_runner", return_value=fallback_response):
            with self.assertRaises(ValueError) as exc_info:
                create_skill(self.db, None, NO_CADENCE_SKILL)

        self.assertIn("Skill Envelope schema validation failed at trigger.value", str(exc_info.exception))

    def test_skill_is_persisted_with_extraction_meta(self) -> None:
        created = create_skill(self.db, None, RULE_ONLY_SKILL)
        stored = self.db.scalars(select(Skill).where(Skill.id == created["id"])).one()
        extraction_meta = stored.envelope_json.get("extraction_meta")

        self.assertEqual(extraction_meta["method"], "rule_only")
        self.assertFalse(extraction_meta["fallback_used"])
        self.assertIn("reasoning_summary", extraction_meta)
        self.assertNotIn("runtime_modes", stored.envelope_json)

    def test_skill_serializer_hides_legacy_runtime_modes(self) -> None:
        created = create_skill(self.db, None, RULE_ONLY_SKILL)
        stored = self.db.scalars(select(Skill).where(Skill.id == created["id"])).one()
        stored.envelope_json = {
            **stored.envelope_json,
            "runtime_modes": ["backtest", "live_signal"],
        }

        payload = skill_to_dict(stored)

        self.assertNotIn("runtime_modes", payload["envelope"])


if __name__ == "__main__":
    unittest.main()
