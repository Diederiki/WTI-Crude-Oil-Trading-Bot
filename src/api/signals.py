"""Signals API endpoints.

Provides REST API access to trading signals and strategy information.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.config.settings import Settings, get_settings
from src.core.logging_config import get_logger
from src.strategy.engine import StrategyEngine
from src.strategy.models.signal import Signal, SignalStatus, SignalType

logger = get_logger("api")
router = APIRouter(prefix="/signals", tags=["signals"])

# Global strategy engine instance (set during startup)
_strategy_engine: StrategyEngine | None = None


def set_strategy_engine(engine: StrategyEngine) -> None:
    """Set the global strategy engine instance.
    
    Args:
        engine: StrategyEngine instance
    """
    global _strategy_engine
    _strategy_engine = engine


def get_strategy_engine() -> StrategyEngine:
    """Get the global strategy engine instance.
    
    Returns:
        StrategyEngine instance
        
    Raises:
        HTTPException: If strategy engine not initialized
    """
    if _strategy_engine is None:
        raise HTTPException(
            status_code=503,
            detail="Strategy engine not initialized",
        )
    return _strategy_engine


class SignalResponse(BaseModel):
    """Signal response model."""
    signal_id: str
    timestamp: str
    symbol: str
    signal_type: str
    status: str
    direction: str
    trigger_price: float
    entry_price: float
    stop_loss: float
    take_profit_levels: list[float]
    confidence: int
    setup_description: str
    reason_codes: list[str]
    market_regime: str
    risk_reward_ratio: float | None
    is_active: bool


class SignalListResponse(BaseModel):
    """Signal list response."""
    signals: list[SignalResponse]
    total: int


class SignalStatsResponse(BaseModel):
    """Signal statistics response."""
    ticks_processed: int
    bars_processed: int
    signals_generated: int
    signals_blocked: int
    active_signals: int
    total_signals: int


class UpdateSignalRequest(BaseModel):
    """Update signal request."""
    status: str = Field(..., description="New status")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


def _signal_to_response(signal: Signal) -> SignalResponse:
    """Convert Signal to response model.
    
    Args:
        signal: Signal instance
        
    Returns:
        SignalResponse
    """
    return SignalResponse(
        signal_id=signal.signal_id,
        timestamp=signal.timestamp.isoformat(),
        symbol=signal.symbol,
        signal_type=signal.signal_type.value,
        status=signal.status.value,
        direction=signal.direction,
        trigger_price=signal.trigger_price,
        entry_price=signal.entry_price,
        stop_loss=signal.stop_loss,
        take_profit_levels=signal.take_profit_levels,
        confidence=signal.confidence,
        setup_description=signal.setup_description,
        reason_codes=signal.reason_codes,
        market_regime=signal.market_regime.value,
        risk_reward_ratio=signal.risk_reward_ratio,
        is_active=signal.is_active,
    )


@router.get(
    "/active",
    response_model=SignalListResponse,
    summary="Get active signals",
    description="Get all currently active trading signals.",
)
async def get_active_signals(
    symbol: str | None = Query(default=None, description="Filter by symbol"),
    direction: str | None = Query(default=None, description="Filter by direction (long/short)"),
    engine: StrategyEngine = Depends(get_strategy_engine),
) -> SignalListResponse:
    """Get active signals."""
    signals = engine.get_active_signals(symbol=symbol, direction=direction)
    
    return SignalListResponse(
        signals=[_signal_to_response(s) for s in signals],
        total=len(signals),
    )


@router.get(
    "/history",
    response_model=SignalListResponse,
    summary="Get signal history",
    description="Get historical trading signals.",
)
async def get_signal_history(
    symbol: str | None = Query(default=None, description="Filter by symbol"),
    limit: int = Query(default=100, ge=1, le=1000, description="Maximum signals to return"),
    engine: StrategyEngine = Depends(get_strategy_engine),
) -> SignalListResponse:
    """Get signal history."""
    signals = engine.get_signal_history(symbol=symbol, limit=limit)
    
    return SignalListResponse(
        signals=[_signal_to_response(s) for s in signals],
        total=len(signals),
    )


@router.get(
    "/{signal_id}",
    response_model=SignalResponse,
    summary="Get signal details",
    description="Get detailed information about a specific signal.",
)
async def get_signal(
    signal_id: str,
    engine: StrategyEngine = Depends(get_strategy_engine),
) -> SignalResponse:
    """Get signal by ID."""
    signal = engine.get_signal(signal_id)
    
    if not signal:
        raise HTTPException(
            status_code=404,
            detail=f"Signal {signal_id} not found",
        )
    
    return _signal_to_response(signal)


@router.post(
    "/{signal_id}/status",
    response_model=SignalResponse,
    summary="Update signal status",
    description="Update the status of a signal (e.g., mark as entered).",
)
async def update_signal_status(
    signal_id: str,
    request: UpdateSignalRequest,
    engine: StrategyEngine = Depends(get_strategy_engine),
) -> SignalResponse:
    """Update signal status."""
    try:
        status = SignalStatus(request.status)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status: {request.status}",
        )
    
    signal = engine.update_signal_status(
        signal_id=signal_id,
        status=status,
        metadata=request.metadata,
    )
    
    if not signal:
        raise HTTPException(
            status_code=404,
            detail=f"Signal {signal_id} not found",
        )
    
    return _signal_to_response(signal)


@router.get(
    "/stats/summary",
    response_model=SignalStatsResponse,
    summary="Get signal statistics",
    description="Get summary statistics about signal generation.",
)
async def get_signal_stats(
    engine: StrategyEngine = Depends(get_strategy_engine),
) -> SignalStatsResponse:
    """Get signal statistics."""
    stats = engine.get_stats()
    
    return SignalStatsResponse(
        ticks_processed=stats.get("ticks_processed", 0),
        bars_processed=stats.get("bars_processed", 0),
        signals_generated=stats.get("signals_generated", 0),
        signals_blocked=stats.get("signals_blocked", 0),
        active_signals=stats.get("active_signals", 0),
        total_signals=stats.get("total_signals", 0),
    )


@router.get(
    "/stats/detectors",
    response_model=dict[str, Any],
    summary="Get detector statistics",
    description="Get detailed statistics from all signal detectors.",
)
async def get_detector_stats(
    engine: StrategyEngine = Depends(get_strategy_engine),
) -> dict[str, Any]:
    """Get detector statistics."""
    return engine.get_stats().get("detectors", {})