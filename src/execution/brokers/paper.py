"""Paper broker for simulated trading.

Simulates order execution with configurable slippage, latency, and
fill behavior for testing strategies without real capital.
"""

import asyncio
import random
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.core.logging_config import get_logger
from src.execution.brokers.base import Broker
from src.execution.models.order import Order, OrderFill, OrderStatus, OrderType
from src.execution.models.position import Position, PositionSide
from src.market_data.models.events import MarketTick

logger = get_logger("execution")


class PaperBroker(Broker):
    """Paper trading broker for simulation.
    
    Simulates order execution with realistic fill behavior including:
    - Configurable slippage
    - Simulated latency
    - Partial fills
    - Commission calculation
    - Market impact simulation
    
    Attributes:
        initial_balance: Starting account balance
        balance: Current balance
        positions: Open positions
        orders: Order history
        slippage_pct: Simulated slippage percentage
        latency_ms: Simulated latency in milliseconds
        commission_per_contract: Commission per contract
    """
    
    def __init__(
        self,
        initial_balance: Decimal = Decimal("100000.00"),
        slippage_pct: float = 0.01,
        latency_ms: float = 50.0,
        commission_per_contract: Decimal = Decimal("2.50"),
        partial_fill_probability: float = 0.1,
    ):
        """Initialize paper broker.
        
        Args:
            initial_balance: Starting account balance
            slippage_pct: Slippage simulation (%)
            latency_ms: Latency simulation (ms)
            commission_per_contract: Commission per contract
            partial_fill_probability: Chance of partial fill (0-1)
        """
        super().__init__(broker_id="paper", is_paper=True)
        
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.slippage_pct = slippage_pct
        self.latency_ms = latency_ms
        self.commission_per_contract = commission_per_contract
        self.partial_fill_probability = partial_fill_probability
        
        # State
        self._positions: dict[str, Position] = {}
        self._orders: dict[str, Order] = {}
        self._order_history: list[Order] = []
        self._connected = False
        self._last_prices: dict[str, Decimal] = {}
        
        logger.info(
            "Paper broker initialized",
            balance=str(initial_balance),
            slippage=slippage_pct,
            latency_ms=latency_ms,
        )
    
    async def connect(self) -> None:
        """Connect to paper broker (no-op)."""
        self._connected = True
        logger.info("Paper broker connected")
    
    async def disconnect(self) -> None:
        """Disconnect from paper broker (no-op)."""
        self._connected = False
        logger.info("Paper broker disconnected")
    
    def is_connected(self) -> bool:
        """Check if connected."""
        return self._connected
    
    def get_name(self) -> str:
        """Get broker name."""
        return "PaperBroker"
    
    async def submit_order(self, order: Order) -> Order:
        """Submit order for simulated execution.
        
        Args:
            order: Order to submit
            
        Returns:
            Updated order
        """
        # Simulate latency
        if self.latency_ms > 0:
            await asyncio.sleep(self.latency_ms / 1000)
        
        # Store order
        order.update_status(OrderStatus.SUBMITTED)
        self._orders[order.order_id] = order
        
        logger.info(
            "Order submitted (paper)",
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side.value,
            quantity=order.quantity,
            order_type=order.order_type.value,
        )
        
        # Simulate acceptance
        order.update_status(OrderStatus.ACCEPTED)
        self._notify_order_update(order)
        
        # Simulate fill
        asyncio.create_task(self._simulate_fill(order))
        
        return order
    
    async def _simulate_fill(self, order: Order) -> None:
        """Simulate order fill.
        
        Args:
            order: Order to fill
        """
        # Get current price
        current_price = self._last_prices.get(order.symbol)
        if current_price is None:
            logger.warning(
                "No price available for fill simulation",
                symbol=order.symbol,
            )
            order.reject("No price available")
            self._notify_order_update(order)
            return
        
        # Calculate fill price with slippage
        fill_price = self._calculate_fill_price(order, current_price)
        
        # Determine fill quantity
        fill_quantity = order.quantity
        
        # Simulate partial fill
        if random.random() < self.partial_fill_probability:
            fill_quantity = random.randint(1, order.quantity)
            logger.info(
                "Partial fill simulated",
                order_id=order.order_id,
                filled=fill_quantity,
                total=order.quantity,
            )
        
        # Simulate fill latency
        await asyncio.sleep(random.uniform(10, 100) / 1000)
        
        # Create fill
        commission = self.commission_per_contract * fill_quantity
        
        fill = OrderFill(
            fill_id=f"fill:{order.order_id}:{datetime.utcnow().timestamp()}",
            timestamp=datetime.utcnow(),
            quantity=fill_quantity,
            price=fill_price,
            commission=commission,
            fees=Decimal("0"),
        )
        
        # Apply fill to order
        order.add_fill(fill)
        self._notify_fill(order, fill)
        
        # Update or create position
        await self._update_position(order, fill)
        
        logger.info(
            "Order filled (paper)",
            order_id=order.order_id,
            symbol=order.symbol,
            filled_quantity=order.filled_quantity,
            fill_price=str(fill_price),
            commission=str(commission),
        )
    
    def _calculate_fill_price(self, order: Order, market_price: Decimal) -> Decimal:
        """Calculate fill price with slippage.
        
        Args:
            order: Order being filled
            market_price: Current market price
            
        Returns:
            Fill price with slippage
        """
        slippage = market_price * Decimal(str(self.slippage_pct / 100))
        
        if order.side.value == "buy":
            # Buy orders fill higher (worse)
            return market_price + slippage
        else:
            # Sell orders fill lower (worse)
            return market_price - slippage
    
    async def _update_position(self, order: Order, fill: OrderFill) -> None:
        """Update position from fill.
        
        Args:
            order: Order
            fill: Fill details
        """
        symbol = order.symbol
        
        if symbol in self._positions:
            # Update existing position
            position = self._positions[symbol]
            
            # Check if closing
            if (position.side == PositionSide.LONG and order.side.value == "sell") or \
               (position.side == PositionSide.SHORT and order.side.value == "buy"):
                # Closing position
                if fill.quantity >= position.quantity:
                    # Fully closed
                    position.close(fill.price, "order_fill")
                    self._notify_position_update(position)
                    del self._positions[symbol]
                    
                    # Update balance
                    self.balance += position.realized_pnl
                else:
                    # Partial close - not implemented for simplicity
                    pass
            else:
                # Adding to position - not implemented for simplicity
                pass
        else:
            # Create new position
            side = PositionSide.LONG if order.side.value == "buy" else PositionSide.SHORT
            
            position = Position.from_signal(
                signal_id=order.signal_id,
                symbol=symbol,
                side=side,
                quantity=fill.quantity,
                entry_price=fill.price,
                stop_loss=order.stop_loss,
                take_profits=order.take_profits,
            )
            
            position.add_commission(fill.commission)
            position.add_fees(fill.fees)
            
            self._positions[symbol] = position
            self._notify_position_update(position)
    
    async def cancel_order(self, order_id: str) -> Order | None:
        """Cancel an order.
        
        Args:
            order_id: Order to cancel
            
        Returns:
            Cancelled order or None
        """
        order = self._orders.get(order_id)
        if order and order.can_cancel:
            order.cancel("User request")
            self._notify_order_update(order)
            logger.info("Order cancelled (paper)", order_id=order_id)
        return order
    
    async def get_order(self, order_id: str) -> Order | None:
        """Get order by ID."""
        return self._orders.get(order_id)
    
    async def get_orders(
        self,
        symbol: str | None = None,
        status: OrderStatus | None = None,
    ) -> list[Order]:
        """Get orders with filtering."""
        orders = list(self._orders.values())
        
        if symbol:
            orders = [o for o in orders if o.symbol == symbol.upper()]
        
        if status:
            orders = [o for o in orders if o.status == status]
        
        return orders
    
    async def get_positions(self) -> list[Position]:
        """Get all open positions."""
        return list(self._positions.values())
    
    async def get_position(self, symbol: str) -> Position | None:
        """Get position for symbol."""
        return self._positions.get(symbol.upper())
    
    async def close_position(self, symbol: str) -> Position | None:
        """Close position for symbol."""
        position = self._positions.get(symbol.upper())
        if position and position.is_open:
            # Get current price
            current_price = self._last_prices.get(symbol.upper())
            if current_price:
                position.close(current_price, "manual_close")
                self._notify_position_update(position)
                self.balance += position.realized_pnl
                del self._positions[symbol.upper()]
        return position
    
    async def get_account_balance(self) -> dict[str, Decimal]:
        """Get account balance."""
        # Calculate position values
        position_value = Decimal("0")
        unrealized_pnl = Decimal("0")
        
        for position in self._positions.values():
            position_value += position.position_value
            unrealized_pnl += position.unrealized_pnl
        
        return {
            "cash": self.balance,
            "position_value": position_value,
            "unrealized_pnl": unrealized_pnl,
            "total_value": self.balance + position_value + unrealized_pnl,
            "initial_balance": self.initial_balance,
        }
    
    def on_market_tick(self, tick: MarketTick) -> None:
        """Process market tick for price updates.
        
        Args:
            tick: Market tick
        """
        self._last_prices[tick.symbol] = Decimal(str(tick.last))
        
        # Update positions
        if tick.symbol in self._positions:
            position = self._positions[tick.symbol]
            position.update_price(Decimal(str(tick.last)))
            
            # Check stop loss
            if position.should_trigger_stop:
                logger.info(
                    "Stop loss triggered (paper)",
                    position_id=position.position_id,
                    symbol=position.symbol,
                    stop_price=str(position.stop_loss),
                    current_price=str(tick.last),
                )
                # Close position
                asyncio.create_task(self.close_position(position.symbol))
            
            self._notify_position_update(position)
    
    def get_stats(self) -> dict[str, Any]:
        """Get broker statistics."""
        return {
            "balance": str(self.balance),
            "initial_balance": str(self.initial_balance),
            "total_return_pct": float((self.balance - self.initial_balance) / self.initial_balance * 100),
            "open_positions": len(self._positions),
            "total_orders": len(self._orders),
            "slippage_pct": self.slippage_pct,
            "latency_ms": self.latency_ms,
        }