"""Feed anomaly detection system.

Detects various types of anomalies in market data feeds including
price spikes, stale feeds, spread anomalies, and cross-feed mismatches.
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from src.core.logging_config import get_logger
from src.market_data.models.events import MarketTick, AnomalyType, FeedAnomaly

logger = get_logger("market_data")


@dataclass
class AnomalyThresholds:
    """Thresholds for anomaly detection."""
    
    # Price spike thresholds
    price_spike_pct: float = 2.0
    """Price change percentage to trigger spike alert."""
    
    price_spike_severity_thresholds: dict[int, float] = field(
        default_factory=lambda: {2: 2.0, 3: 5.0, 4: 10.0, 5: 20.0}
    )
    """Severity level -> min percentage for price spikes."""
    
    # Spread thresholds
    max_spread_pct: float = 0.5
    """Maximum normal spread as percentage."""
    
    spread_severity_thresholds: dict[int, float] = field(
        default_factory=lambda: {2: 0.5, 3: 1.0, 4: 2.0, 5: 5.0}
    )
    """Severity level -> min spread percentage."""
    
    # Stale feed thresholds
    stale_threshold_ms: float = 5000.0
    """Milliseconds without update to be considered stale."""
    
    stale_severity_thresholds: dict[int, float] = field(
        default_factory=lambda: {2: 5000, 3: 15000, 4: 30000, 5: 60000}
    )
    """Severity level -> min stale milliseconds."""
    
    # Volume thresholds
    volume_spike_factor: float = 10.0
    """Volume increase factor to trigger alert."""
    
    # Cross-feed thresholds
    cross_feed_deviation_pct: float = 0.1
    """Price deviation between feeds to trigger alert."""


@dataclass
class SymbolState:
    """State tracking for a symbol across multiple feeds."""
    
    symbol: str
    price_history: deque[MarketTick] = field(default_factory=lambda: deque(maxlen=100))
    volume_history: deque[int] = field(default_factory=lambda: deque(maxlen=20))
    last_update: datetime | None = None
    avg_volume: float = 0.0
    avg_spread_pct: float = 0.0
    
    def add_tick(self, tick: MarketTick) -> None:
        """Add tick to history."""
        self.price_history.append(tick)
        
        if tick.volume:
            self.volume_history.append(tick.volume)
            if len(self.volume_history) > 0:
                self.avg_volume = sum(self.volume_history) / len(self.volume_history)
        
        self.avg_spread_pct = tick.spread_pct
        self.last_update = tick.timestamp
    
    def get_recent_volatility(self, window: int = 20) -> float:
        """Calculate recent price volatility.
        
        Args:
            window: Number of ticks to use
            
        Returns:
            Standard deviation of price changes as percentage
        """
        if len(self.price_history) < 2:
            return 0.0
        
        prices = [t.last for t in list(self.price_history)[-window:]]
        if len(prices) < 2:
            return 0.0
        
        # Calculate price changes
        changes = []
        for i in range(1, len(prices)):
            pct_change = abs(prices[i] - prices[i-1]) / prices[i-1] * 100
            changes.append(pct_change)
        
        if not changes:
            return 0.0
        
        # Return standard deviation
        mean = sum(changes) / len(changes)
        variance = sum((x - mean) ** 2 for x in changes) / len(changes)
        return variance ** 0.5


class AnomalyDetector:
    """Detects anomalies in market data feeds.
    
    Monitors tick streams for various anomaly types and triggers
    alerts when thresholds are exceeded.
    
    Attributes:
        thresholds: Anomaly detection thresholds
        on_anomaly: Callback for detected anomalies
        _symbol_states: State tracking per symbol
        _anomaly_history: Recent anomalies
        _cross_feed_prices: Latest prices per feed
    """
    
    def __init__(
        self,
        thresholds: AnomalyThresholds | None = None,
        on_anomaly: Callable[[FeedAnomaly], None] | None = None,
        max_history: int = 1000,
    ):
        """Initialize anomaly detector.
        
        Args:
            thresholds: Detection thresholds
            on_anomaly: Callback for detected anomalies
            max_history: Maximum anomalies to keep in history
        """
        self.thresholds = thresholds or AnomalyThresholds()
        self.on_anomaly = on_anomaly
        self.max_history = max_history
        
        self._symbol_states: dict[str, SymbolState] = {}
        self._anomaly_history: deque[FeedAnomaly] = deque(maxlen=max_history)
        self._cross_feed_prices: dict[str, dict[str, float]] = {}
        
        logger.info("Anomaly detector initialized")
    
    def process_tick(self, tick: MarketTick) -> list[FeedAnomaly]:
        """Process a tick and detect anomalies.
        
        Args:
            tick: Tick to analyze
            
        Returns:
            List of detected anomalies
        """
        symbol = tick.symbol
        feed_id = tick.feed_source
        
        # Get or create symbol state
        state = self._symbol_states.get(symbol)
        if state is None:
            state = SymbolState(symbol=symbol)
            self._symbol_states[symbol] = state
        
        anomalies = []
        
        # Check for price spike
        if len(state.price_history) > 0:
            anomaly = self._check_price_spike(tick, state)
            if anomaly:
                anomalies.append(anomaly)
        
        # Check for spread anomaly
        anomaly = self._check_spread_anomaly(tick, state)
        if anomaly:
            anomalies.append(anomaly)
        
        # Check for stale feed
        anomaly = self._check_stale_feed(tick, state)
        if anomaly:
            anomalies.append(anomaly)
        
        # Check for volume anomaly
        if tick.volume:
            anomaly = self._check_volume_anomaly(tick, state)
            if anomaly:
                anomalies.append(anomaly)
        
        # Check for cross-feed mismatch
        anomaly = self._check_cross_feed_mismatch(tick)
        if anomaly:
            anomalies.append(anomaly)
        
        # Update state
        state.add_tick(tick)
        
        # Store price for cross-feed comparison
        if feed_id not in self._cross_feed_prices:
            self._cross_feed_prices[feed_id] = {}
        self._cross_feed_prices[feed_id][symbol] = tick.last
        
        # Record anomalies
        for anomaly in anomalies:
            self._record_anomaly(anomaly)
        
        return anomalies
    
    def _check_price_spike(self, tick: MarketTick, state: SymbolState) -> FeedAnomaly | None:
        """Check for price spike anomaly.
        
        Args:
            tick: Current tick
            state: Symbol state
            
        Returns:
            Anomaly if detected, None otherwise
        """
        if len(state.price_history) == 0:
            return None
        
        last_tick = state.price_history[-1]
        price_change_pct = abs(tick.last - last_tick.last) / last_tick.last * 100
        
        # Determine severity
        severity = 0
        for sev, threshold in sorted(self.thresholds.price_spike_severity_thresholds.items()):
            if price_change_pct >= threshold:
                severity = sev
        
        if severity > 0:
            # Check if it's anomalous compared to recent volatility
            volatility = state.get_recent_volatility()
            if volatility > 0 and price_change_pct > volatility * 5:
                severity = min(5, severity + 1)  # Increase severity
            
            return FeedAnomaly(
                anomaly_id=f"{tick.feed_source}:{tick.symbol}:{datetime.utcnow().timestamp()}",
                feed_id=tick.feed_source,
                symbol=tick.symbol,
                anomaly_type=AnomalyType.PRICE_SPIKE,
                detected_at=datetime.utcnow(),
                severity=severity,
                description=f"Price spike: {price_change_pct:.2f}% (volatility: {volatility:.2f}%)",
                expected_value=last_tick.last,
                actual_value=tick.last,
                raw_data={
                    "change_pct": price_change_pct,
                    "volatility": volatility,
                    "last_price": last_tick.last,
                    "current_price": tick.last,
                },
            )
        
        return None
    
    def _check_spread_anomaly(self, tick: MarketTick, state: SymbolState) -> FeedAnomaly | None:
        """Check for spread anomaly.
        
        Args:
            tick: Current tick
            state: Symbol state
            
        Returns:
            Anomaly if detected, None otherwise
        """
        spread_pct = tick.spread_pct
        
        # Determine severity
        severity = 0
        for sev, threshold in sorted(self.thresholds.spread_severity_thresholds.items()):
            if spread_pct >= threshold:
                severity = sev
        
        if severity > 0:
            return FeedAnomaly(
                anomaly_id=f"{tick.feed_source}:{tick.symbol}:{datetime.utcnow().timestamp()}",
                feed_id=tick.feed_source,
                symbol=tick.symbol,
                anomaly_type=AnomalyType.SPREAD_ANOMALY,
                detected_at=datetime.utcnow(),
                severity=severity,
                description=f"Abnormal spread: {spread_pct:.4f}%",
                expected_value=state.avg_spread_pct,
                actual_value=spread_pct,
                raw_data={
                    "spread_pct": spread_pct,
                    "bid": tick.bid,
                    "ask": tick.ask,
                    "avg_spread_pct": state.avg_spread_pct,
                },
            )
        
        return None
    
    def _check_stale_feed(self, tick: MarketTick, state: SymbolState) -> FeedAnomaly | None:
        """Check for stale feed.
        
        Args:
            tick: Current tick
            state: Symbol state
            
        Returns:
            Anomaly if detected, None otherwise
        """
        if state.last_update is None:
            return None
        
        stale_ms = (tick.timestamp - state.last_update).total_seconds() * 1000
        
        # Determine severity
        severity = 0
        for sev, threshold in sorted(self.thresholds.stale_severity_thresholds.items()):
            if stale_ms >= threshold:
                severity = sev
        
        if severity > 0:
            return FeedAnomaly(
                anomaly_id=f"{tick.feed_source}:{tick.symbol}:{datetime.utcnow().timestamp()}",
                feed_id=tick.feed_source,
                symbol=tick.symbol,
                anomaly_type=AnomalyType.STALE_FEED,
                detected_at=datetime.utcnow(),
                severity=severity,
                description=f"Stale feed: {stale_ms:.0f}ms since last update",
                expected_value=None,
                actual_value=stale_ms,
                raw_data={"stale_ms": stale_ms},
            )
        
        return None
    
    def _check_volume_anomaly(self, tick: MarketTick, state: SymbolState) -> FeedAnomaly | None:
        """Check for volume anomaly.
        
        Args:
            tick: Current tick
            state: Symbol state
            
        Returns:
            Anomaly if detected, None otherwise
        """
        if not tick.volume or state.avg_volume == 0:
            return None
        
        volume_increase = tick.volume / state.avg_volume
        
        if volume_increase > self.thresholds.volume_spike_factor:
            return FeedAnomaly(
                anomaly_id=f"{tick.feed_source}:{tick.symbol}:{datetime.utcnow().timestamp()}",
                feed_id=tick.feed_source,
                symbol=tick.symbol,
                anomaly_type=AnomalyType.VOLUME_ANOMALY,
                detected_at=datetime.utcnow(),
                severity=min(5, int(volume_increase / self.thresholds.volume_spike_factor) + 2),
                description=f"Volume spike: {volume_increase:.1f}x average",
                expected_value=state.avg_volume,
                actual_value=tick.volume,
                raw_data={
                    "volume": tick.volume,
                    "avg_volume": state.avg_volume,
                    "increase_factor": volume_increase,
                },
            )
        
        return None
    
    def _check_cross_feed_mismatch(self, tick: MarketTick) -> FeedAnomaly | None:
        """Check for cross-feed price mismatch.
        
        Args:
            tick: Current tick
            
        Returns:
            Anomaly if detected, None otherwise
        """
        symbol = tick.symbol
        current_feed = tick.feed_source
        current_price = tick.last
        
        # Compare with other feeds
        max_deviation = 0
        mismatched_feed = None
        mismatched_price = None
        
        for feed_id, prices in self._cross_feed_prices.items():
            if feed_id == current_feed:
                continue
            
            other_price = prices.get(symbol)
            if other_price is None:
                continue
            
            deviation_pct = abs(current_price - other_price) / other_price * 100
            
            if deviation_pct > max_deviation:
                max_deviation = deviation_pct
                mismatched_feed = feed_id
                mismatched_price = other_price
        
        if max_deviation > self.thresholds.cross_feed_deviation_pct:
            return FeedAnomaly(
                anomaly_id=f"{current_feed}:{symbol}:{datetime.utcnow().timestamp()}",
                feed_id=current_feed,
                symbol=symbol,
                anomaly_type=AnomalyType.CROSS_FEED_MISMATCH,
                detected_at=datetime.utcnow(),
                severity=min(5, int(max_deviation / self.thresholds.cross_feed_deviation_pct) + 1),
                description=f"Cross-feed mismatch: {max_deviation:.3f}% vs {mismatched_feed}",
                expected_value=mismatched_price,
                actual_value=current_price,
                raw_data={
                    "deviation_pct": max_deviation,
                    "other_feed": mismatched_feed,
                    "other_price": mismatched_price,
                    "this_price": current_price,
                },
            )
        
        return None
    
    def _record_anomaly(self, anomaly: FeedAnomaly) -> None:
        """Record a detected anomaly.
        
        Args:
            anomaly: Anomaly to record
        """
        self._anomaly_history.append(anomaly)
        
        logger.warning(
            "Anomaly detected",
            feed_id=anomaly.feed_id,
            symbol=anomaly.symbol,
            type=anomaly.anomaly_type.value,
            severity=anomaly.severity,
            description=anomaly.description,
        )
        
        if self.on_anomaly:
            try:
                self.on_anomaly(anomaly)
            except Exception as e:
                logger.error(
                    "Error in anomaly callback",
                    error=str(e),
                )
    
    def get_anomalies(
        self,
        symbol: str | None = None,
        feed_id: str | None = None,
        anomaly_type: AnomalyType | None = None,
        min_severity: int = 1,
        limit: int = 100,
    ) -> list[FeedAnomaly]:
        """Get filtered anomalies from history.
        
        Args:
            symbol: Optional symbol filter
            feed_id: Optional feed filter
            anomaly_type: Optional type filter
            min_severity: Minimum severity level
            limit: Maximum to return
            
        Returns:
            List of matching anomalies
        """
        anomalies = list(self._anomaly_history)
        
        if symbol:
            anomalies = [a for a in anomalies if a.symbol == symbol.upper()]
        if feed_id:
            anomalies = [a for a in anomalies if a.feed_id == feed_id]
        if anomaly_type:
            anomalies = [a for a in anomalies if a.anomaly_type == anomaly_type]
        
        anomalies = [a for a in anomalies if a.severity >= min_severity]
        
        return anomalies[-limit:] if anomalies else []
    
    def get_symbol_stats(self, symbol: str) -> dict[str, Any] | None:
        """Get statistics for a symbol.
        
        Args:
            symbol: Symbol to look up
            
        Returns:
            Statistics dictionary or None
        """
        state = self._symbol_states.get(symbol.upper())
        if not state:
            return None
        
        return {
            "symbol": symbol,
            "tick_count": len(state.price_history),
            "avg_volume": state.avg_volume,
            "avg_spread_pct": state.avg_spread_pct,
            "recent_volatility": state.get_recent_volatility(),
            "last_update": state.last_update.isoformat() if state.last_update else None,
        }
    
    def reset(self) -> None:
        """Reset detector state."""
        self._symbol_states.clear()
        self._anomaly_history.clear()
        self._cross_feed_prices.clear()
        logger.info("Anomaly detector reset")