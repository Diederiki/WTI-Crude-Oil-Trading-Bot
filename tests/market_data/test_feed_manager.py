"""Tests for feed manager and adapters."""

import asyncio
import pytest
from datetime import datetime

from src.market_data.feed_manager import FeedManager
from src.market_data.adapters.simulated import SimulatedFeedAdapter
from src.market_data.models.events import MarketTick, MarketBar, FeedHealth


@pytest.fixture
def feed_manager():
    """Create a feed manager for testing."""
    return FeedManager()


@pytest.fixture
def simulated_feed():
    """Create a simulated feed for testing."""
    return SimulatedFeedAdapter(
        feed_id="test-sim",
        symbols=["CL=F"],
        config={
            "volatility": 0.1,
            "tick_interval_ms": 100,
            "base_prices": {"CL=F": 75.0},
        },
    )


class TestFeedManager:
    """Test FeedManager functionality."""
    
    @pytest.mark.asyncio
    async def test_register_feed(self, feed_manager, simulated_feed):
        """Test registering a feed."""
        feed_manager.register_feed(simulated_feed)
        
        assert "test-sim" in feed_manager.feeds
        assert feed_manager.feeds["test-sim"] == simulated_feed
    
    @pytest.mark.asyncio
    async def test_register_duplicate_feed(self, feed_manager, simulated_feed):
        """Test registering duplicate feed raises error."""
        feed_manager.register_feed(simulated_feed)
        
        with pytest.raises(ValueError, match="already registered"):
            feed_manager.register_feed(simulated_feed)
    
    @pytest.mark.asyncio
    async def test_unregister_feed(self, feed_manager, simulated_feed):
        """Test unregistering a feed."""
        feed_manager.register_feed(simulated_feed)
        feed_manager.unregister_feed("test-sim")
        
        assert "test-sim" not in feed_manager.feeds
    
    @pytest.mark.asyncio
    async def test_tick_callback(self, feed_manager, simulated_feed):
        """Test tick callback registration and dispatch."""
        received_ticks = []
        
        def on_tick(tick: MarketTick):
            received_ticks.append(tick)
        
        feed_manager.on_tick(on_tick)
        feed_manager.register_feed(simulated_feed)
        
        # Simulate receiving a tick
        tick = MarketTick(
            symbol="CL=F",
            timestamp=datetime.utcnow(),
            bid=75.50,
            ask=75.55,
            last=75.52,
            feed_source="test",
        )
        
        simulated_feed._dispatch_tick(tick)
        
        assert len(received_ticks) == 1
        assert received_ticks[0].symbol == "CL=F"
    
    @pytest.mark.asyncio
    async def test_get_feed_status(self, feed_manager, simulated_feed):
        """Test getting feed status."""
        feed_manager.register_feed(simulated_feed)
        
        status = feed_manager.get_feed_status("test-sim")
        
        assert "test-sim" in status
        assert status["test-sim"].feed_id == "test-sim"
    
    @pytest.mark.asyncio
    async def test_get_last_price(self, feed_manager, simulated_feed):
        """Test getting last price."""
        feed_manager.register_feed(simulated_feed)
        
        # Initially no price
        assert feed_manager.get_last_price("CL=F") is None
        
        # Dispatch a tick
        tick = MarketTick(
            symbol="CL=F",
            timestamp=datetime.utcnow(),
            bid=75.50,
            ask=75.55,
            last=75.52,
            feed_source="test",
        )
        simulated_feed._dispatch_tick(tick)
        
        # Now should have price
        price_data = feed_manager.get_last_price("CL=F")
        assert price_data is not None
        assert price_data["price"] == 75.52
    
    @pytest.mark.asyncio
    async def test_get_price_history(self, feed_manager, simulated_feed):
        """Test getting price history."""
        feed_manager.register_feed(simulated_feed)
        
        # Dispatch multiple ticks
        for i in range(5):
            tick = MarketTick(
                symbol="CL=F",
                timestamp=datetime.utcnow(),
                bid=75.50 + i * 0.01,
                ask=75.55 + i * 0.01,
                last=75.52 + i * 0.01,
                feed_source="test",
            )
            simulated_feed._dispatch_tick(tick)
        
        history = feed_manager.get_price_history("CL=F", limit=10)
        
        assert len(history) == 5
    
    @pytest.mark.asyncio
    async def test_get_healthy_feeds(self, feed_manager, simulated_feed):
        """Test getting healthy feeds."""
        feed_manager.register_feed(simulated_feed)
        
        # Initially not healthy (not connected)
        healthy = feed_manager.get_healthy_feeds()
        assert len(healthy) == 0
        
        # Mark as healthy
        simulated_feed._update_status(FeedHealth.HEALTHY)
        
        healthy = feed_manager.get_healthy_feeds()
        assert "test-sim" in healthy


class TestSimulatedFeedAdapter:
    """Test SimulatedFeedAdapter functionality."""
    
    @pytest.mark.asyncio
    async def test_initialization(self):
        """Test adapter initialization."""
        feed = SimulatedFeedAdapter(
            feed_id="test",
            symbols=["CL=F", "BZ=F"],
        )
        
        assert feed.feed_id == "test"
        assert feed.provider == "simulated"
        assert "CL=F" in feed.symbols
        assert "BZ=F" in feed.symbols
    
    @pytest.mark.asyncio
    async def test_connect_disconnect(self):
        """Test connect and disconnect."""
        feed = SimulatedFeedAdapter(
            feed_id="test",
            symbols=["CL=F"],
        )
        
        await feed.connect()
        assert feed.is_healthy() is True
        
        await feed.disconnect()
        assert feed.is_healthy() is False
    
    @pytest.mark.asyncio
    async def test_subscribe_unsubscribe(self):
        """Test subscribe and unsubscribe."""
        feed = SimulatedFeedAdapter(
            feed_id="test",
            symbols=["CL=F"],
        )
        
        await feed.subscribe(["BZ=F"])
        assert "BZ=F" in feed.symbols
        
        await feed.unsubscribe(["CL=F"])
        assert "CL=F" not in feed.symbols
    
    @pytest.mark.asyncio
    async def test_tick_generation(self):
        """Test tick generation."""
        feed = SimulatedFeedAdapter(
            feed_id="test",
            symbols=["CL=F"],
            config={"tick_interval_ms": 10},
        )
        
        received_ticks = []
        feed.on_tick(lambda t: received_ticks.append(t))
        
        await feed.connect()
        
        # Run briefly to generate ticks
        task = asyncio.create_task(feed.receive_loop())
        await asyncio.sleep(0.05)  # 50ms
        await feed.stop()
        
        # Should have generated some ticks
        assert len(received_ticks) > 0
        assert all(t.symbol == "CL=F" for t in received_ticks)
    
    @pytest.mark.asyncio
    async def test_inject_tick(self):
        """Test injecting custom ticks."""
        feed = SimulatedFeedAdapter(
            feed_id="test",
            symbols=["CL=F"],
        )
        
        received_ticks = []
        feed.on_tick(lambda t: received_ticks.append(t))
        
        tick = MarketTick(
            symbol="CL=F",
            timestamp=datetime.utcnow(),
            bid=75.50,
            ask=75.55,
            last=75.52,
            feed_source="test",
        )
        
        await feed.inject_tick(tick)
        
        assert len(received_ticks) == 1
        assert received_ticks[0].last == 75.52
    
    @pytest.mark.asyncio
    async def test_inject_spike(self):
        """Test injecting price spikes."""
        feed = SimulatedFeedAdapter(
            feed_id="test",
            symbols=["CL=F"],
            config={"base_prices": {"CL=F": 75.0}},
        )
        
        received_ticks = []
        feed.on_tick(lambda t: received_ticks.append(t))
        
        await feed.inject_spike("CL=F", 5.0)  # 5% spike
        
        assert len(received_ticks) == 1
        # Price should be around 75.0 * 1.05 = 78.75
        assert received_ticks[0].last > 78.0