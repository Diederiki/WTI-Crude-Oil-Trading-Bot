"""Tests for tick aggregator."""

import pytest
from datetime import datetime

from src.market_data.aggregator import TickAggregator, BarBuilder
from src.market_data.models.events import MarketTick, MarketBar


class TestBarBuilder:
    """Test BarBuilder functionality."""
    
    def test_builder_initialization(self):
        """Test builder initialization."""
        builder = BarBuilder(
            symbol="CL=F",
            interval_seconds=60,
            open_time=datetime.utcnow(),
        )
        
        assert builder.symbol == "CL=F"
        assert builder.interval_seconds == 60
        assert builder.trades == 0
    
    def test_add_tick(self):
        """Test adding ticks to builder."""
        builder = BarBuilder(
            symbol="CL=F",
            interval_seconds=60,
            open_time=datetime.utcnow(),
        )
        
        tick = MarketTick(
            symbol="CL=F",
            timestamp=datetime.utcnow(),
            bid=75.50,
            ask=75.55,
            last=75.52,
            last_size=100,
            feed_source="test",
        )
        
        builder.add_tick(tick)
        
        assert builder.open == 75.52
        assert builder.high == 75.52
        assert builder.low == 75.52
        assert builder.close == 75.52
        assert builder.volume == 100
        assert builder.trades == 1
    
    def test_multiple_ticks(self):
        """Test adding multiple ticks."""
        builder = BarBuilder(
            symbol="CL=F",
            interval_seconds=60,
            open_time=datetime.utcnow(),
        )
        
        # Add multiple ticks
        for i in range(5):
            tick = MarketTick(
                symbol="CL=F",
                timestamp=datetime.utcnow(),
                bid=75.50 + i * 0.01,
                ask=75.55 + i * 0.01,
                last=75.52 + i * 0.10,  # Increasing prices
                last_size=100,
                feed_source="test",
            )
            builder.add_tick(tick)
        
        assert builder.open == 75.52
        assert builder.high == 75.92
        assert builder.low == 75.52
        assert builder.close == 75.92
        assert builder.volume == 500
        assert builder.trades == 5
    
    def test_build_bar(self):
        """Test building a bar."""
        builder = BarBuilder(
            symbol="CL=F",
            interval_seconds=60,
            open_time=datetime.utcnow(),
        )
        
        tick = MarketTick(
            symbol="CL=F",
            timestamp=datetime.utcnow(),
            bid=75.50,
            ask=75.55,
            last=75.52,
            last_size=100,
            feed_source="test",
        )
        
        builder.add_tick(tick)
        bar = builder.build()
        
        assert isinstance(bar, MarketBar)
        assert bar.symbol == "CL=F"
        assert bar.open == 75.52
        assert bar.volume == 100


class TestTickAggregator:
    """Test TickAggregator functionality."""
    
    def test_aggregator_initialization(self):
        """Test aggregator initialization."""
        agg = TickAggregator(intervals=[60, 300])
        
        assert agg.intervals == [60, 300]
    
    def test_process_tick(self):
        """Test processing a tick."""
        agg = TickAggregator(intervals=[60])
        
        tick = MarketTick(
            symbol="CL=F",
            timestamp=datetime.utcnow(),
            bid=75.50,
            ask=75.55,
            last=75.52,
            last_size=100,
            feed_source="test",
        )
        
        completed = agg.process_tick(tick)
        
        # No bar should complete yet
        assert len(completed) == 0
        
        # Should have active bar
        active = agg.get_active_bar("CL=F", 60)
        assert active is not None
        assert active.trades == 1
    
    def test_bar_callback(self):
        """Test bar callback registration."""
        agg = TickAggregator(intervals=[60])
        
        received_bars = []
        agg.on_bar(lambda b: received_bars.append(b))
        
        # Add ticks
        for i in range(5):
            tick = MarketTick(
                symbol="CL=F",
                timestamp=datetime.utcnow(),
                bid=75.50,
                ask=75.55,
                last=75.52 + i * 0.01,
                last_size=100,
                feed_source="test",
            )
            agg.process_tick(tick)
        
        # Force complete
        agg.force_complete_all()
        
        # Should have received bar
        assert len(received_bars) > 0
    
    def test_multiple_symbols(self):
        """Test handling multiple symbols."""
        agg = TickAggregator(intervals=[60])
        
        # Add ticks for different symbols
        for symbol in ["CL=F", "BZ=F"]:
            tick = MarketTick(
                symbol=symbol,
                timestamp=datetime.utcnow(),
                bid=75.50,
                ask=75.55,
                last=75.52,
                last_size=100,
                feed_source="test",
            )
            agg.process_tick(tick)
        
        # Should have active bars for both
        assert agg.get_active_bar("CL=F", 60) is not None
        assert agg.get_active_bar("BZ=F", 60) is not None
    
    def test_reset(self):
        """Test aggregator reset."""
        agg = TickAggregator(intervals=[60])
        
        tick = MarketTick(
            symbol="CL=F",
            timestamp=datetime.utcnow(),
            bid=75.50,
            ask=75.55,
            last=75.52,
            last_size=100,
            feed_source="test",
        )
        
        agg.process_tick(tick)
        assert agg.get_active_bar("CL=F", 60) is not None
        
        agg.reset()
        assert agg.get_active_bar("CL=F", 60) is None