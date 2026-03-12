"""Correlation detector for cross-market analysis.

Monitors correlated markets (DXY, Brent, ES, etc.) and detects
when WTI shows lagged or aligned response to moves in other markets.
"""

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from src.core.logging_config import get_logger
from src.market_data.models.events import MarketTick
from src.strategy.models.signal import (
    Signal, SignalType, SignalScore, MarketRegime
)

logger = get_logger("strategy")


@dataclass
class CorrelationConfig:
    """Configuration for correlation detection."""
    
    lookback_periods: int = 20
    """Periods for correlation calculation."""
    
    move_threshold_pct: float = 0.3
    """Minimum move in correlated market to trigger analysis."""
    
    wti_response_threshold_pct: float = 0.1
    """Minimum WTI response to consider correlated."""
    
    max_lag_seconds: float = 60.0
    """Maximum time lag for WTI response."""
    
    correlation_threshold: float = 0.6
    """Minimum correlation coefficient for alignment."""
    
    # Market weights for composite index
    dxy_weight: float = -0.4
    """DXY correlation weight (negative - inverse)."""
    
    brent_weight: float = 0.8
    """Brent correlation weight (positive)."""
    
    es_weight: float = 0.3
    """S&P 500 correlation weight."""
    
    gold_weight: float = 0.1
    """Gold correlation weight."""


class CorrelationDetector:
    """Detector for correlation-based signals.
    
    Monitors moves in correlated markets and detects when WTI shows
    aligned or lagged response, indicating potential continuation or
    reversal opportunities.
    
    Detection logic:
    1. Track price changes in correlated markets (DXY, Brent, ES, etc.)
    2. Detect significant moves in correlated markets
    3. Monitor WTI for response (aligned or lagged)
    4. Calculate correlation score
    5. Generate signal if correlation threshold met
    """
    
    # Symbol mappings
    CORRELATED_SYMBOLS = {
        "DX-Y.NYB": "dxy",
        "BZ=F": "brent",
        "ES=F": "es",
        "NQ=F": "nq",
        "GC=F": "gold",
        "ZN=F": "ten_year",
    }
    
    def __init__(self, config: CorrelationConfig | None = None):
        """Initialize correlation detector.
        
        Args:
            config: Detection configuration
        """
        self.config = config or CorrelationConfig()
        
        # Price history per symbol
        self._price_history: dict[str, deque[tuple[datetime, float]]] = {}
        
        # Recent moves in correlated markets
        self._recent_moves: deque[dict[str, Any]] = deque(maxlen=100)
        
        # WTI reference
        self._wti_symbol = "CL=F"
        
        # Active opportunities
        self._active_opportunities: dict[str, dict[str, Any]] = {}
        
        logger.info(
            "Correlation detector initialized",
            lookback=self.config.lookback_periods,
            threshold=self.config.move_threshold_pct,
        )
    
    def on_tick(self, tick: MarketTick) -> Signal | None:
        """Process a tick for correlation analysis.
        
        Args:
            tick: Market tick
            
        Returns:
            Signal if opportunity detected, None otherwise
        """
        symbol = tick.symbol
        
        # Store price
        if symbol not in self._price_history:
            self._price_history[symbol] = deque(maxlen=self.config.lookback_periods * 2)
        
        self._price_history[symbol].append((tick.timestamp, tick.last))
        
        # Check if correlated market moved
        if symbol in self.CORRELATED_SYMBOLS:
            return self._check_correlated_move(symbol, tick)
        
        # Check WTI response to active opportunities
        if symbol == self._wti_symbol:
            return self._check_wti_response(tick)
        
        return None
    
    def _check_correlated_move(self, symbol: str, tick: MarketTick) -> None:
        """Check if correlated market made a significant move.
        
        Args:
            symbol: Correlated market symbol
            tick: Current tick
        """
        history = self._price_history.get(symbol, [])
        if len(history) < 5:
            return
        
        # Calculate recent change
        recent_prices = [p for _, p in list(history)[-10:]]
        if len(recent_prices) < 2:
            return
        
        price_change_pct = (recent_prices[-1] - recent_prices[0]) / recent_prices[0] * 100
        
        # Check if move is significant
        if abs(price_change_pct) < self.config.move_threshold_pct:
            return
        
        # Record the move
        move = {
            "symbol": symbol,
            "market": self.CORRELATED_SYMBOLS[symbol],
            "timestamp": tick.timestamp,
            "price_change_pct": price_change_pct,
            "start_price": recent_prices[0],
            "current_price": recent_prices[-1],
            "wti_response_checked": False,
        }
        
        self._recent_moves.append(move)
        
        logger.info(
            "Correlated market move detected",
            symbol=symbol,
            change_pct=price_change_pct,
            market=self.CORRELATED_SYMBOLS[symbol],
        )
    
    def _check_wti_response(self, tick: MarketTick) -> Signal | None:
        """Check if WTI has responded to recent correlated moves.
        
        Args:
            tick: WTI tick
            
        Returns:
            Signal if response detected, None otherwise
        """
        wti_history = self._price_history.get(self._wti_symbol, [])
        if len(wti_history) < 5:
            return None
        
        # Check recent moves for WTI response
        for move in self._recent_moves:
            if move["wti_response_checked"]:
                continue
            
            # Check time lag
            lag = (tick.timestamp - move["timestamp"]).total_seconds()
            if lag > self.config.max_lag_seconds:
                move["wti_response_checked"] = True
                continue
            
            # Calculate expected WTI move based on correlation
            expected_move = self._calculate_expected_wti_move(move)
            
            if expected_move is None:
                continue
            
            # Calculate actual WTI move since correlated move
            wti_prices = [p for _, p in list(wti_history)]
            wti_change_pct = (wti_prices[-1] - wti_prices[0]) / wti_prices[0] * 100
            
            # Check if WTI responded
            if abs(wti_change_pct) < self.config.wti_response_threshold_pct:
                continue
            
            # Check alignment
            aligned = (expected_move > 0 and wti_change_pct > 0) or \
                     (expected_move < 0 and wti_change_pct < 0)
            
            if not aligned:
                # Divergence - could be reversal signal
                move["wti_response_checked"] = True
                continue
            
            # Calculate correlation score
            correlation_score = self._calculate_correlation_score(
                move["symbol"], self._wti_symbol
            )
            
            if correlation_score < self.config.correlation_threshold:
                continue
            
            # Generate signal
            move["wti_response_checked"] = True
            
            return self._generate_signal(move, wti_change_pct, correlation_score)
        
        return None
    
    def _calculate_expected_wti_move(self, move: dict[str, Any]) -> float | None:
        """Calculate expected WTI move based on correlated market move.
        
        Args:
            move: Correlated market move data
            
        Returns:
            Expected WTI move percentage or None
        """
        market = move["market"]
        change_pct = move["price_change_pct"]
        
        # Apply weights based on market type
        weights = {
            "dxy": self.config.dxy_weight,
            "brent": self.config.brent_weight,
            "es": self.config.es_weight,
            "nq": self.config.es_weight * 1.1,  # Similar to ES
            "gold": self.config.gold_weight,
            "ten_year": -0.2,  # Slight inverse
        }
        
        weight = weights.get(market)
        if weight is None:
            return None
        
        return change_pct * weight
    
    def _calculate_correlation_score(self, symbol1: str, symbol2: str) -> float:
        """Calculate correlation coefficient between two symbols.
        
        Args:
            symbol1: First symbol
            symbol2: Second symbol
            
        Returns:
            Correlation coefficient (-1 to 1)
        """
        history1 = self._price_history.get(symbol1, [])
        history2 = self._price_history.get(symbol2, [])
        
        if len(history1) < 5 or len(history2) < 5:
            return 0.0
        
        # Get price changes
        prices1 = [p for _, p in list(history1)[-self.config.lookback_periods:]]
        prices2 = [p for _, p in list(history2)[-self.config.lookback_periods:]]
        
        if len(prices1) != len(prices2):
            # Use minimum length
            min_len = min(len(prices1), len(prices2))
            prices1 = prices1[-min_len:]
            prices2 = prices2[-min_len:]
        
        if len(prices1) < 3:
            return 0.0
        
        # Calculate returns
        returns1 = [(prices1[i] - prices1[i-1]) / prices1[i-1] for i in range(1, len(prices1))]
        returns2 = [(prices2[i] - prices2[i-1]) / prices2[i-1] for i in range(1, len(prices2))]
        
        # Calculate correlation
        n = len(returns1)
        if n < 2:
            return 0.0
        
        mean1 = sum(returns1) / n
        mean2 = sum(returns2) / n
        
        variance1 = sum((r - mean1) ** 2 for r in returns1)
        variance2 = sum((r - mean2) ** 2 for r in returns2)
        
        if variance1 == 0 or variance2 == 0:
            return 0.0
        
        covariance = sum((returns1[i] - mean1) * (returns2[i] - mean2) for i in range(n))
        
        correlation = covariance / (variance1 ** 0.5 * variance2 ** 0.5)
        
        return correlation
    
    def _generate_signal(
        self,
        move: dict[str, Any],
        wti_change_pct: float,
        correlation_score: float,
    ) -> Signal:
        """Generate correlation-based signal.
        
        Args:
            move: Correlated market move
            wti_change_pct: WTI price change
            correlation_score: Correlation coefficient
            
        Returns:
            Trading signal
        """
        symbol = self._wti_symbol
        
        # Determine direction
        direction = "long" if wti_change_pct > 0 else "short"
        
        # Get current WTI price
        wti_history = self._price_history.get(symbol, [])
        current_price = wti_history[-1][1] if wti_history else 0
        
        # Calculate levels
        if direction == "long":
            entry = current_price
            stop = entry * 0.995
            tp1 = entry + (entry - stop) * 2
            tp2 = entry + (entry - stop) * 3
            signal_type = SignalType.CORRELATION_LONG
        else:
            entry = current_price
            stop = entry * 1.005
            tp1 = entry - (stop - entry) * 2
            tp2 = entry - (stop - entry) * 3
            signal_type = SignalType.CORRELATION_SHORT
        
        # Calculate confidence based on correlation
        confidence = int(abs(correlation_score) * 100)
        
        # Build score
        score = SignalScore(
            sweep_quality=50,
            reclaim_speed=50,
            volatility_regime=70,
            spread_quality=80,
            correlation_alignment=int(abs(correlation_score) * 100),
            event_timing=60,
            feed_confirmation=80,
            liquidity_proximity=60,
            session_context=70,
            overall=confidence,
        )
        
        signal = Signal(
            signal_id=f"correlation:{symbol}:{datetime.utcnow().timestamp()}",
            symbol=symbol,
            signal_type=signal_type,
            direction=direction,
            trigger_price=current_price,
            entry_price=round(entry, 4),
            stop_loss=round(stop, 4),
            take_profit_levels=[round(tp1, 4), round(tp2, 4)],
            confidence=confidence,
            score=score,
            setup_description=f"WTI {'rallying' if direction == 'long' else 'falling'} "
                            f"with {move['market'].upper()} ({move['price_change_pct']:.2f}%)",
            reason_codes=[
                f"correlation_{move['market']}",
                f"correlation_score_{correlation_score:.2f}",
                f"wti_response_{wti_change_pct:.2f}%",
            ],
            market_regime=MarketRegime.TRENDING_UP if direction == "long" else MarketRegime.TRENDING_DOWN,
            correlation_context={
                "correlated_market": move["market"],
                "correlated_change_pct": move["price_change_pct"],
                "correlation_coefficient": correlation_score,
                "wti_change_pct": wti_change_pct,
            },
            time_limit=datetime.utcnow() + timedelta(minutes=5),
        )
        
        logger.info(
            "Correlation signal generated",
            symbol=symbol,
            direction=direction,
            confidence=confidence,
            correlated_market=move["market"],
            correlation=correlation_score,
        )
        
        return signal
    
    def get_correlation_matrix(self) -> dict[str, dict[str, float]]:
        """Get correlation matrix for all tracked symbols.
        
        Returns:
            Correlation matrix
        """
        symbols = list(self._price_history.keys())
        matrix = {}
        
        for sym1 in symbols:
            matrix[sym1] = {}
            for sym2 in symbols:
                if sym1 == sym2:
                    matrix[sym1][sym2] = 1.0
                else:
                    matrix[sym1][sym2] = self._calculate_correlation_score(sym1, sym2)
        
        return matrix
    
    def get_stats(self) -> dict[str, Any]:
        """Get detector statistics.
        
        Returns:
            Statistics dictionary
        """
        return {
            "symbols_tracked": len(self._price_history),
            "recent_moves": len(self._recent_moves),
            "active_opportunities": len(self._active_opportunities),
            "correlation_matrix": self.get_correlation_matrix(),
        }