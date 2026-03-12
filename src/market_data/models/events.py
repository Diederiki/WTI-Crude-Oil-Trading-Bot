"""Normalized market data event models.

This module defines the core data models for market data events including
ticks, bars, and feed status. All models use Pydantic for validation and
are designed for high-frequency, low-latency processing.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AnomalyType(str, Enum):
    """Types of feed anomalies that can be detected."""
    
    PRICE_SPIKE = "price_spike"
    SPREAD_ANOMALY = "spread_anomaly"
    STALE_FEED = "stale_feed"
    VOLUME_ANOMALY = "volume_anomaly"
    TIMESTAMP_ANOMALY = "timestamp_anomaly"
    CROSS_FEED_MISMATCH = "cross_feed_mismatch"
    FEED_GAP = "feed_gap"


class MarketTick(BaseModel):
    """Normalized market tick event.
    
    Represents a single price update from any feed source. This model
    normalizes data from different providers into a common format.
    
    Attributes:
        symbol: Trading symbol (e.g., "CL=F" for WTI crude)
        timestamp: Exchange timestamp (if available) or receive time
        bid: Best bid price
        ask: Best ask price
        last: Last traded price
        bid_size: Size at best bid
        ask_size: Size at best ask
        last_size: Size of last trade
        volume: Cumulative volume (if available)
        exchange: Exchange code
        feed_source: Data feed provider name
        received_at: Local timestamp when tick was received
        trade_conditions: Trade conditions/flags from exchange
        is_extended_hours: Whether tick is from extended hours
    """
    
    model_config = ConfigDict(
        frozen=True,
        extra="allow",
        json_encoders={
            datetime: lambda v: v.isoformat(),
        },
    )
    
    symbol: str = Field(..., min_length=1, max_length=20, description="Trading symbol")
    timestamp: datetime = Field(..., description="Exchange timestamp")
    bid: float = Field(..., gt=0, description="Best bid price")
    ask: float = Field(..., gt=0, description="Best ask price")
    last: float = Field(..., gt=0, description="Last traded price")
    bid_size: int = Field(default=0, ge=0, description="Bid size")
    ask_size: int = Field(default=0, ge=0, description="Ask size")
    last_size: int = Field(default=0, ge=0, description="Last trade size")
    volume: int | None = Field(default=None, ge=0, description="Cumulative volume")
    exchange: str = Field(default="", max_length=20, description="Exchange code")
    feed_source: str = Field(..., min_length=1, max_length=50, description="Feed provider")
    received_at: datetime = Field(default_factory=datetime.utcnow, description="Receive timestamp")
    trade_conditions: list[str] = Field(default_factory=list, description="Trade conditions")
    is_extended_hours: bool = Field(default=False, description="Extended hours flag")
    
    @property
    def spread(self) -> float:
        """Calculate bid-ask spread."""
        return self.ask - self.bid
    
    @property
    def mid(self) -> float:
        """Calculate mid price."""
        return (self.bid + self.ask) / 2
    
    @property
    def spread_pct(self) -> float:
        """Calculate spread as percentage of mid price."""
        mid = self.mid
        return (self.spread / mid) * 100 if mid > 0 else 0
    
    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        """Normalize symbol to uppercase."""
        return v.upper().strip()
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return self.model_dump()
    
    def is_valid(self, max_spread_pct: float = 5.0) -> bool:
        """Check if tick passes basic validity checks.
        
        Args:
            max_spread_pct: Maximum allowed spread percentage
            
        Returns:
            True if tick is valid
        """
        if self.bid <= 0 or self.ask <= 0 or self.last <= 0:
            return False
        if self.bid >= self.ask:
            return False
        if self.spread_pct > max_spread_pct:
            return False
        return True


class MarketBar(BaseModel):
    """Normalized OHLCV bar/candlestick.
    
    Represents aggregated tick data over a time interval.
    
    Attributes:
        symbol: Trading symbol
        timestamp: Bar open timestamp
        interval_seconds: Bar interval in seconds
        open: Opening price
        high: Highest price
        low: Lowest price
        close: Closing price
        volume: Trading volume
        vwap: Volume-weighted average price
        trades: Number of trades
        bid_open: Opening bid
        ask_open: Opening ask
        bid_close: Closing bid
        ask_close: Closing ask
    """
    
    model_config = ConfigDict(
        frozen=True,
        extra="allow",
        json_encoders={
            datetime: lambda v: v.isoformat(),
        },
    )
    
    symbol: str = Field(..., min_length=1, max_length=20)
    timestamp: datetime = Field(..., description="Bar open timestamp")
    interval_seconds: int = Field(..., ge=1, le=86400, description="Bar interval")
    open: float = Field(..., gt=0, description="Opening price")
    high: float = Field(..., gt=0, description="Highest price")
    low: float = Field(..., gt=0, description="Lowest price")
    close: float = Field(..., gt=0, description="Closing price")
    volume: int = Field(default=0, ge=0, description="Trading volume")
    vwap: float | None = Field(default=None, gt=0, description="VWAP")
    trades: int = Field(default=0, ge=0, description="Number of trades")
    bid_open: float | None = Field(default=None, gt=0)
    ask_open: float | None = Field(default=None, gt=0)
    bid_close: float | None = Field(default=None, gt=0)
    ask_close: float | None = Field(default=None, gt=0)
    
    @field_validator("high")
    @classmethod
    def validate_high(cls, v: float, info) -> float:
        """Validate high is highest price."""
        values = info.data
        if "open" in values and v < values["open"]:
            raise ValueError("high must be >= open")
        if "close" in values and v < values["close"]:
            raise ValueError("high must be >= close")
        return v
    
    @field_validator("low")
    @classmethod
    def validate_low(cls, v: float, info) -> float:
        """Validate low is lowest price."""
        values = info.data
        if "open" in values and v > values["open"]:
            raise ValueError("low must be <= open")
        if "close" in values and v > values["close"]:
            raise ValueError("low must be <= close")
        return v
    
    @property
    def range(self) -> float:
        """Calculate price range (high - low)."""
        return self.high - self.low
    
    @property
    def body(self) -> float:
        """Calculate candle body (close - open)."""
        return self.close - self.open
    
    @property
    def body_pct(self) -> float:
        """Calculate body as percentage of open."""
        return (self.body / self.open) * 100 if self.open > 0 else 0
    
    @property
    def is_bullish(self) -> bool:
        """Check if bar is bullish (close > open)."""
        return self.close > self.open
    
    @property
    def is_bearish(self) -> bool:
        """Check if bar is bearish (close < open)."""
        return self.close < self.open
    
    @property
    def is_doji(self, threshold: float = 0.1) -> bool:
        """Check if bar is a doji (body very small relative to range).
        
        Args:
            threshold: Maximum body/range ratio to be considered doji
        """
        if self.range == 0:
            return True
        return abs(self.body) / self.range < threshold


class FeedHealth(str, Enum):
    """Feed health status enumeration."""
    
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    DISCONNECTED = "disconnected"
    UNKNOWN = "unknown"


class FeedStatus(BaseModel):
    """Feed connection status and health metrics.
    
    Tracks the health and performance of a market data feed including
    connection state, latency metrics, and error counts.
    
    Attributes:
        feed_id: Unique feed identifier
        provider: Feed provider name
        symbols: List of subscribed symbols
        status: Current health status
        connected_at: Connection timestamp
        last_message_at: Last message received timestamp
        messages_received: Total messages received
        messages_per_second: Current message rate
        avg_latency_ms: Average latency in milliseconds
        max_latency_ms: Maximum observed latency
        errors_count: Total error count
        reconnects_count: Total reconnection count
        is_connected: Whether feed is currently connected
    """
    
    model_config = ConfigDict(
        extra="allow",
        json_encoders={
            datetime: lambda v: v.isoformat(),
        },
    )
    
    feed_id: str = Field(..., min_length=1)
    provider: str = Field(..., min_length=1)
    symbols: list[str] = Field(default_factory=list)
    status: FeedHealth = Field(default=FeedHealth.UNKNOWN)
    connected_at: datetime | None = Field(default=None)
    last_message_at: datetime | None = Field(default=None)
    messages_received: int = Field(default=0, ge=0)
    messages_per_second: float = Field(default=0.0, ge=0)
    avg_latency_ms: float = Field(default=0.0, ge=0)
    max_latency_ms: float = Field(default=0.0, ge=0)
    errors_count: int = Field(default=0, ge=0)
    reconnects_count: int = Field(default=0, ge=0)
    is_connected: bool = Field(default=False)
    last_error: str | None = Field(default=None)
    
    @property
    def time_since_last_message_ms(self) -> float | None:
        """Calculate milliseconds since last message."""
        if self.last_message_at is None:
            return None
        return (datetime.utcnow() - self.last_message_at).total_seconds() * 1000
    
    @property
    def is_stale(self, stale_threshold_ms: float = 5000) -> bool:
        """Check if feed is stale (no messages for threshold period).
        
        Args:
            stale_threshold_ms: Milliseconds without message to be considered stale
        """
        time_since = self.time_since_last_message_ms
        if time_since is None:
            return True
        return time_since > stale_threshold_ms
    
    def update_health(self) -> "FeedStatus":
        """Update health status based on current metrics.
        
        Returns:
            Updated FeedStatus instance
        """
        if not self.is_connected:
            self.status = FeedHealth.DISCONNECTED
        elif self.errors_count > 10 or self.reconnects_count > 5:
            self.status = FeedHealth.UNHEALTHY
        elif self.is_stale or self.avg_latency_ms > 1000:
            self.status = FeedHealth.DEGRADED
        else:
            self.status = FeedHealth.HEALTHY
        return self


class FeedAnomaly(BaseModel):
    """Feed anomaly detection record.
    
    Records detected anomalies in market data feeds for later analysis
    and potential signal filtering.
    
    Attributes:
        anomaly_id: Unique anomaly identifier
        feed_id: Feed where anomaly was detected
        symbol: Symbol affected
        anomaly_type: Type of anomaly
        detected_at: Detection timestamp
        severity: Severity level (1-5, 5 being highest)
        description: Human-readable description
        expected_value: Expected/normal value
        actual_value: Actual observed value
        raw_data: Raw data that triggered anomaly
        is_resolved: Whether anomaly has been resolved
        resolved_at: Resolution timestamp
    """
    
    model_config = ConfigDict(
        extra="allow",
        json_encoders={
            datetime: lambda v: v.isoformat(),
        },
    )
    
    anomaly_id: str = Field(..., min_length=1)
    feed_id: str = Field(..., min_length=1)
    symbol: str = Field(..., min_length=1)
    anomaly_type: AnomalyType
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    severity: int = Field(..., ge=1, le=5)
    description: str = Field(..., min_length=1)
    expected_value: float | None = Field(default=None)
    actual_value: float | None = Field(default=None)
    raw_data: dict[str, Any] = Field(default_factory=dict)
    is_resolved: bool = Field(default=False)
    resolved_at: datetime | None = Field(default=None)
    
    def resolve(self) -> "FeedAnomaly":
        """Mark anomaly as resolved."""
        self.is_resolved = True
        self.resolved_at = datetime.utcnow()
        return self