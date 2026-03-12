"""Risk API endpoints.

Provides REST API access to risk management and monitoring.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.config.settings import Settings, get_settings
from src.core.logging_config import get_logger
from src.risk.manager import RiskManager

logger = get_logger("api")
router = APIRouter(prefix="/risk", tags=["risk"])

# Global risk manager instance (set during startup)
_risk_manager: RiskManager | None = None


def set_risk_manager(manager: RiskManager) -> None:
    """Set the global risk manager instance.
    
    Args:
        manager: RiskManager instance
    """
    global _risk_manager
    _risk_manager = manager


def get_risk_manager() -> RiskManager:
    """Get the global risk manager instance.
    
    Returns:
        RiskManager instance
        
    Raises:
        HTTPException: If risk manager not initialized
    """
    if _risk_manager is None:
        raise HTTPException(
            status_code=503,
            detail="Risk manager not initialized",
        )
    return _risk_manager


class RiskStatusResponse(BaseModel):
    """Risk status response."""
    status: str
    daily_pnl: str
    daily_trades: int
    daily_orders: int
    open_positions: int
    total_exposure: str
    current_drawdown_pct: str
    consecutive_losses: int
    is_cooldown: bool
    cooldown_until: str | None
    kill_switch_triggered: bool
    kill_switch_reason: str | None
    can_trade: bool


class RiskLimitsResponse(BaseModel):
    """Risk limits response."""
    max_position_size: int
    max_position_pct: str
    max_open_positions: int
    max_daily_loss: str
    max_drawdown_pct: str
    per_trade_risk: str
    max_orders_per_minute: int
    max_trades_per_day: int
    cooldown_after_loss_seconds: int
    max_spread_pct: str
    max_slippage_pct: str
    kill_switch_enabled: bool


class KillSwitchResponse(BaseModel):
    """Kill switch response."""
    triggered: bool
    reason: str | None
    reset: bool


@router.get(
    "/status",
    response_model=RiskStatusResponse,
    summary="Get risk status",
    description="Get current risk status and metrics.",
)
async def get_risk_status(
    risk_manager: RiskManager = Depends(get_risk_manager),
) -> RiskStatusResponse:
    """Get current risk status."""
    status = risk_manager.get_status()
    state = status.get("state", {})
    
    return RiskStatusResponse(
        status=state.get("status", "unknown"),
        daily_pnl=state.get("daily_pnl", "0"),
        daily_trades=state.get("daily_trades", 0),
        daily_orders=state.get("daily_orders", 0),
        open_positions=state.get("open_positions", 0),
        total_exposure=state.get("total_exposure", "0"),
        current_drawdown_pct=state.get("current_drawdown_pct", "0"),
        consecutive_losses=state.get("consecutive_losses", 0),
        is_cooldown=state.get("is_cooldown", False),
        cooldown_until=state.get("cooldown_until"),
        kill_switch_triggered=state.get("kill_switch_triggered", False),
        kill_switch_reason=state.get("kill_switch_reason"),
        can_trade=status.get("can_trade", False),
    )


@router.get(
    "/limits",
    response_model=RiskLimitsResponse,
    summary="Get risk limits",
    description="Get configured risk limits.",
)
async def get_risk_limits(
    risk_manager: RiskManager = Depends(get_risk_manager),
) -> RiskLimitsResponse:
    """Get risk limits."""
    limits = risk_manager.get_status().get("limits", {})
    
    return RiskLimitsResponse(
        max_position_size=limits.get("max_position_size", 0),
        max_position_pct=limits.get("max_position_pct", "0"),
        max_open_positions=limits.get("max_open_positions", 0),
        max_daily_loss=limits.get("max_daily_loss", "0"),
        max_drawdown_pct=limits.get("max_drawdown_pct", "0"),
        per_trade_risk=limits.get("per_trade_risk", "0"),
        max_orders_per_minute=limits.get("max_orders_per_minute", 0),
        max_trades_per_day=limits.get("max_trades_per_day", 0),
        cooldown_after_loss_seconds=limits.get("cooldown_after_loss_seconds", 0),
        max_spread_pct=limits.get("max_spread_pct", "0"),
        max_slippage_pct=limits.get("max_slippage_pct", "0"),
        kill_switch_enabled=limits.get("kill_switch_enabled", False),
    )


@router.post(
    "/kill-switch/reset",
    response_model=KillSwitchResponse,
    summary="Reset kill switch",
    description="Manually reset the kill switch (use with caution).",
)
async def reset_kill_switch(
    risk_manager: RiskManager = Depends(get_risk_manager),
) -> KillSwitchResponse:
    """Reset kill switch."""
    success = risk_manager.reset_kill_switch()
    
    if not success:
        raise HTTPException(
            status_code=400,
            detail="Kill switch not active",
        )
    
    return KillSwitchResponse(
        triggered=False,
        reason=None,
        reset=True,
    )


@router.post(
    "/daily-reset",
    response_model=dict[str, str],
    summary="Reset daily stats",
    description="Reset daily risk statistics (call at market open).",
)
async def reset_daily_stats(
    risk_manager: RiskManager = Depends(get_risk_manager),
) -> dict[str, str]:
    """Reset daily statistics."""
    risk_manager.reset_daily_stats()
    
    return {"message": "Daily risk statistics reset successfully"}


@router.get(
    "/breaches",
    response_model=list[dict[str, Any]],
    summary="Get risk breaches",
    description="Get list of risk breaches.",
)
async def get_risk_breaches(
    risk_manager: RiskManager = Depends(get_risk_manager),
) -> list[dict[str, Any]]:
    """Get risk breaches."""
    return risk_manager.state.breaches