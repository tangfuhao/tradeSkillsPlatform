from fastapi import APIRouter

from app.api.routes import backtests, health, internal_tool_gateway, live_tasks, market_data, skills


api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(skills.router)
api_router.include_router(backtests.router)
api_router.include_router(live_tasks.router)
api_router.include_router(market_data.router)
api_router.include_router(internal_tool_gateway.router)
