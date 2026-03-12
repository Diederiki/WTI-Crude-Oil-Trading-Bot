"""Risk manager for trading risk controls.

Centralized risk management with position limits, drawdown monitoring,
and emergency kill switch functionality.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from src.core.logging_config import get_logger
from src.execution.models.order import Order
from src.execution.models.position import Position
from src.market_data.models.events import MarketTick
from src.risk.models import RiskLimits, RiskState, RiskStatus

logger = get_logger("risk")


class RiskManager:
    """Central risk manager for trading operations.
    
    Monitors all trading activity and enforces risk limits including:
    - Position size limits
    - Daily loss limits
    - Drawdown limits
    - Trade frequency limits
    - Cooldown periods
    - Kill switch
    
    Attributes:
        limits: Risk limits configuration
        state: Current risk state
        _check_interval_seconds: How often to check risk
        _last_check: Last risk check timestamp
    """
    
    def __init__(
        self,
        limits: RiskLimits | None = None,
        check_interval_seconds: float = 5.0,
    ):
        """Initialize risk manager.
        
        Args:
            limits: Risk limits configuration
            check_interval_seconds: Risk check interval
        """
        self.limits = limits or RiskLimits()
        self.state = RiskState()
        self._check_interval_seconds = check_interval_seconds
        self._last_check = datetime.utcnow()
        
        # Order tracking for rate limiting
        self._recent_orders: list[datetime] = []
        
        logger.info(
            "Risk manager initialized",
            max_daily_loss=str(self.limits.max_daily_loss),
            max_drawdown_pct=str(self.limits.max_drawdown_pct),
            kill_switch_enabled=self.limits.kill_switch_enabled,
        )
    
    def check_order(self, order: Order, current_balance: Decimal) -> tuple[bool, str]:
        """Check if order passes risk checks.
        
        Args:
            order: Order to check
            current_balance: Current account balance
            
        Returns:
            Tuple of (allowed, reason)
        """
        # Check kill switch
        if self.state.kill_switch_triggered:
            return False, f"Kill switch active: {self.state.kill_switch_reason}"
        
        # Check cooldown
        if self._is_in_cooldown():
            return False, f"In cooldown until {self.state.cooldown_until}"
        
        # Check daily loss limit
        if self.state.daily_pnl <= -self.limits.max_daily_loss:
            self._trigger_kill_switch("Daily loss limit reached")
            return False, "Daily loss limit reached"
        
        # Check order rate limit
        if not self._check_order_rate():
            return False, "Order rate limit exceeded"
        
        # Check position size
        if order.quantity > self.limits.max_position_size:
            return False, f"Position size {order.quantity} exceeds limit {self.limits.max_position_size}"
        
        # Check max positions
        if self.state.open_positions >= self.limits.max_open_positions:
            return False, f"Max positions ({self.limits.max_open_positions}) reached"
        
        # Check daily trade limit
        if self.state.daily_trades >= self.limits.max_trades_per_day:
            return False, f"Daily trade limit ({self.limits.max_trades_per_day}) reached"
        
        # Check drawdown
        self.state.update_drawdown(current_balance)
        if self.state.current_drawdown_pct >= self.limits.max_drawdown_pct:
            self._trigger_kill_switch(f"Max drawdown ({self.limits.max_drawdown_pct}%) reached")
            return False, "Max drawdown reached"
        
        # All checks passed
        self.state.record_order()
        return True, "OK"
    
    def check_position_open(
        self,
        symbol: str,
        side: str,
        size: int,
        entry_price: Decimal,
        stop_loss: Decimal | None,
        current_balance: Decimal,
    ) -> tuple[bool, str]:
        """Check if position can be opened.
        
        Args:
            symbol: Trading symbol
            side: Position side
            size: Position size
            entry_price: Entry price
            stop_loss: Stop loss price
            current_balance: Current balance
            
        Returns:
            Tuple of (allowed, reason)
        """
        # Check kill switch
        if self.state.kill_switch_triggered:
            return False, "Kill switch active"
        
        # Check position size
        if size > self.limits.max_position_size:
            return False, f"Position size {size} exceeds limit"
        
        # Check position value as % of portfolio
        position_value = entry_price * size
        if current_balance > 0:
            position_pct = position_value / current_balance * 100
            if position_pct > self.limits.max_position_pct:
                return False, f"Position {position_pct:.1f}% exceeds max {self.limits.max_position_pct}%"
        
        # Check per-trade risk
        if stop_loss:
            risk_per_unit = abs(entry_price - stop_loss)
            total_risk = risk_per_unit * size
            if total_risk > self.limits.per_trade_risk:
                return False, f"Trade risk ${total_risk} exceeds limit ${self.limits.per_trade_risk}"
        
        return True, "OK"
    
    def on_position_opened(self, position: Position) -> None:
        """Handle position opened event.
        
        Args:
            position: Opened position
        """
        self.state.open_positions += 1
        self.state.total_exposure += position.position_value
        
        logger.info(
            "Position opened - risk updated",
            position_id=position.position_id,
            open_positions=self.state.open_positions,
            total_exposure=str(self.state.total_exposure),
        )
    
    def on_position_closed(self, position: Position) -> None:
        """Handle position closed event.
        
        Args:
            position: Closed position
        """
        self.state.open_positions = max(0, self.state.open_positions - 1)
        self.state.total_exposure = max(Decimal("0"), self.state.total_exposure - position.entry_value)
        
        # Record trade P&L
        self.state.record_trade(position.realized_pnl)
        
        logger.info(
            "Position closed - risk updated",
            position_id=position.position_id,
            realized_pnl=str(position.realized_pnl),
            daily_pnl=str(self.state.daily_pnl),
            daily_trades=self.state.daily_trades,
        )
    
    def on_market_tick(self, tick: MarketTick) -> None:
        """Process market tick for risk monitoring.
        
        Args:
            tick: Market tick
        """
        # Periodic risk check
        now = datetime.utcnow()
        if (now - self._last_check).total_seconds() >= self._check_interval_seconds:
            self._last_check = now
            self._periodic_check()
    
    def _periodic_check(self) -> None:
        """Perform periodic risk checks."""
        # Reset cooldown if expired
        if self.state.is_cooldown and self.state.cooldown_until:
            if datetime.utcnow() >= self.state.cooldown_until:
                self.state.is_cooldown = False
                self.state.cooldown_until = None
                logger.info("Cooldown period ended")
        
        # Clean up old order timestamps
        cutoff = datetime.utcnow() - timedelta(minutes=1)
        self._recent_orders = [t for t in self._recent_orders if t > cutoff]
    
    def _is_in_cooldown(self) -> bool:
        """Check if system is in cooldown period.
        
        Returns:
            True if in cooldown
        """
        if not self.state.is_cooldown:
            return False
        
        if self.state.cooldown_until is None:
            return False
        
        return datetime.utcnow() < self.state.cooldown_until
    
    def _check_order_rate(self) -> bool:
        """Check if order rate is within limits.
        
        Returns:
            True if within limits
        """
        # Clean old entries
        cutoff = datetime.utcnow() - timedelta(minutes=1)
        self._recent_orders = [t for t in self._recent_orders if t > cutoff]
        
        # Check rate
        return len(self._recent_orders) < self.limits.max_orders_per_minute
    
    def _trigger_kill_switch(self, reason: str) -> None:
        """Trigger kill switch.
        
        Args:
            reason: Reason for trigger
        """
        if not self.limits.kill_switch_enabled:
            return
        
        self.state.trigger_kill_switch(reason)
        
        logger.critical(
            "KILL SWITCH TRIGGERED",
            reason=reason,
            daily_pnl=str(self.state.daily_pnl),
            drawdown_pct=str(self.state.current_drawdown_pct),
        )
    
    def reset_kill_switch(self) -> bool:
        """Reset kill switch (manual override).
        
        Returns:
            True if reset successful
        """
        if not self.state.kill_switch_triggered:
            return False
        
        self.state.reset_kill_switch()
        logger.warning("Kill switch manually reset")
        return True
    
    def reset_daily_stats(self) -> None:
        """Reset daily statistics (call at market open)."""
        self.state.reset_daily_stats()
        logger.info("Daily risk stats reset")
    
    def get_status(self) -> dict[str, Any]:
        """Get current risk status.
        
        Returns:
            Risk status dictionary
        """
        return {
            "limits": self.limits.to_dict(),
            "state": self.state.to_dict(),
            "can_trade": not self.state.kill_switch_triggered and not self._is_in_cooldown(),
        }
    
    def check_spread(self, spread_pct: Decimal) -> tuple[bool, str]:
        """Check if spread is acceptable.
        
        Args:
            spread_pct: Spread as percentage
            
        Returns:
            Tuple of (acceptable, reason)
        """
        if spread_pct > self.limits.max_spread_pct:
            return False, f"Spread {spread_pct}% exceeds max {self.limits.max_spread_pct}%"
        return True, "OK"
    
    def check_slippage(self, slippage_pct: Decimal) -> tuple[bool, str]:
        """Check if slippage is acceptable.
        
        Args:
            slippage_pct: Slippage as percentage
            
        Returns:
            Tuple of (acceptable, reason)
        """
        if slippage_pct > self.limits.max_slippage_pct:
            return False, f"Slippage {slippage_pct}% exceeds max {self.limits.max_slippage_pct}%"
        return True, "OK"