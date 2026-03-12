"""Tests for market data event models."""

import pytest
from datetime import datetime

from src.market_data.models.events import (
    MarketTick,
    MarketBar,
    FeedStatus,
    FeedHealth,
    FeedAnomaly,
    AnomalyType,
)


class TestMarketTick:
    """Test MarketTick model."""
    
    def test_tick_creation(self):
        """Test creating a valid tick."""
        tick = MarketTick(
            symbol="CL=F",
            timestamp=datetime.utcnow(),
            bid=75.50,
            ask=75.55,
            last=75.52,
            bid_size=100,
            ask_size=150,
            last_size=50,
            volume=1000000,
            exchange="NYMEX",
            feed_source="test",
        )
        
        assert tick.symbol == "CL=F"
        assert tick.bid == 75.50
        assert tick.ask == 75.55
        assert tick.last == 75.52
    
    def test_spread_calculation(self):
        """Test spread calculation."""
        tick = MarketTick(
            symbol="CL=F",
            timestamp=datetime.utcnow(),
            bid=75.50,
            ask=75.55,
            last=75.52,
            feed_source="test",
        )
        
        assert tick.spread == 0.05
        assert tick.mid == 75.525
        assert abs(tick.spread_pct - 0.066) < 0.001
    
    def test_symbol_normalization(self):
        """Test symbol is normalized to uppercase."""
        tick = MarketTick(
            symbol="cl=f",
            timestamp=datetime.utcnow(),
            bid=75.50,
            ask=75.55,
            last=75.52,
            feed_source="test",
        )
        
        assert tick.symbol == "CL=F"
    
    def test_invalid_tick(self):
        """Test tick validation catches invalid prices."""
        with pytest.raises(Exception):
            MarketTick(
                symbol="CL=F",
                timestamp=datetime.utcnow(),
                bid=-1,
                ask=75.55,
                last=75.52,
                feed_source="test",
            )
    
    def test_is_valid(self):
        """Test tick validity check."""
        tick = MarketTick(
            symbol="CL=F",
            timestamp=datetime.utcnow(),
            bid=75.50,
            ask=75.55,
            last=75.52,
            feed_source="test",
        )
        
        assert tick.is_valid() is True
        
        # Invalid: bid >= ask
        tick_invalid = MarketTick(
            symbol="CL=F",
            timestamp=datetime.utcnow(),
            bid=75.60,
            ask=75.55,
            last=75.52,
            feed_source="test",
        )
        assert tick_invalid.is_valid() is False


class TestMarketBar:
    """Test MarketBar model."""
    
    def test_bar_creation(self):
        """Test creating a valid bar."""
        bar = MarketBar(
            symbol="CL=F",
            timestamp=datetime.utcnow(),
            interval_seconds=60,
            open=75.50,
            high=75.80,
            low=75.40,
            close=75.65,
            volume=10000,
            trades=500,
        )
        
        assert bar.symbol == "CL=F"
        assert bar.open == 75.50
        assert bar.high == 75.80
        assert bar.low == 75.40
        assert bar.close == 75.65
    
    def test_bar_properties(self):
        """Test bar calculated properties."""
        bar = MarketBar(
            symbol="CL=F",
            timestamp=datetime.utcnow(),
            interval_seconds=60,
            open=75.50,
            high=75.80,
            low=75.40,
            close=75.65,
            volume=10000,
        )
        
        assert bar.range == 0.40
        assert bar.body == 0.15
        assert bar.is_bullish is True
        assert bar.is_bearish is False
    
    def test_bearish_bar(self):
        """Test bearish bar detection."""
        bar = MarketBar(
            symbol="CL=F",
            timestamp=datetime.utcnow(),
            interval_seconds=60,
            open=75.65,
            high=75.80,
            low=75.40,
            close=75.50,
            volume=10000,
        )
        
        assert bar.is_bullish is False
        assert bar.is_bearish is True


class TestFeedStatus:
    """Test FeedStatus model."""
    
    def test_status_creation(self):
        """Test creating feed status."""
        status = FeedStatus(
            feed_id="test-feed",
            provider="simulated",
            symbols=["CL=F", "BZ=F"],
        )
        
        assert status.feed_id == "test-feed"
        assert status.provider == "simulated"
        assert status.symbols == ["CL=F", "BZ=F"]
        assert status.status == FeedHealth.UNKNOWN
    
    def test_is_stale(self):
        """Test stale detection."""
        status = FeedStatus(
            feed_id="test-feed",
            provider="simulated",
            last_message_at=datetime.utcnow(),
        )
        
        assert status.is_stale(stale_threshold_ms=5000) is False
        
        # Old timestamp should be stale
        old_status = FeedStatus(
            feed_id="test-feed",
            provider="simulated",
            last_message_at=datetime(2020, 1, 1),
        )
        assert old_status.is_stale(stale_threshold_ms=5000) is True


class TestFeedAnomaly:
    """Test FeedAnomaly model."""
    
    def test_anomaly_creation(self):
        """Test creating an anomaly."""
        anomaly = FeedAnomaly(
            anomaly_id="test-1",
            feed_id="test-feed",
            symbol="CL=F",
            anomaly_type=AnomalyType.PRICE_SPIKE,
            severity=4,
            description="Price spike detected",
            expected_value=75.50,
            actual_value=80.00,
        )
        
        assert anomaly.anomaly_id == "test-1"
        assert anomaly.severity == 4
        assert anomaly.anomaly_type == AnomalyType.PRICE_SPIKE
    
    def test_resolve_anomaly(self):
        """Test resolving an anomaly."""
        anomaly = FeedAnomaly(
            anomaly_id="test-1",
            feed_id="test-feed",
            symbol="CL=F",
            anomaly_type=AnomalyType.PRICE_SPIKE,
            severity=4,
            description="Price spike detected",
        )
        
        assert anomaly.is_resolved is False
        
        anomaly.resolve()
        
        assert anomaly.is_resolved is True
        assert anomaly.resolved_at is not None