"""Fake spike filter for cross-feed validation.

Detects when a price spike appears on one feed but is not confirmed
by other reference feeds, indicating a potential data anomaly.
"""

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from src.core.logging_config import get_logger
from src.market_data.models.events import MarketTick, FeedAnomaly, AnomalyType

logger = get_logger("strategy")


@dataclass
class FakeSpikeConfig:
    """Configuration for fake spike detection."""
    
    confirmation_timeout_ms: float = 500.0
    """Time to wait for confirmation from other feeds."""
    
    max_price_deviation_pct: float = 0.1
    """Maximum allowed deviation between feeds for normal conditions."""
    
    spike_threshold_pct: float = 0.5
    """Price change percentage to be considered a spike."""
    
    min_spike_severity: int = 3
    """Minimum anomaly severity to consider as potential fake."""
    
    confirmation_feeds_required: int = 1
    """Number of other feeds required for confirmation."""


class FakeSpikeFilter:
    """Filter for detecting fake price spikes.
    
    Monitors multiple feeds and compares price movements. When a spike
    is detected on one feed, it checks if other feeds confirm the move.
    If not confirmed, the spike is flagged as potentially fake.
    
    Detection logic:
    1. Monitor all feeds for price spikes
    2. When spike detected on primary feed, check other feeds
    3. If other feeds don't show similar move within timeout, flag as fake
    4. Block signals based on fake spikes
    """
    
    def __init__(self, config: FakeSpikeConfig | None = None):
        """Initialize fake spike filter.
        
        Args:
            config: Filter configuration
        """
        self.config = config or FakeSpikeConfig()
        
        # Price history per feed per symbol
        self._price_history: dict[str, dict[str, deque[tuple[datetime, float]]]] = {}
        
        # Pending confirmations (spikes waiting for confirmation)
        self._pending_confirmations: deque[dict[str, Any]] = deque(maxlen=100)
        
        # Blocked symbols (temporarily blocked due to fake spike)
        self._blocked_symbols: dict[str, datetime] = {}
        
        # Statistics
        self._fake_spikes_detected: int = 0
        self._confirmed_spikes: int = 0
        
        logger.info(
            "Fake spike filter initialized",
            timeout_ms=self.config.confirmation_timeout_ms,
            threshold_pct=self.config.spike_threshold_pct,
        )
    
    def on_tick(self, tick: MarketTick) -> FeedAnomaly | None:
        """Process tick for fake spike detection.
        
        Args:
            tick: Market tick
            
        Returns:
            Anomaly if fake spike detected, None otherwise
        """
        symbol = tick.symbol
        feed_id = tick.feed_source
        
        # Initialize storage
        if symbol not in self._price_history:
            self._price_history[symbol] = {}
        if feed_id not in self._price_history[symbol]:
            self._price_history[symbol][feed_id] = deque(maxlen=50)
        
        # Store price
        self._price_history[symbol][feed_id].append((tick.timestamp, tick.last))
        
        # Check for spike on this feed
        spike = self._detect_spike(symbol, feed_id, tick)
        if spike:
            # Check for confirmation from other feeds
            confirmed = self._check_confirmation(symbol, feed_id, tick, spike)
            
            if not confirmed:
                # Fake spike detected
                return self._create_anomaly(symbol, feed_id, tick, spike)
            else:
                self._confirmed_spikes += 1
                logger.info(
                    "Spike confirmed by other feeds",
                    symbol=symbol,
                    feed=feed_id,
                    spike_pct=spike["change_pct"],
                )
        
        # Clean up old pending confirmations
        self._cleanup_pending()
        
        return None
    
    def _detect_spike(
        self,
        symbol: str,
        feed_id: str,
        tick: MarketTick,
    ) -> dict[str, Any] | None:
        """Detect if tick represents a price spike.
        
        Args:
            symbol: Trading symbol
            feed_id: Feed identifier
            tick: Current tick
            
        Returns:
            Spike data or None
        """
        history = self._price_history[symbol][feed_id]
        if len(history) < 5:
            return None
        
        # Get recent prices
        recent = list(history)[-10:]
        if len(recent) < 5:
            return None
        
        prev_price = recent[-2][1]  # Price before current
        current_price = tick.last
        
        # Calculate change
        change_pct = abs(current_price - prev_price) / prev_price * 100
        
        if change_pct < self.config.spike_threshold_pct:
            return None
        
        return {
            "prev_price": prev_price,
            "current_price": current_price,
            "change_pct": change_pct,
            "direction": "up" if current_price > prev_price else "down",
            "timestamp": tick.timestamp,
        }
    
    def _check_confirmation(
        self,
        symbol: str,
        spike_feed_id: str,
        tick: MarketTick,
        spike: dict[str, Any],
    ) -> bool:
        """Check if other feeds confirm the spike.
        
        Args:
            symbol: Trading symbol
            spike_feed_id: Feed where spike was detected
            tick: Current tick
            spike: Spike data
            
        Returns:
            True if confirmed by other feeds
        """
        symbol_feeds = self._price_history.get(symbol, {})
        
        confirmations = 0
        
        for feed_id, history in symbol_feeds.items():
            if feed_id == spike_feed_id:
                continue
            
            if len(history) < 2:
                continue
            
            # Get recent price change on this feed
            recent = list(history)[-5:]
            prev_price = recent[0][1]
            current_price = recent[-1][1]
            
            change_pct = (current_price - prev_price) / prev_price * 100
            
            # Check if direction matches
            if spike["direction"] == "up" and change_pct < 0:
                continue
            if spike["direction"] == "down" and change_pct > 0:
                continue
            
            # Check if magnitude is similar (within 50% of spike)
            spike_magnitude = abs(spike["change_pct"])
            feed_magnitude = abs(change_pct)
            
            if feed_magnitude >= spike_magnitude * 0.5:
                confirmations += 1
                
                if confirmations >= self.config.confirmation_feeds_required:
                    return True
        
        # Not enough confirmations - add to pending
        self._pending_confirmations.append({
            "symbol": symbol,
            "feed_id": spike_feed_id,
            "spike": spike,
            "timestamp": tick.timestamp,
            "confirmed": False,
        })
        
        return False
    
    def _create_anomaly(
        self,
        symbol: str,
        feed_id: str,
        tick: MarketTick,
        spike: dict[str, Any],
    ) -> FeedAnomaly:
        """Create anomaly for fake spike.
        
        Args:
            symbol: Trading symbol
            feed_id: Feed with fake spike
            tick: Current tick
            spike: Spike data
            
        Returns:
            FeedAnomaly
        """
        self._fake_spikes_detected += 1
        
        # Block the symbol temporarily
        self._blocked_symbols[symbol] = datetime.utcnow()
        
        logger.warning(
            "Fake spike detected",
            symbol=symbol,
            feed=feed_id,
            spike_pct=spike["change_pct"],
        )
        
        return FeedAnomaly(
            anomaly_id=f"fake_spike:{symbol}:{datetime.utcnow().timestamp()}",
            feed_id=feed_id,
            symbol=symbol,
            anomaly_type=AnomalyType.CROSS_FEED_MISMATCH,
            detected_at=datetime.utcnow(),
            severity=4,
            description=f"Unconfirmed price spike: {spike['change_pct']:.2f}% on {feed_id}",
            expected_value=spike["prev_price"],
            actual_value=spike["current_price"],
            raw_data={
                "spike_pct": spike["change_pct"],
                "direction": spike["direction"],
                "feeds_checked": len(self._price_history.get(symbol, {})),
            },
        )
    
    def _cleanup_pending(self) -> None:
        """Clean up old pending confirmations."""
        now = datetime.utcnow()
        timeout = timedelta(milliseconds=self.config.confirmation_timeout_ms)
        
        # Remove expired pending confirmations
        expired = [
            p for p in self._pending_confirmations
            if now - p["timestamp"] > timeout and not p["confirmed"]
        ]
        
        for p in expired:
            # These are now confirmed fake spikes
            logger.info(
                "Spike confirmation timeout - marking as fake",
                symbol=p["symbol"],
                feed=p["feed_id"],
            )
            self._fake_spikes_detected += 1
            self._blocked_symbols[p["symbol"]] = now
    
    def is_blocked(self, symbol: str) -> bool:
        """Check if symbol is temporarily blocked due to fake spike.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            True if blocked
        """
        if symbol not in self._blocked_symbols:
            return False
        
        # Check if block has expired (5 seconds)
        block_time = self._blocked_symbols[symbol]
        if datetime.utcnow() - block_time > timedelta(seconds=5):
            del self._blocked_symbols[symbol]
            return False
        
        return True
    
    def get_stats(self) -> dict[str, Any]:
        """Get filter statistics.
        
        Returns:
            Statistics dictionary
        """
        return {
            "fake_spikes_detected": self._fake_spikes_detected,
            "confirmed_spikes": self._confirmed_spikes,
            "blocked_symbols": list(self._blocked_symbols.keys()),
            "pending_confirmations": len(self._pending_confirmations),
            "symbols_monitored": len(self._price_history),
            "feeds_per_symbol": {
                sym: len(feeds) for sym, feeds in self._price_history.items()
            },
        }