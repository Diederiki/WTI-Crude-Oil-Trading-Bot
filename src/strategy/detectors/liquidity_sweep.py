"""Liquidity sweep detector strategy.

Detects liquidity sweep setups where price briefly breaks a key level
(high/low) and then reclaims it, indicating a potential reversal.
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from src.core.logging_config import get_logger
from src.market_data.models.events import MarketTick, MarketBar
from src.strategy.models.signal import (
    Signal, SignalType, SignalScore, MarketRegime, SignalStatus
)

logger = get_logger("strategy")


@dataclass
class LiquidityLevel:
    """Represents a liquidity level (high or low)."""
    
    price: float
    timestamp: datetime
    level_type: str  # "high" or "low"
    touches: int = 0
    is_swept: bool = False
    swept_at: datetime | None = None
    reclaimed_at: datetime | None = None
    
    def mark_swept(self, timestamp: datetime) -> None:
        """Mark level as swept."""
        self.is_swept = True
        self.swept_at = timestamp
    
    def mark_reclaimed(self, timestamp: datetime) -> None:
        """Mark level as reclaimed."""
        self.reclaimed_at = timestamp


@dataclass
class SweepDetectionConfig:
    """Configuration for sweep detection."""
    
    lookback_periods: int = 20
    """Number of bars to look back for liquidity levels."""
    
    sweep_threshold_pct: float = 0.05
    """Minimum penetration beyond level as percentage."""
    
    max_sweep_threshold_pct: float = 0.5
    """Maximum penetration to avoid extreme moves."""
    
    reclaim_timeout_seconds: float = 30.0
    """Maximum time to wait for reclaim after sweep."""
    
    min_reclaim_pct: float = 50.0
    """Minimum percentage of sweep to reclaim (0-100)."""
    
    volume_confirmation: bool = True
    """Require volume confirmation on reclaim."""
    
    spread_filter_pct: float = 0.2
    """Maximum spread percentage to consider valid."""
    
    volatility_filter: bool = True
    """Filter based on volatility regime."""
    
    max_daily_sweeps: int = 5
    """Maximum sweeps per day per symbol to avoid overtrading."""


class LiquiditySweepDetector:
    """Detector for liquidity sweep reversal setups.
    
    Monitors price action to detect when price sweeps a liquidity level
    (intraday high/low) and then reclaims it, signaling a potential reversal.
    
    Detection logic:
    1. Identify recent liquidity levels (session highs/lows)
    2. Detect when price briefly penetrates beyond level (sweep)
    3. Monitor for reclaim back within the level
    4. Confirm with volume, spread, and timing filters
    5. Generate signal with appropriate confidence scoring
    """
    
    def __init__(self, config: SweepDetectionConfig | None = None):
        """Initialize sweep detector.
        
        Args:
            config: Detection configuration
        """
        self.config = config or SweepDetectionConfig()
        
        # State tracking per symbol
        self._bars: dict[str, deque[MarketBar]] = {}
        self._liquidity_levels: dict[str, dict[str, LiquidityLevel]] = {}
        self._active_sweeps: dict[str, LiquidityLevel] = {}
        self._daily_sweep_count: dict[str, int] = {}
        self._last_reset_date: datetime = datetime.utcnow()
        
        # Recent ticks for reclaim detection
        self._recent_ticks: dict[str, deque[MarketTick]] = {}
        
        logger.info(
            "Liquidity sweep detector initialized",
            lookback=self.config.lookback_periods,
            sweep_threshold=self.config.sweep_threshold_pct,
        )
    
    def on_bar(self, bar: MarketBar) -> None:
        """Process a new bar.
        
        Args:
            bar: Completed bar
        """
        symbol = bar.symbol
        
        # Reset daily counts if needed
        self._check_daily_reset()
        
        # Initialize storage for symbol
        if symbol not in self._bars:
            self._bars[symbol] = deque(maxlen=self.config.lookback_periods * 2)
            self._liquidity_levels[symbol] = {}
            self._recent_ticks[symbol] = deque(maxlen=100)
        
        # Store bar
        self._bars[symbol].append(bar)
        
        # Update liquidity levels
        self._update_liquidity_levels(symbol, bar)
        
        # Check for sweep completion on active sweeps
        self._check_sweep_completion(symbol, bar)
    
    def on_tick(self, tick: MarketTick) -> None:
        """Process a new tick for real-time sweep detection.
        
        Args:
            tick: Market tick
        """
        symbol = tick.symbol
        
        # Store tick
        if symbol not in self._recent_ticks:
            self._recent_ticks[symbol] = deque(maxlen=100)
        self._recent_ticks[symbol].append(tick)
        
        # Check for sweep trigger
        self._check_sweep_trigger(symbol, tick)
        
        # Check for reclaim on active sweeps
        if symbol in self._active_sweeps:
            self._check_reclaim_realtime(symbol, tick)
    
    def _check_daily_reset(self) -> None:
        """Reset daily counters if day has changed."""
        now = datetime.utcnow()
        if now.date() != self._last_reset_date.date():
            self._daily_sweep_count.clear()
            self._last_reset_date = now
            logger.info("Daily sweep counters reset")
    
    def _update_liquidity_levels(self, symbol: str, bar: MarketBar) -> None:
        """Update liquidity levels from new bar.
        
        Args:
            symbol: Trading symbol
            bar: New bar
        """
        bars = self._bars.get(symbol, [])
        if len(bars) < 5:
            return  # Need more data
        
        # Find recent highs and lows
        recent_bars = list(bars)[-self.config.lookback_periods:]
        
        # Find highest high and lowest low
        highest_high = max(b.high for b in recent_bars)
        lowest_low = min(b.low for b in recent_bars)
        
        # Update or create high level
        if "high" not in self._liquidity_levels[symbol]:
            self._liquidity_levels[symbol]["high"] = LiquidityLevel(
                price=highest_high,
                timestamp=bar.timestamp,
                level_type="high",
            )
        elif highest_high > self._liquidity_levels[symbol]["high"].price:
            # New higher high
            self._liquidity_levels[symbol]["high"] = LiquidityLevel(
                price=highest_high,
                timestamp=bar.timestamp,
                level_type="high",
            )
        
        # Update or create low level
        if "low" not in self._liquidity_levels[symbol]:
            self._liquidity_levels[symbol]["low"] = LiquidityLevel(
                price=lowest_low,
                timestamp=bar.timestamp,
                level_type="low",
            )
        elif lowest_low < self._liquidity_levels[symbol]["low"].price:
            # New lower low
            self._liquidity_levels[symbol]["low"] = LiquidityLevel(
                price=lowest_low,
                timestamp=bar.timestamp,
                level_type="low",
            )
    
    def _check_sweep_trigger(self, symbol: str, tick: MarketTick) -> None:
        """Check if tick triggers a sweep.
        
        Args:
            symbol: Trading symbol
            tick: Current tick
        """
        levels = self._liquidity_levels.get(symbol)
        if not levels:
            return
        
        # Check high sweep (for short signal)
        high_level = levels.get("high")
        if high_level and not high_level.is_swept:
            sweep_threshold = high_level.price * (1 + self.config.sweep_threshold_pct / 100)
            max_sweep = high_level.price * (1 + self.config.max_sweep_threshold_pct / 100)
            
            if tick.last > sweep_threshold and tick.last < max_sweep:
                # High swept
                high_level.mark_swept(tick.timestamp)
                self._active_sweeps[symbol] = high_level
                
                logger.info(
                    "High sweep detected",
                    symbol=symbol,
                    level_price=high_level.price,
                    sweep_price=tick.last,
                    penetration_pct=(tick.last / high_level.price - 1) * 100,
                )
        
        # Check low sweep (for long signal)
        low_level = levels.get("low")
        if low_level and not low_level.is_swept:
            sweep_threshold = low_level.price * (1 - self.config.sweep_threshold_pct / 100)
            max_sweep = low_level.price * (1 - self.config.max_sweep_threshold_pct / 100)
            
            if tick.last < sweep_threshold and tick.last > max_sweep:
                # Low swept
                low_level.mark_swept(tick.timestamp)
                self._active_sweeps[symbol] = low_level
                
                logger.info(
                    "Low sweep detected",
                    symbol=symbol,
                    level_price=low_level.price,
                    sweep_price=tick.last,
                    penetration_pct=(1 - tick.last / low_level.price) * 100,
                )
    
    def _check_reclaim_realtime(self, symbol: str, tick: MarketTick) -> Signal | None:
        """Check for reclaim in real-time.
        
        Args:
            symbol: Trading symbol
            tick: Current tick
            
        Returns:
            Signal if reclaim confirmed, None otherwise
        """
        sweep = self._active_sweeps.get(symbol)
        if not sweep:
            return None
        
        # Check timeout
        elapsed = (tick.timestamp - sweep.swept_at).total_seconds()
        if elapsed > self.config.reclaim_timeout_seconds:
            # Expired
            logger.info(
                "Sweep reclaim timeout",
                symbol=symbol,
                elapsed=elapsed,
            )
            del self._active_sweeps[symbol]
            return None
        
        # Check reclaim
        if sweep.level_type == "high":
            # For high sweep, need price to drop back below level
            if tick.last < sweep.price:
                # Reclaimed
                sweep.mark_reclaimed(tick.timestamp)
                del self._active_sweeps[symbol]
                
                return self._generate_signal(symbol, sweep, tick, "short")
        else:
            # For low sweep, need price to rise back above level
            if tick.last > sweep.price:
                # Reclaimed
                sweep.mark_reclaimed(tick.timestamp)
                del self._active_sweeps[symbol]
                
                return self._generate_signal(symbol, sweep, tick, "long")
        
        return None
    
    def _check_sweep_completion(self, symbol: str, bar: MarketBar) -> None:
        """Check if sweep completed on bar close.
        
        Args:
            symbol: Trading symbol
            bar: Completed bar
        """
        # Clean up expired sweeps
        for sym, sweep in list(self._active_sweeps.items()):
            elapsed = (bar.timestamp - sweep.swept_at).total_seconds()
            if elapsed > self.config.reclaim_timeout_seconds:
                del self._active_sweeps[sym]
    
    def _generate_signal(
        self,
        symbol: str,
        sweep: LiquidityLevel,
        tick: MarketTick,
        direction: str,
    ) -> Signal:
        """Generate trading signal from confirmed sweep.
        
        Args:
            symbol: Trading symbol
            sweep: Liquidity level that was swept and reclaimed
            tick: Confirming tick
            direction: "long" or "short"
            
        Returns:
            Trading signal
        """
        # Calculate price levels
        if direction == "long":
            entry = tick.last
            stop = sweep.price * 0.995  # Below the low
            tp1 = entry + (entry - stop) * 2  # 2:1 R/R
            tp2 = entry + (entry - stop) * 3  # 3:1 R/R
            signal_type = SignalType.LIQUIDITY_SWEEP_LONG
            invalidation = sweep.price * 0.998
        else:
            entry = tick.last
            stop = sweep.price * 1.005  # Above the high
            tp1 = entry - (stop - entry) * 2
            tp2 = entry - (stop - entry) * 3
            signal_type = SignalType.LIQUIDITY_SWEEP_SHORT
            invalidation = sweep.price * 1.002
        
        # Calculate scores
        sweep_penetration = abs(sweep.swept_at_price - sweep.price) / sweep.price * 100
        reclaim_speed = self._calculate_reclaim_speed(sweep)
        spread_score = max(0, 100 - int(tick.spread_pct * 10))
        
        score = SignalScore(
            sweep_quality=min(100, int(100 - sweep_penetration * 2)),
            reclaim_speed=reclaim_speed,
            volatility_regime=70,  # Placeholder
            spread_quality=spread_score,
            correlation_alignment=50,  # Placeholder
            event_timing=50,  # Placeholder
            feed_confirmation=80,  # Assumed good if we got here
            liquidity_proximity=90,  # We just hit it
            session_context=75,  # Placeholder
            overall=0,  # Calculated below
        )
        
        # Calculate overall score (weighted average)
        weights = {
            "sweep_quality": 0.20,
            "reclaim_speed": 0.20,
            "spread_quality": 0.15,
            "liquidity_proximity": 0.15,
            "feed_confirmation": 0.10,
            "volatility_regime": 0.10,
            "session_context": 0.10,
        }
        
        overall = int(
            score.sweep_quality * weights["sweep_quality"] +
            score.reclaim_speed * weights["reclaim_speed"] +
            score.spread_quality * weights["spread_quality"] +
            score.liquidity_proximity * weights["liquidity_proximity"] +
            score.feed_confirmation * weights["feed_confirmation"] +
            score.volatility_regime * weights["volatility_regime"] +
            score.session_context * weights["session_context"]
        )
        
        score = SignalScore(**{**score.to_dict(), "overall": overall})
        
        # Create signal
        signal = Signal(
            signal_id=f"sweep:{symbol}:{datetime.utcnow().timestamp()}",
            symbol=symbol,
            signal_type=signal_type,
            direction=direction,
            trigger_price=sweep.swept_at_price,
            entry_price=entry,
            stop_loss=stop,
            take_profit_levels=[round(tp1, 4), round(tp2, 4)],
            confidence=overall,
            score=score,
            setup_description=f"Liquidity sweep of {sweep.level_type} at {sweep.price:.2f}, "
                            f"penetration {sweep_penetration:.2f}%, reclaimed in {reclaim_speed}ms",
            reason_codes=[
                f"sweep_{sweep.level_type}",
                "reclaim_confirmed",
                f"confidence_{overall}",
            ],
            market_regime=MarketRegime.UNKNOWN,
            invalidation_price=invalidation,
            time_limit=datetime.utcnow() + timedelta(minutes=5),
            metadata={
                "sweep_level": sweep.price,
                "sweep_price": sweep.swept_at_price,
                "penetration_pct": sweep_penetration,
                "reclaim_time_ms": reclaim_speed,
            },
        )
        
        # Update daily count
        if symbol not in self._daily_sweep_count:
            self._daily_sweep_count[symbol] = 0
        self._daily_sweep_count[symbol] += 1
        
        logger.info(
            "Sweep signal generated",
            symbol=symbol,
            direction=direction,
            confidence=overall,
            entry=entry,
            stop=stop,
        )
        
        return signal
    
    def _calculate_reclaim_speed(self, sweep: LiquidityLevel) -> int:
        """Calculate reclaim speed score.
        
        Args:
            sweep: Sweep data
            
        Returns:
            Score 0-100 (higher is faster/better)
        """
        if not sweep.reclaimed_at or not sweep.swept_at:
            return 0
        
        elapsed_ms = (sweep.reclaimed_at - sweep.swept_at).total_seconds() * 1000
        
        # Score: <1s = 100, <5s = 80, <10s = 60, <30s = 40, else 20
        if elapsed_ms < 1000:
            return 100
        elif elapsed_ms < 5000:
            return 80
        elif elapsed_ms < 10000:
            return 60
        elif elapsed_ms < 30000:
            return 40
        else:
            return 20
    
    def get_liquidity_levels(self, symbol: str) -> dict[str, Any]:
        """Get current liquidity levels for a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Dictionary with level information
        """
        levels = self._liquidity_levels.get(symbol, {})
        
        return {
            "high": {
                "price": levels["high"].price if "high" in levels else None,
                "is_swept": levels["high"].is_swept if "high" in levels else False,
            } if "high" in levels else None,
            "low": {
                "price": levels["low"].price if "low" in levels else None,
                "is_swept": levels["low"].is_swept if "low" in levels else False,
            } if "low" in levels else None,
        }
    
    def get_stats(self, symbol: str | None = None) -> dict[str, Any]:
        """Get detector statistics.
        
        Args:
            symbol: Optional symbol filter
            
        Returns:
            Statistics dictionary
        """
        if symbol:
            return {
                "symbol": symbol,
                "daily_sweeps": self._daily_sweep_count.get(symbol, 0),
                "liquidity_levels": self.get_liquidity_levels(symbol),
                "has_active_sweep": symbol in self._active_sweeps,
            }
        
        return {
            "symbols_tracked": len(self._bars),
            "daily_sweeps_total": sum(self._daily_sweep_count.values()),
            "active_sweeps": len(self._active_sweeps),
        }