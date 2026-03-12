"""Breakout detector for news and inventory events.

Detects when price breaks out of a consolidation range with momentum,
typically around news events like EIA inventory releases.
"""

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from src.core.logging_config import get_logger
from src.market_data.models.events import MarketTick, MarketBar
from src.strategy.models.signal import (
    Signal, SignalType, SignalScore, MarketRegime, SignalStatus
)

logger = get_logger("strategy")


@dataclass
class BreakoutConfig:
    """Configuration for breakout detection."""
    
    consolidation_periods: int = 10
    """Number of bars to identify consolidation."""
    
    consolidation_range_pct: float = 0.5
    """Maximum range percentage to be considered consolidation."""
    
    breakout_threshold_pct: float = 0.3
    """Minimum breakout move as percentage of range."""
    
    volume_confirmation: bool = True
    """Require volume confirmation."""
    
    volume_multiplier: float = 1.5
    """Minimum volume increase for confirmation."""
    
    acceptance_periods: int = 2
    """Number of periods price must hold beyond breakout."""
    
    momentum_lookback: int = 3
    """Periods to check for momentum."""
    
    max_spread_pct: float = 0.2
    """Maximum spread for valid breakout."""


class BreakoutDetector:
    """Detector for breakout continuation setups.
    
    Identifies consolidation periods and detects when price breaks out
    with momentum and volume confirmation. Designed for news-driven moves.
    
    Detection logic:
    1. Identify consolidation range (tight price action)
    2. Detect breakout beyond range with momentum
    3. Confirm with volume increase
    4. Wait for acceptance (hold beyond level)
    5. Generate continuation signal
    """
    
    def __init__(self, config: BreakoutConfig | None = None):
        """Initialize breakout detector.
        
        Args:
            config: Detection configuration
        """
        self.config = config or BreakoutConfig()
        
        # State tracking
        self._bars: dict[str, deque[MarketBar]] = {}
        self._consolidation_ranges: dict[str, dict[str, float]] = {}
        self._breakout_state: dict[str, dict[str, Any]] = {}
        self._volume_history: dict[str, deque[int]] = {}
        
        logger.info(
            "Breakout detector initialized",
            consolidation_periods=self.config.consolidation_periods,
            breakout_threshold=self.config.breakout_threshold_pct,
        )
    
    def on_bar(self, bar: MarketBar) -> Signal | None:
        """Process a new bar.
        
        Args:
            bar: Completed bar
            
        Returns:
            Signal if breakout confirmed, None otherwise
        """
        symbol = bar.symbol
        
        # Initialize storage
        if symbol not in self._bars:
            self._bars[symbol] = deque(maxlen=50)
            self._volume_history[symbol] = deque(maxlen=20)
        
        # Store bar and volume
        self._bars[symbol].append(bar)
        self._volume_history[symbol].append(bar.volume)
        
        # Need enough data
        if len(self._bars[symbol]) < self.config.consolidation_periods:
            return None
        
        # Check for active breakout monitoring
        if symbol in self._breakout_state:
            return self._check_breakout_acceptance(symbol, bar)
        
        # Look for consolidation and breakout
        consolidation = self._identify_consolidation(symbol)
        if consolidation:
            return self._check_breakout(symbol, bar, consolidation)
        
        return None
    
    def on_tick(self, tick: MarketTick) -> None:
        """Process tick for real-time breakout monitoring.
        
        Args:
            tick: Market tick
        """
        # Ticks used for fine-grained monitoring during breakout
        symbol = tick.symbol
        
        if symbol not in self._breakout_state:
            return
        
        state = self._breakout_state[symbol]
        
        # Update extreme prices during acceptance period
        if state["direction"] == "up":
            state["extreme_price"] = max(state["extreme_price"], tick.last)
        else:
            state["extreme_price"] = min(state["extreme_price"], tick.last)
    
    def _identify_consolidation(self, symbol: str) -> dict[str, float] | None:
        """Identify if price is in consolidation.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Consolidation range or None
        """
        bars = list(self._bars.get(symbol, []))[-self.config.consolidation_periods:]
        if len(bars) < self.config.consolidation_periods:
            return None
        
        # Calculate range
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        
        range_high = max(highs)
        range_low = min(lows)
        range_size = range_high - range_low
        range_pct = (range_size / range_low) * 100
        
        # Check if tight enough for consolidation
        if range_pct > self.config.consolidation_range_pct:
            return None
        
        # Store consolidation range
        consolidation = {
            "high": range_high,
            "low": range_low,
            "mid": (range_high + range_low) / 2,
            "size": range_size,
            "pct": range_pct,
        }
        
        self._consolidation_ranges[symbol] = consolidation
        
        return consolidation
    
    def _check_breakout(
        self,
        symbol: str,
        bar: MarketBar,
        consolidation: dict[str, float],
    ) -> Signal | None:
        """Check if bar represents a valid breakout.
        
        Args:
            symbol: Trading symbol
            bar: Current bar
            consolidation: Consolidation range
            
        Returns:
            Signal if valid breakout, None otherwise
        """
        range_size = consolidation["size"]
        threshold = range_size * (self.config.breakout_threshold_pct / 100)
        
        # Check upward breakout
        if bar.close > consolidation["high"] + threshold:
            direction = "up"
            breakout_price = bar.close
        # Check downward breakout
        elif bar.close < consolidation["low"] - threshold:
            direction = "down"
            breakout_price = bar.close
        else:
            return None
        
        # Volume confirmation
        if self.config.volume_confirmation:
            avg_volume = sum(self._volume_history[symbol]) / len(self._volume_history[symbol])
            if bar.volume < avg_volume * self.config.volume_multiplier:
                logger.debug(
                    "Breakout rejected - insufficient volume",
                    symbol=symbol,
                    volume=bar.volume,
                    avg_volume=avg_volume,
                )
                return None
        
        # Start monitoring for acceptance
        self._breakout_state[symbol] = {
            "direction": direction,
            "breakout_price": breakout_price,
            "consolidation": consolidation,
            "breakout_bar": bar,
            "periods_since": 0,
            "extreme_price": breakout_price,
            "confirmed": False,
        }
        
        logger.info(
            "Breakout detected, monitoring acceptance",
            symbol=symbol,
            direction=direction,
            price=breakout_price,
        )
        
        return None
    
    def _check_breakout_acceptance(
        self,
        symbol: str,
        bar: MarketBar,
    ) -> Signal | None:
        """Check if breakout has been accepted.
        
        Args:
            symbol: Trading symbol
            bar: Current bar
            
        Returns:
            Signal if accepted, None if still monitoring
        """
        state = self._breakout_state[symbol]
        state["periods_since"] += 1
        
        consolidation = state["consolidation"]
        direction = state["direction"]
        
        # Check if price held beyond breakout level
        if direction == "up":
            # Price should stay above consolidation high
            if bar.low < consolidation["high"]:
                # Failed - dropped back into range
                logger.info(
                    "Breakout failed - dropped back into range",
                    symbol=symbol,
                    low=bar.low,
                    consolidation_high=consolidation["high"],
                )
                del self._breakout_state[symbol]
                return None
        else:
            # Price should stay below consolidation low
            if bar.high > consolidation["low"]:
                # Failed
                logger.info(
                    "Breakout failed - rallied back into range",
                    symbol=symbol,
                    high=bar.high,
                    consolidation_low=consolidation["low"],
                )
                del self._breakout_state[symbol]
                return None
        
        # Check if we've waited enough periods
        if state["periods_since"] >= self.config.acceptance_periods:
            # Breakout accepted
            return self._generate_signal(symbol, state, bar)
        
        return None
    
    def _generate_signal(
        self,
        symbol: str,
        state: dict[str, Any],
        bar: MarketBar,
    ) -> Signal:
        """Generate breakout signal.
        
        Args:
            symbol: Trading symbol
            state: Breakout state
            bar: Confirming bar
            
        Returns:
            Trading signal
        """
        direction = state["direction"]
        consolidation = state["consolidation"]
        breakout_price = state["breakout_price"]
        
        # Calculate levels
        if direction == "up":
            entry = bar.close
            stop = consolidation["low"]  # Below consolidation
            tp1 = entry + (entry - stop) * 1.5
            tp2 = entry + (entry - stop) * 2.5
            signal_type = SignalType.BREAKOUT_LONG
            invalidation = consolidation["mid"]
            setup_desc = f"Upside breakout from {consolidation['pct']:.2f}% consolidation"
        else:
            entry = bar.close
            stop = consolidation["high"]  # Above consolidation
            tp1 = entry - (stop - entry) * 1.5
            tp2 = entry - (stop - entry) * 2.5
            signal_type = SignalType.BREAKOUT_SHORT
            invalidation = consolidation["mid"]
            setup_desc = f"Downside breakout from {consolidation['pct']:.2f}% consolidation"
        
        # Calculate scores
        momentum_score = self._calculate_momentum_score(symbol, direction)
        volume_score = self._calculate_volume_score(symbol, bar)
        
        score = SignalScore(
            sweep_quality=60,  # Not applicable but give moderate score
            reclaim_speed=50,
            volatility_regime=70,
            spread_quality=80,
            correlation_alignment=50,
            event_timing=85,  # Often around events
            feed_confirmation=80,
            liquidity_proximity=60,
            session_context=75,
            overall=0,
        )
        
        # Weighted overall
        overall = int(
            momentum_score * 0.25 +
            volume_score * 0.25 +
            score.volatility_regime * 0.15 +
            score.event_timing * 0.15 +
            score.spread_quality * 0.10 +
            score.feed_confirmation * 0.10
        )
        
        score = SignalScore(**{**score.to_dict(), "overall": overall})
        
        signal = Signal(
            signal_id=f"breakout:{symbol}:{datetime.utcnow().timestamp()}",
            symbol=symbol,
            signal_type=signal_type,
            direction="long" if direction == "up" else "short",
            trigger_price=breakout_price,
            entry_price=round(entry, 4),
            stop_loss=round(stop, 4),
            take_profit_levels=[round(tp1, 4), round(tp2, 4)],
            confidence=overall,
            score=score,
            setup_description=setup_desc,
            reason_codes=[
                "breakout_confirmed",
                f"consolidation_{consolidation['pct']:.2f}%",
                f"momentum_{momentum_score}",
                f"volume_{volume_score}",
            ],
            market_regime=MarketRegime.TRENDING_UP if direction == "up" else MarketRegime.TRENDING_DOWN,
            invalidation_price=invalidation,
            time_limit=datetime.utcnow() + timedelta(minutes=10),
            metadata={
                "consolidation_high": consolidation["high"],
                "consolidation_low": consolidation["low"],
                "consolidation_pct": consolidation["pct"],
                "breakout_price": breakout_price,
                "periods_to_acceptance": state["periods_since"],
            },
        )
        
        # Clean up state
        del self._breakout_state[symbol]
        
        logger.info(
            "Breakout signal generated",
            symbol=symbol,
            direction=direction,
            confidence=overall,
            entry=entry,
            stop=stop,
        )
        
        return signal
    
    def _calculate_momentum_score(self, symbol: str, direction: str) -> int:
        """Calculate momentum score.
        
        Args:
            symbol: Trading symbol
            direction: "up" or "down"
            
        Returns:
            Score 0-100
        """
        bars = list(self._bars.get(symbol, []))[-self.config.momentum_lookback:]
        if len(bars) < 2:
            return 50
        
        # Count consecutive bars in direction
        consecutive = 0
        for bar in reversed(bars):
            if direction == "up" and bar.close > bar.open:
                consecutive += 1
            elif direction == "down" and bar.close < bar.open:
                consecutive += 1
            else:
                break
        
        return min(100, consecutive * 30 + 40)
    
    def _calculate_volume_score(self, symbol: str, bar: MarketBar) -> int:
        """Calculate volume confirmation score.
        
        Args:
            symbol: Trading symbol
            bar: Current bar
            
        Returns:
            Score 0-100
        """
        volumes = list(self._volume_history.get(symbol, []))
        if len(volumes) < 5:
            return 50
        
        avg_volume = sum(volumes) / len(volumes)
        if avg_volume == 0:
            return 50
        
        ratio = bar.volume / avg_volume
        
        # Score based on volume multiplier
        if ratio >= 3.0:
            return 100
        elif ratio >= 2.0:
            return 85
        elif ratio >= 1.5:
            return 70
        elif ratio >= 1.2:
            return 55
        else:
            return 40
    
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
                "bar_count": len(self._bars.get(symbol, [])),
                "has_consolidation": symbol in self._consolidation_ranges,
                "monitoring_breakout": symbol in self._breakout_state,
            }
        
        return {
            "symbols_tracked": len(self._bars),
            "monitoring_breakouts": len(self._breakout_state),
        }