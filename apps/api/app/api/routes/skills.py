from sqlalchemy import select
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import LiveTask, Skill
from app.schemas import SkillCreateRequest, SkillResponse
from app.services.execution_cleanup import delete_strategy_cascade
from app.services.execution_lifecycle import LIVE_RUNTIME_OWNING_STATUSES
from app.services.serializers import skill_to_dict
from app.services.skills import create_skill


router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("", response_model=list[SkillResponse])
def list_skills(db: Session = Depends(get_db)) -> list[SkillResponse]:
    skills = db.scalars(select(Skill).order_by(Skill.created_at.desc())).all()
    active_live_task_by_skill_id = {
        task.skill_id: task.id
        for task in db.scalars(
            select(LiveTask).where(LiveTask.status.in_(LIVE_RUNTIME_OWNING_STATUSES)).order_by(LiveTask.created_at.desc())
        ).all()
    }
    return [
        SkillResponse.model_validate(
            skill_to_dict(
                skill,
                has_active_live_runtime=skill.id in active_live_task_by_skill_id,
                active_live_task_id=active_live_task_by_skill_id.get(skill.id),
            )
        )
        for skill in skills
    ]


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
    active_live_task = db.scalar(
        select(LiveTask).where(
            LiveTask.skill_id == skill.id,
            LiveTask.status.in_(LIVE_RUNTIME_OWNING_STATUSES),
        )
    )
    return SkillResponse.model_validate(
        skill_to_dict(
            skill,
            has_active_live_runtime=active_live_task is not None,
            active_live_task_id=active_live_task.id if active_live_task is not None else None,
        )
    )


@router.delete("/{skill_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_skill(skill_id: str, db: Session = Depends(get_db)) -> Response:
    skill = db.get(Skill, skill_id)
    if skill is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found.")
    try:
        delete_strategy_cascade(db, skill)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
