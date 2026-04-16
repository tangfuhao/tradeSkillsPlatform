from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas import (
    CsvIngestionDiscoveryResponse,
    CsvIngestionJobResponse,
    CsvIngestionRunResponse,
    MarketCandleResponse,
    MarketOverviewResponse,
    MarketSyncStatusResponse,
    MarketUniverseItemResponse,
)
from app.services.market_data_store import (
    fetch_candles,
    get_market_overview,
    get_market_sync_status,
    list_market_symbols,
    list_market_universe,
    normalize_timeframe,
)
from app.services.market_data_sync import (
    discover_local_csv_ingestion_jobs,
    get_csv_ingestion_backlog,
    list_csv_ingestion_jobs,
    run_csv_ingestion_job,
    run_pending_csv_ingestion_jobs,
)
from app.services.utils import ms_to_datetime


router = APIRouter(prefix="/market-data", tags=["market-data"])


@router.get("/overview", response_model=MarketOverviewResponse)
def market_overview(db: Session = Depends(get_db)) -> MarketOverviewResponse:
    return MarketOverviewResponse.model_validate(get_market_overview(db))


@router.get("/sync-status", response_model=MarketSyncStatusResponse)
def market_sync_status(db: Session = Depends(get_db)) -> MarketSyncStatusResponse:
    return MarketSyncStatusResponse.model_validate(get_market_sync_status(db))


@router.get("/ingest-jobs", response_model=list[CsvIngestionJobResponse])
def market_ingest_jobs(
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[CsvIngestionJobResponse]:
    jobs = list_csv_ingestion_jobs(db, status=status_filter, limit=limit)
    return [CsvIngestionJobResponse.model_validate(item) for item in jobs]


@router.post("/ingest-jobs/discover", response_model=CsvIngestionDiscoveryResponse)
def discover_market_ingest_jobs(db: Session = Depends(get_db)) -> CsvIngestionDiscoveryResponse:
    return CsvIngestionDiscoveryResponse.model_validate(discover_local_csv_ingestion_jobs(db))


@router.post("/ingest-jobs/run", response_model=CsvIngestionRunResponse)
def run_market_ingest_jobs(
    job_id: str | None = Query(None),
    limit: int = Query(1, ge=1, le=50),
    discover: bool = Query(True),
    runner_id: str = Query("manual-api", min_length=1, max_length=128),
    db: Session = Depends(get_db),
) -> CsvIngestionRunResponse:
    if job_id is not None:
        discovery_summary = discover_local_csv_ingestion_jobs(db) if discover else None
        try:
            result = run_csv_ingestion_job(db, job_id, runner_id=runner_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        payload = {
            "requested_limit": 1,
            "completed_count": 1 if result["status"] == "completed" else 0,
            "failed_count": 1 if result["status"] == "failed" else 0,
            "jobs": [result],
            "discovery": discovery_summary,
            "backlog": get_csv_ingestion_backlog(db),
        }
        return CsvIngestionRunResponse.model_validate(payload)
    return CsvIngestionRunResponse.model_validate(
        run_pending_csv_ingestion_jobs(db, limit=limit, runner_id=runner_id, discover=discover)
    )


@router.get("/universe", response_model=list[MarketUniverseItemResponse])
def market_universe(db: Session = Depends(get_db)) -> list[MarketUniverseItemResponse]:
    return [MarketUniverseItemResponse.model_validate(item) for item in list_market_universe(db)]


@router.get("/symbols", response_model=list[str])
def market_symbols(db: Session = Depends(get_db)) -> list[str]:
    return list_market_symbols(db)


@router.get("/candles", response_model=list[MarketCandleResponse])
def market_candles(
    market_symbol: str = Query(..., min_length=3),
    timeframe: str = Query("1m"),
    limit: int = Query(200, ge=1, le=2000),
    end_time_ms: int | None = Query(None),
    db: Session = Depends(get_db),
) -> list[MarketCandleResponse]:
    try:
        candles = fetch_candles(
            db,
            market_symbol=market_symbol,
            timeframe=normalize_timeframe(timeframe),
            limit=limit,
            end_time=ms_to_datetime(end_time_ms) if end_time_ms is not None else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return [MarketCandleResponse.model_validate(item) for item in candles]
