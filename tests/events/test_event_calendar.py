"""Tests for event calendar."""

import pytest
from datetime import datetime, timedelta

from src.events.calendar import EventCalendar
from src.events.models import Event, EventType, EventImpact, EventStatus


class TestEventCalendar:
    """Test EventCalendar functionality."""
    
    @pytest.fixture
    def calendar(self):
        """Create event calendar for testing."""
        return EventCalendar()
    
    def test_add_event(self, calendar):
        """Test adding event to calendar."""
        event = Event(
            event_id="eia-1",
            event_type=EventType.EIA_CRUDE_INVENTORIES,
            name="EIA Crude",
            scheduled_time=datetime.utcnow() + timedelta(hours=1),
        )
        
        calendar.add_event(event)
        
        assert calendar.get_event("eia-1") == event
    
    def test_remove_event(self, calendar):
        """Test removing event from calendar."""
        event = Event(
            event_id="eia-1",
            event_type=EventType.EIA_CRUDE_INVENTORIES,
            name="EIA Crude",
            scheduled_time=datetime.utcnow() + timedelta(hours=1),
        )
        
        calendar.add_event(event)
        removed = calendar.remove_event("eia-1")
        
        assert removed == event
        assert calendar.get_event("eia-1") is None
    
    def test_get_events_by_type(self, calendar):
        """Test getting events by type."""
        event1 = Event(
            event_id="eia-1",
            event_type=EventType.EIA_CRUDE_INVENTORIES,
            name="EIA Crude",
            scheduled_time=datetime.utcnow() + timedelta(hours=1),
        )
        
        event2 = Event(
            event_id="fomc-1",
            event_type=EventType.FOMC_STATEMENT,
            name="FOMC",
            scheduled_time=datetime.utcnow() + timedelta(hours=2),
        )
        
        calendar.add_event(event1)
        calendar.add_event(event2)
        
        eia_events = calendar.get_events(event_type=EventType.EIA_CRUDE_INVENTORIES)
        
        assert len(eia_events) == 1
        assert eia_events[0].event_id == "eia-1"
    
    def test_get_upcoming_events(self, calendar):
        """Test getting upcoming events."""
        event1 = Event(
            event_id="eia-1",
            event_type=EventType.EIA_CRUDE_INVENTORIES,
            name="EIA Crude",
            scheduled_time=datetime.utcnow() + timedelta(hours=1),
        )
        
        event2 = Event(
            event_id="eia-2",
            event_type=EventType.EIA_CRUDE_INVENTORIES,
            name="EIA Crude 2",
            scheduled_time=datetime.utcnow() + timedelta(hours=25),
        )
        
        calendar.add_event(event1)
        calendar.add_event(event2)
        
        upcoming = calendar.get_upcoming_events(hours=24)
        
        assert len(upcoming) == 1
        assert upcoming[0].event_id == "eia-1"
    
    def test_get_active_event_windows(self, calendar):
        """Test getting active event windows."""
        # Event in pre-window
        event = Event(
            event_id="eia-1",
            event_type=EventType.EIA_CRUDE_INVENTORIES,
            name="EIA Crude",
            scheduled_time=datetime.utcnow() + timedelta(minutes=5),
            pre_event_minutes=10,
        )
        
        calendar.add_event(event)
        
        active = calendar.get_active_event_windows()
        
        assert len(active) == 1
        assert active[0].event_id == "eia-1"
    
    def test_is_trading_allowed(self, calendar):
        """Test trading allowed check."""
        # Event that blocks trading
        event = Event(
            event_id="eia-1",
            event_type=EventType.EIA_CRUDE_INVENTORIES,
            name="EIA Crude",
            scheduled_time=datetime.utcnow() + timedelta(minutes=5),
            pre_event_minutes=10,
            trading_disabled=True,
        )
        
        calendar.add_event(event)
        
        allowed, blocking = calendar.is_trading_allowed()
        
        assert allowed is False
        assert "eia-1" in blocking
    
    def test_generate_eia_schedule(self, calendar):
        """Test EIA schedule generation."""
        start = datetime.utcnow()
        
        events = calendar.generate_eia_schedule(
            start_date=start,
            weeks=2,
        )
        
        assert len(events) == 2
        assert all(e.event_type == EventType.EIA_CRUDE_INVENTORIES for e in events)
    
    def test_add_opec_meeting(self, calendar):
        """Test adding OPEC meeting."""
        scheduled = datetime.utcnow() + timedelta(days=7)
        
        event = calendar.add_opec_meeting(
            scheduled_time=scheduled,
            name="OPEC+ Meeting",
        )
        
        assert event.event_type == EventType.OPEC_MEETING
        assert event.impact == EventImpact.CRITICAL
        assert calendar.get_event(event.event_id) is not None
    
    def test_add_fomc_meeting(self, calendar):
        """Test adding FOMC meeting."""
        scheduled = datetime.utcnow() + timedelta(days=14)
        
        event = calendar.add_fomc_meeting(scheduled_time=scheduled)
        
        assert event.event_type == EventType.FOMC_STATEMENT
        assert event.impact == EventImpact.CRITICAL
    
    def test_set_event_result(self, calendar):
        """Test setting event result."""
        event = Event(
            event_id="eia-1",
            event_type=EventType.EIA_CRUDE_INVENTORIES,
            name="EIA Crude",
            scheduled_time=datetime.utcnow(),
        )
        
        calendar.add_event(event)
        
        updated = calendar.set_event_result(
            event_id="eia-1",
            actual="-2.5",
            forecast="-1.5",
            previous="-3.0",
        )
        
        assert updated is not None
        assert updated.result is not None
        assert updated.result.actual == "-2.5"
        assert updated.status == EventStatus.RELEASED
    
    def test_cleanup_old_events(self, calendar):
        """Test cleaning up old events."""
        # Old event
        old_event = Event(
            event_id="old-1",
            event_type=EventType.EIA_CRUDE_INVENTORIES,
            name="Old EIA",
            scheduled_time=datetime.utcnow() - timedelta(days=10),
        )
        
        # Recent event
        recent_event = Event(
            event_id="recent-1",
            event_type=EventType.EIA_CRUDE_INVENTORIES,
            name="Recent EIA",
            scheduled_time=datetime.utcnow() - timedelta(days=1),
        )
        
        calendar.add_event(old_event)
        calendar.add_event(recent_event)
        
        removed = calendar.cleanup_old_events(days=7)
        
        assert removed == 1
        assert calendar.get_event("old-1") is None
        assert calendar.get_event("recent-1") is not None
    
    def test_get_stats(self, calendar):
        """Test getting calendar statistics."""
        event = Event(
            event_id="eia-1",
            event_type=EventType.EIA_CRUDE_INVENTORIES,
            name="EIA Crude",
            scheduled_time=datetime.utcnow() + timedelta(hours=1),
        )
        
        calendar.add_event(event)
        
        stats = calendar.get_stats()
        
        assert stats["total_events"] == 1
        assert "upcoming_24h" in stats
        assert "events_by_type" in stats