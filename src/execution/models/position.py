"""Position models for tracking open positions.

Manages open positions with P&L calculation, risk metrics, and
position lifecycle tracking.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PositionSide(str, Enum):
    """Position side enumeration."""
    LONG = "long"
    SHORT = "short"


class Position(BaseModel):
    """Open position with P&L tracking.
    
    Tracks an open position from entry through exit with
    real-time P&L calculation and risk metrics.
    
    Attributes:
        position_id: Unique position identifier
        signal_id: Associated signal ID
        symbol: Trading symbol
        side: Long or short
        quantity: Position size
        entry_price: Average entry price
        entry_time: Entry timestamp
        exit_price: Exit price (when closed)
        exit_time: Exit timestamp
        stop_loss: Stop loss price
        take_profits: Take profit targets
        unrealized_pnl: Current unrealized P&L
        realized_pnl: Realized P&L (when closed)
        total_commission: Total commissions paid
        total_fees: Total fees paid
        highest_price: Highest price seen (for trailing stops)
        lowest_price: Lowest price seen
        is_open: Whether position is still open
        metadata: Additional position data
    """
    
    model_config = ConfigDict(
        extra="allow",
        json_encoders={
            datetime: lambda v: v.isoformat(),
            Decimal: lambda v: str(v),
        },
    )
    
    # Identification
    position_id: str = Field(..., min_length=1)
    signal_id: str | None = Field(default=None)
    order_id: str | None = Field(default=None)
    
    # Position details
    symbol: str = Field(..., min_length=1)
    side: PositionSide
    quantity: int = Field(..., gt=0)
    
    # Entry tracking
    entry_price: Decimal
    entry_time: datetime = Field(default_factory=datetime.utcnow)
    
    # Exit tracking
    exit_price: Decimal | None = Field(default=None)
    exit_time: datetime | None = Field(default=None)
    
    # Risk management
    stop_loss: Decimal | None = Field(default=None)
    take_profits: list[Decimal] = Field(default_factory=list)
    trailing_stop_distance: Decimal | None = Field(default=None)
    
    # P&L tracking
    unrealized_pnl: Decimal = Field(default=Decimal("0"))
    realized_pnl: Decimal = Field(default=Decimal("0"))
    total_commission: Decimal = Field(default=Decimal("0"))
    total_fees: Decimal = Field(default=Decimal("0"))
    
    # Price tracking
    current_price: Decimal | None = Field(default=None)
    highest_price: Decimal | None = Field(default=None)
    lowest_price: Decimal | None = Field(default=None)
    
    # Status
    is_open: bool = Field(default=True)
    close_reason: str | None = Field(default=None)
    
    # Metadata
    metadata: dict[str, Any] = Field(default_factory=dict)
    
    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        """Normalize symbol to uppercase."""
        return v.upper().strip()
    
    @property
    def position_value(self) -> Decimal:
        """Calculate current position value."""
        if self.current_price is None:
            return self.entry_price * self.quantity
        return self.current_price * self.quantity
    
    @property
    def entry_value(self) -> Decimal:
        """Calculate entry value."""
        return self.entry_price * self.quantity
    
    @property
    def market_value(self) -> Decimal:
        """Calculate current market value."""
        if self.current_price is None:
            return self.entry_value
        return self.current_price * self.quantity
    
    def update_price(self, price: Decimal) -> "Position":
        """Update current price and recalculate P&L.
        
        Args:
            price: Current market price
            
        Returns:
            Self for chaining
        """
        self.current_price = price
        
        # Update high/low tracking
        if self.highest_price is None or price > self.highest_price:
            self.highest_price = price
        if self.lowest_price is None or price < self.lowest_price:
            self.lowest_price = price
        
        # Calculate unrealized P&L
        if self.side == PositionSide.LONG:
            self.unrealized_pnl = (price - self.entry_price) * self.quantity
        else:
            self.unrealized_pnl = (self.entry_price - price) * self.quantity
        
        return self
    
    def close(
        self,
        exit_price: Decimal,
        reason: str = "manual",
    ) -> "Position":
        """Close the position.
        
        Args:
            exit_price: Exit price
            reason: Close reason
            
        Returns:
            Self for chaining
        """
        self.exit_price = exit_price
        self.exit_time = datetime.utcnow()
        self.is_open = False
        self.close_reason = reason
        
        # Calculate realized P&L
        if self.side == PositionSide.LONG:
            self.realized_pnl = (exit_price - self.entry_price) * self.quantity
        else:
            self.realized_pnl = (self.entry_price - exit_price) * self.quantity
        
        # Subtract costs
        self.realized_pnl -= (self.total_commission + self.total_fees)
        
        # Clear unrealized
        self.unrealized_pnl = Decimal("0")
        self.current_price = exit_price
        
        return self
    
    @property
    def pnl_percentage(self) -> float:
        """Calculate P&L as percentage of entry value."""
        if self.entry_value == 0:
            return 0.0
        
        if self.is_open:
            pnl = self.unrealized_pnl
        else:
            pnl = self.realized_pnl
        
        return float(pnl / self.entry_value * 100)
    
    @property
    def risk_amount(self) -> Decimal:
        """Calculate risk amount based on stop loss."""
        if self.stop_loss is None:
            return Decimal("0")
        
        if self.side == PositionSide.LONG:
            return (self.entry_price - self.stop_loss) * self.quantity
        else:
            return (self.stop_loss - self.entry_price) * self.quantity
    
    @property
    def distance_to_stop_pct(self) -> float:
        """Calculate percentage distance to stop loss."""
        if self.stop_loss is None or self.current_price is None:
            return 0.0
        
        if self.side == PositionSide.LONG:
            return float((self.current_price - self.stop_loss) / self.entry_price * 100)
        else:
            return float((self.stop_loss - self.current_price) / self.entry_price * 100)
    
    @property
    def should_trigger_stop(self) -> bool:
        """Check if stop loss should be triggered."""
        if self.stop_loss is None or self.current_price is None:
            return False
        
        if self.side == PositionSide.LONG:
            return self.current_price <= self.stop_loss
        else:
            return self.current_price >= self.stop_loss
    
    def update_trailing_stop(self) -> "Position":
        """Update trailing stop based on price movement.
        
        Returns:
            Self for chaining
        """
        if self.trailing_stop_distance is None:
            return self
        
        if self.side == PositionSide.LONG:
            # For longs, trail below highest price
            if self.highest_price is not None:
                new_stop = self.highest_price - self.trailing_stop_distance
                if self.stop_loss is None or new_stop > self.stop_loss:
                    self.stop_loss = new_stop
        else:
            # For shorts, trail above lowest price
            if self.lowest_price is not None:
                new_stop = self.lowest_price + self.trailing_stop_distance
                if self.stop_loss is None or new_stop < self.stop_loss:
                    self.stop_loss = new_stop
        
        return self
    
    def add_commission(self, amount: Decimal) -> "Position":
        """Add commission to position.
        
        Args:
            amount: Commission amount
            
        Returns:
            Self for chaining
        """
        self.total_commission += amount
        return self
    
    def add_fees(self, amount: Decimal) -> "Position":
        """Add fees to position.
        
        Args:
            amount: Fee amount
            
        Returns:
            Self for chaining
        """
        self.total_fees += amount
        return self
    
    def to_dict(self) -> dict[str, Any]:
        """Convert position to dictionary."""
        return {
            "position_id": self.position_id,
            "signal_id": self.signal_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": self.quantity,
            "entry_price": str(self.entry_price),
            "entry_time": self.entry_time.isoformat(),
            "exit_price": str(self.exit_price) if self.exit_price else None,
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "current_price": str(self.current_price) if self.current_price else None,
            "stop_loss": str(self.stop_loss) if self.stop_loss else None,
            "unrealized_pnl": str(self.unrealized_pnl),
            "realized_pnl": str(self.realized_pnl),
            "pnl_percentage": self.pnl_percentage,
            "is_open": self.is_open,
            "position_value": str(self.position_value),
        }
    
    @classmethod
    def from_signal(
        cls,
        signal_id: str,
        symbol: str,
        side: PositionSide,
        quantity: int,
        entry_price: Decimal,
        stop_loss: Decimal | None = None,
        take_profits: list[Decimal] | None = None,
    ) -> "Position":
        """Create position from signal.
        
        Args:
            signal_id: Signal ID
            symbol: Trading symbol
            side: Long or short
            quantity: Position size
            entry_price: Entry price
            stop_loss: Stop loss price
            take_profits: Take profit targets
            
        Returns:
            New position
        """
        return cls(
            position_id=f"pos:{symbol}:{datetime.utcnow().timestamp()}",
            signal_id=signal_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profits=take_profits or [],
            highest_price=entry_price,
            lowest_price=entry_price,
            current_price=entry_price,
        )