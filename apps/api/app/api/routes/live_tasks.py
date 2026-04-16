from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas import ExecutionControlRequest, LiveSignalResponse, LiveTaskCreateRequest, LiveTaskResponse, PortfolioStateResponse
from app.services.live_service import (
    LiveTaskConflictError,
    LiveTaskOwnershipError,
    LiveTaskService,
    LiveTaskTriggerRejectedError,
    trigger_live_task_manually,
)


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
    except LiveTaskOwnershipError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": str(exc),
                "skill_id": exc.skill_id,
                "existing_live_task_id": exc.existing_task_id,
                "existing_status": exc.existing_status,
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return LiveTaskResponse.model_validate(task)


@router.post("/live-tasks/{task_id}/trigger", response_model=LiveSignalResponse)
def trigger_live_task(task_id: str) -> LiveSignalResponse:
    try:
        signal = trigger_live_task_manually(task_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (LiveTaskTriggerRejectedError, LiveTaskConflictError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
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


@router.post("/live-tasks/{task_id}/control", response_model=LiveTaskResponse)
def control_live_task(
    task_id: str,
    payload: ExecutionControlRequest,
    db: Session = Depends(get_db),
) -> LiveTaskResponse:
    service = LiveTaskService(db)
    try:
        task = service.control_task(task_id, payload.action, expected_revision=payload.expected_revision)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return LiveTaskResponse.model_validate(task)


@router.delete("/live-tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_live_task(task_id: str, db: Session = Depends(get_db)) -> None:
    service = LiveTaskService(db)
    try:
        service.delete_task(task_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
