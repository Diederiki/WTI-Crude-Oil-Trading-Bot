"""Dashboard API endpoints for system monitoring.

Provides REST API endpoints for accessing dashboard data including
system status, performance metrics, signals, orders, and positions.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.api.deps import get_current_active_user
from src.dashboard import get_dashboard_service
from src.core.logging_config import get_logger

logger = get_logger("api.dashboard")

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/status", response_model=dict[str, Any])
async def get_full_status(
    current_user: dict = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Get complete system status for dashboard.
    
    Returns comprehensive status information from all system components
    including market data, strategy, execution, risk, events, and WebSocket.
    
    Returns:
        Complete system status dictionary
    """
    service = get_dashboard_service()
    
    if not service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dashboard service not initialized",
        )
    
    try:
        return service.get_full_status()
    except Exception as e:
        logger.error("Failed to get full status", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get status: {str(e)}",
        )


@router.get("/symbol/{symbol}", response_model=dict[str, Any])
async def get_symbol_overview(
    symbol: str,
    current_user: dict = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Get overview for a specific symbol.
    
    Args:
        symbol: Trading symbol (e.g., CL=F)
        
    Returns:
        Symbol overview with price, position, and orders
    """
    service = get_dashboard_service()
    
    if not service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dashboard service not initialized",
        )
    
    try:
        return service.get_symbol_overview(symbol)
    except Exception as e:
        logger.error("Failed to get symbol overview", symbol=symbol, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get symbol overview: {str(e)}",
        )


@router.get("/performance", response_model=dict[str, Any])
async def get_performance_summary(
    current_user: dict = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Get trading performance summary.
    
    Returns account balance, P&L, position summary, and order statistics.
    
    Returns:
        Performance metrics dictionary
    """
    service = get_dashboard_service()
    
    if not service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dashboard service not initialized",
        )
    
    try:
        return service.get_performance_summary()
    except Exception as e:
        logger.error("Failed to get performance summary", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get performance: {str(e)}",
        )


@router.get("/signals", response_model=list[dict[str, Any]])
async def get_recent_signals(
    limit: int = Query(default=20, ge=1, le=100),
    current_user: dict = Depends(get_current_active_user),
) -> list[dict[str, Any]]:
    """Get recent trading signals.
    
    Args:
        limit: Maximum number of signals to return (1-100)
        
    Returns:
        List of recent signals
    """
    service = get_dashboard_service()
    
    if not service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dashboard service not initialized",
        )
    
    try:
        return service.get_recent_signals(limit)
    except Exception as e:
        logger.error("Failed to get signals", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get signals: {str(e)}",
        )


@router.get("/orders", response_model=list[dict[str, Any]])
async def get_recent_orders(
    limit: int = Query(default=20, ge=1, le=100),
    current_user: dict = Depends(get_current_active_user),
) -> list[dict[str, Any]]:
    """Get recent orders.
    
    Args:
        limit: Maximum number of orders to return (1-100)
        
    Returns:
        List of recent orders
    """
    service = get_dashboard_service()
    
    if not service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dashboard service not initialized",
        )
    
    try:
        return service.get_recent_orders(limit)
    except Exception as e:
        logger.error("Failed to get orders", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get orders: {str(e)}",
        )


@router.get("/fills", response_model=list[dict[str, Any]])
async def get_recent_fills(
    limit: int = Query(default=20, ge=1, le=100),
    current_user: dict = Depends(get_current_active_user),
) -> list[dict[str, Any]]:
    """Get recent order fills.
    
    Args:
        limit: Maximum number of fills to return (1-100)
        
    Returns:
        List of recent fills
    """
    service = get_dashboard_service()
    
    if not service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dashboard service not initialized",
        )
    
    try:
        return service.get_recent_fills(limit)
    except Exception as e:
        logger.error("Failed to get fills", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get fills: {str(e)}",
        )


@router.get("/risk", response_model=dict[str, Any])
async def get_risk_metrics(
    current_user: dict = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Get current risk metrics.
    
    Returns kill switch status, daily stats, drawdown, limits, and cooldown.
    
    Returns:
        Risk metrics dictionary
    """
    service = get_dashboard_service()
    
    if not service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dashboard service not initialized",
        )
    
    try:
        return service.get_risk_metrics()
    except Exception as e:
        logger.error("Failed to get risk metrics", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get risk metrics: {str(e)}",
        )


@router.get("/events", response_model=list[dict[str, Any]])
async def get_upcoming_events(
    hours: int = Query(default=24, ge=1, le=168),
    current_user: dict = Depends(get_current_active_user),
) -> list[dict[str, Any]]:
    """Get upcoming economic events.
    
    Args:
        hours: Number of hours to look ahead (1-168)
        
    Returns:
        List of upcoming events
    """
    service = get_dashboard_service()
    
    if not service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dashboard service not initialized",
        )
    
    try:
        return service.get_upcoming_events(hours)
    except Exception as e:
        logger.error("Failed to get events", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get events: {str(e)}",
        )


@router.get("/system/metrics", response_model=dict[str, Any])
async def get_system_metrics(
    current_user: dict = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Get system resource metrics.
    
    Returns CPU, memory, and disk usage statistics.
    
    Returns:
        System metrics dictionary
    """
    try:
        import psutil
        
        return {
            "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
            "cpu": {
                "percent": psutil.cpu_percent(interval=0.1),
                "count": psutil.cpu_count(),
                "freq": psutil.cpu_freq()._asdict() if psutil.cpu_freq() else None,
            },
            "memory": {
                "total": psutil.virtual_memory().total,
                "available": psutil.virtual_memory().available,
                "percent": psutil.virtual_memory().percent,
                "used": psutil.virtual_memory().used,
            },
            "disk": {
                "total": psutil.disk_usage("/").total,
                "used": psutil.disk_usage("/").used,
                "free": psutil.disk_usage("/").free,
                "percent": psutil.disk_usage("/").percent,
            },
        }
    except Exception as e:
        logger.error("Failed to get system metrics", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get system metrics: {str(e)}",
        )
