"""Market data ingestion module.

This module provides real-time market data ingestion from multiple sources
with normalized event models, feed health monitoring, and automatic reconnection.
"""

from src.market_data.models.events import MarketTick, MarketBar, FeedStatus
from src.market_data.feed_manager import FeedManager
from src.market_data.adapters.base import FeedAdapter

__all__ = [
    "MarketTick",
    "MarketBar", 
    "FeedStatus",
    "FeedManager",
    "FeedAdapter",
]