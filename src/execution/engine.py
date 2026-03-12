"""Execution engine for order management.

Coordinates order submission, position tracking, and risk management
with support for multiple brokers and order types.
"""

import asyncio
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from src.core.logging_config import get_logger
from src.event_bus import EventBus, Event, EventType
from src.execution.brokers.base import Broker
from src.execution.models.order import Order, OrderSide, OrderType, OrderStatus, OrderFill
from src.execution.models.position import Position, PositionSide
from src.risk.manager import RiskManager
from src.strategy.models.signal import Signal

logger = get_logger("execution")


class ExecutionEngine:
    """Main execution engine for order management.
    
    Coordinates between signals, risk management, and broker execution
    with full order lifecycle management and position tracking.
    
    Attributes:
        broker: Broker for order execution
        risk_manager: Risk manager for validation
        event_bus: Event bus for notifications
        _order_callbacks: Order update callbacks
        _position_callbacks: Position update callbacks
        _running: Whether engine is running
    """
    
    def __init__(
        self,
        broker: Broker,
        risk_manager: RiskManager,
        event_bus: EventBus | None = None,
    ):
        """Initialize execution engine.
        
        Args:
            broker: Broker for order execution
            risk_manager: Risk manager for validation
            event_bus: Optional event bus
        """
        self.broker = broker
        self.risk_manager = risk_manager
        self.event_bus = event_bus
        
        # Callbacks
        self._order_callbacks: list[Callable[[Order], None]] = []
        self._position_callbacks: list[Callable[[Position], None]] = []
        
        # State
        self._running = False
        
        # Register broker callbacks
        self.broker.on_order_update(self._on_broker_order_update)
        self.broker.on_fill(self._on_broker_fill)
        self.broker.on_position_update(self._on_broker_position_update)
        
        logger.info("Execution engine initialized")
    
    async def start(self) -> None:
        """Start the execution engine."""
        if self._running:
            return
        
        # Connect broker
        await self.broker.connect()
        
        self._running = True
        logger.info("Execution engine started")
    
    async def stop(self) -> None:
        """Stop the execution engine."""
        if not self._running:
            return
        
        self._running = False
        
        # Disconnect broker
        await self.broker.disconnect()
        
        logger.info("Execution engine stopped")
    
    def on_order_update(self, callback: Callable[[Order], None]) -> None:
        """Register order update callback.
        
        Args:
            callback: Function to call on order updates
        """
        self._order_callbacks.append(callback)
    
    def on_position_update(self, callback: Callable[[Position], None]) -> None:
        """Register position update callback.
        
        Args:
            callback: Function to call on position updates
        """
        self._position_callbacks.append(callback)
    
    async def execute_signal(self, signal: Signal) -> Order | None:
        """Execute a trading signal.
        
        Args:
            signal: Signal to execute
            
        Returns:
            Submitted order or None if rejected
        """
        if not self._running:
            logger.warning("Execution engine not running")
            return None
        
        # Get account balance
        balance_info = await self.broker.get_account_balance()
        current_balance = balance_info.get("total_value", Decimal("0"))
        
        # Determine order side
        side = OrderSide.BUY if signal.is_long else OrderSide.SELL
        
        # Check risk
        allowed, reason = self.risk_manager.check_position_open(
            symbol=signal.symbol,
            side=signal.direction,
            size=signal.position_size,
            entry_price=Decimal(str(signal.entry_price)),
            stop_loss=Decimal(str(signal.stop_loss)) if signal.stop_loss else None,
            current_balance=current_balance,
        )
        
        if not allowed:
            logger.warning(
                "Signal rejected by risk manager",
                signal_id=signal.signal_id,
                reason=reason,
            )
            return None
        
        # Create order
        order = Order.create_limit_order(
            symbol=signal.symbol,
            side=side,
            quantity=signal.position_size,
            price=Decimal(str(signal.entry_price)),
            signal_id=signal.signal_id,
        )
        
        # Add stop loss and take profits
        if signal.stop_loss:
            order.stop_loss = Decimal(str(signal.stop_loss))
        if signal.take_profit_levels:
            order.take_profits = [Decimal(str(tp)) for tp in signal.take_profit_levels]
        
        # Check order risk
        allowed, reason = self.risk_manager.check_order(order, current_balance)
        if not allowed:
            logger.warning(
                "Order rejected by risk manager",
                order_id=order.order_id,
                reason=reason,
            )
            return None
        
        # Submit order
        try:
            submitted = await self.broker.submit_order(order)
            
            logger.info(
                "Order submitted for signal",
                signal_id=signal.signal_id,
                order_id=submitted.order_id,
                symbol=submitted.symbol,
                side=submitted.side.value,
                quantity=submitted.quantity,
            )
            
            # Notify
            self._notify_order_update(submitted)
            
            # Publish event
            if self.event_bus:
                await self.event_bus.publish(Event.create(
                    event_type=EventType.ORDER_SUBMITTED,
                    source="execution_engine",
                    payload=submitted.to_dict(),
                ))
            
            return submitted
            
        except Exception as e:
            logger.error(
                "Failed to submit order",
                signal_id=signal.signal_id,
                error=str(e),
            )
            return None
    
    async def cancel_order(self, order_id: str) -> Order | None:
        """Cancel an order.
        
        Args:
            order_id: Order to cancel
            
        Returns:
            Cancelled order or None
        """
        order = await self.broker.cancel_order(order_id)
        if order:
            self._notify_order_update(order)
        return order
    
    async def close_position(self, symbol: str) -> Position | None:
        """Close position for symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Closed position or None
        """
        position = await self.broker.close_position(symbol)
        if position:
            self.risk_manager.on_position_closed(position)
            self._notify_position_update(position)
        return position
    
    async def close_all_positions(self) -> list[Position]:
        """Close all open positions.
        
        Returns:
            List of closed positions
        """
        positions = await self.broker.get_positions()
        closed = []
        
        for position in positions:
            if position.is_open:
                closed_pos = await self.close_position(position.symbol)
                if closed_pos:
                    closed.append(closed_pos)
        
        return closed
    
    def _on_broker_order_update(self, order: Order) -> None:
        """Handle broker order update.
        
        Args:
            order: Updated order
        """
        self._notify_order_update(order)
        
        # Publish event
        if self.event_bus:
            asyncio.create_task(self.event_bus.publish(Event.create(
                event_type=EventType.ORDER_SUBMITTED,
                source="execution_engine",
                payload=order.to_dict(),
            )))
    
    def _on_broker_fill(self, order: Order, fill: OrderFill) -> None:
        """Handle broker fill.
        
        Args:
            order: Filled order
            fill: Fill details
        """
        logger.info(
            "Order fill received",
            order_id=order.order_id,
            fill_id=fill.fill_id,
            quantity=fill.quantity,
            price=str(fill.price),
        )
        
        # Publish event
        if self.event_bus:
            asyncio.create_task(self.event_bus.publish(Event.create(
                event_type=EventType.ORDER_FILLED,
                source="execution_engine",
                payload={
                    "order": order.to_dict(),
                    "fill": {
                        "fill_id": fill.fill_id,
                        "quantity": fill.quantity,
                        "price": str(fill.price),
                        "timestamp": fill.timestamp.isoformat(),
                    },
                },
            )))
    
    def _on_broker_position_update(self, position: Position) -> None:
        """Handle broker position update.
        
        Args:
            position: Updated position
        """
        # Update risk manager
        if position.is_open:
            self.risk_manager.on_position_opened(position)
        else:
            self.risk_manager.on_position_closed(position)
        
        self._notify_position_update(position)
    
    def _notify_order_update(self, order: Order) -> None:
        """Notify order callbacks.
        
        Args:
            order: Updated order
        """
        for callback in self._order_callbacks:
            try:
                callback(order)
            except Exception as e:
                logger.error("Error in order callback", error=str(e))
    
    def _notify_position_update(self, position: Position) -> None:
        """Notify position callbacks.
        
        Args:
            position: Updated position
        """
        for callback in self._position_callbacks:
            try:
                callback(position)
            except Exception as e:
                logger.error("Error in position callback", error=str(e))
    
    async def get_account_summary(self) -> dict[str, Any]:
        """Get account summary.
        
        Returns:
            Account summary
        """
        balance = await self.broker.get_account_balance()
        positions = await self.broker.get_positions()
        risk_status = self.risk_manager.get_status()
        
        return {
            "balance": balance,
            "positions": [p.to_dict() for p in positions],
            "risk": risk_status,
            "open_position_count": len(positions),
        }
    
    def is_running(self) -> bool:
        """Check if engine is running.
        
        Returns:
            True if running
        """
        return self._running