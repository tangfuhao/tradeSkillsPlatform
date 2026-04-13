from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas import BacktestCreateRequest, BacktestResponse, TraceResponse
from app.services.backtest_service import BacktestService, execute_backtest_job


router = APIRouter(prefix="/backtests", tags=["backtests"])


@router.get("", response_model=list[BacktestResponse])
def list_backtests(db: Session = Depends(get_db)) -> list[BacktestResponse]:
    service = BacktestService(db)
    return [BacktestResponse.model_validate(item) for item in service.list_runs()]


@router.post("", response_model=BacktestResponse, status_code=status.HTTP_202_ACCEPTED)
def create_backtest(
    payload: BacktestCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> BacktestResponse:
    service = BacktestService(db)
    try:
        run = service.create_run(
            skill_id=payload.skill_id,
            start_time=payload.start_time,
            end_time=payload.end_time,
            initial_capital=payload.initial_capital,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    background_tasks.add_task(execute_backtest_job, run["id"])
    return BacktestResponse.model_validate(run)


@router.get("/{run_id}", response_model=BacktestResponse)
def get_backtest(run_id: str, db: Session = Depends(get_db)) -> BacktestResponse:
    service = BacktestService(db)
    try:
        return BacktestResponse.model_validate(service.get_run(run_id))
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{run_id}/summary", response_model=BacktestResponse)
def get_backtest_summary(run_id: str, db: Session = Depends(get_db)) -> BacktestResponse:
    service = BacktestService(db)
    try:
        return BacktestResponse.model_validate(service.get_run(run_id))
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{run_id}/traces", response_model=list[TraceResponse])
def get_backtest_traces(run_id: str, db: Session = Depends(get_db)) -> list[TraceResponse]:
    service = BacktestService(db)
    try:
        return [TraceResponse.model_validate(item) for item in service.get_traces(run_id)]
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
