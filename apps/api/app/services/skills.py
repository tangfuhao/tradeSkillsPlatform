from __future__ import annotations

import hashlib

from sqlalchemy.orm import Session

from app.models import Skill
from app.services.envelope_extractor import extract_skill_envelope
from app.services.serializers import skill_to_dict
from app.services.utils import new_id


def create_skill(db: Session, title: str | None, skill_text: str) -> dict:
    extraction = extract_skill_envelope(skill_text, title_override=title)
    if extraction.errors:
        raise ValueError("; ".join(extraction.errors))
    skill = Skill(
        id=new_id("skill"),
        title=title or skill_text.splitlines()[0].lstrip("# ").strip(),
        raw_text=skill_text,
        source_hash=f"sha256:{hashlib.sha256(skill_text.encode('utf-8')).hexdigest()}",
        validation_status="passed",
        envelope_json=extraction.envelope,
        validation_errors_json=extraction.errors,
        validation_warnings_json=extraction.warnings,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill_to_dict(skill)
