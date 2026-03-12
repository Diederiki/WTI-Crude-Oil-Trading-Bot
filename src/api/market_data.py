"""Market data API endpoints.

Provides REST API access to market data, feed status, and anomalies.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.config.settings import Settings, get_settings
from src.core.logging_config import get_logger
from src.market_data.feed_manager import FeedManager
from src.market_data.models.events import MarketTick, MarketBar, FeedStatus, FeedAnomaly

logger = get_logger("api")
router = APIRouter(prefix="/market-data", tags=["market-data"])

# Global feed manager instance (set during startup)
_feed_manager: FeedManager | None = None


def set_feed_manager(manager: FeedManager) -> None:
    """Set the global feed manager instance.
    
    Args:
        manager: FeedManager instance
    """
    global _feed_manager
    _feed_manager = manager


def get_feed_manager() -> FeedManager:
    """Get the global feed manager instance.
    
    Returns:
        FeedManager instance
        
    Raises:
        HTTPException: If feed manager not initialized
    """
    if _feed_manager is None:
        raise HTTPException(
            status_code=503,
            detail="Feed manager not initialized",
        )
    return _feed_manager


class TickResponse(BaseModel):
    """Tick response model."""
    symbol: str
    timestamp: str
    bid: float
    ask: float
    last: float
    bid_size: int
    ask_size: int
    last_size: int
    volume: int | None
    exchange: str
    feed_source: str


class BarResponse(BaseModel):
    """Bar response model."""
    symbol: str
    timestamp: str
    interval_seconds: int
    open: float
    high: float
    low: float
    close: float
    volume: int
    vwap: float | None
    trades: int


class FeedStatusResponse(BaseModel):
    """Feed status response model."""
    feed_id: str
    provider: str
    symbols: list[str]
    status: str
    is_connected: bool
    messages_received: int
    messages_per_second: float
    avg_latency_ms: float
    errors_count: int
    reconnects_count: int
    last_message_at: str | None


class AnomalyResponse(BaseModel):
    """Anomaly response model."""
    anomaly_id: str
    feed_id: str
    symbol: str
    anomaly_type: str
    detected_at: str
    severity: int
    description: str
    expected_value: float | None
    actual_value: float | None


class PriceResponse(BaseModel):
    """Last price response model."""
    symbol: str
    price: float
    bid: float
    ask: float
    timestamp: str
    feed_source: str


@router.get(
    "/feeds",
    response_model=list[FeedStatusResponse],
    summary="List all feeds",
    description="Get status of all registered market data feeds.",
)
async def list_feeds(
    feed_manager: FeedManager = Depends(get_feed_manager),
) -> list[FeedStatusResponse]:
    """List all feeds and their status."""
    statuses = feed_manager.get_feed_status()
    
    return [
        FeedStatusResponse(
            feed_id=s.feed_id,
            provider=s.provider,
            symbols=s.symbols,
            status=s.status.value,
            is_connected=s.is_connected,
            messages_received=s.messages_received,
            messages_per_second=s.messages_per_second,
            avg_latency_ms=s.avg_latency_ms,
            errors_count=s.errors_count,
            reconnects_count=s.reconnects_count,
            last_message_at=s.last_message_at.isoformat() if s.last_message_at else None,
        )
        for s in statuses.values()
    ]


@router.get(
    "/feeds/{feed_id}",
    response_model=FeedStatusResponse,
    summary="Get feed status",
    description="Get detailed status of a specific feed.",
)
async def get_feed_status(
    feed_id: str,
    feed_manager: FeedManager = Depends(get_feed_manager),
) -> FeedStatusResponse:
    """Get status of a specific feed."""
    statuses = feed_manager.get_feed_status(feed_id)
    
    if not statuses:
        raise HTTPException(
            status_code=404,
            detail=f"Feed {feed_id} not found",
        )
    
    s = list(statuses.values())[0]
    return FeedStatusResponse(
        feed_id=s.feed_id,
        provider=s.provider,
        symbols=s.symbols,
        status=s.status.value,
        is_connected=s.is_connected,
        messages_received=s.messages_received,
        messages_per_second=s.messages_per_second,
        avg_latency_ms=s.avg_latency_ms,
        errors_count=s.errors_count,
        reconnects_count=s.reconnects_count,
        last_message_at=s.last_message_at.isoformat() if s.last_message_at else None,
    )


@router.get(
    "/price/{symbol}",
    response_model=PriceResponse,
    summary="Get last price",
    description="Get the last known price for a symbol.",
)
async def get_last_price(
    symbol: str,
    feed_manager: FeedManager = Depends(get_feed_manager),
) -> PriceResponse:
    """Get last known price for a symbol."""
    price_data = feed_manager.get_last_price(symbol)
    
    if not price_data:
        raise HTTPException(
            status_code=404,
            detail=f"No price data for {symbol}",
        )
    
    return PriceResponse(
        symbol=symbol.upper(),
        price=price_data["price"],
        bid=price_data["bid"],
        ask=price_data["ask"],
        timestamp=price_data["timestamp"],
        feed_source=price_data["feed_source"],
    )


@router.get(
    "/prices",
    response_model=dict[str, PriceResponse],
    summary="Get all prices",
    description="Get last known prices for all symbols.",
)
async def get_all_prices(
    feed_manager: FeedManager = Depends(get_feed_manager),
) -> dict[str, PriceResponse]:
    """Get all last known prices."""
    result = {}
    
    for symbol in feed_manager._last_prices.keys():
        price_data = feed_manager.get_last_price(symbol)
        if price_data:
            result[symbol] = PriceResponse(
                symbol=symbol,
                price=price_data["price"],
                bid=price_data["bid"],
                ask=price_data["ask"],
                timestamp=price_data["timestamp"],
                feed_source=price_data["feed_source"],
            )
    
    return result


@router.get(
    "/history/{symbol}",
    response_model=list[TickResponse],
    summary="Get price history",
    description="Get recent tick history for a symbol.",
)
async def get_price_history(
    symbol: str,
    limit: int = Query(default=100, ge=1, le=1000),
    feed_manager: FeedManager = Depends(get_feed_manager),
) -> list[TickResponse]:
    """Get recent price history for a symbol."""
    history = feed_manager.get_price_history(symbol, limit)
    
    return [
        TickResponse(
            symbol=t.symbol,
            timestamp=t.timestamp.isoformat(),
            bid=t.bid,
            ask=t.ask,
            last=t.last,
            bid_size=t.bid_size,
            ask_size=t.ask_size,
            last_size=t.last_size,
            volume=t.volume,
            exchange=t.exchange,
            feed_source=t.feed_source,
        )
        for t in history
    ]


@router.get(
    "/anomalies",
    response_model=list[AnomalyResponse],
    summary="List anomalies",
    description="Get recent feed anomalies with optional filtering.",
)
async def list_anomalies(
    symbol: str | None = Query(default=None),
    feed_id: str | None = Query(default=None),
    min_severity: int = Query(default=1, ge=1, le=5),
    limit: int = Query(default=100, ge=1, le=1000),
    feed_manager: FeedManager = Depends(get_feed_manager),
) -> list[AnomalyResponse]:
    """Get recent anomalies."""
    anomalies = feed_manager.get_anomalies(
        symbol=symbol,
        feed_id=feed_id,
        limit=limit,
    )
    
    # Filter by severity
    anomalies = [a for a in anomalies if a.severity >= min_severity]
    
    return [
        AnomalyResponse(
            anomaly_id=a.anomaly_id,
            feed_id=a.feed_id,
            symbol=a.symbol,
            anomaly_type=a.anomaly_type.value,
            detected_at=a.detected_at.isoformat(),
            severity=a.severity,
            description=a.description,
            expected_value=a.expected_value,
            actual_value=a.actual_value,
        )
        for a in anomalies
    ]


@router.get(
    "/stats/{symbol}",
    response_model=dict[str, Any],
    summary="Get symbol statistics",
    description="Get trading statistics for a symbol.",
)
async def get_symbol_stats(
    symbol: str,
    feed_manager: FeedManager = Depends(get_feed_manager),
) -> dict[str, Any]:
    """Get statistics for a symbol."""
    # Get price history stats
    history = feed_manager.get_price_history(symbol, limit=100)
    
    if not history:
        raise HTTPException(
            status_code=404,
            detail=f"No data for {symbol}",
        )
    
    # Calculate statistics
    prices = [t.last for t in history]
    bids = [t.bid for t in history]
    asks = [t.ask for t in history]
    
    return {
        "symbol": symbol.upper(),
        "tick_count": len(history),
        "price": {
            "current": prices[-1],
            "open": prices[0],
            "high": max(prices),
            "low": min(prices),
            "change": prices[-1] - prices[0],
            "change_pct": (prices[-1] - prices[0]) / prices[0] * 100 if prices[0] else 0,
        },
        "spread": {
            "current": asks[-1] - bids[-1],
            "avg": sum(a - b for a, b in zip(asks, bids)) / len(bids),
            "min": min(a - b for a, b in zip(asks, bids)),
            "max": max(a - b for a, b in zip(asks, bids)),
        },
        "volume": {
            "total": sum(t.volume for t in history if t.volume),
        },
        "last_update": history[-1].timestamp.isoformat(),
    }