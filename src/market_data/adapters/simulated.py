"""Simulated feed adapter for testing and development.

This adapter generates synthetic market data for testing the system
without requiring live market data connections.
"""

import asyncio
import random
from datetime import datetime
from typing import Any

from src.core.logging_config import get_logger
from src.market_data.adapters.base import FeedAdapter
from src.market_data.models.events import MarketTick, MarketBar, FeedHealth

logger = get_logger("market_data")


class SimulatedFeedAdapter(FeedAdapter):
    """Simulated market data feed for testing.
    
    Generates synthetic price data using random walk with configurable
    volatility and trend parameters. Useful for testing without live
    market data connections.
    
    Attributes:
        base_prices: Starting prices for each symbol
        current_prices: Current prices for each symbol
        volatility: Price volatility as percentage
        trend: Price trend bias (-1 to 1)
        tick_interval_ms: Interval between ticks in milliseconds
    """
    
    # Default base prices for common symbols
    DEFAULT_BASE_PRICES: dict[str, float] = {
        "CL=F": 75.0,      # WTI Crude Oil
        "BZ=F": 80.0,      # Brent Crude
        "DX-Y.NYB": 103.0, # US Dollar Index
        "ES=F": 4500.0,    # E-mini S&P 500
        "NQ=F": 15500.0,   # E-mini Nasdaq
        "GC=F": 2000.0,    # Gold
        "ZN=F": 110.0,     # 10-Year T-Note
        "ZT=F": 102.0,     # 2-Year T-Note
    }
    
    def __init__(
        self,
        feed_id: str,
        symbols: list[str],
        config: dict[str, Any] | None = None,
    ):
        """Initialize simulated feed.
        
        Args:
            feed_id: Unique feed identifier
            symbols: Symbols to simulate
            config: Configuration options:
                - base_prices: Dict of symbol -> base price
                - volatility: Volatility percentage (default: 0.1)
                - trend: Trend bias -1 to 1 (default: 0)
                - tick_interval_ms: Ms between ticks (default: 100)
                - bar_interval_seconds: Seconds per bar (default: 60)
        """
        super().__init__(feed_id, "simulated", symbols, config)
        
        # Price configuration
        self.base_prices: dict[str, float] = self.config.get(
            "base_prices", self.DEFAULT_BASE_PRICES
        )
        self.current_prices: dict[str, float] = {}
        self.volatility: float = self.config.get("volatility", 0.1)
        self.trend: float = self.config.get("trend", 0.0)
        
        # Timing configuration
        self.tick_interval_ms: float = self.config.get("tick_interval_ms", 100)
        self.bar_interval_seconds: int = self.config.get("bar_interval_seconds", 60)
        
        # Bar aggregation state
        self._bar_state: dict[str, dict[str, Any]] = {}
        self._bar_timer: asyncio.Task | None = None
        self._tick_task: asyncio.Task | None = None
        
        # Initialize prices
        for symbol in symbols:
            base = self.base_prices.get(symbol, 100.0)
            self.current_prices[symbol] = base
            self._init_bar_state(symbol)
        
        logger.info(
            "Simulated feed initialized",
            feed_id=feed_id,
            symbols=symbols,
            volatility=self.volatility,
            trend=self.trend,
        )
    
    def _init_bar_state(self, symbol: str) -> None:
        """Initialize bar aggregation state for a symbol."""
        price = self.current_prices.get(symbol, 100.0)
        now = datetime.utcnow()
        self._bar_state[symbol] = {
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": 0,
            "trades": 0,
            "start_time": now,
            "vwap_sum": 0.0,
            "vwap_vol": 0,
        }
    
    async def connect(self) -> None:
        """Connect to simulated feed (no-op)."""
        self._update_status(FeedHealth.HEALTHY)
        logger.info("Simulated feed connected", feed_id=self.feed_id)
    
    async def disconnect(self) -> None:
        """Disconnect from simulated feed."""
        self._running = False
        
        if self._tick_task:
            self._tick_task.cancel()
            try:
                await self._tick_task
            except asyncio.CancelledError:
                pass
        
        if self._bar_timer:
            self._bar_timer.cancel()
            try:
                await self._bar_timer
            except asyncio.CancelledError:
                pass
        
        self._update_status(FeedHealth.DISCONNECTED)
        logger.info("Simulated feed disconnected", feed_id=self.feed_id)
    
    async def subscribe(self, symbols: list[str]) -> None:
        """Subscribe to additional symbols."""
        for symbol in symbols:
            sym = symbol.upper()
            if sym not in self.symbols:
                self.symbols.append(sym)
                base = self.base_prices.get(sym, 100.0)
                self.current_prices[sym] = base
                self._init_bar_state(sym)
        
        self.status.symbols = self.symbols.copy()
        logger.info(
            "Subscribed to symbols",
            feed_id=self.feed_id,
            symbols=symbols,
        )
    
    async def unsubscribe(self, symbols: list[str]) -> None:
        """Unsubscribe from symbols."""
        for symbol in symbols:
            sym = symbol.upper()
            if sym in self.symbols:
                self.symbols.remove(sym)
                self.current_prices.pop(sym, None)
                self._bar_state.pop(sym, None)
        
        self.status.symbols = self.symbols.copy()
        logger.info(
            "Unsubscribed from symbols",
            feed_id=self.feed_id,
            symbols=symbols,
        )
    
    async def receive_loop(self) -> None:
        """Main receive loop - generates simulated ticks."""
        self._tick_task = asyncio.create_task(self._tick_generator())
        self._bar_timer = asyncio.create_task(self._bar_generator())
        
        try:
            await asyncio.gather(self._tick_task, self._bar_timer)
        except asyncio.CancelledError:
            logger.info("Receive loop cancelled", feed_id=self.feed_id)
        except Exception as e:
            logger.error(
                "Error in receive loop",
                feed_id=self.feed_id,
                error=str(e),
            )
            self._update_status(FeedHealth.UNHEALTHY, str(e))
    
    async def _tick_generator(self) -> None:
        """Generate simulated ticks."""
        while self._running:
            try:
                for symbol in self.symbols:
                    tick = self._generate_tick(symbol)
                    self._dispatch_tick(tick)
                    self._update_bar_state(symbol, tick)
                
                await asyncio.sleep(self.tick_interval_ms / 1000)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    "Error generating tick",
                    feed_id=self.feed_id,
                    error=str(e),
                )
                self.status.errors_count += 1
    
    async def _bar_generator(self) -> None:
        """Generate bars at regular intervals."""
        while self._running:
            try:
                await asyncio.sleep(self.bar_interval_seconds)
                self._emit_bars()
                self._reset_bar_state()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    "Error generating bar",
                    feed_id=self.feed_id,
                    error=str(e),
                )
    
    def _generate_tick(self, symbol: str) -> MarketTick:
        """Generate a simulated tick for a symbol."""
        current = self.current_prices.get(symbol, 100.0)
        
        # Random walk with trend
        change_pct = random.gauss(self.trend * 0.01, self.volatility / 100)
        new_price = current * (1 + change_pct)
        
        # Ensure positive price
        new_price = max(0.01, new_price)
        self.current_prices[symbol] = new_price
        
        # Generate bid/ask around last price
        spread = new_price * 0.0001  # 1bp spread
        bid = new_price - spread / 2
        ask = new_price + spread / 2
        
        # Random sizes
        bid_size = random.randint(1, 100) * 10
        ask_size = random.randint(1, 100) * 10
        last_size = random.randint(1, 50) * 10
        
        return MarketTick(
            symbol=symbol,
            timestamp=datetime.utcnow(),
            bid=round(bid, 4),
            ask=round(ask, 4),
            last=round(new_price, 4),
            bid_size=bid_size,
            ask_size=ask_size,
            last_size=last_size,
            volume=random.randint(100000, 1000000),
            exchange="SIM",
            feed_source=self.provider,
        )
    
    def _update_bar_state(self, symbol: str, tick: MarketTick) -> None:
        """Update bar aggregation state with new tick."""
        state = self._bar_state.get(symbol)
        if state is None:
            return
        
        price = tick.last
        size = tick.last_size
        
        state["high"] = max(state["high"], price)
        state["low"] = min(state["low"], price)
        state["close"] = price
        state["volume"] += size
        state["trades"] += 1
        state["vwap_sum"] += price * size
        state["vwap_vol"] += size
    
    def _emit_bars(self) -> None:
        """Emit completed bars."""
        for symbol in self.symbols:
            state = self._bar_state.get(symbol)
            if state is None or state["trades"] == 0:
                continue
            
            vwap = None
            if state["vwap_vol"] > 0:
                vwap = state["vwap_sum"] / state["vwap_vol"]
            
            bar = MarketBar(
                symbol=symbol,
                timestamp=state["start_time"],
                interval_seconds=self.bar_interval_seconds,
                open=round(state["open"], 4),
                high=round(state["high"], 4),
                low=round(state["low"], 4),
                close=round(state["close"], 4),
                volume=state["volume"],
                vwap=round(vwap, 4) if vwap else None,
                trades=state["trades"],
            )
            
            self._dispatch_bar(bar)
    
    def _reset_bar_state(self) -> None:
        """Reset bar state for new interval."""
        for symbol in self.symbols:
            self._init_bar_state(symbol)
    
    async def inject_tick(self, tick: MarketTick) -> None:
        """Inject a custom tick (for testing).
        
        Args:
            tick: Tick to inject
        """
        self._dispatch_tick(tick)
        self._update_bar_state(tick.symbol, tick)
        logger.debug(
            "Injected tick",
            feed_id=self.feed_id,
            symbol=tick.symbol,
            price=tick.last,
        )
    
    async def inject_spike(self, symbol: str, spike_pct: float) -> None:
        """Inject a price spike (for testing anomaly detection).
        
        Args:
            symbol: Symbol to spike
            spike_pct: Percentage to spike (positive or negative)
        """
        current = self.current_prices.get(symbol, 100.0)
        spiked_price = current * (1 + spike_pct / 100)
        
        tick = MarketTick(
            symbol=symbol,
            timestamp=datetime.utcnow(),
            bid=round(spiked_price * 0.9999, 4),
            ask=round(spiked_price * 1.0001, 4),
            last=round(spiked_price, 4),
            bid_size=100,
            ask_size=100,
            last_size=1000,
            volume=1000000,
            exchange="SIM",
            feed_source=self.provider,
        )
        
        await self.inject_tick(tick)
        logger.info(
            "Injected price spike",
            feed_id=self.feed_id,
            symbol=symbol,
            spike_pct=spike_pct,
            price=spiked_price,
        )