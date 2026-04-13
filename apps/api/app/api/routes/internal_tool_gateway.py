from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.schemas import ToolGatewayExecuteRequest, ToolGatewayExecuteResponse
from app.tool_gateway.demo_gateway import execute_tool_gateway_request


router = APIRouter(prefix="/internal/tool-gateway", include_in_schema=False)


@router.post("/execute", response_model=ToolGatewayExecuteResponse, include_in_schema=False)
def execute_tool_gateway(
    payload: ToolGatewayExecuteRequest,
    db: Session = Depends(get_db),
    x_tool_gateway_secret: str | None = Header(default=None, alias="X-Tool-Gateway-Secret"),
) -> ToolGatewayExecuteResponse:
    if settings.tool_gateway_shared_secret and x_tool_gateway_secret != settings.tool_gateway_shared_secret:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid tool gateway secret.")

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
