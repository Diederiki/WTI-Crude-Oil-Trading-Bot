"""Event models for economic calendar and news events.

Defines event types, impact levels, and event data structures for
trading around economic releases and news events.
"""

from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventType(str, Enum):
    """Types of economic events."""
    
    # Energy/Oil events
    EIA_CRUDE_INVENTORIES = "eia_crude_inventories"
    EIA_GASOLINE_INVENTORIES = "eia_gasoline_inventories"
    EIA_DISTILLATE_INVENTORIES = "eia_distillate_inventories"
    EIA_REFINERY_UTILIZATION = "eia_refinery_utilization"
    EIA_NATURAL_GAS_STORAGE = "eia_natural_gas_storage"
    
    # OPEC events
    OPEC_MEETING = "opec_meeting"
    OPEC_MONTHLY_REPORT = "opec_monthly_report"
    
    # Economic indicators
    NON_FARM_PAYROLLS = "non_farm_payrolls"
    UNEMPLOYMENT_RATE = "unemployment_rate"
    CPI = "cpi"
    PPI = "ppi"
    GDP = "gdp"
    FOMC_STATEMENT = "fomc_statement"
    FOMC_MINUTES = "fomc_minutes"
    FED_CHAIR_SPEECH = "fed_chair_speech"
    
    # Market events
    OPTIONS_EXPIRATION = "options_expiration"
    FUTURES_EXPIRATION = "futures_expiration"
    MARKET_HOLIDAY = "market_holiday"


class EventImpact(str, Enum):
    """Event impact level."""
    
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EventStatus(str, Enum):
    """Event lifecycle status."""
    
    SCHEDULED = "scheduled"       # Future event
    APPROACHING = "approaching"   # Within pre-event window
    ACTIVE = "active"             # Event time
    RELEASED = "released"         # Data released
    PROCESSING = "processing"     # Post-event processing
    COMPLETED = "completed"       # Event complete
    CANCELLED = "cancelled"       # Event cancelled


class EventResult(BaseModel):
    """Event result/actual data.
    
    Attributes:
        actual: Actual released value
        forecast: Forecast/consensus value
        previous: Previous period value
        revision: Revised previous value
        surprise_pct: Surprise vs forecast (%)
        market_reaction: Initial market reaction
    """
    
    model_config = ConfigDict(frozen=True)
    
    actual: str | None = Field(default=None)
    forecast: str | None = Field(default=None)
    previous: str | None = Field(default=None)
    revision: str | None = Field(default=None)
    surprise_pct: float | None = Field(default=None)
    market_reaction: str | None = Field(default=None)  # "bullish", "bearish", "neutral"
    
    def calculate_surprise(self) -> float | None:
        """Calculate surprise percentage vs forecast."""
        if self.actual is None or self.forecast is None:
            return None
        
        try:
            actual_val = float(self.actual)
            forecast_val = float(self.forecast)
            
            if forecast_val == 0:
                return None
            
            return (actual_val - forecast_val) / abs(forecast_val) * 100
        except (ValueError, TypeError):
            return None


class Event(BaseModel):
    """Economic event with full context.
    
    Represents a scheduled economic event with timing, impact,
    and trading configuration.
    
    Attributes:
        event_id: Unique event identifier
        event_type: Type of event
        name: Human-readable event name
        description: Event description
        scheduled_time: Scheduled release time (UTC)
        timezone: Original timezone
        country: Affected country/region
        currency: Affected currency
        impact: Impact level
        status: Current status
        result: Event results
        
        # Trading configuration
        pre_event_minutes: Minutes before event to start special handling
        post_event_minutes: Minutes after event for special handling
        trading_disabled: Whether trading is disabled during event
        size_reduction_pct: Position size reduction during event
        spread_filter_multiplier: Spread filter multiplier during event
        
        # Metadata
        source: Data source
        url: URL for more info
        metadata: Additional data
    """
    
    model_config = ConfigDict(
        extra="allow",
        json_encoders={
            datetime: lambda v: v.isoformat(),
        },
    )
    
    # Identification
    event_id: str = Field(..., min_length=1)
    event_type: EventType
    name: str = Field(..., min_length=1)
    description: str = Field(default="")
    
    # Timing
    scheduled_time: datetime
    timezone: str = Field(default="UTC")
    country: str = Field(default="US")
    currency: str = Field(default="USD")
    
    # Classification
    impact: EventImpact = Field(default=EventImpact.MEDIUM)
    status: EventStatus = Field(default=EventStatus.SCHEDULED)
    
    # Results
    result: EventResult | None = Field(default=None)
    released_at: datetime | None = Field(default=None)
    
    # Trading configuration
    pre_event_minutes: int = Field(default=5, ge=0)
    post_event_minutes: int = Field(default=15, ge=0)
    trading_disabled: bool = Field(default=False)
    size_reduction_pct: float = Field(default=0.0, ge=0, le=100)
    spread_filter_multiplier: float = Field(default=1.0, ge=0.5)
    
    # Metadata
    source: str = Field(default="")
    url: str | None = Field(default=None)
    metadata: dict[str, Any] = Field(default_factory=dict)
    
    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, v: str) -> str:
        """Normalize currency to uppercase."""
        return v.upper()
    
    @property
    def is_high_impact(self) -> bool:
        """Check if high or critical impact."""
        return self.impact in [EventImpact.HIGH, EventImpact.CRITICAL]
    
    @property
    def pre_event_start(self) -> datetime:
        """Calculate pre-event window start time."""
        return self.scheduled_time - timedelta(minutes=self.pre_event_minutes)
    
    @property
    def post_event_end(self) -> datetime:
        """Calculate post-event window end time."""
        return self.scheduled_time + timedelta(minutes=self.post_event_minutes)
    
    def get_current_phase(self, now: datetime | None = None) -> str:
        """Get current event phase.
        
        Args:
            now: Current time (default: now)
            
        Returns:
            Phase: "pre", "active", "post", or "none"
        """
        if now is None:
            now = datetime.utcnow()
        
        if self.status in [EventStatus.COMPLETED, EventStatus.CANCELLED]:
            return "none"
        
        if now < self.pre_event_start:
            return "none"
        
        if now < self.scheduled_time:
            return "pre"
        
        if now < self.post_event_end:
            return "post"
        
        return "none"
    
    def is_in_event_window(self, now: datetime | None = None) -> bool:
        """Check if currently in event window.
        
        Args:
            now: Current time (default: now)
            
        Returns:
            True if in event window
        """
        phase = self.get_current_phase(now)
        return phase in ["pre", "active", "post"]
    
    def is_trading_allowed(self, now: datetime | None = None) -> bool:
        """Check if trading is allowed.
        
        Args:
            now: Current time (default: now)
            
        Returns:
            True if trading allowed
        """
        if not self.trading_disabled:
            return True
        
        return not self.is_in_event_window(now)
    
    def update_status(self, status: EventStatus) -> "Event":
        """Update event status.
        
        Args:
            status: New status
            
        Returns:
            Self for chaining
        """
        self.status = status
        
        if status == EventStatus.RELEASED:
            self.released_at = datetime.utcnow()
        
        return self
    
    def set_result(self, result: EventResult) -> "Event":
        """Set event result.
        
        Args:
            result: Event result data
            
        Returns:
            Self for chaining
        """
        self.result = result
        
        # Calculate surprise
        if result.surprise_pct is None:
            result = EventResult(
                **result.model_dump(exclude={"surprise_pct"}),
                surprise_pct=result.calculate_surprise(),
            )
            self.result = result
        
        return self
    
    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "name": self.name,
            "scheduled_time": self.scheduled_time.isoformat(),
            "timezone": self.timezone,
            "impact": self.impact.value,
            "status": self.status.value,
            "phase": self.get_current_phase(),
            "trading_allowed": self.is_trading_allowed(),
            "pre_event_start": self.pre_event_start.isoformat(),
            "post_event_end": self.post_event_end.isoformat(),
        }


class EventWindowConfig(BaseModel):
    """Configuration for event windows.
    
    Defines how the system should behave around different
    types of events.
    
    Attributes:
        event_type: Type of event
        pre_event_minutes: Minutes before event for special handling
        post_event_minutes: Minutes after event for special handling
        trading_disabled: Disable trading during window
        size_reduction_pct: Reduce position sizes
        spread_multiplier: Relax spread filter
        volatility_filter_multiplier: Adjust volatility filter
        enable_breakout_mode: Enable breakout detection
    """
    
    model_config = ConfigDict(frozen=True)
    
    event_type: EventType
    pre_event_minutes: int = Field(default=5, ge=0)
    post_event_minutes: int = Field(default=15, ge=0)
    trading_disabled: bool = Field(default=False)
    size_reduction_pct: float = Field(default=0.0, ge=0, le=100)
    spread_multiplier: float = Field(default=1.0, ge=0.5)
    volatility_filter_multiplier: float = Field(default=1.0, ge=0.5)
    enable_breakout_mode: bool = Field(default=True)