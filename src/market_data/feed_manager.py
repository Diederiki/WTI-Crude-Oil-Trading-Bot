"""Feed manager for orchestrating multiple market data feeds.

The FeedManager coordinates multiple feed adapters, provides unified
access to market data, monitors feed health, and handles failover.
"""

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Any

from src.core.logging_config import get_logger
from src.core.redis_client import RedisClient
from src.market_data.adapters.base import FeedAdapter
from src.market_data.models.events import MarketTick, MarketBar, FeedStatus, FeedHealth, FeedAnomaly, AnomalyType

logger = get_logger("market_data")


class FeedManager:
    """Manages multiple market data feeds with health monitoring.
    
    The FeedManager is responsible for:
    - Registering and managing multiple feed adapters
    - Distributing ticks/bars to registered callbacks
    - Monitoring feed health and detecting anomalies
    - Providing unified access to market data across feeds
    - Handling feed failover and redundancy
    
    Attributes:
        feeds: Dictionary of feed_id -> FeedAdapter
        tick_callbacks: Global tick callbacks
        bar_callbacks: Global bar callbacks
        feed_status_callbacks: Feed status change callbacks
        redis: Optional Redis client for pub/sub
        _running: Whether manager is running
        _health_check_task: Background health check task
        _anomaly_history: List of detected anomalies
    """
    
    def __init__(self, redis: RedisClient | None = None):
        """Initialize feed manager.
        
        Args:
            redis: Optional Redis client for caching and pub/sub
        """
        self.feeds: dict[str, FeedAdapter] = {}
        self.tick_callbacks: list[Callable[[MarketTick], None]] = []
        self.bar_callbacks: list[Callable[[MarketBar], None]] = []
        self.feed_status_callbacks: list[Callable[[str, FeedStatus], None]] = []
        
        self.redis = redis
        self._running = False
        self._health_check_task: asyncio.Task | None = None
        self._anomaly_history: list[FeedAnomaly] = []
        self._last_prices: dict[str, dict[str, Any]] = {}
        self._price_history: dict[str, list[MarketTick]] = {}
        self._max_history_per_symbol = 1000
        
        logger.info("Feed manager initialized")
    
    def register_feed(self, feed: FeedAdapter) -> None:
        """Register a feed adapter.
        
        Args:
            feed: Feed adapter to register
        """
        if feed.feed_id in self.feeds:
            raise ValueError(f"Feed {feed.feed_id} already registered")
        
        # Register callbacks
        feed.on_tick(self._on_tick)
        feed.on_bar(self._on_bar)
        feed.on_status_change(self._on_feed_status_change)
        
        self.feeds[feed.feed_id] = feed
        logger.info(
            "Feed registered",
            feed_id=feed.feed_id,
            provider=feed.provider,
            symbols=feed.symbols,
        )
    
    def unregister_feed(self, feed_id: str) -> None:
        """Unregister a feed adapter.
        
        Args:
            feed_id: ID of feed to unregister
        """
        feed = self.feeds.pop(feed_id, None)
        if feed:
            logger.info("Feed unregistered", feed_id=feed_id)
    
    def on_tick(self, callback: Callable[[MarketTick], None]) -> None:
        """Register global tick callback.
        
        Args:
            callback: Function to call for all ticks
        """
        self.tick_callbacks.append(callback)
        logger.debug(
            "Global tick callback registered",
            callback=callback.__name__ if hasattr(callback, "__name__") else "anonymous",
        )
    
    def on_bar(self, callback: Callable[[MarketBar], None]) -> None:
        """Register global bar callback.
        
        Args:
            callback: Function to call for all bars
        """
        self.bar_callbacks.append(callback)
        logger.debug(
            "Global bar callback registered",
            callback=callback.__name__ if hasattr(callback, "__name__") else "anonymous",
        )
    
    def on_feed_status_change(self, callback: Callable[[str, FeedStatus], None]) -> None:
        """Register feed status change callback.
        
        Args:
            callback: Function(feed_id, status) to call on status changes
        """
        self.feed_status_callbacks.append(callback)
    
    def _on_tick(self, tick: MarketTick) -> None:
        """Internal tick handler from feeds.
        
        Args:
            tick: Tick event from a feed
        """
        # Store price history
        symbol = tick.symbol
        if symbol not in self._price_history:
            self._price_history[symbol] = []
        
        history = self._price_history[symbol]
        history.append(tick)
        
        # Trim history
        if len(history) > self._max_history_per_symbol:
            history.pop(0)
        
        # Update last prices
        self._last_prices[symbol] = {
            "price": tick.last,
            "bid": tick.bid,
            "ask": tick.ask,
            "timestamp": tick.timestamp,
            "feed_source": tick.feed_source,
        }
        
        # Check for anomalies
        self._check_tick_anomalies(tick, history)
        
        # Dispatch to global callbacks
        for callback in self.tick_callbacks:
            try:
                callback(tick)
            except Exception as e:
                logger.error(
                    "Error in global tick callback",
                    error=str(e),
                    callback=callback.__name__ if hasattr(callback, "__name__") else "anonymous",
                )
        
        # Publish to Redis if available
        if self.redis:
            asyncio.create_task(self._publish_tick(tick))
    
    def _on_bar(self, bar: MarketBar) -> None:
        """Internal bar handler from feeds.
        
        Args:
            bar: Bar event from a feed
        """
        for callback in self.bar_callbacks:
            try:
                callback(bar)
            except Exception as e:
                logger.error(
                    "Error in global bar callback",
                    error=str(e),
                    callback=callback.__name__ if hasattr(callback, "__name__") else "anonymous",
                )
        
        # Publish to Redis if available
        if self.redis:
            asyncio.create_task(self._publish_bar(bar))
    
    def _on_feed_status_change(self, status: FeedStatus) -> None:
        """Handle feed status changes.
        
        Args:
            status: New feed status
        """
        logger.info(
            "Feed status changed",
            feed_id=status.feed_id,
            status=status.status,
        )
        
        for callback in self.feed_status_callbacks:
            try:
                callback(status.feed_id, status)
            except Exception as e:
                logger.error(
                    "Error in feed status callback",
                    error=str(e),
                )
    
    def _check_tick_anomalies(self, tick: MarketTick, history: list[MarketTick]) -> None:
        """Check for anomalies in tick data.
        
        Args:
            tick: Current tick
            history: Recent tick history for symbol
        """
        if len(history) < 2:
            return
        
        # Check for price spike
        prev_tick = history[-2]
        price_change_pct = abs(tick.last - prev_tick.last) / prev_tick.last * 100
        
        if price_change_pct > 5:  # 5% spike threshold
            self._record_anomaly(
                tick.feed_source,
                tick.symbol,
                AnomalyType.PRICE_SPIKE,
                4,
                f"Price spike detected: {price_change_pct:.2f}%",
                prev_tick.last,
                tick.last,
            )
        
        # Check for spread anomaly
        if tick.spread_pct > 2:  # 2% spread threshold
            self._record_anomaly(
                tick.feed_source,
                tick.symbol,
                AnomalyType.SPREAD_ANOMALY,
                3,
                f"Abnormal spread: {tick.spread_pct:.4f}%",
                None,
                tick.spread_pct,
            )
        
        # Check for stale feed
        time_since_last = (tick.timestamp - prev_tick.timestamp).total_seconds()
        if time_since_last > 60:  # 60 second gap
            self._record_anomaly(
                tick.feed_source,
                tick.symbol,
                AnomalyType.FEED_GAP,
                2,
                f"Feed gap: {time_since_last:.1f}s",
                None,
                time_since_last,
            )
    
    def _record_anomaly(
        self,
        feed_id: str,
        symbol: str,
        anomaly_type: AnomalyType,
        severity: int,
        description: str,
        expected_value: float | None,
        actual_value: float | None,
    ) -> None:
        """Record a detected anomaly.
        
        Args:
            feed_id: Feed where anomaly was detected
            symbol: Affected symbol
            anomaly_type: Type of anomaly
            severity: Severity level 1-5
            description: Human-readable description
            expected_value: Expected/normal value
            actual_value: Actual observed value
        """
        anomaly = FeedAnomaly(
            anomaly_id=f"{feed_id}:{symbol}:{datetime.utcnow().timestamp()}",
            feed_id=feed_id,
            symbol=symbol,
            anomaly_type=anomaly_type,
            severity=severity,
            description=description,
            expected_value=expected_value,
            actual_value=actual_value,
        )
        
        self._anomaly_history.append(anomaly)
        
        # Keep only recent anomalies
        if len(self._anomaly_history) > 1000:
            self._anomaly_history = self._anomaly_history[-1000:]
        
        logger.warning(
            "Feed anomaly detected",
            feed_id=feed_id,
            symbol=symbol,
            anomaly_type=anomaly_type.value,
            severity=severity,
            description=description,
        )
    
    async def _publish_tick(self, tick: MarketTick) -> None:
        """Publish tick to Redis.
        
        Args:
            tick: Tick to publish
        """
        if not self.redis:
            return
        
        try:
            channel = f"ticks:{tick.symbol}"
            await self.redis.publish(channel, tick.model_dump_json())
        except Exception as e:
            logger.error(
                "Failed to publish tick to Redis",
                error=str(e),
                symbol=tick.symbol,
            )
    
    async def _publish_bar(self, bar: MarketBar) -> None:
        """Publish bar to Redis.
        
        Args:
            bar: Bar to publish
        """
        if not self.redis:
            return
        
        try:
            channel = f"bars:{bar.symbol}"
            await self.redis.publish(channel, bar.model_dump_json())
        except Exception as e:
            logger.error(
                "Failed to publish bar to Redis",
                error=str(e),
                symbol=bar.symbol,
            )
    
    async def start(self) -> None:
        """Start all feeds and health monitoring."""
        if self._running:
            logger.warning("Feed manager already running")
            return
        
        self._running = True
        
        # Start all feeds
        for feed in self.feeds.values():
            try:
                await feed.start()
                asyncio.create_task(feed.receive_loop())
            except Exception as e:
                logger.error(
                    "Failed to start feed",
                    feed_id=feed.feed_id,
                    error=str(e),
                )
        
        # Start health monitoring
        self._health_check_task = asyncio.create_task(self._health_check_loop())
        
        logger.info("Feed manager started", feed_count=len(self.feeds))
    
    async def stop(self) -> None:
        """Stop all feeds and monitoring."""
        if not self._running:
            logger.warning("Feed manager not running")
            return
        
        self._running = False
        
        # Stop health monitoring
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
        
        # Stop all feeds
        for feed in self.feeds.values():
            try:
                await feed.stop()
            except Exception as e:
                logger.error(
                    "Error stopping feed",
                    feed_id=feed.feed_id,
                    error=str(e),
                )
        
        logger.info("Feed manager stopped")
    
    async def _health_check_loop(self) -> None:
        """Background health check loop."""
        while self._running:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds
                
                for feed in self.feeds.values():
                    status = feed.get_status()
                    
                    # Check for stale feeds
                    if status.is_stale(stale_threshold_ms=10000):
                        logger.warning(
                            "Feed appears stale",
                            feed_id=feed.feed_id,
                            ms_since_last_message=status.time_since_last_message_ms,
                        )
                        
                        # Attempt reconnection if configured
                        if feed.config.get("auto_reconnect", True):
                            logger.info(
                                "Attempting feed reconnection",
                                feed_id=feed.feed_id,
                            )
                            try:
                                await feed.stop()
                                await asyncio.sleep(1)
                                await feed.start()
                                asyncio.create_task(feed.receive_loop())
                                feed.status.reconnects_count += 1
                            except Exception as e:
                                logger.error(
                                    "Feed reconnection failed",
                                    feed_id=feed.feed_id,
                                    error=str(e),
                                )
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in health check loop", error=str(e))
    
    def get_feed_status(self, feed_id: str | None = None) -> dict[str, FeedStatus]:
        """Get status of all feeds or a specific feed.
        
        Args:
            feed_id: Optional specific feed ID
            
        Returns:
            Dictionary of feed_id -> FeedStatus
        """
        if feed_id:
            feed = self.feeds.get(feed_id)
            if feed:
                return {feed_id: feed.get_status()}
            return {}
        
        return {fid: feed.get_status() for fid, feed in self.feeds.items()}
    
    def get_last_price(self, symbol: str) -> dict[str, Any] | None:
        """Get last known price for a symbol.
        
        Args:
            symbol: Symbol to look up
            
        Returns:
            Price data or None if not available
        """
        return self._last_prices.get(symbol.upper())
    
    def get_price_history(
        self,
        symbol: str,
        limit: int = 100,
    ) -> list[MarketTick]:
        """Get recent price history for a symbol.
        
        Args:
            symbol: Symbol to look up
            limit: Maximum number of ticks to return
            
        Returns:
            List of recent ticks
        """
        history = self._price_history.get(symbol.upper(), [])
        return history[-limit:] if history else []
    
    def get_anomalies(
        self,
        symbol: str | None = None,
        feed_id: str | None = None,
        limit: int = 100,
    ) -> list[FeedAnomaly]:
        """Get recent anomalies.
        
        Args:
            symbol: Optional symbol filter
            feed_id: Optional feed filter
            limit: Maximum number to return
            
        Returns:
            List of recent anomalies
        """
        anomalies = self._anomaly_history
        
        if symbol:
            anomalies = [a for a in anomalies if a.symbol == symbol.upper()]
        if feed_id:
            anomalies = [a for a in anomalies if a.feed_id == feed_id]
        
        return anomalies[-limit:] if anomalies else []
    
    def get_healthy_feeds(self) -> list[str]:
        """Get list of healthy feed IDs.
        
        Returns:
            List of healthy feed IDs
        """
        return [
            fid for fid, feed in self.feeds.items()
            if feed.is_healthy()
        ]
    
    def get_best_feed_for_symbol(self, symbol: str) -> str | None:
        """Get the best (healthiest) feed for a symbol.
        
        Args:
            symbol: Symbol to look up
            
        Returns:
            Best feed ID or None
        """
        symbol = symbol.upper()
        candidates = []
        
        for feed_id, feed in self.feeds.items():
            if symbol in feed.symbols and feed.is_healthy():
                # Score by message rate and latency
                status = feed.get_status()
                score = status.messages_per_second - (status.avg_latency_ms / 100)
                candidates.append((feed_id, score))
        
        if not candidates:
            return None
        
        # Return feed with highest score
        return max(candidates, key=lambda x: x[1])[0]