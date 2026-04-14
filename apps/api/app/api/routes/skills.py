from sqlalchemy import select
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Skill
from app.schemas import SkillCreateRequest, SkillResponse
from app.services.serializers import skill_to_dict
from app.services.skills import create_skill


router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("", response_model=list[SkillResponse])
def list_skills(db: Session = Depends(get_db)) -> list[SkillResponse]:
    skills = db.scalars(select(Skill).order_by(Skill.created_at.desc())).all()
    return [SkillResponse.model_validate(skill_to_dict(skill)) for skill in skills]


@router.post("", response_model=SkillResponse, status_code=status.HTTP_201_CREATED)
def create_skill_route(payload: SkillCreateRequest, db: Session = Depends(get_db)) -> SkillResponse:
    try:
        skill = create_skill(db, payload.title, payload.skill_text)
        return SkillResponse.model_validate(skill)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/{skill_id}", response_model=SkillResponse)
def get_skill(skill_id: str, db: Session = Depends(get_db)) -> SkillResponse:
    skill = db.get(Skill, skill_id)
    if skill is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found.")
    return SkillResponse.model_validate(skill_to_dict(skill))
