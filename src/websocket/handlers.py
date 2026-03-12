"""WebSocket handlers for different data types.

Provides handlers for market data, signals, orders, and system status
WebSocket subscriptions.
"""

from typing import Any

from src.core.logging_config import get_logger
from src.execution.models.order import Order, OrderFill
from src.execution.models.position import Position
from src.market_data.models.events import MarketTick, MarketBar
from src.strategy.models.signal import Signal
from src.websocket.manager import WebSocketManager

logger = get_logger("websocket")


class MarketDataHandler:
    """Handler for market data WebSocket broadcasts.
    
    Broadcasts ticks and bars to subscribed clients.
    
    Attributes:
        manager: WebSocket manager
    """
    
    def __init__(self, manager: WebSocketManager):
        """Initialize handler.
        
        Args:
            manager: WebSocket manager
        """
        self.manager = manager
    
    def on_tick(self, tick: MarketTick) -> None:
        """Handle tick for broadcasting.
        
        Args:
            tick: Market tick
        """
        message = {
            "type": "tick",
            "data": {
                "symbol": tick.symbol,
                "timestamp": tick.timestamp.isoformat(),
                "bid": tick.bid,
                "ask": tick.ask,
                "last": tick.last,
                "bid_size": tick.bid_size,
                "ask_size": tick.ask_size,
                "last_size": tick.last_size,
                "volume": tick.volume,
                "spread": tick.spread,
            },
        }
        
        # Broadcast asynchronously
        import asyncio
        asyncio.create_task(
            self.manager.broadcast(message, subscription_type="market_data")
        )
    
    def on_bar(self, bar: MarketBar) -> None:
        """Handle bar for broadcasting.
        
        Args:
            bar: Market bar
        """
        message = {
            "type": "bar",
            "data": {
                "symbol": bar.symbol,
                "timestamp": bar.timestamp.isoformat(),
                "interval": bar.interval_seconds,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "vwap": bar.vwap,
                "trades": bar.trades,
            },
        }
        
        import asyncio
        asyncio.create_task(
            self.manager.broadcast(message, subscription_type="market_data")
        )


class SignalHandler:
    """Handler for signal WebSocket broadcasts.
    
    Broadcasts trading signals to subscribed clients.
    
    Attributes:
        manager: WebSocket manager
    """
    
    def __init__(self, manager: WebSocketManager):
        """Initialize handler.
        
        Args:
            manager: WebSocket manager
        """
        self.manager = manager
    
    def on_signal(self, signal: Signal) -> None:
        """Handle signal for broadcasting.
        
        Args:
            signal: Trading signal
        """
        message = {
            "type": "signal",
            "data": {
                "signal_id": signal.signal_id,
                "timestamp": signal.timestamp.isoformat(),
                "symbol": signal.symbol,
                "signal_type": signal.signal_type.value,
                "direction": signal.direction,
                "trigger_price": signal.trigger_price,
                "entry_price": signal.entry_price,
                "stop_loss": signal.stop_loss,
                "take_profit_levels": signal.take_profit_levels,
                "confidence": signal.confidence,
                "setup_description": signal.setup_description,
                "risk_reward_ratio": signal.risk_reward_ratio,
            },
        }
        
        import asyncio
        asyncio.create_task(
            self.manager.broadcast(message, subscription_type="signals")
        )


class OrderHandler:
    """Handler for order WebSocket broadcasts.
    
    Broadcasts order updates and fills to subscribed clients.
    
    Attributes:
        manager: WebSocket manager
    """
    
    def __init__(self, manager: WebSocketManager):
        """Initialize handler.
        
        Args:
            manager: WebSocket manager
        """
        self.manager = manager
    
    def on_order_update(self, order: Order) -> None:
        """Handle order update for broadcasting.
        
        Args:
            order: Updated order
        """
        message = {
            "type": "order_update",
            "data": {
                "order_id": order.order_id,
                "symbol": order.symbol,
                "side": order.side.value,
                "status": order.status.value,
                "quantity": order.quantity,
                "filled_quantity": order.filled_quantity,
                "remaining_quantity": order.remaining_quantity,
                "average_fill_price": str(order.average_fill_price) if order.average_fill_price else None,
                "fill_percentage": order.fill_percentage,
                "is_active": order.is_active,
            },
        }
        
        import asyncio
        asyncio.create_task(
            self.manager.broadcast(message, subscription_type="orders")
        )
    
    def on_fill(self, order: Order, fill: OrderFill) -> None:
        """Handle fill for broadcasting.
        
        Args:
            order: Filled order
            fill: Fill details
        """
        message = {
            "type": "fill",
            "data": {
                "order_id": order.order_id,
                "fill_id": fill.fill_id,
                "symbol": order.symbol,
                "quantity": fill.quantity,
                "price": str(fill.price),
                "commission": str(fill.commission),
                "timestamp": fill.timestamp.isoformat(),
            },
        }
        
        import asyncio
        asyncio.create_task(
            self.manager.broadcast(message, subscription_type="orders")
        )


class PositionHandler:
    """Handler for position WebSocket broadcasts.
    
    Broadcasts position updates to subscribed clients.
    
    Attributes:
        manager: WebSocket manager
    """
    
    def __init__(self, manager: WebSocketManager):
        """Initialize handler.
        
        Args:
            manager: WebSocket manager
        """
        self.manager = manager
    
    def on_position_update(self, position: Position) -> None:
        """Handle position update for broadcasting.
        
        Args:
            position: Updated position
        """
        message = {
            "type": "position_update",
            "data": {
                "position_id": position.position_id,
                "symbol": position.symbol,
                "side": position.side.value,
                "quantity": position.quantity,
                "entry_price": str(position.entry_price),
                "current_price": str(position.current_price) if position.current_price else None,
                "unrealized_pnl": str(position.unrealized_pnl),
                "realized_pnl": str(position.realized_pnl),
                "pnl_percentage": position.pnl_percentage,
                "is_open": position.is_open,
            },
        }
        
        import asyncio
        asyncio.create_task(
            self.manager.broadcast(message, subscription_type="positions")
        )


class SystemStatusHandler:
    """Handler for system status WebSocket broadcasts.
    
    Broadcasts system status and alerts to subscribed clients.
    
    Attributes:
        manager: WebSocket manager
    """
    
    def __init__(self, manager: WebSocketManager):
        """Initialize handler.
        
        Args:
            manager: WebSocket manager
        """
        self.manager = manager
    
    async def broadcast_status(self, status: dict[str, Any]) -> None:
        """Broadcast system status.
        
        Args:
            status: System status dictionary
        """
        message = {
            "type": "system_status",
            "data": status,
        }
        
        await self.manager.broadcast(message, subscription_type="system")
    
    async def broadcast_alert(self, alert_type: str, message: str, data: dict[str, Any] | None = None) -> None:
        """Broadcast system alert.
        
        Args:
            alert_type: Type of alert
            message: Alert message
            data: Optional alert data
        """
        alert = {
            "type": "alert",
            "data": {
                "alert_type": alert_type,
                "message": message,
                "timestamp": datetime.utcnow().isoformat(),
                **(data or {}),
            },
        }
        
        await self.manager.broadcast(alert, subscription_type="alerts")
        
from datetime import datetime