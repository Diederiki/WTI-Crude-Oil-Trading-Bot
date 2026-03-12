"""Main API router aggregation.

This module aggregates all API routers and provides a single point
of entry for the FastAPI application. Routers are organized by
functionality with appropriate prefixes and tags.
"""

from fastapi import APIRouter

from src.api import health, system, market_data, signals, execution, risk, events, dashboard, websocket

# Create main API router
api_router = APIRouter(prefix="/api/v1")

# Include sub-routers with appropriate tags and prefixes
api_router.include_router(
    health.router,
    prefix="/health",
    tags=["health"],
)

api_router.include_router(
    system.router,
    prefix="/system",
    tags=["system"],
)

api_router.include_router(
    market_data.router,
    prefix="/market-data",
    tags=["market-data"],
)

api_router.include_router(
    signals.router,
    prefix="/signals",
    tags=["signals"],
)

api_router.include_router(
    execution.router,
    prefix="/execution",
    tags=["execution"],
)

api_router.include_router(
    risk.router,
    prefix="/risk",
    tags=["risk"],
)

api_router.include_router(
    events.router,
    prefix="/events",
    tags=["events"],
)

api_router.include_router(
    dashboard.router,
    prefix="/dashboard",
    tags=["dashboard"],
)

# WebSocket routes are at root level (not under /api/v1)
# They are registered directly in main.py
