"""Signal models for trading strategy.

Defines the Signal model with comprehensive scoring, risk parameters,
and lifecycle management for trading opportunities.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SignalType(str, Enum):
    """Types of trading signals."""
    
    LIQUIDITY_SWEEP_LONG = "liquidity_sweep_long"
    LIQUIDITY_SWEEP_SHORT = "liquidity_sweep_short"
    BREAKOUT_LONG = "breakout_long"
    BREAKOUT_SHORT = "breakout_short"
    CORRELATION_LONG = "correlation_long"
    CORRELATION_SHORT = "correlation_short"
    MOMENTUM_LONG = "momentum_long"
    MOMENTUM_SHORT = "momentum_short"
    REVERSAL_LONG = "reversal_long"
    REVERSAL_SHORT = "reversal_short"


class SignalStatus(str, Enum):
    """Signal lifecycle status."""
    
    PENDING = "pending"           # Generated but not yet actionable
    ACTIVE = "active"             # Ready for execution
    TRIGGERED = "triggered"       # Entry condition met
    ENTERED = "entered"           # Position opened
    EXPIRED = "expired"           # Time limit reached
    CANCELLED = "cancelled"       # Manually cancelled
    INVALIDATED = "invalidated"   # Setup no longer valid


class MarketRegime(str, Enum):
    """Market regime classification."""
    
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    VOLATILE = "volatile"
    LOW_VOLATILITY = "low_volatility"
    UNKNOWN = "unknown"


class SignalScore(BaseModel):
    """Detailed signal scoring breakdown.
    
    Provides granular scoring for different factors that contribute
to overall signal confidence.
    
    Attributes:
        sweep_quality: Quality of liquidity sweep (0-100)
        reclaim_speed: Speed of level reclaim (0-100)
        volatility_regime: Appropriateness of volatility (0-100)
        spread_quality: Spread tightness (0-100)
        correlation_alignment: Correlation factor alignment (0-100)
        event_timing: Proximity to key events (0-100)
        feed_confirmation: Cross-feed confirmation (0-100)
        liquidity_proximity: Distance to liquidity zones (0-100)
        session_context: Appropriateness for session (0-100)
        overall: Weighted overall score (0-100)
    """
    
    model_config = ConfigDict(frozen=True)
    
    sweep_quality: int = Field(default=0, ge=0, le=100)
    reclaim_speed: int = Field(default=0, ge=0, le=100)
    volatility_regime: int = Field(default=0, ge=0, le=100)
    spread_quality: int = Field(default=0, ge=0, le=100)
    correlation_alignment: int = Field(default=0, ge=0, le=100)
    event_timing: int = Field(default=0, ge=0, le=100)
    feed_confirmation: int = Field(default=0, ge=0, le=100)
    liquidity_proximity: int = Field(default=0, ge=0, le=100)
    session_context: int = Field(default=0, ge=0, le=100)
    overall: int = Field(default=0, ge=0, le=100)
    
    def to_dict(self) -> dict[str, int]:
        """Convert to dictionary."""
        return {
            "sweep_quality": self.sweep_quality,
            "reclaim_speed": self.reclaim_speed,
            "volatility_regime": self.volatility_regime,
            "spread_quality": self.spread_quality,
            "correlation_alignment": self.correlation_alignment,
            "event_timing": self.event_timing,
            "feed_confirmation": self.feed_confirmation,
            "liquidity_proximity": self.liquidity_proximity,
            "session_context": self.session_context,
            "overall": self.overall,
        }


class Signal(BaseModel):
    """Trading signal with complete context and scoring.
    
    Represents a detected trading opportunity with all relevant
    information for decision-making and execution.
    
    Attributes:
        signal_id: Unique signal identifier
        timestamp: When signal was generated
        symbol: Trading symbol
        signal_type: Type of signal
        status: Current lifecycle status
        direction: "long" or "short"
        trigger_price: Price that triggered the signal
        entry_price: Suggested entry price
        stop_loss: Stop loss price
        take_profit_levels: List of take profit targets
        position_size: Suggested position size
        confidence: Overall confidence score (0-100)
        score: Detailed scoring breakdown
        setup_description: Human-readable setup description
        reason_codes: List of reason codes
        market_regime: Current market regime
        session: Trading session
        event_context: Related economic events
        correlation_context: Cross-market correlation data
        invalidation_price: Price level that invalidates setup
        time_limit: Maximum time to wait for entry
        metadata: Additional strategy-specific data
    """
    
    model_config = ConfigDict(
        extra="allow",
        json_encoders={
            datetime: lambda v: v.isoformat(),
        },
    )
    
    # Identification
    signal_id: str = Field(..., min_length=1)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    symbol: str = Field(..., min_length=1)
    
    # Signal classification
    signal_type: SignalType
    status: SignalStatus = Field(default=SignalStatus.PENDING)
    direction: str = Field(..., pattern="^(long|short)$")
    
    # Price levels
    trigger_price: float = Field(..., gt=0)
    entry_price: float = Field(..., gt=0)
    stop_loss: float = Field(..., gt=0)
    take_profit_levels: list[float] = Field(default_factory=list)
    
    # Sizing
    position_size: int = Field(default=1, ge=1)
    max_position_pct: float = Field(default=5.0, gt=0, le=100)
    
    # Scoring
    confidence: int = Field(..., ge=0, le=100)
    score: SignalScore = Field(default_factory=SignalScore)
    
    # Context
    setup_description: str = Field(..., min_length=1)
    reason_codes: list[str] = Field(default_factory=list)
    market_regime: MarketRegime = Field(default=MarketRegime.UNKNOWN)
    session: str = Field(default="")
    
    # Event and correlation context
    event_context: dict[str, Any] = Field(default_factory=dict)
    correlation_context: dict[str, Any] = Field(default_factory=dict)
    
    # Risk management
    invalidation_price: float | None = Field(default=None)
    time_limit: datetime | None = Field(default=None)
    max_slippage_pct: float = Field(default=0.1, ge=0)
    
    # Metadata
    metadata: dict[str, Any] = Field(default_factory=dict)
    
    # Lifecycle tracking
    triggered_at: datetime | None = Field(default=None)
    entered_at: datetime | None = Field(default=None)
    exited_at: datetime | None = Field(default=None)
    pnl: float | None = Field(default=None)
    
    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        """Normalize symbol to uppercase."""
        return v.upper().strip()
    
    @property
    def risk_reward_ratio(self) -> float | None:
        """Calculate risk/reward ratio."""
        if not self.take_profit_levels:
            return None
        
        risk = abs(self.entry_price - self.stop_loss)
        if risk == 0:
            return None
        
        reward = abs(self.take_profit_levels[0] - self.entry_price)
        return reward / risk
    
    @property
    def risk_amount(self) -> float:
        """Calculate risk amount per unit."""
        return abs(self.entry_price - self.stop_loss)
    
    @property
    def is_long(self) -> bool:
        """Check if long signal."""
        return self.direction == "long"
    
    @property
    def is_short(self) -> bool:
        """Check if short signal."""
        return self.direction == "short"
    
    @property
    def is_active(self) -> bool:
        """Check if signal is still active."""
        return self.status in [SignalStatus.PENDING, SignalStatus.ACTIVE]
    
    def update_status(self, status: SignalStatus) -> "Signal":
        """Update signal status.
        
        Args:
            status: New status
            
        Returns:
            Self for chaining
        """
        self.status = status
        
        if status == SignalStatus.TRIGGERED:
            self.triggered_at = datetime.utcnow()
        elif status == SignalStatus.ENTERED:
            self.entered_at = datetime.utcnow()
        elif status in [SignalStatus.EXPIRED, SignalStatus.CANCELLED, SignalStatus.INVALIDATED]:
            if self.entered_at:
                self.exited_at = datetime.utcnow()
        
        return self
    
    def check_invalidation(self, current_price: float) -> bool:
        """Check if signal should be invalidated based on price.
        
        Args:
            current_price: Current market price
            
        Returns:
            True if signal is invalidated
        """
        if self.invalidation_price is None:
            return False
        
        if self.is_long and current_price < self.invalidation_price:
            return True
        if self.is_short and current_price > self.invalidation_price:
            return True
        
        return False
    
    def check_time_expired(self) -> bool:
        """Check if signal has expired based on time limit.
        
        Returns:
            True if expired
        """
        if self.time_limit is None:
            return False
        return datetime.utcnow() > self.time_limit
    
    def to_execution_request(self) -> dict[str, Any]:
        """Convert to order execution request format.
        
        Returns:
            Execution request dictionary
        """
        return {
            "signal_id": self.signal_id,
            "symbol": self.symbol,
            "side": "buy" if self.is_long else "sell",
            "quantity": self.position_size,
            "order_type": "limit",  # Or market based on config
            "price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profits": self.take_profit_levels,
            "metadata": {
                "signal_type": self.signal_type.value,
                "confidence": self.confidence,
                "setup": self.setup_description,
            },
        }
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "signal_id": self.signal_id,
            "timestamp": self.timestamp.isoformat(),
            "symbol": self.symbol,
            "signal_type": self.signal_type.value,
            "status": self.status.value,
            "direction": self.direction,
            "trigger_price": self.trigger_price,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit_levels": self.take_profit_levels,
            "position_size": self.position_size,
            "confidence": self.confidence,
            "score": self.score.to_dict(),
            "setup_description": self.setup_description,
            "reason_codes": self.reason_codes,
            "market_regime": self.market_regime.value,
            "risk_reward_ratio": self.risk_reward_ratio,
            "is_active": self.is_active,
        }