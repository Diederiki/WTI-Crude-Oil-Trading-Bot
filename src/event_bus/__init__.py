"""Event bus for internal pub/sub communication.

Provides decoupled communication between components using an in-memory
event bus with optional Redis backing for cross-process communication.
"""

from src.event_bus.bus import EventBus, get_event_bus
from src.event_bus.events import Event, EventType

__all__ = ["EventBus", "get_event_bus", "Event", "EventType"]