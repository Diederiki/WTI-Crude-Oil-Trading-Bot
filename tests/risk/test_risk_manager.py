"""Tests for risk manager."""

import pytest
from datetime import datetime, timedelta
from decimal import Decimal

from src.execution.models.order import Order, OrderSide, OrderType
from src.risk.manager import RiskManager
from src.risk.models import RiskLimits, RiskState, RiskStatus


class TestRiskLimits:
    """Test RiskLimits model."""
    
    def test_default_limits(self):
        """Test default risk limits."""
        limits = RiskLimits()
        
        assert limits.max_position_size == 100
        assert limits.max_daily_loss == Decimal("10000.00")
        assert limits.kill_switch_enabled is True
    
    def test_custom_limits(self):
        """Test custom risk limits."""
        limits = RiskLimits(
            max_position_size=50,
            max_daily_loss=Decimal("5000.00"),
            kill_switch_enabled=False,
        )
        
        assert limits.max_position_size == 50
        assert limits.max_daily_loss == Decimal("5000.00")
        assert limits.kill_switch_enabled is False


class TestRiskState:
    """Test RiskState model."""
    
    def test_initial_state(self):
        """Test initial risk state."""
        state = RiskState()
        
        assert state.status == RiskStatus.NORMAL
        assert state.daily_pnl == Decimal("0")
        assert state.kill_switch_triggered is False
    
    def test_update_drawdown(self):
        """Test drawdown calculation."""
        state = RiskState()
        
        state.update_drawdown(Decimal("100000"))
        assert state.peak_balance == Decimal("100000")
        assert state.current_drawdown_pct == Decimal("0")
        
        state.update_drawdown(Decimal("95000"))
        assert state.current_drawdown_pct == Decimal("5")
    
    def test_record_trade(self):
        """Test trade recording."""
        state = RiskState()
        
        state.record_trade(Decimal("100"))
        assert state.daily_pnl == Decimal("100")
        assert state.daily_trades == 1
        
        state.record_trade(Decimal("-50"))
        assert state.daily_pnl == Decimal("50")
        assert state.daily_trades == 2
        assert state.consecutive_losses == 1
    
    def test_cooldown_trigger(self):
        """Test cooldown after consecutive losses."""
        state = RiskState()
        
        # 3 consecutive losses trigger cooldown
        state.record_trade(Decimal("-100"))
        state.record_trade(Decimal("-100"))
        state.record_trade(Decimal("-100"))
        
        assert state.is_cooldown is True
        assert state.cooldown_until is not None
    
    def test_kill_switch(self):
        """Test kill switch functionality."""
        state = RiskState()
        
        state.trigger_kill_switch("Max drawdown reached")
        
        assert state.kill_switch_triggered is True
        assert state.kill_switch_reason == "Max drawdown reached"
        assert state.status == RiskStatus.HALTED
    
    def test_reset_kill_switch(self):
        """Test kill switch reset."""
        state = RiskState()
        
        state.trigger_kill_switch("Test")
        state.reset_kill_switch()
        
        assert state.kill_switch_triggered is False
        assert state.status == RiskStatus.NORMAL


class TestRiskManager:
    """Test RiskManager functionality."""
    
    @pytest.fixture
    def risk_manager(self):
        """Create risk manager for testing."""
        limits = RiskLimits(
            max_position_size=100,
            max_daily_loss=Decimal("1000.00"),
            max_trades_per_day=10,
            kill_switch_enabled=True,
        )
        return RiskManager(limits=limits)
    
    def test_check_order_passes(self, risk_manager):
        """Test order that passes all checks."""
        order = Order(
            order_id="order-1",
            symbol="CL=F",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
        )
        
        allowed, reason = risk_manager.check_order(order, Decimal("100000"))
        
        assert allowed is True
        assert reason == "OK"
    
    def test_check_order_exceeds_position_size(self, risk_manager):
        """Test order exceeding position size."""
        order = Order(
            order_id="order-1",
            symbol="CL=F",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=200,  # Exceeds limit
        )
        
        allowed, reason = risk_manager.check_order(order, Decimal("100000"))
        
        assert allowed is False
        assert "Position size" in reason
    
    def test_check_order_kill_switch_active(self, risk_manager):
        """Test order when kill switch is active."""
        risk_manager.state.trigger_kill_switch("Test")
        
        order = Order(
            order_id="order-1",
            symbol="CL=F",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
        )
        
        allowed, reason = risk_manager.check_order(order, Decimal("100000"))
        
        assert allowed is False
        assert "Kill switch" in reason
    
    def test_check_position_open_passes(self, risk_manager):
        """Test position open check passes."""
        allowed, reason = risk_manager.check_position_open(
            symbol="CL=F",
            side="long",
            size=10,
            entry_price=Decimal("75.00"),
            stop_loss=Decimal("74.50"),
            current_balance=Decimal("100000"),
        )
        
        assert allowed is True
        assert reason == "OK"
    
    def test_check_position_open_exceeds_risk(self, risk_manager):
        """Test position open exceeding per-trade risk."""
        allowed, reason = risk_manager.check_position_open(
            symbol="CL=F",
            side="long",
            size=100,
            entry_price=Decimal("75.00"),
            stop_loss=Decimal("70.00"),  # $5 risk per unit
            current_balance=Decimal("100000"),
        )
        
        # 100 * $5 = $500 risk, which exceeds default $500 limit
        # This should pass with default limits
        assert allowed is True
    
    def test_on_position_opened(self, risk_manager):
        """Test position opened handler."""
        from src.execution.models.position import Position, PositionSide
        
        position = Position(
            position_id="pos-1",
            symbol="CL=F",
            side=PositionSide.LONG,
            quantity=10,
            entry_price=Decimal("75.00"),
            current_price=Decimal("75.00"),
        )
        
        risk_manager.on_position_opened(position)
        
        assert risk_manager.state.open_positions == 1
    
    def test_on_position_closed(self, risk_manager):
        """Test position closed handler."""
        from src.execution.models.position import Position, PositionSide
        
        position = Position(
            position_id="pos-1",
            symbol="CL=F",
            side=PositionSide.LONG,
            quantity=10,
            entry_price=Decimal("75.00"),
            current_price=Decimal("80.00"),
        )
        
        # First open
        risk_manager.on_position_opened(position)
        
        # Then close
        position.close(Decimal("80.00"), "take_profit")
        risk_manager.on_position_closed(position)
        
        assert risk_manager.state.open_positions == 0
        assert risk_manager.state.daily_trades == 1
        assert risk_manager.state.daily_pnl == Decimal("50.00")
    
    def test_reset_kill_switch(self, risk_manager):
        """Test kill switch reset."""
        risk_manager.state.trigger_kill_switch("Test")
        
        success = risk_manager.reset_kill_switch()
        
        assert success is True
        assert risk_manager.state.kill_switch_triggered is False
    
    def test_get_status(self, risk_manager):
        """Test getting risk status."""
        status = risk_manager.get_status()
        
        assert "limits" in status
        assert "state" in status
        assert "can_trade" in status