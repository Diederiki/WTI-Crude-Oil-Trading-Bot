"""Market data feed adapters.

Adapters for different market data providers implementing the FeedAdapter interface.
"""

from src.market_data.adapters.base import FeedAdapter
from src.market_data.adapters.simulated import SimulatedFeedAdapter

__all__ = ["FeedAdapter", "SimulatedFeedAdapter"]