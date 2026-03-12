"""Tests for signal models."""

import pytest
from datetime import datetime, timedelta

from src.strategy.models.signal import (
    Signal,
    SignalType,
    SignalStatus,
    SignalScore,
    MarketRegime,
)


class TestSignalScore:
    """Test SignalScore model."""
    
    def test_score_creation(self):
        """Test creating a score."""
        score = SignalScore(
            sweep_quality=80,
            reclaim_speed=70,
            overall=75,
        )
        
        assert score.sweep_quality == 80
        assert score.reclaim_speed == 70
        assert score.overall == 75
    
    def test_score_bounds(self):
        """Test score validation bounds."""
        with pytest.raises(Exception):
            SignalScore(overall=101)  # Max is 100
        
        with pytest.raises(Exception):
            SignalScore(overall=-1)  # Min is 0
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        score = SignalScore(
            sweep_quality=80,
            reclaim_speed=70,
            overall=75,
        )
        
        d = score.to_dict()
        assert d["sweep_quality"] == 80
        assert d["reclaim_speed"] == 70
        assert d["overall"] == 75


class TestSignal:
    """Test Signal model."""
    
    def test_signal_creation(self):
        """Test creating a signal."""
        signal = Signal(
            signal_id="test-1",
            symbol="CL=F",
            signal_type=SignalType.LIQUIDITY_SWEEP_LONG,
            direction="long",
            trigger_price=75.50,
            entry_price=75.55,
            stop_loss=75.30,
            take_profit_levels=[76.00, 76.50],
            confidence=75,
            setup_description="Test setup",
        )
        
        assert signal.signal_id == "test-1"
        assert signal.symbol == "CL=F"
        assert signal.direction == "long"
        assert signal.is_long is True
        assert signal.is_short is False
    
    def test_symbol_normalization(self):
        """Test symbol normalization."""
        signal = Signal(
            signal_id="test-1",
            symbol="cl=f",
            signal_type=SignalType.LIQUIDITY_SWEEP_LONG,
            direction="long",
            trigger_price=75.50,
            entry_price=75.55,
            stop_loss=75.30,
            confidence=75,
            setup_description="Test",
        )
        
        assert signal.symbol == "CL=F"
    
    def test_risk_reward_ratio(self):
        """Test risk/reward calculation."""
        signal = Signal(
            signal_id="test-1",
            symbol="CL=F",
            signal_type=SignalType.LIQUIDITY_SWEEP_LONG,
            direction="long",
            trigger_price=75.50,
            entry_price=75.55,
            stop_loss=75.30,  # Risk: 0.25
            take_profit_levels=[76.05],  # Reward: 0.50
            confidence=75,
            setup_description="Test",
        )
        
        assert signal.risk_reward_ratio == 2.0
    
    def test_risk_amount(self):
        """Test risk amount calculation."""
        signal = Signal(
            signal_id="test-1",
            symbol="CL=F",
            signal_type=SignalType.LIQUIDITY_SWEEP_LONG,
            direction="long",
            trigger_price=75.50,
            entry_price=75.55,
            stop_loss=75.30,
            confidence=75,
            setup_description="Test",
        )
        
        assert signal.risk_amount == 0.25
    
    def test_update_status(self):
        """Test status updates."""
        signal = Signal(
            signal_id="test-1",
            symbol="CL=F",
            signal_type=SignalType.LIQUIDITY_SWEEP_LONG,
            direction="long",
            trigger_price=75.50,
            entry_price=75.55,
            stop_loss=75.30,
            confidence=75,
            setup_description="Test",
        )
        
        assert signal.status == SignalStatus.PENDING
        
        signal.update_status(SignalStatus.ACTIVE)
        assert signal.status == SignalStatus.ACTIVE
        
        signal.update_status(SignalStatus.ENTERED)
        assert signal.status == SignalStatus.ENTERED
        assert signal.entered_at is not None
    
    def test_check_invalidation(self):
        """Test invalidation check."""
        signal = Signal(
            signal_id="test-1",
            symbol="CL=F",
            signal_type=SignalType.LIQUIDITY_SWEEP_LONG,
            direction="long",
            trigger_price=75.50,
            entry_price=75.55,
            stop_loss=75.30,
            invalidation_price=75.40,
            confidence=75,
            setup_description="Test",
        )
        
        assert signal.check_invalidation(75.50) is False
        assert signal.check_invalidation(75.35) is True
    
    def test_time_expiry(self):
        """Test time expiry check."""
        signal = Signal(
            signal_id="test-1",
            symbol="CL=F",
            signal_type=SignalType.LIQUIDITY_SWEEP_LONG,
            direction="long",
            trigger_price=75.50,
            entry_price=75.55,
            stop_loss=75.30,
            time_limit=datetime.utcnow() - timedelta(minutes=1),
            confidence=75,
            setup_description="Test",
        )
        
        assert signal.check_time_expired() is True
    
    def test_to_execution_request(self):
        """Test conversion to execution request."""
        signal = Signal(
            signal_id="test-1",
            symbol="CL=F",
            signal_type=SignalType.LIQUIDITY_SWEEP_LONG,
            direction="long",
            trigger_price=75.50,
            entry_price=75.55,
            stop_loss=75.30,
            take_profit_levels=[76.00, 76.50],
            position_size=10,
            confidence=75,
            setup_description="Test setup",
        )
        
        req = signal.to_execution_request()
        
        assert req["signal_id"] == "test-1"
        assert req["symbol"] == "CL=F"
        assert req["side"] == "buy"
        assert req["quantity"] == 10
        assert req["price"] == 75.55
        assert req["stop_loss"] == 75.30
        assert req["take_profits"] == [76.00, 76.50]
    
    def test_is_active(self):
        """Test active status check."""
        signal = Signal(
            signal_id="test-1",
            symbol="CL=F",
            signal_type=SignalType.LIQUIDITY_SWEEP_LONG,
            direction="long",
            trigger_price=75.50,
            entry_price=75.55,
            stop_loss=75.30,
            confidence=75,
            setup_description="Test",
        )
        
        assert signal.is_active is True
        
        signal.update_status(SignalStatus.ENTERED)
        assert signal.is_active is False
        
        signal.update_status(SignalStatus.EXPIRED)
        assert signal.is_active is False