"""Execution API endpoints.

Provides REST API access to order management, positions, and account info.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.config.settings import Settings, get_settings
from src.core.logging_config import get_logger
from src.execution.engine import ExecutionEngine
from src.execution.models.order import Order, OrderStatus
from src.execution.models.position import Position

logger = get_logger("api")
router = APIRouter(prefix="/execution", tags=["execution"])

# Global execution engine instance (set during startup)
_execution_engine: ExecutionEngine | None = None


def set_execution_engine(engine: ExecutionEngine) -> None:
    """Set the global execution engine instance.
    
    Args:
        engine: ExecutionEngine instance
    """
    global _execution_engine
    _execution_engine = engine


def get_execution_engine() -> ExecutionEngine:
    """Get the global execution engine instance.
    
    Returns:
        ExecutionEngine instance
        
    Raises:
        HTTPException: If execution engine not initialized
    """
    if _execution_engine is None:
        raise HTTPException(
            status_code=503,
            detail="Execution engine not initialized",
        )
    return _execution_engine


class OrderResponse(BaseModel):
    """Order response model."""
    order_id: str
    symbol: str
    side: str
    order_type: str
    status: str
    quantity: int
    filled_quantity: int
    remaining_quantity: int
    price: str | None
    average_fill_price: str | None
    fill_percentage: float
    is_active: bool
    created_at: str


class PositionResponse(BaseModel):
    """Position response model."""
    position_id: str
    signal_id: str | None
    symbol: str
    side: str
    quantity: int
    entry_price: str
    current_price: str | None
    unrealized_pnl: str
    realized_pnl: str
    pnl_percentage: float
    stop_loss: str | None
    is_open: bool


class AccountSummaryResponse(BaseModel):
    """Account summary response."""
    cash: str
    position_value: str
    unrealized_pnl: str
    total_value: str
    open_position_count: int


class CancelOrderResponse(BaseModel):
    """Cancel order response."""
    success: bool
    order_id: str
    message: str


@router.get(
    "/orders",
    response_model=list[OrderResponse],
    summary="List orders",
    description="Get orders with optional filtering.",
)
async def list_orders(
    symbol: str | None = Query(default=None, description="Filter by symbol"),
    status: str | None = Query(default=None, description="Filter by status"),
    engine: ExecutionEngine = Depends(get_execution_engine),
) -> list[OrderResponse]:
    """List orders."""
    order_status = OrderStatus(status) if status else None
    orders = await engine.broker.get_orders(symbol=symbol, status=order_status)
    
    return [
        OrderResponse(
            order_id=o.order_id,
            symbol=o.symbol,
            side=o.side.value,
            order_type=o.order_type.value,
            status=o.status.value,
            quantity=o.quantity,
            filled_quantity=o.filled_quantity,
            remaining_quantity=o.remaining_quantity,
            price=str(o.price) if o.price else None,
            average_fill_price=str(o.average_fill_price) if o.average_fill_price else None,
            fill_percentage=o.fill_percentage,
            is_active=o.is_active,
            created_at=o.created_at.isoformat(),
        )
        for o in orders
    ]


@router.get(
    "/orders/{order_id}",
    response_model=OrderResponse,
    summary="Get order details",
    description="Get detailed information about a specific order.",
)
async def get_order(
    order_id: str,
    engine: ExecutionEngine = Depends(get_execution_engine),
) -> OrderResponse:
    """Get order by ID."""
    order = await engine.broker.get_order(order_id)
    
    if not order:
        raise HTTPException(
            status_code=404,
            detail=f"Order {order_id} not found",
        )
    
    return OrderResponse(
        order_id=order.order_id,
        symbol=order.symbol,
        side=order.side.value,
        order_type=order.order_type.value,
        status=order.status.value,
        quantity=order.quantity,
        filled_quantity=order.filled_quantity,
        remaining_quantity=order.remaining_quantity,
        price=str(order.price) if order.price else None,
        average_fill_price=str(order.average_fill_price) if order.average_fill_price else None,
        fill_percentage=order.fill_percentage,
        is_active=order.is_active,
        created_at=order.created_at.isoformat(),
    )


@router.post(
    "/orders/{order_id}/cancel",
    response_model=CancelOrderResponse,
    summary="Cancel order",
    description="Cancel an open order.",
)
async def cancel_order(
    order_id: str,
    engine: ExecutionEngine = Depends(get_execution_engine),
) -> CancelOrderResponse:
    """Cancel an order."""
    order = await engine.cancel_order(order_id)
    
    if not order:
        raise HTTPException(
            status_code=404,
            detail=f"Order {order_id} not found or cannot be cancelled",
        )
    
    return CancelOrderResponse(
        success=True,
        order_id=order_id,
        message=f"Order {order_id} cancelled successfully",
    )


@router.get(
    "/positions",
    response_model=list[PositionResponse],
    summary="List positions",
    description="Get all open positions.",
)
async def list_positions(
    engine: ExecutionEngine = Depends(get_execution_engine),
) -> list[PositionResponse]:
    """List open positions."""
    positions = await engine.broker.get_positions()
    
    return [
        PositionResponse(
            position_id=p.position_id,
            signal_id=p.signal_id,
            symbol=p.symbol,
            side=p.side.value,
            quantity=p.quantity,
            entry_price=str(p.entry_price),
            current_price=str(p.current_price) if p.current_price else None,
            unrealized_pnl=str(p.unrealized_pnl),
            realized_pnl=str(p.realized_pnl),
            pnl_percentage=p.pnl_percentage,
            stop_loss=str(p.stop_loss) if p.stop_loss else None,
            is_open=p.is_open,
        )
        for p in positions
    ]


@router.get(
    "/positions/{symbol}",
    response_model=PositionResponse,
    summary="Get position",
    description="Get position for a specific symbol.",
)
async def get_position(
    symbol: str,
    engine: ExecutionEngine = Depends(get_execution_engine),
) -> PositionResponse:
    """Get position by symbol."""
    position = await engine.broker.get_position(symbol)
    
    if not position:
        raise HTTPException(
            status_code=404,
            detail=f"No position for {symbol}",
        )
    
    return PositionResponse(
        position_id=position.position_id,
        signal_id=position.signal_id,
        symbol=position.symbol,
        side=position.side.value,
        quantity=position.quantity,
        entry_price=str(position.entry_price),
        current_price=str(position.current_price) if position.current_price else None,
        unrealized_pnl=str(position.unrealized_pnl),
        realized_pnl=str(position.realized_pnl),
        pnl_percentage=position.pnl_percentage,
        stop_loss=str(position.stop_loss) if position.stop_loss else None,
        is_open=position.is_open,
    )


@router.post(
    "/positions/{symbol}/close",
    response_model=PositionResponse,
    summary="Close position",
    description="Close position for a symbol.",
)
async def close_position(
    symbol: str,
    engine: ExecutionEngine = Depends(get_execution_engine),
) -> PositionResponse:
    """Close position for symbol."""
    position = await engine.close_position(symbol)
    
    if not position:
        raise HTTPException(
            status_code=404,
            detail=f"No position for {symbol}",
        )
    
    return PositionResponse(
        position_id=position.position_id,
        signal_id=position.signal_id,
        symbol=position.symbol,
        side=position.side.value,
        quantity=position.quantity,
        entry_price=str(position.entry_price),
        current_price=str(position.current_price) if position.current_price else None,
        unrealized_pnl=str(position.unrealized_pnl),
        realized_pnl=str(position.realized_pnl),
        pnl_percentage=position.pnl_percentage,
        stop_loss=str(position.stop_loss) if position.stop_loss else None,
        is_open=position.is_open,
    )


@router.post(
    "/positions/close-all",
    response_model=list[PositionResponse],
    summary="Close all positions",
    description="Close all open positions.",
)
async def close_all_positions(
    engine: ExecutionEngine = Depends(get_execution_engine),
) -> list[PositionResponse]:
    """Close all positions."""
    positions = await engine.close_all_positions()
    
    return [
        PositionResponse(
            position_id=p.position_id,
            signal_id=p.signal_id,
            symbol=p.symbol,
            side=p.side.value,
            quantity=p.quantity,
            entry_price=str(p.entry_price),
            current_price=str(p.current_price) if p.current_price else None,
            unrealized_pnl=str(p.unrealized_pnl),
            realized_pnl=str(p.realized_pnl),
            pnl_percentage=p.pnl_percentage,
            stop_loss=str(p.stop_loss) if p.stop_loss else None,
            is_open=p.is_open,
        )
        for p in positions
    ]


@router.get(
    "/account",
    response_model=AccountSummaryResponse,
    summary="Get account summary",
    description="Get account balance and position summary.",
)
async def get_account_summary(
    engine: ExecutionEngine = Depends(get_execution_engine),
) -> AccountSummaryResponse:
    """Get account summary."""
    summary = await engine.get_account_summary()
    balance = summary.get("balance", {})
    
    return AccountSummaryResponse(
        cash=str(balance.get("cash", "0")),
        position_value=str(balance.get("position_value", "0")),
        unrealized_pnl=str(balance.get("unrealized_pnl", "0")),
        total_value=str(balance.get("total_value", "0")),
        open_position_count=summary.get("open_position_count", 0),
    )