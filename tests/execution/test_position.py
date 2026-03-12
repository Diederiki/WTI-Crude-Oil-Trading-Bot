"""Tests for position models."""

import pytest
from datetime import datetime
from decimal import Decimal

from src.execution.models.position import Position, PositionSide


class TestPosition:
    """Test Position model."""
    
    def test_position_creation(self):
        """Test creating a position."""
        position = Position(
            position_id="pos-1",
            symbol="CL=F",
            side=PositionSide.LONG,
            quantity=10,
            entry_price=Decimal("75.50"),
        )
        
        assert position.position_id == "pos-1"
        assert position.symbol == "CL=F"
        assert position.side == PositionSide.LONG
        assert position.quantity == 10
        assert position.is_open is True
    
    def test_symbol_normalization(self):
        """Test symbol normalization."""
        position = Position(
            position_id="pos-1",
            symbol="cl=f",
            side=PositionSide.LONG,
            quantity=10,
            entry_price=Decimal("75.50"),
        )
        
        assert position.symbol == "CL=F"
    
    def test_position_value(self):
        """Test position value calculation."""
        position = Position(
            position_id="pos-1",
            symbol="CL=F",
            side=PositionSide.LONG,
            quantity=10,
            entry_price=Decimal("75.50"),
            current_price=Decimal("76.00"),
        )
        
        assert position.position_value == Decimal("760.00")
        assert position.entry_value == Decimal("755.00")
    
    def test_update_price_long(self):
        """Test price update for long position."""
        position = Position(
            position_id="pos-1",
            symbol="CL=F",
            side=PositionSide.LONG,
            quantity=10,
            entry_price=Decimal("75.50"),
        )
        
        position.update_price(Decimal("76.00"))
        
        assert position.current_price == Decimal("76.00")
        assert position.unrealized_pnl == Decimal("5.00")
    
    def test_update_price_short(self):
        """Test price update for short position."""
        position = Position(
            position_id="pos-1",
            symbol="CL=F",
            side=PositionSide.SHORT,
            quantity=10,
            entry_price=Decimal("75.50"),
        )
        
        position.update_price(Decimal("74.00"))
        
        assert position.current_price == Decimal("74.00")
        assert position.unrealized_pnl == Decimal("15.00")
    
    def test_pnl_percentage(self):
        """Test P&L percentage calculation."""
        position = Position(
            position_id="pos-1",
            symbol="CL=F",
            side=PositionSide.LONG,
            quantity=10,
            entry_price=Decimal("75.00"),
            current_price=Decimal("80.00"),
        )
        
        # P&L = (80 - 75) * 10 = 50
        # Entry value = 75 * 10 = 750
        # % = 50 / 750 * 100 = 6.67%
        assert abs(position.pnl_percentage - 6.67) < 0.01
    
    def test_risk_amount(self):
        """Test risk amount calculation."""
        position = Position(
            position_id="pos-1",
            symbol="CL=F",
            side=PositionSide.LONG,
            quantity=10,
            entry_price=Decimal("75.50"),
            stop_loss=Decimal("74.50"),
        )
        
        # Risk = (75.50 - 74.50) * 10 = 10
        assert position.risk_amount == Decimal("10.00")
    
    def test_should_trigger_stop_long(self):
        """Test stop trigger for long position."""
        position = Position(
            position_id="pos-1",
            symbol="CL=F",
            side=PositionSide.LONG,
            quantity=10,
            entry_price=Decimal("75.50"),
            stop_loss=Decimal("74.50"),
            current_price=Decimal("74.00"),
        )
        
        assert position.should_trigger_stop is True
    
    def test_should_trigger_stop_short(self):
        """Test stop trigger for short position."""
        position = Position(
            position_id="pos-1",
            symbol="CL=F",
            side=PositionSide.SHORT,
            quantity=10,
            entry_price=Decimal("75.50"),
            stop_loss=Decimal("76.50"),
            current_price=Decimal("77.00"),
        )
        
        assert position.should_trigger_stop is True
    
    def test_trailing_stop_long(self):
        """Test trailing stop for long position."""
        position = Position(
            position_id="pos-1",
            symbol="CL=F",
            side=PositionSide.LONG,
            quantity=10,
            entry_price=Decimal("75.00"),
            trailing_stop_distance=Decimal("2.00"),
        )
        
        # Price rises to 80
        position.update_price(Decimal("80.00"))
        position.update_trailing_stop()
        
        # Stop should be at 80 - 2 = 78
        assert position.stop_loss == Decimal("78.00")
    
    def test_trailing_stop_short(self):
        """Test trailing stop for short position."""
        position = Position(
            position_id="pos-1",
            symbol="CL=F",
            side=PositionSide.SHORT,
            quantity=10,
            entry_price=Decimal("75.00"),
            trailing_stop_distance=Decimal("2.00"),
        )
        
        # Price falls to 70
        position.update_price(Decimal("70.00"))
        position.update_trailing_stop()
        
        # Stop should be at 70 + 2 = 72
        assert position.stop_loss == Decimal("72.00")
    
    def test_close_position(self):
        """Test closing a position."""
        position = Position(
            position_id="pos-1",
            symbol="CL=F",
            side=PositionSide.LONG,
            quantity=10,
            entry_price=Decimal("75.00"),
        )
        
        position.close(Decimal("80.00"), "take_profit")
        
        assert position.is_open is False
        assert position.exit_price == Decimal("80.00")
        assert position.realized_pnl == Decimal("50.00")
        assert position.close_reason == "take_profit"
    
    def test_from_signal(self):
        """Test creating position from signal."""
        position = Position.from_signal(
            signal_id="sig-1",
            symbol="CL=F",
            side=PositionSide.LONG,
            quantity=10,
            entry_price=Decimal("75.50"),
            stop_loss=Decimal("74.50"),
            take_profits=[Decimal("77.00"), Decimal("78.00")],
        )
        
        assert position.signal_id == "sig-1"
        assert position.stop_loss == Decimal("74.50")
        assert position.take_profits == [Decimal("77.00"), Decimal("78.00")]
    
    def test_add_commission(self):
        """Test adding commission."""
        position = Position(
            position_id="pos-1",
            symbol="CL=F",
            side=PositionSide.LONG,
            quantity=10,
            entry_price=Decimal("75.50"),
        )
        
        position.add_commission(Decimal("5.00"))
        
        assert position.total_commission == Decimal("5.00")