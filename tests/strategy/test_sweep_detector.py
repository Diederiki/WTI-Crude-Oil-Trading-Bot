"""Tests for liquidity sweep detector."""

import pytest
from datetime import datetime, timedelta

from src.market_data.models.events import MarketTick, MarketBar
from src.strategy.detectors.liquidity_sweep import (
    LiquiditySweepDetector,
    SweepDetectionConfig,
    LiquidityLevel,
)
from src.strategy.models.signal import SignalType, SignalStatus


class TestLiquidityLevel:
    """Test LiquidityLevel dataclass."""
    
    def test_level_creation(self):
        """Test creating a level."""
        level = LiquidityLevel(
            price=75.50,
            timestamp=datetime.utcnow(),
            level_type="high",
        )
        
        assert level.price == 75.50
        assert level.level_type == "high"
        assert level.is_swept is False
    
    def test_mark_swept(self):
        """Test marking level as swept."""
        level = LiquidityLevel(
            price=75.50,
            timestamp=datetime.utcnow(),
            level_type="high",
        )
        
        ts = datetime.utcnow()
        level.mark_swept(ts)
        
        assert level.is_swept is True
        assert level.swept_at == ts
    
    def test_mark_reclaimed(self):
        """Test marking level as reclaimed."""
        level = LiquidityLevel(
            price=75.50,
            timestamp=datetime.utcnow(),
            level_type="high",
        )
        
        ts = datetime.utcnow()
        level.mark_swept(ts)
        level.mark_reclaimed(ts + timedelta(seconds=5))
        
        assert level.reclaimed_at is not None


class TestLiquiditySweepDetector:
    """Test LiquiditySweepDetector."""
    
    @pytest.fixture
    def detector(self):
        """Create detector for testing."""
        return LiquiditySweepDetector(
            config=SweepDetectionConfig(
                lookback_periods=5,
                sweep_threshold_pct=0.1,
                reclaim_timeout_seconds=10.0,
            )
        )
    
    def test_detector_initialization(self, detector):
        """Test detector initialization."""
        assert detector.config.lookback_periods == 5
        assert detector.config.sweep_threshold_pct == 0.1
    
    def test_bar_processing_builds_levels(self, detector):
        """Test that bar processing builds liquidity levels."""
        # Add several bars to build history
        for i in range(10):
            bar = MarketBar(
                symbol="CL=F",
                timestamp=datetime.utcnow() + timedelta(minutes=i),
                interval_seconds=60,
                open=75.0 + i * 0.1,
                high=75.5 + i * 0.1,
                low=74.5 + i * 0.1,
                close=75.2 + i * 0.1,
                volume=1000,
            )
            detector.on_bar(bar)
        
        levels = detector.get_liquidity_levels("CL=F")
        assert levels["high"] is not None
        assert levels["low"] is not None
    
    def test_sweep_detection_high(self, detector):
        """Test detecting a high sweep."""
        # Build history
        for i in range(10):
            bar = MarketBar(
                symbol="CL=F",
                timestamp=datetime.utcnow() + timedelta(minutes=i),
                interval_seconds=60,
                open=75.0,
                high=75.50,
                low=74.50,
                close=75.20,
                volume=1000,
            )
            detector.on_bar(bar)
        
        # Sweep the high
        tick = MarketTick(
            symbol="CL=F",
            timestamp=datetime.utcnow() + timedelta(minutes=10),
            bid=75.60,
            ask=75.65,
            last=75.62,  # Above high of 75.50
            feed_source="test",
        )
        
        detector.on_tick(tick)
        
        # Check that high is marked as swept
        levels = detector.get_liquidity_levels("CL=F")
        assert levels["high"]["is_swept"] is True
    
    def test_sweep_detection_low(self, detector):
        """Test detecting a low sweep."""
        # Build history
        for i in range(10):
            bar = MarketBar(
                symbol="CL=F",
                timestamp=datetime.utcnow() + timedelta(minutes=i),
                interval_seconds=60,
                open=75.0,
                high=75.50,
                low=74.50,
                close=75.20,
                volume=1000,
            )
            detector.on_bar(bar)
        
        # Sweep the low
        tick = MarketTick(
            symbol="CL=F",
            timestamp=datetime.utcnow() + timedelta(minutes=10),
            bid=74.40,
            ask=74.45,
            last=74.42,  # Below low of 74.50
            feed_source="test",
        )
        
        detector.on_tick(tick)
        
        # Check that low is marked as swept
        levels = detector.get_liquidity_levels("CL=F")
        assert levels["low"]["is_swept"] is True
    
    def test_reclaim_generates_signal(self, detector):
        """Test that reclaim generates a signal."""
        # Build history
        base_time = datetime.utcnow()
        for i in range(10):
            bar = MarketBar(
                symbol="CL=F",
                timestamp=base_time + timedelta(minutes=i),
                interval_seconds=60,
                open=75.0,
                high=75.50,
                low=74.50,
                close=75.20,
                volume=1000,
            )
            detector.on_bar(bar)
        
        # Sweep the low
        sweep_tick = MarketTick(
            symbol="CL=F",
            timestamp=base_time + timedelta(minutes=10),
            bid=74.40,
            ask=74.45,
            last=74.42,
            feed_source="test",
        )
        detector.on_tick(sweep_tick)
        
        # Reclaim - price back above low
        reclaim_tick = MarketTick(
            symbol="CL=F",
            timestamp=base_time + timedelta(minutes=10, seconds=5),
            bid=74.55,
            ask=74.60,
            last=74.58,
            feed_source="test",
        )
        signal = detector.on_tick(reclaim_tick)
        
        # Should have generated a signal
        assert signal is not None
        assert signal.signal_type == SignalType.LIQUIDITY_SWEEP_LONG
        assert signal.direction == "long"
        assert signal.confidence > 0
    
    def test_daily_sweep_limit(self, detector):
        """Test daily sweep limit tracking."""
        # Initially should be 0
        stats = detector.get_stats("CL=F")
        assert stats["daily_sweeps"] == 0
        
        # After generating signals, count should increase
        # (This would require full signal generation flow)