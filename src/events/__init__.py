"""Event and news engine module.

Provides economic event calendar, event scheduling, and event-based
trading controls for news-driven strategies.
"""

from src.events.models import Event, EventType, EventImpact, EventStatus
from src.events.calendar import EventCalendar
from src.events.engine import EventEngine

__all__ = [
    "Event",
    "EventType",
    "EventImpact",
    "EventStatus",
    "EventCalendar",
    "EventEngine",
]