"""Risk management models.

Defines risk limits, risk state, and risk-related data models.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RiskStatus(str, Enum):
    """Risk system status."""
    NORMAL = "normal"
    WARNING = "warning"
    BREACH = "breach"
    HALTED = "halted"


class RiskLimits(BaseModel):
    """Risk limits configuration.
    
    Defines all risk parameters for trading operations.
    
    Attributes:
        max_position_size: Maximum contracts per position
        max_position_pct: Max position as % of portfolio
        max_daily_loss: Maximum daily loss limit
        max_drawdown_pct: Maximum drawdown before halt
        per_trade_risk: Maximum risk per trade
        max_open_positions: Maximum concurrent positions
        max_orders_per_minute: Rate limiting
        max_trades_per_day: Daily trade limit
        cooldown_after_loss_seconds: Cooldown period
        max_spread_pct: Maximum acceptable spread
        max_slippage_pct: Maximum acceptable slippage
        kill_switch_enabled: Whether kill switch is active
    """
    
    model_config = ConfigDict(frozen=True)
    
    # Position limits
    max_position_size: int = Field(default=100, ge=1)
    max_position_pct: Decimal = Field(default=Decimal("10.0"))
    max_open_positions: int = Field(default=5, ge=1)
    
    # Loss limits
    max_daily_loss: Decimal = Field(default=Decimal("10000.00"))
    max_drawdown_pct: Decimal = Field(default=Decimal("5.0"))
    per_trade_risk: Decimal = Field(default=Decimal("500.00"))
    
    # Trading frequency limits
    max_orders_per_minute: int = Field(default=10, ge=1)
    max_trades_per_day: int = Field(default=50, ge=1)
    cooldown_after_loss_seconds: int = Field(default=300, ge=0)
    
    # Execution quality limits
    max_spread_pct: Decimal = Field(default=Decimal("0.5"))
    max_slippage_pct: Decimal = Field(default=Decimal("0.1"))
    
    # Safety
    kill_switch_enabled: bool = Field(default=True)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "max_position_size": self.max_position_size,
            "max_position_pct": str(self.max_position_pct),
            "max_open_positions": self.max_open_positions,
            "max_daily_loss": str(self.max_daily_loss),
            "max_drawdown_pct": str(self.max_drawdown_pct),
            "per_trade_risk": str(self.per_trade_risk),
            "max_orders_per_minute": self.max_orders_per_minute,
            "max_trades_per_day": self.max_trades_per_day,
            "cooldown_after_loss_seconds": self.cooldown_after_loss_seconds,
            "max_spread_pct": str(self.max_spread_pct),
            "max_slippage_pct": str(self.max_slippage_pct),
            "kill_switch_enabled": self.kill_switch_enabled,
        }


class RiskState(BaseModel):
    """Current risk state tracking.
    
    Tracks real-time risk metrics and breach status.
    
    Attributes:
        status: Current risk status
        daily_pnl: Today's realized P&L
        daily_trades: Number of trades today
        daily_orders: Number of orders today
        open_positions: Current open position count
        total_exposure: Total position exposure
        current_drawdown_pct: Current drawdown percentage
        last_trade_time: Timestamp of last trade
        last_loss_time: Timestamp of last losing trade
        consecutive_losses: Count of consecutive losses
        is_cooldown: Whether in cooldown period
        kill_switch_triggered: Whether kill switch is active
        breaches: List of risk breaches
    """
    
    model_config = ConfigDict(
        extra="allow",
        json_encoders={
            datetime: lambda v: v.isoformat(),
            Decimal: lambda v: str(v),
        },
    )
    
    status: RiskStatus = Field(default=RiskStatus.NORMAL)
    
    # Daily tracking
    daily_pnl: Decimal = Field(default=Decimal("0"))
    daily_trades: int = Field(default=0)
    daily_orders: int = Field(default=0)
    
    # Position tracking
    open_positions: int = Field(default=0)
    total_exposure: Decimal = Field(default=Decimal("0"))
    
    # Drawdown tracking
    peak_balance: Decimal = Field(default=Decimal("0"))
    current_drawdown_pct: Decimal = Field(default=Decimal("0"))
    
    # Time tracking
    last_trade_time: datetime | None = Field(default=None)
    last_loss_time: datetime | None = Field(default=None)
    consecutive_losses: int = Field(default=0)
    is_cooldown: bool = Field(default=False)
    cooldown_until: datetime | None = Field(default=None)
    
    # Safety
    kill_switch_triggered: bool = Field(default=False)
    kill_switch_triggered_at: datetime | None = Field(default=None)
    kill_switch_reason: str | None = Field(default=None)
    
    # Breach history
    breaches: list[dict[str, Any]] = Field(default_factory=list)
    
    def update_drawdown(self, current_balance: Decimal) -> None:
        """Update drawdown calculation.
        
        Args:
            current_balance: Current account balance
        """
        # Update peak
        if current_balance > self.peak_balance:
            self.peak_balance = current_balance
        
        # Calculate drawdown
        if self.peak_balance > 0:
            self.current_drawdown_pct = (self.peak_balance - current_balance) / self.peak_balance * 100
        
        # Update status if needed
        if self.current_drawdown_pct > 5:
            self.status = RiskStatus.WARNING
        if self.current_drawdown_pct > 10:
            self.status = RiskStatus.BREACH
    
    def record_trade(self, pnl: Decimal) -> None:
        """Record a completed trade.
        
        Args:
            pnl: Trade P&L
        """
        self.daily_trades += 1
        self.daily_pnl += pnl
        self.last_trade_time = datetime.utcnow()
        
        if pnl < 0:
            self.last_loss_time = datetime.utcnow()
            self.consecutive_losses += 1
            
            # Check if cooldown needed
            if self.consecutive_losses >= 3:
                self.is_cooldown = True
                self.cooldown_until = datetime.utcnow() + timedelta(minutes=5)
        else:
            self.consecutive_losses = 0
            self.is_cooldown = False
            self.cooldown_until = None
    
    def record_order(self) -> None:
        """Record an order submission."""
        self.daily_orders += 1
    
    def record_breach(self, breach_type: str, message: str) -> None:
        """Record a risk breach.
        
        Args:
            breach_type: Type of breach
            message: Breach description
        """
        self.breaches.append({
            "timestamp": datetime.utcnow().isoformat(),
            "type": breach_type,
            "message": message,
        })
        
        self.status = RiskStatus.BREACH
    
    def trigger_kill_switch(self, reason: str) -> None:
        """Trigger kill switch.
        
        Args:
            reason: Reason for trigger
        """
        self.kill_switch_triggered = True
        self.kill_switch_triggered_at = datetime.utcnow()
        self.kill_switch_reason = reason
        self.status = RiskStatus.HALTED
    
    def reset_kill_switch(self) -> None:
        """Reset kill switch."""
        self.kill_switch_triggered = False
        self.kill_switch_triggered_at = None
        self.kill_switch_reason = None
        self.status = RiskStatus.NORMAL
    
    def reset_daily_stats(self) -> None:
        """Reset daily statistics."""
        self.daily_pnl = Decimal("0")
        self.daily_trades = 0
        self.daily_orders = 0
        self.breaches.clear()
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "status": self.status.value,
            "daily_pnl": str(self.daily_pnl),
            "daily_trades": self.daily_trades,
            "daily_orders": self.daily_orders,
            "open_positions": self.open_positions,
            "total_exposure": str(self.total_exposure),
            "current_drawdown_pct": str(self.current_drawdown_pct),
            "consecutive_losses": self.consecutive_losses,
            "is_cooldown": self.is_cooldown,
            "cooldown_until": self.cooldown_until.isoformat() if self.cooldown_until else None,
            "kill_switch_triggered": self.kill_switch_triggered,
            "kill_switch_reason": self.kill_switch_reason,
        }


from datetime import timedelta  # Import at end to avoid circular import