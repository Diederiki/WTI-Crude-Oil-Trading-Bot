"""Strategy engine for coordinating signal generation.

Orchestrates multiple detectors, manages signal lifecycle, and provides
unified signal generation with risk and validation filters.
"""

import asyncio
from collections import deque
from datetime import datetime, timedelta
from typing import Any, Callable

from src.core.logging_config import get_logger
from src.event_bus import EventBus, Event, EventType
from src.market_data.models.events import MarketTick, MarketBar
from src.strategy.models.signal import Signal, SignalStatus
from src.strategy.detectors.liquidity_sweep import LiquiditySweepDetector, SweepDetectionConfig
from src.strategy.detectors.breakout import BreakoutDetector, BreakoutConfig
from src.strategy.detectors.correlation import CorrelationDetector, CorrelationConfig
from src.strategy.detectors.fake_spike_filter import FakeSpikeFilter, FakeSpikeConfig

logger = get_logger("strategy")


class StrategyEngine:
    """Main strategy engine coordinating all detectors.
    
    The StrategyEngine manages multiple signal detectors, filters signals
    through risk and validation checks, and maintains signal lifecycle.
    
    Attributes:
        event_bus: Event bus for publishing signals
        detectors: Dictionary of active detectors
        fake_spike_filter: Filter for anomalous price spikes
        signals: Active and historical signals
        signal_callbacks: Callbacks for new signals
        config: Engine configuration
        _running: Whether engine is running
    """
    
    def __init__(
        self,
        event_bus: EventBus | None = None,
        config: dict[str, Any] | None = None,
    ):
        """Initialize strategy engine.
        
        Args:
            event_bus: Optional event bus for signal publishing
            config: Engine configuration
        """
        self.event_bus = event_bus
        self.config = config or {}
        
        # Initialize detectors
        self.detectors = {
            "liquidity_sweep": LiquiditySweepDetector(
                config=SweepDetectionConfig(
                    lookback_periods=self.config.get("sweep_lookback", 20),
                    sweep_threshold_pct=self.config.get("sweep_threshold", 0.05),
                    reclaim_timeout_seconds=self.config.get("reclaim_timeout", 30.0),
                )
            ),
            "breakout": BreakoutDetector(
                config=BreakoutConfig(
                    consolidation_periods=self.config.get("consolidation_periods", 10),
                    breakout_threshold_pct=self.config.get("breakout_threshold", 0.3),
                )
            ),
            "correlation": CorrelationDetector(
                config=CorrelationConfig(
                    lookback_periods=self.config.get("correlation_lookback", 20),
                    move_threshold_pct=self.config.get("correlation_move_threshold", 0.3),
                )
            ),
        }
        
        # Fake spike filter
        self.fake_spike_filter = FakeSpikeFilter(
            config=FakeSpikeConfig(
                confirmation_timeout_ms=self.config.get("spike_confirmation_ms", 500),
                spike_threshold_pct=self.config.get("spike_threshold", 0.5),
            )
        )
        
        # Signal tracking
        self._signals: dict[str, Signal] = {}
        self._signal_history: deque[Signal] = deque(maxlen=1000)
        self._signal_callbacks: list[Callable[[Signal], None]] = []
        
        # Statistics
        self._stats = {
            "ticks_processed": 0,
            "bars_processed": 0,
            "signals_generated": 0,
            "signals_blocked": 0,
        }
        
        self._running = False
        
        logger.info(
            "Strategy engine initialized",
            detectors=list(self.detectors.keys()),
        )
    
    def on_signal(self, callback: Callable[[Signal], None]) -> None:
        """Register callback for new signals.
        
        Args:
            callback: Function to call when signal is generated
        """
        self._signal_callbacks.append(callback)
        logger.debug(
            "Signal callback registered",
            callback=callback.__name__ if hasattr(callback, "__name__") else "anonymous",
        )
    
    def on_tick(self, tick: MarketTick) -> Signal | None:
        """Process tick through all detectors.
        
        Args:
            tick: Market tick
            
        Returns:
            Signal if generated, None otherwise
        """
        if not self._running:
            return None
        
        self._stats["ticks_processed"] += 1
        
        # Check fake spike filter first
        anomaly = self.fake_spike_filter.on_tick(tick)
        if anomaly:
            # Publish anomaly event
            if self.event_bus:
                asyncio.create_task(self.event_bus.publish(Event.create(
                    event_type=EventType.ANOMALY_DETECTED,
                    source="strategy_engine",
                    payload=anomaly.to_dict(),
                )))
        
        # Check if symbol is blocked due to fake spike
        if self.fake_spike_filter.is_blocked(tick.symbol):
            logger.debug("Symbol blocked due to fake spike", symbol=tick.symbol)
            return None
        
        # Route to appropriate detectors
        signal = None
        
        # Liquidity sweep detector
        sweep_detector = self.detectors["liquidity_sweep"]
        sweep_detector.on_tick(tick)
        
        # Correlation detector
        corr_detector = self.detectors["correlation"]
        signal = corr_detector.on_tick(tick)
        
        if signal:
            return self._process_signal(signal)
        
        return None
    
    def on_bar(self, bar: MarketBar) -> Signal | None:
        """Process bar through all detectors.
        
        Args:
            bar: Completed bar
            
        Returns:
            Signal if generated, None otherwise
        """
        if not self._running:
            return None
        
        self._stats["bars_processed"] += 1
        
        signal = None
        
        # Liquidity sweep detector
        sweep_detector = self.detectors["liquidity_sweep"]
        sweep_detector.on_bar(bar)
        
        # Breakout detector
        breakout_detector = self.detectors["breakout"]
        signal = breakout_detector.on_bar(bar)
        
        if signal:
            return self._process_signal(signal)
        
        return None
    
    def _process_signal(self, signal: Signal) -> Signal | None:
        """Process and validate a generated signal.
        
        Args:
            signal: Generated signal
            
        Returns:
            Validated signal or None if rejected
        """
        # Check minimum confidence
        min_confidence = self.config.get("min_confidence", 60)
        if signal.confidence < min_confidence:
            logger.debug(
                "Signal rejected - low confidence",
                signal_id=signal.signal_id,
                confidence=signal.confidence,
                min_required=min_confidence,
            )
            self._stats["signals_blocked"] += 1
            return None
        
        # Check for duplicate signals
        if signal.signal_id in self._signals:
            logger.debug("Signal rejected - duplicate", signal_id=signal.signal_id)
            return None
        
        # Store signal
        signal.update_status(SignalStatus.ACTIVE)
        self._signals[signal.signal_id] = signal
        self._signal_history.append(signal)
        self._stats["signals_generated"] += 1
        
        logger.info(
            "Signal generated and validated",
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            type=signal.signal_type.value,
            confidence=signal.confidence,
        )
        
        # Notify callbacks
        for callback in self._signal_callbacks:
            try:
                callback(signal)
            except Exception as e:
                logger.error(
                    "Error in signal callback",
                    error=str(e),
                )
        
        # Publish event
        if self.event_bus:
            asyncio.create_task(self.event_bus.publish(Event.create(
                event_type=EventType.SIGNAL_GENERATED,
                source="strategy_engine",
                payload=signal.to_dict(),
            )))
        
        return signal
    
    def update_signal_status(
        self,
        signal_id: str,
        status: SignalStatus,
        metadata: dict[str, Any] | None = None,
    ) -> Signal | None:
        """Update signal status.
        
        Args:
            signal_id: Signal identifier
            status: New status
            metadata: Optional metadata to update
            
        Returns:
            Updated signal or None
        """
        signal = self._signals.get(signal_id)
        if not signal:
            return None
        
        signal.update_status(status)
        
        if metadata:
            signal.metadata.update(metadata)
        
        # Publish update
        if self.event_bus:
            asyncio.create_task(self.event_bus.publish(Event.create(
                event_type=EventType.SIGNAL_UPDATED,
                source="strategy_engine",
                payload={
                    "signal_id": signal_id,
                    "status": status.value,
                    "metadata": metadata,
                },
            )))
        
        return signal
    
    def get_signal(self, signal_id: str) -> Signal | None:
        """Get signal by ID.
        
        Args:
            signal_id: Signal identifier
            
        Returns:
            Signal or None
        """
        return self._signals.get(signal_id)
    
    def get_active_signals(
        self,
        symbol: str | None = None,
        direction: str | None = None,
    ) -> list[Signal]:
        """Get active signals with optional filtering.
        
        Args:
            symbol: Optional symbol filter
            direction: Optional direction filter
            
        Returns:
            List of active signals
        """
        signals = [
            s for s in self._signals.values()
            if s.is_active
        ]
        
        if symbol:
            signals = [s for s in signals if s.symbol == symbol.upper()]
        
        if direction:
            signals = [s for s in signals if s.direction == direction]
        
        return signals
    
    def get_signal_history(
        self,
        symbol: str | None = None,
        limit: int = 100,
    ) -> list[Signal]:
        """Get signal history.
        
        Args:
            symbol: Optional symbol filter
            limit: Maximum number to return
            
        Returns:
            List of historical signals
        """
        signals = list(self._signal_history)
        
        if symbol:
            signals = [s for s in signals if s.symbol == symbol.upper()]
        
        return signals[-limit:]
    
    def get_stats(self) -> dict[str, Any]:
        """Get engine statistics.
        
        Returns:
            Statistics dictionary
        """
        return {
            **self._stats,
            "active_signals": len([s for s in self._signals.values() if s.is_active]),
            "total_signals": len(self._signals),
            "detectors": {
                name: detector.get_stats() if hasattr(detector, "get_stats") else {}
                for name, detector in self.detectors.items()
            },
            "fake_spike_filter": self.fake_spike_filter.get_stats(),
        }
    
    def start(self) -> None:
        """Start the strategy engine."""
        self._running = True
        logger.info("Strategy engine started")
    
    def stop(self) -> None:
        """Stop the strategy engine."""
        self._running = False
        logger.info("Strategy engine stopped")
    
    def is_running(self) -> bool:
        """Check if engine is running.
        
        Returns:
            True if running
        """
        return self._running