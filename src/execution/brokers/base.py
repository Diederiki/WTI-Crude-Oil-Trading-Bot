"""Base broker interface.

All broker implementations must implement this interface to ensure
consistent behavior across different broker integrations.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from src.core.logging_config import get_logger
from src.execution.models.order import Order, OrderFill, OrderStatus
from src.execution.models.position import Position

logger = get_logger("execution")


class Broker(ABC):
    """Abstract base class for broker implementations.
    
    This class defines the interface that all brokers must implement.
    It provides common functionality for order management and position
    tracking.
    
    Attributes:
        broker_id: Unique broker identifier
        is_paper: Whether this is a paper/simulated broker
        _order_callbacks: Callbacks for order updates
        _fill_callbacks: Callbacks for fill events
        _position_callbacks: Callbacks for position updates
    """
    
    def __init__(self, broker_id: str, is_paper: bool = False):
        """Initialize broker.
        
        Args:
            broker_id: Unique broker identifier
            is_paper: Whether this is paper trading
        """
        self.broker_id = broker_id
        self.is_paper = is_paper
        
        # Event callbacks
        self._order_callbacks: list[Callable[[Order], None]] = []
        self._fill_callbacks: list[Callable[[Order, OrderFill], None]] = []
        self._position_callbacks: list[Callable[[Position], None]] = []
        
        logger.info(
            "Broker initialized",
            broker_id=broker_id,
            is_paper=is_paper,
        )
    
    @abstractmethod
    async def connect(self) -> None:
        """Connect to broker.
        
        Establishes connection to the broker API and prepares
        for trading operations.
        """
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from broker.
        
        Closes connection and cleans up resources.
        """
        pass
    
    @abstractmethod
    async def submit_order(self, order: Order) -> Order:
        """Submit order to broker.
        
        Args:
            order: Order to submit
            
        Returns:
            Updated order with broker response
        """
        pass
    
    @abstractmethod
    async def cancel_order(self, order_id: str) -> Order | None:
        """Cancel an order.
        
        Args:
            order_id: Order to cancel
            
        Returns:
            Cancelled order or None if not found
        """
        pass
    
    @abstractmethod
    async def get_order(self, order_id: str) -> Order | None:
        """Get order by ID.
        
        Args:
            order_id: Order identifier
            
        Returns:
            Order or None if not found
        """
        pass
    
    @abstractmethod
    async def get_orders(
        self,
        symbol: str | None = None,
        status: OrderStatus | None = None,
    ) -> list[Order]:
        """Get orders with optional filtering.
        
        Args:
            symbol: Optional symbol filter
            status: Optional status filter
            
        Returns:
            List of orders
        """
        pass
    
    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """Get all open positions.
        
        Returns:
            List of open positions
        """
        pass
    
    @abstractmethod
    async def get_position(self, symbol: str) -> Position | None:
        """Get position for symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Position or None if not found
        """
        pass
    
    @abstractmethod
    async def close_position(self, symbol: str) -> Position | None:
        """Close position for symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Closed position or None if not found
        """
        pass
    
    @abstractmethod
    async def get_account_balance(self) -> dict[str, Decimal]:
        """Get account balance information.
        
        Returns:
            Dictionary with balance details
        """
        pass
    
    def on_order_update(self, callback: Callable[[Order], None]) -> None:
        """Register callback for order updates.
        
        Args:
            callback: Function to call on order updates
        """
        self._order_callbacks.append(callback)
    
    def on_fill(self, callback: Callable[[Order, OrderFill], None]) -> None:
        """Register callback for fill events.
        
        Args:
            callback: Function to call on fills
        """
        self._fill_callbacks.append(callback)
    
    def on_position_update(self, callback: Callable[[Position], None]) -> None:
        """Register callback for position updates.
        
        Args:
            callback: Function to call on position updates
        """
        self._position_callbacks.append(callback)
    
    def _notify_order_update(self, order: Order) -> None:
        """Notify order update callbacks.
        
        Args:
            order: Updated order
        """
        for callback in self._order_callbacks:
            try:
                callback(order)
            except Exception as e:
                logger.error(
                    "Error in order callback",
                    error=str(e),
                )
    
    def _notify_fill(self, order: Order, fill: OrderFill) -> None:
        """Notify fill callbacks.
        
        Args:
            order: Order that was filled
            fill: Fill details
        """
        for callback in self._fill_callbacks:
            try:
                callback(order, fill)
            except Exception as e:
                logger.error(
                    "Error in fill callback",
                    error=str(e),
                )
    
    def _notify_position_update(self, position: Position) -> None:
        """Notify position update callbacks.
        
        Args:
            position: Updated position
        """
        for callback in self._position_callbacks:
            try:
                callback(position)
            except Exception as e:
                logger.error(
                    "Error in position callback",
                    error=str(e),
                )
    
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if broker is connected.
        
        Returns:
            True if connected
        """
        pass
    
    @abstractmethod
    def get_name(self) -> str:
        """Get broker name.
        
        Returns:
            Broker name
        """
        pass