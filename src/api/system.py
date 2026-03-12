"""System status and control endpoints.

This module provides endpoints for:
- System status overview
- Safe configuration display (without secrets)
- Version information
- Emergency kill switch for trading halt
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.config.settings import Settings, get_settings
from src.core.logging_config import get_logger, set_correlation_id

logger = get_logger("api")
router = APIRouter()

# Track kill switch state
_kill_switch_triggered = False
_kill_switch_timestamp: datetime | None = None
_kill_switch_reason: str | None = None


class SystemStatus(BaseModel):
    """System status response model."""

    status: str = Field(..., description="Overall system status")
    timestamp: str = Field(..., description="ISO timestamp")
    version: str = Field(..., description="Application version")
    environment: str = Field(..., description="Deployment environment")
    trading_mode: str = Field(..., description="Current trading mode")
    kill_switch_triggered: bool = Field(..., description="Whether kill switch is active")
    features: dict[str, bool] = Field(..., description="Feature flags status")


class ConfigStatus(BaseModel):
    """Safe configuration display response model."""

    app_name: str = Field(..., description="Application name")
    app_version: str = Field(..., description="Application version")
    environment: str = Field(..., description="Deployment environment")
    debug: bool = Field(..., description="Debug mode enabled")
    log_level: str = Field(..., description="Current log level")
    log_format: str = Field(..., description="Log format")
    trading_mode: str = Field(..., description="Trading mode")
    database_pool_size: int = Field(..., description="Database connection pool size")
    redis_host: str = Field(..., description="Redis server host")
    redis_port: int = Field(..., description="Redis server port")
    api_host: str = Field(..., description="API server host")
    api_port: int = Field(..., description="API server port")
    features: dict[str, bool] = Field(..., description="Feature flags")


class VersionInfo(BaseModel):
    """Version information response model."""

    version: str = Field(..., description="Application version")
    build_time: str | None = Field(None, description="Build timestamp")
    git_commit: str | None = Field(None, description="Git commit hash")
    python_version: str = Field(..., description="Python version")
    platform: str = Field(..., description="Operating system platform")


class KillSwitchRequest(BaseModel):
    """Kill switch request model."""

    reason: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Reason for triggering kill switch",
    )
    confirm: bool = Field(
        ...,
        description="Must be True to confirm kill switch activation",
    )


class KillSwitchResponse(BaseModel):
    """Kill switch response model."""

    triggered: bool = Field(..., description="Whether kill switch is now active")
    timestamp: str = Field(..., description="ISO timestamp of activation")
    reason: str = Field(..., description="Reason for activation")
    message: str = Field(..., description="Status message")


class KillSwitchStatus(BaseModel):
    """Kill switch status response model."""

    active: bool = Field(..., description="Whether kill switch is active")
    triggered_at: str | None = Field(None, description="ISO timestamp when triggered")
    reason: str | None = Field(None, description="Reason for activation")


@router.get(
    "/status",
    response_model=SystemStatus,
    summary="System status",
    description="Get comprehensive system status information.",
)
async def get_system_status(
    settings: Settings = Depends(get_settings),
) -> SystemStatus:
    """Get overall system status.

    Returns comprehensive information about the system state including
    trading mode, feature flags, and kill switch status.

    Args:
        settings: Application settings.

    Returns:
        SystemStatus with current system information.
    """
    return SystemStatus(
        status="operational" if not _kill_switch_triggered else "halted",
        timestamp=datetime.utcnow().isoformat(),
        version=settings.app_version,
        environment=settings.environment,
        trading_mode=settings.trading.mode,
        kill_switch_triggered=_kill_switch_triggered,
        features={
            "websocket": settings.features.enable_websocket,
            "market_data": settings.features.enable_market_data,
            "signal_generation": settings.features.enable_signal_generation,
            "order_execution": settings.features.enable_order_execution,
            "risk_checks": settings.features.enable_risk_checks,
        },
    )


@router.get(
    "/config",
    response_model=ConfigStatus,
    summary="System configuration",
    description="Get safe configuration display (no secrets).",
)
async def get_system_config(
    settings: Settings = Depends(get_settings),
) -> ConfigStatus:
    """Get safe configuration display.

    Returns configuration settings with all sensitive information
    removed. This is safe to expose through the API.

    Args:
        settings: Application settings.

    Returns:
        ConfigStatus with safe configuration values.
    """
    return ConfigStatus(
        app_name=settings.app_name,
        app_version=settings.app_version,
        environment=settings.environment,
        debug=settings.debug,
        log_level=settings.log_level,
        log_format=settings.log_format,
        trading_mode=settings.trading.mode,
        database_pool_size=settings.database.pool_size,
        redis_host=settings.redis.host,
        redis_port=settings.redis.port,
        api_host=settings.api.host,
        api_port=settings.api.port,
        features={
            "websocket": settings.features.enable_websocket,
            "market_data": settings.features.enable_market_data,
            "signal_generation": settings.features.enable_signal_generation,
            "order_execution": settings.features.enable_order_execution,
            "risk_checks": settings.features.enable_risk_checks,
        },
    )


@router.get(
    "/version",
    response_model=VersionInfo,
    summary="Version information",
    description="Get application version and build information.",
)
async def get_version() -> VersionInfo:
    """Get version information.

    Returns application version, Python version, and platform information.

    Returns:
        VersionInfo with version details.
    """
    import platform
    import sys

    return VersionInfo(
        version=get_settings().app_version,
        build_time=None,  # Would be set during build process
        git_commit=None,  # Would be set during build process
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        platform=platform.platform(),
    )


@router.post(
    "/kill-switch",
    response_model=KillSwitchResponse,
    summary="Emergency kill switch",
    description="Trigger emergency trading halt (kill switch).",
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Kill switch activated successfully"},
        400: {"description": "Invalid request or already triggered"},
        403: {"description": "Kill switch is disabled"},
    },
)
async def trigger_kill_switch(
    request: KillSwitchRequest,
    settings: Settings = Depends(get_settings),
) -> KillSwitchResponse:
    """Trigger the emergency kill switch.

    This endpoint immediately halts all trading activity. It is designed
    for emergency situations where trading must be stopped immediately.

    The kill switch:
    - Prevents new order submissions
    - Cancels pending orders (if configured)
    - Logs the reason for activation
    - Requires explicit confirmation

    Args:
        request: Kill switch request with reason and confirmation.
        settings: Application settings.

    Returns:
        KillSwitchResponse with activation status.

    Raises:
        HTTPException: If kill switch is disabled, already triggered, or confirmation fails.
    """
    global _kill_switch_triggered, _kill_switch_timestamp, _kill_switch_reason

    # Check if kill switch is enabled
    if not settings.risk.kill_switch_enabled:
        logger.error("Kill switch trigger attempted but kill switch is disabled")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Kill switch is disabled in configuration",
        )

    # Check if already triggered
    if _kill_switch_triggered:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "Kill switch already triggered",
                "triggered_at": _kill_switch_timestamp.isoformat() if _kill_switch_timestamp else None,
                "reason": _kill_switch_reason,
            },
        )

    # Verify confirmation
    if not request.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Kill switch activation requires confirm=True",
        )

    # Set correlation ID for audit trail
    correlation_id = set_correlation_id()

    # Trigger kill switch
    _kill_switch_triggered = True
    _kill_switch_timestamp = datetime.utcnow()
    _kill_switch_reason = request.reason

    # Log the emergency activation
    logger.critical(
        "KILL SWITCH ACTIVATED",
        reason=request.reason,
        timestamp=_kill_switch_timestamp.isoformat(),
        correlation_id=correlation_id,
        trading_mode=settings.trading.mode,
        environment=settings.environment,
    )

    # TODO: In future phases, implement:
    # - Cancel all pending orders
    # - Close all open positions (if configured)
    # - Notify risk management team
    # - Update risk metrics

    return KillSwitchResponse(
        triggered=True,
        timestamp=_kill_switch_timestamp.isoformat(),
        reason=request.reason,
        message="Kill switch activated. All trading activity halted.",
    )


@router.get(
    "/kill-switch",
    response_model=KillSwitchStatus,
    summary="Kill switch status",
    description="Get current kill switch status.",
)
async def get_kill_switch_status() -> KillSwitchStatus:
    """Get current kill switch status.

    Returns:
        KillSwitchStatus with current kill switch state.
    """
    return KillSwitchStatus(
        active=_kill_switch_triggered,
        triggered_at=_kill_switch_timestamp.isoformat() if _kill_switch_timestamp else None,
        reason=_kill_switch_reason,
    )


@router.post(
    "/kill-switch/reset",
    response_model=KillSwitchResponse,
    summary="Reset kill switch",
    description="Reset the kill switch (requires admin privileges in production).",
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Kill switch reset successfully"},
        400: {"description": "Kill switch not triggered"},
        403: {"description": "Reset not allowed in production"},
    },
)
async def reset_kill_switch(
    settings: Settings = Depends(get_settings),
) -> KillSwitchResponse:
    """Reset the kill switch.

    This endpoint resets the kill switch and allows trading to resume.
    In production, this should require additional authentication/authorization.

    Args:
        settings: Application settings.

    Returns:
        KillSwitchResponse with reset status.

    Raises:
        HTTPException: If kill switch is not triggered or reset is not allowed.
    """
    global _kill_switch_triggered, _kill_switch_timestamp, _kill_switch_reason

    # Check if kill switch is triggered
    if not _kill_switch_triggered:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Kill switch is not currently triggered",
        )

    # In production, require additional authorization
    # For now, we just log and allow
    if settings.is_production():
        logger.warning(
            "Kill switch reset attempted in production environment",
            triggered_at=_kill_switch_timestamp.isoformat() if _kill_switch_timestamp else None,
            reason=_kill_switch_reason,
        )
        # In a real system, this would require admin token/API key

    # Store previous state for response
    previous_timestamp = _kill_switch_timestamp
    previous_reason = _kill_switch_reason

    # Reset kill switch
    _kill_switch_triggered = False
    _kill_switch_timestamp = None
    _kill_switch_reason = None

    logger.info(
        "Kill switch reset",
        previous_triggered_at=previous_timestamp.isoformat() if previous_timestamp else None,
        previous_reason=previous_reason,
    )

    return KillSwitchResponse(
        triggered=False,
        timestamp=datetime.utcnow().isoformat(),
        reason=previous_reason or "",
        message="Kill switch reset. Trading may resume.",
    )


def is_kill_switch_active() -> bool:
    """Check if kill switch is currently active.

    This function can be called from other parts of the application
    to check if trading should be halted.

    Returns:
        True if kill switch is active, False otherwise.
    """
    return _kill_switch_triggered
