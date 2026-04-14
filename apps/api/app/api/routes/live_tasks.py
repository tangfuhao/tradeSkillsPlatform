from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.runtime.scheduler import scheduler_manager
from app.schemas import LiveSignalResponse, LiveTaskCreateRequest, LiveTaskResponse, PortfolioStateResponse
from app.services.live_service import LiveTaskService, execute_live_task


router = APIRouter(tags=["live"])


@router.get("/live-tasks", response_model=list[LiveTaskResponse])
def list_live_tasks(db: Session = Depends(get_db)) -> list[LiveTaskResponse]:
    service = LiveTaskService(db)
    return [LiveTaskResponse.model_validate(item) for item in service.list_tasks()]


@router.post("/live-tasks", response_model=LiveTaskResponse, status_code=status.HTTP_201_CREATED)
def create_live_task(payload: LiveTaskCreateRequest, db: Session = Depends(get_db)) -> LiveTaskResponse:
    service = LiveTaskService(db)
    try:
        task = service.create_task(payload.skill_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    scheduler_manager.schedule_live_task(task["id"], task["cadence_seconds"])
    return LiveTaskResponse.model_validate(task)


@router.post("/live-tasks/{task_id}/trigger", response_model=LiveSignalResponse)
def trigger_live_task(task_id: str) -> LiveSignalResponse:
    signal = execute_live_task(task_id)
    if signal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Live task not found or inactive.")
    return LiveSignalResponse.model_validate(signal)


@router.get("/live-signals", response_model=list[LiveSignalResponse])
def list_live_signals(live_task_id: str | None = None, db: Session = Depends(get_db)) -> list[LiveSignalResponse]:
    service = LiveTaskService(db)
    return [LiveSignalResponse.model_validate(item) for item in service.list_signals(live_task_id)]


@router.get("/live-tasks/{task_id}/portfolio", response_model=PortfolioStateResponse)
def get_live_task_portfolio(task_id: str, db: Session = Depends(get_db)) -> PortfolioStateResponse:
    service = LiveTaskService(db)
    try:
        return PortfolioStateResponse.model_validate(service.get_portfolio(task_id))
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
