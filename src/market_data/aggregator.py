"""Tick aggregation engine for creating OHLCV bars.

Aggregates high-frequency tick data into bar/candlestick data at
configurable intervals with VWAP and other metrics.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable

from src.core.logging_config import get_logger
from src.market_data.models.events import MarketTick, MarketBar

logger = get_logger("market_data")


@dataclass
class BarBuilder:
    """Builder for constructing bars from ticks.
    
    Maintains state for bar construction including OHLC values,
    volume, and VWAP calculations.
    """
    
    symbol: str
    interval_seconds: int
    open_time: datetime
    
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: int = 0
    trades: int = 0
    vwap_numerator: float = 0.0
    bid_open: float = 0.0
    ask_open: float = 0.0
    bid_close: float = 0.0
    ask_close: float = 0.0
    
    def add_tick(self, tick: MarketTick) -> None:
        """Add a tick to the bar.
        
        Args:
            tick: Tick to add
        """
        price = tick.last
        size = tick.last_size or 0
        
        if self.trades == 0:
            # First tick initializes the bar
            self.open = price
            self.high = price
            self.low = price
            self.bid_open = tick.bid
            self.ask_open = tick.ask
        
        # Update OHLC
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.close = price
        self.bid_close = tick.bid
        self.ask_close = tick.ask
        
        # Update volume
        self.volume += size
        self.trades += 1
        
        # Update VWAP
        self.vwap_numerator += price * size
    
    def build(self) -> MarketBar:
        """Build the bar.
        
        Returns:
            Completed MarketBar
        """
        vwap = None
        if self.volume > 0:
            vwap = self.vwap_numerator / self.volume
        
        return MarketBar(
            symbol=self.symbol,
            timestamp=self.open_time,
            interval_seconds=self.interval_seconds,
            open=round(self.open, 4),
            high=round(self.high, 4),
            low=round(self.low, 4),
            close=round(self.close, 4),
            volume=self.volume,
            vwap=round(vwap, 4) if vwap else None,
            trades=self.trades,
            bid_open=round(self.bid_open, 4) if self.bid_open else None,
            ask_open=round(self.ask_open, 4) if self.ask_open else None,
            bid_close=round(self.bid_close, 4) if self.bid_close else None,
            ask_close=round(self.ask_close, 4) if self.ask_close else None,
        )
    
    def is_complete(self, current_time: datetime) -> bool:
        """Check if bar interval is complete.
        
        Args:
            current_time: Current time to check against
            
        Returns:
            True if bar interval has elapsed
        """
        elapsed = (current_time - self.open_time).total_seconds()
        return elapsed >= self.interval_seconds


class TickAggregator:
    """Aggregates ticks into bars at configurable intervals.
    
    Supports multiple symbols and intervals simultaneously with
    automatic bar completion and emission.
    
    Attributes:
        intervals: List of bar intervals in seconds
        bar_callbacks: Callbacks for completed bars
        _builders: Active bar builders per (symbol, interval)
        _running: Whether aggregator is running
    """
    
    # Common intervals
    INTERVAL_1S = 1
    INTERVAL_5S = 5
    INTERVAL_10S = 10
    INTERVAL_15S = 15
    INTERVAL_30S = 30
    INTERVAL_1M = 60
    INTERVAL_5M = 300
    INTERVAL_15M = 900
    INTERVAL_30M = 1800
    INTERVAL_1H = 3600
    INTERVAL_4H = 14400
    INTERVAL_1D = 86400
    
    def __init__(
        self,
        intervals: list[int] | None = None,
    ):
        """Initialize tick aggregator.
        
        Args:
            intervals: List of bar intervals in seconds (default: [60])
        """
        self.intervals = intervals or [self.INTERVAL_1M]
        self.bar_callbacks: list[Callable[[MarketBar], None]] = []
        
        self._builders: dict[tuple[str, int], BarBuilder] = {}
        self._running = False
        
        logger.info(
            "Tick aggregator initialized",
            intervals=self.intervals,
        )
    
    def on_bar(self, callback: Callable[[MarketBar], None]) -> None:
        """Register a callback for completed bars.
        
        Args:
            callback: Function to call when bar is completed
        """
        self.bar_callbacks.append(callback)
        logger.debug(
            "Bar callback registered",
            callback=callback.__name__ if hasattr(callback, "__name__") else "anonymous",
        )
    
    def process_tick(self, tick: MarketTick) -> list[MarketBar]:
        """Process a tick and return any completed bars.
        
        Args:
            tick: Tick to process
            
        Returns:
            List of completed bars
        """
        symbol = tick.symbol
        now = tick.timestamp
        completed_bars = []
        
        for interval in self.intervals:
            key = (symbol, interval)
            builder = self._builders.get(key)
            
            # Check if we need a new builder
            if builder is None or builder.is_complete(now):
                # Complete existing bar if present
                if builder is not None and builder.trades > 0:
                    bar = builder.build()
                    completed_bars.append(bar)
                    self._emit_bar(bar)
                
                # Create new builder aligned to interval
                aligned_time = self._align_time(now, interval)
                builder = BarBuilder(
                    symbol=symbol,
                    interval_seconds=interval,
                    open_time=aligned_time,
                )
                self._builders[key] = builder
            
            # Add tick to builder
            builder.add_tick(tick)
        
        return completed_bars
    
    def _align_time(self, dt: datetime, interval_seconds: int) -> datetime:
        """Align datetime to interval boundary.
        
        Args:
            dt: Datetime to align
            interval_seconds: Interval in seconds
            
        Returns:
            Aligned datetime
        """
        timestamp = dt.timestamp()
        aligned_timestamp = (timestamp // interval_seconds) * interval_seconds
        return datetime.utcfromtimestamp(aligned_timestamp)
    
    def _emit_bar(self, bar: MarketBar) -> None:
        """Emit bar to all registered callbacks.
        
        Args:
            bar: Bar to emit
        """
        for callback in self.bar_callbacks:
            try:
                callback(bar)
            except Exception as e:
                logger.error(
                    "Error in bar callback",
                    error=str(e),
                    callback=callback.__name__ if hasattr(callback, "__name__") else "anonymous",
                )
    
    def force_complete_all(self) -> list[MarketBar]:
        """Force complete all active bars.
        
        Returns:
            List of all completed bars
        """
        completed = []
        now = datetime.utcnow()
        
        for key, builder in list(self._builders.items()):
            if builder.trades > 0:
                bar = builder.build()
                completed.append(bar)
                self._emit_bar(bar)
            
            # Reset builder
            symbol, interval = key
            self._builders[key] = BarBuilder(
                symbol=symbol,
                interval_seconds=interval,
                open_time=self._align_time(now, interval),
            )
        
        logger.info(
            "Force completed all bars",
            bar_count=len(completed),
        )
        
        return completed
    
    def get_active_bar(self, symbol: str, interval: int) -> BarBuilder | None:
        """Get the active bar builder for a symbol/interval.
        
        Args:
            symbol: Symbol to look up
            interval: Interval in seconds
            
        Returns:
            Active BarBuilder or None
        """
        return self._builders.get((symbol.upper(), interval))
    
    def get_active_bars_summary(self) -> dict[str, dict[str, Any]]:
        """Get summary of all active bars.
        
        Returns:
            Dictionary of active bar summaries
        """
        summary = {}
        
        for (symbol, interval), builder in self._builders.items():
            if builder.trades > 0:
                key = f"{symbol}:{interval}s"
                summary[key] = {
                    "symbol": symbol,
                    "interval": interval,
                    "open_time": builder.open_time.isoformat(),
                    "open": builder.open,
                    "high": builder.high,
                    "low": builder.low,
                    "close": builder.close,
                    "volume": builder.volume,
                    "trades": builder.trades,
                }
        
        return summary
    
    def reset(self) -> None:
        """Reset all active bars."""
        self._builders.clear()
        logger.info("Tick aggregator reset")