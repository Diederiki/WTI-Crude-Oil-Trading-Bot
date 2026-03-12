"""Events API endpoints.

Provides REST API access to economic events and event calendar.
"""

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.config.settings import Settings, get_settings
from src.core.logging_config import get_logger
from src.events.engine import EventEngine
from src.events.models import Event, EventType, EventImpact, EventStatus

logger = get_logger("api")
router = APIRouter(prefix="/events", tags=["events"])

# Global event engine instance (set during startup)
_event_engine: EventEngine | None = None


def set_event_engine(engine: EventEngine) -> None:
    """Set the global event engine instance.
    
    Args:
        engine: EventEngine instance
    """
    global _event_engine
    _event_engine = engine


def get_event_engine() -> EventEngine:
    """Get the global event engine instance.
    
    Returns:
        EventEngine instance
        
    Raises:
        HTTPException: If event engine not initialized
    """
    if _event_engine is None:
        raise HTTPException(
            status_code=503,
            detail="Event engine not initialized",
        )
    return _event_engine


class EventResponse(BaseModel):
    """Event response model."""
    event_id: str
    event_type: str
    name: str
    description: str
    scheduled_time: str
    timezone: str
    country: str
    currency: str
    impact: str
    status: str
    phase: str
    trading_allowed: bool
    pre_event_start: str
    post_event_end: str


class EventListResponse(BaseModel):
    """Event list response."""
    events: list[EventResponse]
    total: int


class EventContextResponse(BaseModel):
    """Event context response."""
    in_event_window: bool
    active_events: list[dict[str, Any]]
    upcoming_events: list[dict[str, Any]]
    position_size_reduction_pct: float
    spread_filter_multiplier: float
    trading_allowed: bool


class CreateEventRequest(BaseModel):
    """Create event request."""
    event_type: str = Field(..., description="Event type")
    name: str = Field(..., description="Event name")
    scheduled_time: str = Field(..., description="Scheduled time (ISO format)")
    impact: str = Field(default="medium", description="Impact level")
    description: str = Field(default="", description="Event description")
    pre_event_minutes: int = Field(default=5, description="Pre-event window minutes")
    post_event_minutes: int = Field(default=15, description="Post-event window minutes")
    trading_disabled: bool = Field(default=False, description="Disable trading during event")
    size_reduction_pct: float = Field(default=0.0, description="Position size reduction %")


class SetResultRequest(BaseModel):
    """Set event result request."""
    actual: str = Field(..., description="Actual value")
    forecast: str | None = Field(default=None, description="Forecast value")
    previous: str | None = Field(default=None, description="Previous value")


@router.get(
    "/upcoming",
    response_model=EventListResponse,
    summary="Get upcoming events",
    description="Get upcoming economic events.",
)
async def get_upcoming_events(
    hours: float = Query(default=24.0, description="Hours to look ahead"),
    min_impact: str | None = Query(default=None, description="Minimum impact level"),
    engine: EventEngine = Depends(get_event_engine),
) -> EventListResponse:
    """Get upcoming events."""
    impact = EventImpact(min_impact) if min_impact else None
    events = engine.calendar.get_upcoming_events(
        hours=hours,
        min_impact=impact,
    )
    
    return EventListResponse(
        events=[
            EventResponse(
                event_id=e.event_id,
                event_type=e.event_type.value,
                name=e.name,
                description=e.description,
                scheduled_time=e.scheduled_time.isoformat(),
                timezone=e.timezone,
                country=e.country,
                currency=e.currency,
                impact=e.impact.value,
                status=e.status.value,
                phase=e.get_current_phase(),
                trading_allowed=e.is_trading_allowed(),
                pre_event_start=e.pre_event_start.isoformat(),
                post_event_end=e.post_event_end.isoformat(),
            )
            for e in events
        ],
        total=len(events),
    )


@router.get(
    "/active",
    response_model=EventListResponse,
    summary="Get active event windows",
    description="Get events currently in their event window.",
)
async def get_active_events(
    engine: EventEngine = Depends(get_event_engine),
) -> EventListResponse:
    """Get active event windows."""
    events = engine.calendar.get_active_event_windows()
    
    return EventListResponse(
        events=[
            EventResponse(
                event_id=e.event_id,
                event_type=e.event_type.value,
                name=e.name,
                description=e.description,
                scheduled_time=e.scheduled_time.isoformat(),
                timezone=e.timezone,
                country=e.country,
                currency=e.currency,
                impact=e.impact.value,
                status=e.status.value,
                phase=e.get_current_phase(),
                trading_allowed=e.is_trading_allowed(),
                pre_event_start=e.pre_event_start.isoformat(),
                post_event_end=e.post_event_end.isoformat(),
            )
            for e in events
        ],
        total=len(events),
    )


@router.get(
    "/context",
    response_model=EventContextResponse,
    summary="Get event context",
    description="Get current event context for trading decisions.",
)
async def get_event_context(
    engine: EventEngine = Depends(get_event_engine),
) -> EventContextResponse:
    """Get current event context."""
    context = engine.get_event_context()
    
    return EventContextResponse(
        in_event_window=context["in_event_window"],
        active_events=context["active_events"],
        upcoming_events=context["upcoming_events"],
        position_size_reduction_pct=context["position_size_reduction_pct"],
        spread_filter_multiplier=context["spread_filter_multiplier"],
        trading_allowed=context["trading_allowed"],
    )


@router.get(
    "/{event_id}",
    response_model=EventResponse,
    summary="Get event details",
    description="Get detailed information about a specific event.",
)
async def get_event(
    event_id: str,
    engine: EventEngine = Depends(get_event_engine),
) -> EventResponse:
    """Get event by ID."""
    event = engine.calendar.get_event(event_id)
    
    if not event:
        raise HTTPException(
            status_code=404,
            detail=f"Event {event_id} not found",
        )
    
    return EventResponse(
        event_id=event.event_id,
        event_type=event.event_type.value,
        name=event.name,
        description=event.description,
        scheduled_time=event.scheduled_time.isoformat(),
        timezone=event.timezone,
        country=event.country,
        currency=event.currency,
        impact=event.impact.value,
        status=event.status.value,
        phase=event.get_current_phase(),
        trading_allowed=event.is_trading_allowed(),
        pre_event_start=event.pre_event_start.isoformat(),
        post_event_end=event.post_event_end.isoformat(),
    )


@router.post(
    "/",
    response_model=EventResponse,
    summary="Create event",
    description="Create a new manual event.",
)
async def create_event(
    request: CreateEventRequest,
    engine: EventEngine = Depends(get_event_engine),
) -> EventResponse:
    """Create a new event."""
    try:
        scheduled_time = datetime.fromisoformat(request.scheduled_time)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid scheduled_time format. Use ISO format.",
        )
    
    event = Event(
        event_id=f"manual:{scheduled_time.timestamp()}",
        event_type=EventType(request.event_type),
        name=request.name,
        description=request.description,
        scheduled_time=scheduled_time,
        impact=EventImpact(request.impact),
        pre_event_minutes=request.pre_event_minutes,
        post_event_minutes=request.post_event_minutes,
        trading_disabled=request.trading_disabled,
        size_reduction_pct=request.size_reduction_pct,
    )
    
    engine.calendar.add_event(event)
    
    return EventResponse(
        event_id=event.event_id,
        event_type=event.event_type.value,
        name=event.name,
        description=event.description,
        scheduled_time=event.scheduled_time.isoformat(),
        timezone=event.timezone,
        country=event.country,
        currency=event.currency,
        impact=event.impact.value,
        status=event.status.value,
        phase=event.get_current_phase(),
        trading_allowed=event.is_trading_allowed(),
        pre_event_start=event.pre_event_start.isoformat(),
        post_event_end=event.post_event_end.isoformat(),
    )


@router.post(
    "/{event_id}/result",
    response_model=EventResponse,
    summary="Set event result",
    description="Set the result for an event.",
)
async def set_event_result(
    event_id: str,
    request: SetResultRequest,
    engine: EventEngine = Depends(get_event_engine),
) -> EventResponse:
    """Set event result."""
    event = engine.calendar.set_event_result(
        event_id=event_id,
        actual=request.actual,
        forecast=request.forecast,
        previous=request.previous,
    )
    
    if not event:
        raise HTTPException(
            status_code=404,
            detail=f"Event {event_id} not found",
        )
    
    return EventResponse(
        event_id=event.event_id,
        event_type=event.event_type.value,
        name=event.name,
        description=event.description,
        scheduled_time=event.scheduled_time.isoformat(),
        timezone=event.timezone,
        country=event.country,
        currency=event.currency,
        impact=event.impact.value,
        status=event.status.value,
        phase=event.get_current_phase(),
        trading_allowed=event.is_trading_allowed(),
        pre_event_start=event.pre_event_start.isoformat(),
        post_event_end=event.post_event_end.isoformat(),
    )


@router.post(
    "/schedule/eia",
    response_model=EventListResponse,
    summary="Generate EIA schedule",
    description="Generate EIA crude inventory schedule for upcoming weeks.",
)
async def generate_eia_schedule(
    weeks: int = Query(default=4, ge=1, le=12, description="Number of weeks"),
    engine: EventEngine = Depends(get_event_engine),
) -> EventListResponse:
    """Generate EIA schedule."""
    events = engine.calendar.generate_eia_schedule(
        start_date=datetime.utcnow(),
        weeks=weeks,
    )
    
    return EventListResponse(
        events=[
            EventResponse(
                event_id=e.event_id,
                event_type=e.event_type.value,
                name=e.name,
                description=e.description,
                scheduled_time=e.scheduled_time.isoformat(),
                timezone=e.timezone,
                country=e.country,
                currency=e.currency,
                impact=e.impact.value,
                status=e.status.value,
                phase=e.get_current_phase(),
                trading_allowed=e.is_trading_allowed(),
                pre_event_start=e.pre_event_start.isoformat(),
                post_event_end=e.post_event_end.isoformat(),
            )
            for e in events
        ],
        total=len(events),
    )


@router.get(
    "/stats/summary",
    response_model=dict[str, Any],
    summary="Get event statistics",
    description="Get event engine statistics.",
)
async def get_event_stats(
    engine: EventEngine = Depends(get_event_engine),
) -> dict[str, Any]:
    """Get event statistics."""
    return engine.get_stats()