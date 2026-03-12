"""Base feed adapter interface.

All market data feed adapters must implement this interface to ensure
consistent behavior across different data providers.
"""

from abc import ABC, abstractmethod
from asyncio import Queue
from collections.abc import Callable
from datetime import datetime
from typing import Any

from src.core.logging_config import get_logger
from src.market_data.models.events import FeedStatus, MarketTick, MarketBar, FeedHealth

logger = get_logger("market_data")


class FeedAdapter(ABC):
    """Abstract base class for market data feed adapters.
    
    This class defines the interface that all feed adapters must implement.
    It provides common functionality for connection management, health monitoring,
    and event distribution.
    
    Attributes:
        feed_id: Unique identifier for this feed instance
        provider: Name of the data provider
        symbols: List of symbols to subscribe to
        config: Provider-specific configuration
        tick_callbacks: List of callbacks for tick events
        bar_callbacks: List of callbacks for bar events
        status_callbacks: List of callbacks for status changes
        status: Current feed status
        _tick_queue: Queue for tick events
        _running: Whether the feed is running
    """
    
    def __init__(
        self,
        feed_id: str,
        provider: str,
        symbols: list[str],
        config: dict[str, Any] | None = None,
    ):
        """Initialize the feed adapter.
        
        Args:
            feed_id: Unique identifier for this feed
            provider: Provider name (e.g., "polygon", "ibkr")
            symbols: List of symbols to subscribe
            config: Provider-specific configuration
        """
        self.feed_id = feed_id
        self.provider = provider
        self.symbols = [s.upper() for s in symbols]
        self.config = config or {}
        
        # Event callbacks
        self.tick_callbacks: list[Callable[[MarketTick], None]] = []
        self.bar_callbacks: list[Callable[[MarketBar], None]] = []
        self.status_callbacks: list[Callable[[FeedStatus], None]] = []
        
        # Status tracking
        self.status = FeedStatus(
            feed_id=feed_id,
            provider=provider,
            symbols=self.symbols.copy(),
        )
        
        # Internal state
        self._tick_queue: Queue[MarketTick] | None = None
        self._running = False
        self._last_tick_time: dict[str, datetime] = {}
        self._connection_start_time: datetime | None = None
        
        logger.info(
            "Feed adapter initialized",
            feed_id=feed_id,
            provider=provider,
            symbols=symbols,
        )
    
    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the feed.
        
        This method should establish the connection to the data provider
        and prepare for receiving data. It should update the connection
        status and handle any authentication required.
        
        Raises:
            ConnectionError: If connection fails
            AuthenticationError: If authentication fails
        """
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to the feed.
        
        This method should gracefully close the connection and clean up
        any resources. It should update the connection status.
        """
        pass
    
    @abstractmethod
    async def subscribe(self, symbols: list[str]) -> None:
        """Subscribe to additional symbols.
        
        Args:
            symbols: List of symbols to subscribe to
        """
        pass
    
    @abstractmethod
    async def unsubscribe(self, symbols: list[str]) -> None:
        """Unsubscribe from symbols.
        
        Args:
            symbols: List of symbols to unsubscribe from
        """
        pass
    
    @abstractmethod
    async def receive_loop(self) -> None:
        """Main receive loop for market data.
        
        This method should run continuously while the feed is active,
        receiving data from the provider and dispatching events.
        It should handle reconnection automatically.
        """
        pass
    
    def on_tick(self, callback: Callable[[MarketTick], None]) -> None:
        """Register a callback for tick events.
        
        Args:
            callback: Function to call when a tick is received
        """
        self.tick_callbacks.append(callback)
        logger.debug(
            "Tick callback registered",
            feed_id=self.feed_id,
            callback=callback.__name__ if hasattr(callback, "__name__") else "anonymous",
        )
    
    def on_bar(self, callback: Callable[[MarketBar], None]) -> None:
        """Register a callback for bar events.
        
        Args:
            callback: Function to call when a bar is completed
        """
        self.bar_callbacks.append(callback)
        logger.debug(
            "Bar callback registered",
            feed_id=self.feed_id,
            callback=callback.__name__ if hasattr(callback, "__name__") else "anonymous",
        )
    
    def on_status_change(self, callback: Callable[[FeedStatus], None]) -> None:
        """Register a callback for status changes.
        
        Args:
            callback: Function to call when feed status changes
        """
        self.status_callbacks.append(callback)
        logger.debug(
            "Status callback registered",
            feed_id=self.feed_id,
        )
    
    def remove_tick_callback(self, callback: Callable[[MarketTick], None]) -> None:
        """Remove a tick callback.
        
        Args:
            callback: Callback to remove
        """
        if callback in self.tick_callbacks:
            self.tick_callbacks.remove(callback)
    
    def remove_bar_callback(self, callback: Callable[[MarketBar], None]) -> None:
        """Remove a bar callback.
        
        Args:
            callback: Callback to remove
        """
        if callback in self.bar_callbacks:
            self.bar_callbacks.remove(callback)
    
    def _dispatch_tick(self, tick: MarketTick) -> None:
        """Dispatch tick to all registered callbacks.
        
        Args:
            tick: Tick event to dispatch
        """
        self._last_tick_time[tick.symbol] = datetime.utcnow()
        self.status.messages_received += 1
        self.status.last_message_at = datetime.utcnow()
        
        for callback in self.tick_callbacks:
            try:
                callback(tick)
            except Exception as e:
                logger.error(
                    "Error in tick callback",
                    feed_id=self.feed_id,
                    error=str(e),
                    callback=callback.__name__ if hasattr(callback, "__name__") else "anonymous",
                )
    
    def _dispatch_bar(self, bar: MarketBar) -> None:
        """Dispatch bar to all registered callbacks.
        
        Args:
            bar: Bar event to dispatch
        """
        for callback in self.bar_callbacks:
            try:
                callback(bar)
            except Exception as e:
                logger.error(
                    "Error in bar callback",
                    feed_id=self.feed_id,
                    error=str(e),
                    callback=callback.__name__ if hasattr(callback, "__name__") else "anonymous",
                )
    
    def _update_status(self, status: FeedHealth, error: str | None = None) -> None:
        """Update feed status and notify callbacks.
        
        Args:
            status: New health status
            error: Optional error message
        """
        old_status = self.status.status
        self.status.status = status
        
        if error:
            self.status.last_error = error
            self.status.errors_count += 1
        
        if status == FeedHealth.HEALTHY:
            self.status.is_connected = True
            if self._connection_start_time is None:
                self._connection_start_time = datetime.utcnow()
                self.status.connected_at = self._connection_start_time
        elif status == FeedHealth.DISCONNECTED:
            self.status.is_connected = False
            self._connection_start_time = None
        
        # Notify if status changed
        if old_status != status:
            logger.info(
                "Feed status changed",
                feed_id=self.feed_id,
                old_status=old_status,
                new_status=status,
                error=error,
            )
            for callback in self.status_callbacks:
                try:
                    callback(self.status)
                except Exception as e:
                    logger.error(
                        "Error in status callback",
                        feed_id=self.feed_id,
                        error=str(e),
                    )
    
    def get_status(self) -> FeedStatus:
        """Get current feed status.
        
        Returns:
            Current FeedStatus
        """
        return self.status.update_health()
    
    def is_healthy(self) -> bool:
        """Check if feed is healthy.
        
        Returns:
            True if feed is healthy and connected
        """
        return self.status.is_connected and self.status.status == FeedHealth.HEALTHY
    
    def is_running(self) -> bool:
        """Check if feed is running.
        
        Returns:
            True if feed receive loop is active
        """
        return self._running
    
    async def start(self) -> None:
        """Start the feed.
        
        Connects to the feed and starts the receive loop.
        """
        if self._running:
            logger.warning("Feed already running", feed_id=self.feed_id)
            return
        
        self._running = True
        await self.connect()
        logger.info("Feed started", feed_id=self.feed_id)
    
    async def stop(self) -> None:
        """Stop the feed.
        
        Stops the receive loop and disconnects from the feed.
        """
        if not self._running:
            logger.warning("Feed not running", feed_id=self.feed_id)
            return
        
        self._running = False
        await self.disconnect()
        logger.info("Feed stopped", feed_id=self.feed_id)
    
    def get_symbol_health(self, symbol: str, stale_threshold_ms: float = 5000) -> dict[str, Any]:
        """Get health information for a specific symbol.
        
        Args:
            symbol: Symbol to check
            stale_threshold_ms: Milliseconds to consider stale
            
        Returns:
            Dictionary with health information
        """
        last_time = self._last_tick_time.get(symbol)
        if last_time is None:
            return {
                "symbol": symbol,
                "has_data": False,
                "is_stale": True,
                "ms_since_last_tick": None,
            }
        
        ms_since = (datetime.utcnow() - last_time).total_seconds() * 1000
        return {
            "symbol": symbol,
            "has_data": True,
            "is_stale": ms_since > stale_threshold_ms,
            "ms_since_last_tick": ms_since,
            "last_tick_time": last_time.isoformat(),
        }