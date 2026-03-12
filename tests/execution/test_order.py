"""Tests for order models."""

import pytest
from datetime import datetime
from decimal import Decimal

from src.execution.models.order import (
    Order,
    OrderStatus,
    OrderType,
    OrderSide,
    OrderFill,
    TimeInForce,
)


class TestOrderFill:
    """Test OrderFill model."""
    
    def test_fill_creation(self):
        """Test creating a fill."""
        fill = OrderFill(
            fill_id="fill-1",
            timestamp=datetime.utcnow(),
            quantity=10,
            price=Decimal("75.50"),
            commission=Decimal("2.50"),
        )
        
        assert fill.fill_id == "fill-1"
        assert fill.quantity == 10
        assert fill.price == Decimal("75.50")
    
    def test_fill_value(self):
        """Test fill value calculation."""
        fill = OrderFill(
            fill_id="fill-1",
            timestamp=datetime.utcnow(),
            quantity=10,
            price=Decimal("75.50"),
            commission=Decimal("2.50"),
        )
        
        assert fill.value == Decimal("755.00")
        assert fill.total_cost == Decimal("757.50")


class TestOrder:
    """Test Order model."""
    
    def test_order_creation(self):
        """Test creating an order."""
        order = Order(
            order_id="order-1",
            symbol="CL=F",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            price=Decimal("75.50"),
        )
        
        assert order.order_id == "order-1"
        assert order.symbol == "CL=F"
        assert order.side == OrderSide.BUY
        assert order.status == OrderStatus.PENDING
    
    def test_symbol_normalization(self):
        """Test symbol normalization."""
        order = Order(
            order_id="order-1",
            symbol="cl=f",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
        )
        
        assert order.symbol == "CL=F"
    
    def test_remaining_quantity(self):
        """Test remaining quantity calculation."""
        order = Order(
            order_id="order-1",
            symbol="CL=F",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=100,
            filled_quantity=30,
        )
        
        assert order.remaining_quantity == 70
    
    def test_is_filled(self):
        """Test filled check."""
        order = Order(
            order_id="order-1",
            symbol="CL=F",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=100,
            filled_quantity=100,
        )
        
        assert order.is_filled is True
    
    def test_is_active(self):
        """Test active check."""
        order = Order(
            order_id="order-1",
            symbol="CL=F",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=100,
            status=OrderStatus.PENDING,
        )
        
        assert order.is_active is True
        
        order.status = OrderStatus.FILLED
        assert order.is_active is False
    
    def test_can_cancel(self):
        """Test cancel eligibility."""
        order = Order(
            order_id="order-1",
            symbol="CL=F",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=100,
            status=OrderStatus.SUBMITTED,
        )
        
        assert order.can_cancel is True
        
        order.status = OrderStatus.FILLED
        assert order.can_cancel is False
    
    def test_add_fill(self):
        """Test adding fills."""
        order = Order(
            order_id="order-1",
            symbol="CL=F",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=100,
        )
        
        fill = OrderFill(
            fill_id="fill-1",
            timestamp=datetime.utcnow(),
            quantity=50,
            price=Decimal("75.50"),
            commission=Decimal("2.50"),
        )
        
        order.add_fill(fill)
        
        assert order.filled_quantity == 50
        assert order.status == OrderStatus.PARTIALLY_FILLED
        assert order.average_fill_price == Decimal("75.50")
    
    def test_complete_fill(self):
        """Test complete fill."""
        order = Order(
            order_id="order-1",
            symbol="CL=F",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=100,
        )
        
        fill = OrderFill(
            fill_id="fill-1",
            timestamp=datetime.utcnow(),
            quantity=100,
            price=Decimal("75.50"),
            commission=Decimal("2.50"),
        )
        
        order.add_fill(fill)
        
        assert order.is_filled is True
        assert order.status == OrderStatus.FILLED
    
    def test_cancel(self):
        """Test order cancellation."""
        order = Order(
            order_id="order-1",
            symbol="CL=F",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=100,
            status=OrderStatus.SUBMITTED,
        )
        
        order.cancel("User request")
        
        assert order.status == OrderStatus.CANCELLED
        assert order.metadata.get("cancel_reason") == "User request"
    
    def test_reject(self):
        """Test order rejection."""
        order = Order(
            order_id="order-1",
            symbol="CL=F",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=100,
        )
        
        order.reject("Insufficient funds")
        
        assert order.status == OrderStatus.REJECTED
        assert order.reject_reason == "Insufficient funds"
    
    def test_create_market_order(self):
        """Test market order factory."""
        order = Order.create_market_order(
            symbol="CL=F",
            side=OrderSide.BUY,
            quantity=100,
        )
        
        assert order.order_type == OrderType.MARKET
        assert order.symbol == "CL=F"
        assert order.side == OrderSide.BUY
    
    def test_create_limit_order(self):
        """Test limit order factory."""
        order = Order.create_limit_order(
            symbol="CL=F",
            side=OrderSide.BUY,
            quantity=100,
            price=Decimal("75.50"),
        )
        
        assert order.order_type == OrderType.LIMIT
        assert order.price == Decimal("75.50")
    
    def test_check_slippage(self):
        """Test slippage check."""
        order = Order(
            order_id="order-1",
            symbol="CL=F",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=100,
            max_slippage_pct=Decimal("0.1"),
        )
        
        # Within slippage
        assert order.check_slippage(Decimal("75.50"), Decimal("75.55")) is True
        
        # Exceeds slippage
        assert order.check_slippage(Decimal("75.50"), Decimal("76.00")) is False