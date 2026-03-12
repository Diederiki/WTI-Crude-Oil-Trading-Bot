"""Tests for event models."""

import pytest
from datetime import datetime, timedelta

from src.events.models import (
    Event,
    EventType,
    EventImpact,
    EventStatus,
    EventResult,
    EventWindowConfig,
)


class TestEventResult:
    """Test EventResult model."""
    
    def test_result_creation(self):
        """Test creating event result."""
        result = EventResult(
            actual="-2.5",
            forecast="-1.5",
            previous="-3.0",
        )
        
        assert result.actual == "-2.5"
        assert result.forecast == "-1.5"
        assert result.previous == "-3.0"
    
    def test_calculate_surprise(self):
        """Test surprise calculation."""
        result = EventResult(
            actual="-2.5",
            forecast="-1.5",
        )
        
        # Surprise = (-2.5 - (-1.5)) / |-1.5| * 100 = -66.67%
        surprise = result.calculate_surprise()
        assert surprise is not None
        assert abs(surprise - (-66.67)) < 0.01
    
    def test_calculate_surprise_no_forecast(self):
        """Test surprise calculation without forecast."""
        result = EventResult(actual="-2.5")
        
        surprise = result.calculate_surprise()
        assert surprise is None


class TestEvent:
    """Test Event model."""
    
    def test_event_creation(self):
        """Test creating an event."""
        event = Event(
            event_id="eia-20240101",
            event_type=EventType.EIA_CRUDE_INVENTORIES,
            name="EIA Crude Oil Inventories",
            scheduled_time=datetime.utcnow() + timedelta(hours=1),
            impact=EventImpact.HIGH,
        )
        
        assert event.event_id == "eia-20240101"
        assert event.event_type == EventType.EIA_CRUDE_INVENTORIES
        assert event.impact == EventImpact.HIGH
        assert event.status == EventStatus.SCHEDULED
    
    def test_is_high_impact(self):
        """Test high impact check."""
        high_event = Event(
            event_id="eia-1",
            event_type=EventType.EIA_CRUDE_INVENTORIES,
            name="EIA",
            scheduled_time=datetime.utcnow(),
            impact=EventImpact.HIGH,
        )
        
        low_event = Event(
            event_id="low-1",
            event_type=EventType.EIA_CRUDE_INVENTORIES,
            name="Low",
            scheduled_time=datetime.utcnow(),
            impact=EventImpact.LOW,
        )
        
        assert high_event.is_high_impact is True
        assert low_event.is_high_impact is False
    
    def test_pre_event_start(self):
        """Test pre-event start calculation."""
        scheduled = datetime.utcnow() + timedelta(hours=1)
        
        event = Event(
            event_id="eia-1",
            event_type=EventType.EIA_CRUDE_INVENTORIES,
            name="EIA",
            scheduled_time=scheduled,
            pre_event_minutes=10,
        )
        
        expected_start = scheduled - timedelta(minutes=10)
        assert event.pre_event_start == expected_start
    
    def test_post_event_end(self):
        """Test post-event end calculation."""
        scheduled = datetime.utcnow() + timedelta(hours=1)
        
        event = Event(
            event_id="eia-1",
            event_type=EventType.EIA_CRUDE_INVENTORIES,
            name="EIA",
            scheduled_time=scheduled,
            post_event_minutes=30,
        )
        
        expected_end = scheduled + timedelta(minutes=30)
        assert event.post_event_end == expected_end
    
    def test_get_current_phase_pre(self):
        """Test phase detection - pre-event."""
        scheduled = datetime.utcnow() + timedelta(minutes=5)
        
        event = Event(
            event_id="eia-1",
            event_type=EventType.EIA_CRUDE_INVENTORIES,
            name="EIA",
            scheduled_time=scheduled,
            pre_event_minutes=10,
        )
        
        assert event.get_current_phase() == "pre"
    
    def test_get_current_phase_post(self):
        """Test phase detection - post-event."""
        scheduled = datetime.utcnow() - timedelta(minutes=5)
        
        event = Event(
            event_id="eia-1",
            event_type=EventType.EIA_CRUDE_INVENTORIES,
            name="EIA",
            scheduled_time=scheduled,
            post_event_minutes=30,
        )
        
        assert event.get_current_phase() == "post"
    
    def test_get_current_phase_none(self):
        """Test phase detection - no event window."""
        scheduled = datetime.utcnow() + timedelta(hours=2)
        
        event = Event(
            event_id="eia-1",
            event_type=EventType.EIA_CRUDE_INVENTORIES,
            name="EIA",
            scheduled_time=scheduled,
            pre_event_minutes=10,
        )
        
        assert event.get_current_phase() == "none"
    
    def test_is_in_event_window(self):
        """Test event window check."""
        scheduled = datetime.utcnow() + timedelta(minutes=5)
        
        event = Event(
            event_id="eia-1",
            event_type=EventType.EIA_CRUDE_INVENTORIES,
            name="EIA",
            scheduled_time=scheduled,
            pre_event_minutes=10,
            post_event_minutes=30,
        )
        
        assert event.is_in_event_window() is True
    
    def test_is_trading_allowed(self):
        """Test trading allowed check."""
        scheduled = datetime.utcnow() + timedelta(minutes=5)
        
        # Trading not disabled
        event = Event(
            event_id="eia-1",
            event_type=EventType.EIA_CRUDE_INVENTORIES,
            name="EIA",
            scheduled_time=scheduled,
            pre_event_minutes=10,
            trading_disabled=False,
        )
        
        assert event.is_trading_allowed() is True
        
        # Trading disabled
        event_disabled = Event(
            event_id="eia-2",
            event_type=EventType.EIA_CRUDE_INVENTORIES,
            name="EIA",
            scheduled_time=scheduled,
            pre_event_minutes=10,
            trading_disabled=True,
        )
        
        assert event_disabled.is_trading_allowed() is False
    
    def test_update_status(self):
        """Test status update."""
        event = Event(
            event_id="eia-1",
            event_type=EventType.EIA_CRUDE_INVENTORIES,
            name="EIA",
            scheduled_time=datetime.utcnow(),
        )
        
        assert event.status == EventStatus.SCHEDULED
        
        event.update_status(EventStatus.ACTIVE)
        assert event.status == EventStatus.ACTIVE
    
    def test_set_result(self):
        """Test setting result."""
        event = Event(
            event_id="eia-1",
            event_type=EventType.EIA_CRUDE_INVENTORIES,
            name="EIA",
            scheduled_time=datetime.utcnow(),
        )
        
        result = EventResult(
            actual="-2.5",
            forecast="-1.5",
            previous="-3.0",
        )
        
        event.set_result(result)
        
        assert event.result is not None
        assert event.result.actual == "-2.5"


class TestEventWindowConfig:
    """Test EventWindowConfig model."""
    
    def test_config_creation(self):
        """Test creating window config."""
        config = EventWindowConfig(
            event_type=EventType.EIA_CRUDE_INVENTORIES,
            pre_event_minutes=10,
            post_event_minutes=30,
            trading_disabled=False,
            size_reduction_pct=50.0,
        )
        
        assert config.event_type == EventType.EIA_CRUDE_INVENTORIES
        assert config.pre_event_minutes == 10
        assert config.size_reduction_pct == 50.0