"""Order models for execution management.

Defines order types, statuses, and the Order model with full lifecycle
management for trading operations.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OrderSide(str, Enum):
    """Order side enumeration."""
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    """Order type enumeration."""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    TRAILING_STOP = "trailing_stop"


class OrderStatus(str, Enum):
    """Order lifecycle status."""
    PENDING = "pending"           # Created but not submitted
    SUBMITTED = "submitted"       # Sent to broker
    ACCEPTED = "accepted"         # Acknowledged by broker
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class TimeInForce(str, Enum):
    """Time in force options."""
    GTC = "gtc"  # Good till cancelled
    DAY = "day"  # Day order
    IOC = "ioc"  # Immediate or cancel
    FOK = "fok"  # Fill or kill


class OrderFill(BaseModel):
    """Represents a single fill/execution.
    
    Attributes:
        fill_id: Unique fill identifier
        timestamp: Fill timestamp
        quantity: Filled quantity
        price: Fill price
        commission: Trading commission
        fees: Additional fees
    """
    
    model_config = ConfigDict(frozen=True)
    
    fill_id: str
    timestamp: datetime
    quantity: int = Field(..., gt=0)
    price: Decimal
    commission: Decimal = Field(default=Decimal("0"))
    fees: Decimal = Field(default=Decimal("0"))
    
    @property
    def value(self) -> Decimal:
        """Calculate fill value."""
        return self.price * self.quantity
    
    @property
    def total_cost(self) -> Decimal:
        """Calculate total cost including fees."""
        return self.value + self.commission + self.fees


class Order(BaseModel):
    """Trading order with full lifecycle management.
    
    Represents a trading order from creation through fill, with
    support for complex order types and risk management.
    
    Attributes:
        order_id: Unique order identifier
        client_order_id: Client-provided order ID
        signal_id: Associated signal ID
        symbol: Trading symbol
        side: Buy or sell
        order_type: Order type
        status: Current order status
        quantity: Order quantity
        filled_quantity: Already filled quantity
        remaining_quantity: Quantity left to fill
        price: Order price (for limit orders)
        stop_price: Stop price (for stop orders)
        time_in_force: Order duration
        created_at: Creation timestamp
        submitted_at: Submission timestamp
        filled_at: Fill timestamp
        cancelled_at: Cancellation timestamp
        fills: List of fills
        average_fill_price: Weighted average fill price
        total_commission: Total commission paid
        total_fees: Total fees paid
        stop_loss: Associated stop loss price
        take_profits: Associated take profit prices
        metadata: Additional order data
        reject_reason: Reason for rejection
    """
    
    model_config = ConfigDict(
        extra="allow",
        json_encoders={
            datetime: lambda v: v.isoformat(),
            Decimal: lambda v: str(v),
        },
    )
    
    # Identification
    order_id: str = Field(..., min_length=1)
    client_order_id: str | None = Field(default=None)
    signal_id: str | None = Field(default=None)
    
    # Order details
    symbol: str = Field(..., min_length=1)
    side: OrderSide
    order_type: OrderType
    status: OrderStatus = Field(default=OrderStatus.PENDING)
    time_in_force: TimeInForce = Field(default=TimeInForce.DAY)
    
    # Quantity tracking
    quantity: int = Field(..., gt=0)
    filled_quantity: int = Field(default=0, ge=0)
    
    # Pricing
    price: Decimal | None = Field(default=None)
    stop_price: Decimal | None = Field(default=None)
    trailing_stop_distance: Decimal | None = Field(default=None)
    
    # Fill tracking
    fills: list[OrderFill] = Field(default_factory=list)
    average_fill_price: Decimal | None = Field(default=None)
    total_commission: Decimal = Field(default=Decimal("0"))
    total_fees: Decimal = Field(default=Decimal("0"))
    
    # Risk management
    stop_loss: Decimal | None = Field(default=None)
    take_profits: list[Decimal] = Field(default_factory=list)
    max_slippage_pct: Decimal = Field(default=Decimal("0.1"))
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    submitted_at: datetime | None = Field(default=None)
    accepted_at: datetime | None = Field(default=None)
    filled_at: datetime | None = Field(default=None)
    cancelled_at: datetime | None = Field(default=None)
    expired_at: datetime | None = Field(default=None)
    
    # Error tracking
    reject_reason: str | None = Field(default=None)
    error_message: str | None = Field(default=None)
    
    # Metadata
    metadata: dict[str, Any] = Field(default_factory=dict)
    
    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        """Normalize symbol to uppercase."""
        return v.upper().strip()
    
    @property
    def remaining_quantity(self) -> int:
        """Calculate remaining quantity to fill."""
        return self.quantity - self.filled_quantity
    
    @property
    def is_filled(self) -> bool:
        """Check if order is completely filled."""
        return self.filled_quantity >= self.quantity
    
    @property
    def is_active(self) -> bool:
        """Check if order is still active."""
        return self.status in [
            OrderStatus.PENDING,
            OrderStatus.SUBMITTED,
            OrderStatus.ACCEPTED,
            OrderStatus.PARTIALLY_FILLED,
        ]
    
    @property
    def can_cancel(self) -> bool:
        """Check if order can be cancelled."""
        return self.status in [
            OrderStatus.PENDING,
            OrderStatus.SUBMITTED,
            OrderStatus.ACCEPTED,
            OrderStatus.PARTIALLY_FILLED,
        ]
    
    @property
    def fill_percentage(self) -> float:
        """Calculate fill percentage."""
        if self.quantity == 0:
            return 0.0
        return (self.filled_quantity / self.quantity) * 100
    
    @property
    def total_value(self) -> Decimal:
        """Calculate total filled value."""
        return sum(fill.value for fill in self.fills)
    
    @property
    def total_cost_with_fees(self) -> Decimal:
        """Calculate total cost including all fees."""
        return self.total_value + self.total_commission + self.total_fees
    
    def update_status(self, status: OrderStatus) -> "Order":
        """Update order status.
        
        Args:
            status: New status
            
        Returns:
            Self for chaining
        """
        self.status = status
        
        now = datetime.utcnow()
        
        if status == OrderStatus.SUBMITTED and not self.submitted_at:
            self.submitted_at = now
        elif status == OrderStatus.ACCEPTED and not self.accepted_at:
            self.accepted_at = now
        elif status == OrderStatus.FILLED and not self.filled_at:
            self.filled_at = now
        elif status == OrderStatus.CANCELLED and not self.cancelled_at:
            self.cancelled_at = now
        elif status == OrderStatus.EXPIRED and not self.expired_at:
            self.expired_at = now
        
        return self
    
    def add_fill(self, fill: OrderFill) -> "Order":
        """Add a fill to the order.
        
        Args:
            fill: Fill to add
            
        Returns:
            Self for chaining
        """
        self.fills.append(fill)
        self.filled_quantity += fill.quantity
        self.total_commission += fill.commission
        self.total_fees += fill.fees
        
        # Update average fill price
        if self.filled_quantity > 0:
            total_value = sum(f.value for f in self.fills)
            self.average_fill_price = total_value / self.filled_quantity
        
        # Update status
        if self.filled_quantity >= self.quantity:
            self.update_status(OrderStatus.FILLED)
        else:
            self.update_status(OrderStatus.PARTIALLY_FILLED)
        
        return self
    
    def cancel(self, reason: str | None = None) -> "Order":
        """Cancel the order.
        
        Args:
            reason: Optional cancellation reason
            
        Returns:
            Self for chaining
        """
        if self.can_cancel:
            self.update_status(OrderStatus.CANCELLED)
            if reason:
                self.metadata["cancel_reason"] = reason
        
        return self
    
    def reject(self, reason: str) -> "Order":
        """Reject the order.
        
        Args:
            reason: Rejection reason
            
        Returns:
            Self for chaining
        """
        self.update_status(OrderStatus.REJECTED)
        self.reject_reason = reason
        return self
    
    def check_slippage(self, expected_price: Decimal, actual_price: Decimal) -> bool:
        """Check if slippage is within acceptable range.
        
        Args:
            expected_price: Expected fill price
            actual_price: Actual fill price
            
        Returns:
            True if slippage acceptable
        """
        if expected_price == 0:
            return True
        
        slippage_pct = abs(actual_price - expected_price) / expected_price * 100
        return slippage_pct <= self.max_slippage_pct
    
    def to_dict(self) -> dict[str, Any]:
        """Convert order to dictionary."""
        return {
            "order_id": self.order_id,
            "client_order_id": self.client_order_id,
            "signal_id": self.signal_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "order_type": self.order_type.value,
            "status": self.status.value,
            "quantity": self.quantity,
            "filled_quantity": self.filled_quantity,
            "remaining_quantity": self.remaining_quantity,
            "price": str(self.price) if self.price else None,
            "stop_price": str(self.stop_price) if self.stop_price else None,
            "average_fill_price": str(self.average_fill_price) if self.average_fill_price else None,
            "fill_percentage": self.fill_percentage,
            "total_commission": str(self.total_commission),
            "total_fees": str(self.total_fees),
            "is_filled": self.is_filled,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
            "filled_at": self.filled_at.isoformat() if self.filled_at else None,
        }
    
    @classmethod
    def create_market_order(
        cls,
        symbol: str,
        side: OrderSide,
        quantity: int,
        signal_id: str | None = None,
    ) -> "Order":
        """Create a market order.
        
        Args:
            symbol: Trading symbol
            side: Buy or sell
            quantity: Order quantity
            signal_id: Associated signal ID
            
        Returns:
            New market order
        """
        return cls(
            order_id=f"mkt:{symbol}:{datetime.utcnow().timestamp()}",
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            signal_id=signal_id,
        )
    
    @classmethod
    def create_limit_order(
        cls,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: Decimal,
        signal_id: str | None = None,
        time_in_force: TimeInForce = TimeInForce.DAY,
    ) -> "Order":
        """Create a limit order.
        
        Args:
            symbol: Trading symbol
            side: Buy or sell
            quantity: Order quantity
            price: Limit price
            signal_id: Associated signal ID
            time_in_force: Order duration
            
        Returns:
            New limit order
        """
        return cls(
            order_id=f"lmt:{symbol}:{datetime.utcnow().timestamp()}",
            symbol=symbol,
            side=side,
            order_type=OrderType.LIMIT,
            quantity=quantity,
            price=price,
            signal_id=signal_id,
            time_in_force=time_in_force,
        )
    
    @classmethod
    def create_stop_order(
        cls,
        symbol: str,
        side: OrderSide,
        quantity: int,
        stop_price: Decimal,
        signal_id: str | None = None,
    ) -> "Order":
        """Create a stop order.
        
        Args:
            symbol: Trading symbol
            side: Buy or sell
            quantity: Order quantity
            stop_price: Stop trigger price
            signal_id: Associated signal ID
            
        Returns:
            New stop order
        """
        return cls(
            order_id=f"stp:{symbol}:{datetime.utcnow().timestamp()}",
            symbol=symbol,
            side=side,
            order_type=OrderType.STOP,
            quantity=quantity,
            stop_price=stop_price,
            signal_id=signal_id,
        )