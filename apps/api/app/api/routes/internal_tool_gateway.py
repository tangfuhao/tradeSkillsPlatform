from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.schemas import (
    ToolGatewayExecuteRequest,
    ToolGatewayExecuteResponse,
    ToolGatewayMarketCandlesRequest,
    ToolGatewayMarketScanRequest,
    ToolGatewayMarketSymbolRequest,
    ToolGatewaySignalIntentRequest,
    ToolGatewayStateGetRequest,
    ToolGatewayStateSaveRequest,
)
from app.tool_gateway.market_handlers import (
    handle_get_candles,
    handle_get_funding_rate,
    handle_get_open_interest,
    handle_market_metadata,
    handle_scan_market,
)
from app.tool_gateway.signal_handlers import handle_signal_intent
from app.tool_gateway.state_handlers import handle_get_strategy_state, handle_save_strategy_state
from app.tool_gateway.demo_gateway import execute_tool_gateway_request


router = APIRouter(prefix="/internal/tool-gateway", include_in_schema=False)


def _require_tool_gateway_secret(
    x_tool_gateway_secret: str | None = Header(default=None, alias="X-Tool-Gateway-Secret"),
) -> None:
    if settings.tool_gateway_shared_secret and x_tool_gateway_secret != settings.tool_gateway_shared_secret:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid tool gateway secret.")


@router.post("/market/scan", response_model=ToolGatewayExecuteResponse, include_in_schema=False)
def market_scan(
    payload: ToolGatewayMarketScanRequest,
    db: Session = Depends(get_db),
    _: None = Depends(_require_tool_gateway_secret),
) -> ToolGatewayExecuteResponse:
    return ToolGatewayExecuteResponse.model_validate(
        handle_scan_market(
            db,
            as_of=payload.as_of or payload.trigger_time,
            trace_index=payload.trace_index,
            top_n=payload.top_n,
            sort_by=payload.sort_by,
        )
    )


@router.post("/market/metadata", response_model=ToolGatewayExecuteResponse, include_in_schema=False)
def market_metadata(
    payload: ToolGatewayMarketSymbolRequest,
    db: Session = Depends(get_db),
    _: None = Depends(_require_tool_gateway_secret),
) -> ToolGatewayExecuteResponse:
    return ToolGatewayExecuteResponse.model_validate(
        handle_market_metadata(
            db,
            as_of=payload.as_of or payload.trigger_time,
            trace_index=payload.trace_index,
            market_symbol=payload.market_symbol,
            mode=payload.mode,
        )
    )


@router.post("/market/candles", response_model=ToolGatewayExecuteResponse, include_in_schema=False)
def market_candles(
    payload: ToolGatewayMarketCandlesRequest,
    db: Session = Depends(get_db),
    _: None = Depends(_require_tool_gateway_secret),
) -> ToolGatewayExecuteResponse:
    return ToolGatewayExecuteResponse.model_validate(
        handle_get_candles(
            db,
            as_of=payload.as_of or payload.trigger_time,
            market_symbol=payload.market_symbol,
            timeframe=payload.timeframe,
            limit=payload.limit,
        )
    )


@router.post("/market/funding-rate", response_model=ToolGatewayExecuteResponse, include_in_schema=False)
def market_funding_rate(
    payload: ToolGatewayMarketSymbolRequest,
    db: Session = Depends(get_db),
    _: None = Depends(_require_tool_gateway_secret),
) -> ToolGatewayExecuteResponse:
    return ToolGatewayExecuteResponse.model_validate(
        handle_get_funding_rate(
            db,
            as_of=payload.as_of or payload.trigger_time,
            trace_index=payload.trace_index,
            market_symbol=payload.market_symbol,
        )
    )


@router.post("/market/open-interest", response_model=ToolGatewayExecuteResponse, include_in_schema=False)
def market_open_interest(
    payload: ToolGatewayMarketSymbolRequest,
    db: Session = Depends(get_db),
    _: None = Depends(_require_tool_gateway_secret),
) -> ToolGatewayExecuteResponse:
    return ToolGatewayExecuteResponse.model_validate(
        handle_get_open_interest(
            db,
            as_of=payload.as_of or payload.trigger_time,
            trace_index=payload.trace_index,
            market_symbol=payload.market_symbol,
        )
    )


@router.post("/state/get", response_model=ToolGatewayExecuteResponse, include_in_schema=False)
def state_get(
    payload: ToolGatewayStateGetRequest,
    db: Session = Depends(get_db),
    _: None = Depends(_require_tool_gateway_secret),
) -> ToolGatewayExecuteResponse:
    return ToolGatewayExecuteResponse.model_validate(handle_get_strategy_state(db, skill_id=payload.skill_id))


@router.post("/state/save", response_model=ToolGatewayExecuteResponse, include_in_schema=False)
def state_save(
    payload: ToolGatewayStateSaveRequest,
    db: Session = Depends(get_db),
    _: None = Depends(_require_tool_gateway_secret),
) -> ToolGatewayExecuteResponse:
    return ToolGatewayExecuteResponse.model_validate(
        handle_save_strategy_state(db, skill_id=payload.skill_id, patch=payload.patch)
    )


@router.post("/signal/simulate-order", response_model=ToolGatewayExecuteResponse, include_in_schema=False)
def signal_simulate_order(
    payload: ToolGatewaySignalIntentRequest,
    _: None = Depends(_require_tool_gateway_secret),
) -> ToolGatewayExecuteResponse:
    return ToolGatewayExecuteResponse.model_validate(
        handle_signal_intent(
            tool_name="simulate_order",
            action=payload.action,
            symbol=payload.symbol,
            direction=payload.direction,
            size_pct=payload.size_pct,
            reason=payload.reason,
            stop_loss_pct=payload.stop_loss_pct,
            take_profit_pct=payload.take_profit_pct,
        )
    )


@router.post("/signal/emit", response_model=ToolGatewayExecuteResponse, include_in_schema=False)
def signal_emit(
    payload: ToolGatewaySignalIntentRequest,
    _: None = Depends(_require_tool_gateway_secret),
) -> ToolGatewayExecuteResponse:
    return ToolGatewayExecuteResponse.model_validate(
        handle_signal_intent(
            tool_name="emit_signal",
            action=payload.action,
            symbol=payload.symbol,
            direction=payload.direction,
            size_pct=payload.size_pct,
            reason=payload.reason,
            stop_loss_pct=payload.stop_loss_pct,
            take_profit_pct=payload.take_profit_pct,
        )
    )


@router.post("/execute", response_model=ToolGatewayExecuteResponse, include_in_schema=False)
def execute_tool_gateway(
    payload: ToolGatewayExecuteRequest,
    db: Session = Depends(get_db),
    _: None = Depends(_require_tool_gateway_secret),
) -> ToolGatewayExecuteResponse:
    result = execute_tool_gateway_request(
        db=db,
        tool_name=payload.tool_name,
        skill_id=payload.skill_id,
        mode=payload.mode,
        trigger_time=payload.trigger_time,
        arguments=payload.arguments,
        as_of=payload.as_of,
        trace_index=payload.trace_index,
    )
    return ToolGatewayExecuteResponse.model_validate(result)
