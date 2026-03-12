"""Event definitions for the event bus.

Defines all event types and the base Event class used for internal
communication between system components.
"""

from datetime import datetime
from enum import Enum, auto
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EventType(str, Enum):
    """Event types for internal communication."""
    
    # Market data events
    TICK_RECEIVED = "tick_received"
    BAR_COMPLETED = "bar_completed"
    PRICE_UPDATE = "price_update"
    
    # Signal events
    SIGNAL_GENERATED = "signal_generated"
    SIGNAL_UPDATED = "signal_updated"
    SIGNAL_EXPIRED = "signal_expired"
    
    # Order events
    ORDER_SUBMITTED = "order_submitted"
    ORDER_FILLED = "order_filled"
    ORDER_CANCELLED = "order_cancelled"
    ORDER_REJECTED = "order_rejected"
    
    # Position events
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"
    POSITION_UPDATED = "position_updated"
    
    # Risk events
    RISK_LIMIT_BREACH = "risk_limit_breach"
    KILL_SWITCH_TRIGGERED = "kill_switch_triggered"
    
    # System events
    FEED_HEALTH_CHANGE = "feed_health_change"
    ANOMALY_DETECTED = "anomaly_detected"
    SYSTEM_ALERT = "system_alert"


class Event(BaseModel):
    """Base event class for internal communication.
    
    All events have a type, timestamp, source component, and payload.
    Events are immutable once created.
    
    Attributes:
        event_type: Type of event
        timestamp: When event was created
        source: Component that generated the event
        payload: Event data (type-specific)
        correlation_id: Optional correlation ID for tracing
    """
    
    model_config = ConfigDict(
        frozen=True,
        extra="allow",
        json_encoders={
            datetime: lambda v: v.isoformat(),
        },
    )
    
    event_type: EventType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    source: str = Field(..., min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = Field(default=None)
    
    def __repr__(self) -> str:
        return f"Event({self.event_type.value}, source={self.source})"
    
    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary."""
        return {
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "payload": self.payload,
            "correlation_id": self.correlation_id,
        }
    
    @classmethod
    def create(
        cls,
        event_type: EventType,
        source: str,
        payload: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> "Event":
        """Create a new event.
        
        Args:
            event_type: Type of event
            source: Source component
            payload: Event data
            correlation_id: Optional correlation ID
            
        Returns:
            New Event instance
        """
        return cls(
            event_type=event_type,
            source=source,
            payload=payload or {},
            correlation_id=correlation_id,
        )