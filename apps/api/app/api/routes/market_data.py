from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas import MarketCandleResponse, MarketOverviewResponse, MarketSyncStatusResponse, MarketUniverseItemResponse
from app.services.market_data_store import (
    fetch_candles,
    get_market_overview,
    get_market_sync_status,
    list_market_symbols,
    list_market_universe,
    normalize_timeframe,
)
from app.services.utils import ms_to_datetime


router = APIRouter(prefix="/market-data", tags=["market-data"])


@router.get("/overview", response_model=MarketOverviewResponse)
def market_overview(db: Session = Depends(get_db)) -> MarketOverviewResponse:
    return MarketOverviewResponse.model_validate(get_market_overview(db))


@router.get("/sync-status", response_model=MarketSyncStatusResponse)
def market_sync_status(db: Session = Depends(get_db)) -> MarketSyncStatusResponse:
    return MarketSyncStatusResponse.model_validate(get_market_sync_status(db))


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
