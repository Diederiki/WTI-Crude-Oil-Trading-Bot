"""Event calendar for managing economic events.

Provides scheduling, retrieval, and management of economic events
including EIA releases, OPEC meetings, and other market-moving events.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from src.core.logging_config import get_logger
from src.events.models import Event, EventType, EventImpact, EventStatus

logger = get_logger("events")


class EventCalendar:
    """Calendar for managing economic events.
    
    Maintains a schedule of economic events with support for:
    - Adding/removing events
    - Querying events by time range
    - Getting upcoming events
    - Checking for active event windows
    - EIA-specific event management
    
    Attributes:
        _events: Dictionary of event_id -> Event
        _events_by_type: Index of event_type -> [event_ids]
        _events_by_date: Index of date -> [event_ids]
    """
    
    # Default EIA schedule (Wednesdays at 10:30 AM ET, except holidays)
    EIA_WEEKDAY = 2  # Wednesday
    EIA_HOUR_ET = 10
    EIA_MINUTE = 30
    
    def __init__(self):
        """Initialize event calendar."""
        self._events: dict[str, Event] = {}
        self._events_by_type: dict[EventType, list[str]] = defaultdict(list)
        self._events_by_date: dict[str, list[str]] = defaultdict(list)
        
        logger.info("Event calendar initialized")
    
    def add_event(self, event: Event) -> None:
        """Add an event to the calendar.
        
        Args:
            event: Event to add
        """
        self._events[event.event_id] = event
        self._events_by_type[event.event_type].append(event.event_id)
        
        date_key = event.scheduled_time.strftime("%Y-%m-%d")
        self._events_by_date[date_key].append(event.event_id)
        
        logger.info(
            "Event added to calendar",
            event_id=event.event_id,
            event_type=event.event_type.value,
            scheduled_time=event.scheduled_time.isoformat(),
        )
    
    def remove_event(self, event_id: str) -> Event | None:
        """Remove an event from the calendar.
        
        Args:
            event_id: Event to remove
            
        Returns:
            Removed event or None
        """
        event = self._events.pop(event_id, None)
        
        if event:
            # Remove from indices
            if event_id in self._events_by_type[event.event_type]:
                self._events_by_type[event.event_type].remove(event_id)
            
            date_key = event.scheduled_time.strftime("%Y-%m-%d")
            if event_id in self._events_by_date[date_key]:
                self._events_by_date[date_key].remove(event_id)
        
        return event
    
    def get_event(self, event_id: str) -> Event | None:
        """Get event by ID.
        
        Args:
            event_id: Event identifier
            
        Returns:
            Event or None
        """
        return self._events.get(event_id)
    
    def get_events(
        self,
        event_type: EventType | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        impact: EventImpact | None = None,
        status: EventStatus | None = None,
    ) -> list[Event]:
        """Get events with filtering.
        
        Args:
            event_type: Filter by event type
            start_time: Filter events after this time
            end_time: Filter events before this time
            impact: Filter by impact level
            status: Filter by status
            
        Returns:
            List of matching events
        """
        events = list(self._events.values())
        
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        
        if start_time:
            events = [e for e in events if e.scheduled_time >= start_time]
        
        if end_time:
            events = [e for e in events if e.scheduled_time <= end_time]
        
        if impact:
            events = [e for e in events if e.impact == impact]
        
        if status:
            events = [e for e in events if e.status == status]
        
        return sorted(events, key=lambda e: e.scheduled_time)
    
    def get_upcoming_events(
        self,
        hours: float = 24.0,
        event_type: EventType | None = None,
        min_impact: EventImpact | None = None,
    ) -> list[Event]:
        """Get upcoming events.
        
        Args:
            hours: Look ahead hours
            event_type: Filter by event type
            min_impact: Minimum impact level
            
        Returns:
            List of upcoming events
        """
        now = datetime.utcnow()
        end_time = now + timedelta(hours=hours)
        
        events = self.get_events(
            event_type=event_type,
            start_time=now,
            end_time=end_time,
        )
        
        if min_impact:
            impact_order = {
                EventImpact.LOW: 0,
                EventImpact.MEDIUM: 1,
                EventImpact.HIGH: 2,
                EventImpact.CRITICAL: 3,
            }
            min_level = impact_order.get(min_impact, 0)
            events = [
                e for e in events
                if impact_order.get(e.impact, 0) >= min_level
            ]
        
        return events
    
    def get_active_event_windows(
        self,
        now: datetime | None = None,
    ) -> list[Event]:
        """Get events currently in their event window.
        
        Args:
            now: Current time (default: now)
            
        Returns:
            List of events in active window
        """
        if now is None:
            now = datetime.utcnow()
        
        return [
            e for e in self._events.values()
            if e.is_in_event_window(now)
        ]
    
    def is_trading_allowed(
        self,
        now: datetime | None = None,
    ) -> tuple[bool, list[str]]:
        """Check if trading is allowed.
        
        Args:
            now: Current time (default: now)
            
        Returns:
            Tuple of (allowed, blocking_event_ids)
        """
        if now is None:
            now = datetime.utcnow()
        
        blocking_events = []
        
        for event in self._events.values():
            if not event.is_trading_allowed(now):
                blocking_events.append(event.event_id)
        
        return len(blocking_events) == 0, blocking_events
    
    def get_next_eia_release(self, now: datetime | None = None) -> Event | None:
        """Get next EIA crude inventories release.
        
        Args:
            now: Current time (default: now)
            
        Returns:
            Next EIA event or None
        """
        events = self.get_upcoming_events(
            hours=168,  # 1 week
            event_type=EventType.EIA_CRUDE_INVENTORIES,
        )
        
        return events[0] if events else None
    
    def generate_eia_schedule(
        self,
        start_date: datetime,
        weeks: int = 4,
    ) -> list[Event]:
        """Generate EIA crude inventory schedule.
        
        Creates events for weekly EIA crude inventory releases.
        
        Args:
            start_date: Start date for schedule
            weeks: Number of weeks to generate
            
        Returns:
            List of generated events
        """
        events = []
        
        # Find first Wednesday
        current = start_date
        while current.weekday() != self.EIA_WEEKDAY:
            current += timedelta(days=1)
        
        for i in range(weeks):
            event_date = current + timedelta(weeks=i)
            
            # Convert ET to UTC (ET = UTC-5 or UTC-4 with DST)
            # For simplicity, assume UTC-5 (add 5 hours for UTC)
            scheduled_time = event_date.replace(
                hour=self.EIA_HOUR_ET + 5,
                minute=self.EIA_MINUTE,
                second=0,
                microsecond=0,
            )
            
            event = Event(
                event_id=f"eia_crude:{scheduled_time.strftime('%Y%m%d')}",
                event_type=EventType.EIA_CRUDE_INVENTORIES,
                name="EIA Crude Oil Inventories",
                description="Weekly US crude oil inventory report",
                scheduled_time=scheduled_time,
                timezone="ET",
                country="US",
                currency="USD",
                impact=EventImpact.HIGH,
                pre_event_minutes=10,
                post_event_minutes=30,
                trading_disabled=False,
                size_reduction_pct=50.0,
                spread_filter_multiplier=2.0,
                source="EIA",
                url="https://www.eia.gov/petroleum/supply/weekly/",
            )
            
            self.add_event(event)
            events.append(event)
        
        logger.info(
            "Generated EIA schedule",
            weeks=weeks,
            events_generated=len(events),
        )
        
        return events
    
    def add_opec_meeting(
        self,
        scheduled_time: datetime,
        name: str = "OPEC+ Meeting",
        description: str = "OPEC and allied producers meeting",
    ) -> Event:
        """Add OPEC meeting event.
        
        Args:
            scheduled_time: Meeting time
            name: Event name
            description: Event description
            
        Returns:
            Created event
        """
        event = Event(
            event_id=f"opec:{scheduled_time.strftime('%Y%m%d%H%M')}",
            event_type=EventType.OPEC_MEETING,
            name=name,
            description=description,
            scheduled_time=scheduled_time,
            timezone="UTC",
            country="Global",
            currency="USD",
            impact=EventImpact.CRITICAL,
            pre_event_minutes=60,
            post_event_minutes=120,
            trading_disabled=False,
            size_reduction_pct=75.0,
            spread_filter_multiplier=3.0,
            source="OPEC",
        )
        
        self.add_event(event)
        return event
    
    def add_fomc_meeting(
        self,
        scheduled_time: datetime,
    ) -> Event:
        """Add FOMC meeting event.
        
        Args:
            scheduled_time: Meeting time
            
        Returns:
            Created event
        """
        event = Event(
            event_id=f"fomc:{scheduled_time.strftime('%Y%m%d%H%M')}",
            event_type=EventType.FOMC_STATEMENT,
            name="FOMC Statement",
            description="Federal Reserve monetary policy statement",
            scheduled_time=scheduled_time,
            timezone="ET",
            country="US",
            currency="USD",
            impact=EventImpact.CRITICAL,
            pre_event_minutes=30,
            post_event_minutes=60,
            trading_disabled=False,
            size_reduction_pct=50.0,
            spread_filter_multiplier=2.5,
            source="Federal Reserve",
        )
        
        self.add_event(event)
        return event
    
    def update_event_status(
        self,
        event_id: str,
        status: EventStatus,
    ) -> Event | None:
        """Update event status.
        
        Args:
            event_id: Event to update
            status: New status
            
        Returns:
            Updated event or None
        """
        event = self._events.get(event_id)
        
        if event:
            event.update_status(status)
            logger.info(
                "Event status updated",
                event_id=event_id,
                new_status=status.value,
            )
        
        return event
    
    def set_event_result(
        self,
        event_id: str,
        actual: str,
        forecast: str | None = None,
        previous: str | None = None,
    ) -> Event | None:
        """Set event result.
        
        Args:
            event_id: Event to update
            actual: Actual value
            forecast: Forecast value
            previous: Previous value
            
        Returns:
            Updated event or None
        """
        from src.events.models import EventResult
        
        event = self._events.get(event_id)
        
        if event:
            result = EventResult(
                actual=actual,
                forecast=forecast,
                previous=previous,
            )
            event.set_result(result)
            event.update_status(EventStatus.RELEASED)
            
            logger.info(
                "Event result set",
                event_id=event_id,
                actual=actual,
                surprise_pct=result.surprise_pct,
            )
        
        return event
    
    def cleanup_old_events(self, days: int = 7) -> int:
        """Remove events older than specified days.
        
        Args:
            days: Days to keep
            
        Returns:
            Number of events removed
        """
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        to_remove = [
            event_id for event_id, event in self._events.items()
            if event.scheduled_time < cutoff
        ]
        
        for event_id in to_remove:
            self.remove_event(event_id)
        
        logger.info(
            "Cleaned up old events",
            removed=len(to_remove),
            cutoff=cutoff.isoformat(),
        )
        
        return len(to_remove)
    
    def get_stats(self) -> dict[str, Any]:
        """Get calendar statistics.
        
        Returns:
            Statistics dictionary
        """
        now = datetime.utcnow()
        
        upcoming = self.get_upcoming_events(hours=24)
        active_windows = self.get_active_event_windows(now)
        
        return {
            "total_events": len(self._events),
            "upcoming_24h": len(upcoming),
            "active_windows": len(active_windows),
            "events_by_type": {
                et.value: len(ids) for et, ids in self._events_by_type.items()
            },
            "next_eia": self.get_next_eia_release(now).to_dict() if self.get_next_eia_release(now) else None,
        }