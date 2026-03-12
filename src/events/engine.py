"""Event engine for managing event-driven trading logic.

Integrates event calendar with strategy engine and risk manager to
enable event-aware trading decisions.
"""

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from src.core.logging_config import get_logger
from src.event_bus import EventBus, Event, EventType as BusEventType
from src.events.calendar import EventCalendar
from src.events.models import Event, EventStatus, EventImpact
from src.strategy.engine import StrategyEngine
from src.risk.manager import RiskManager

logger = get_logger("events")


class EventEngine:
    """Event engine for event-aware trading.
    
    Monitors economic events and adjusts trading behavior accordingly:
    - Disables/enables trading around events
    - Adjusts position sizes during events
    - Activates breakout mode for high-impact events
    - Provides event context to strategies
    
    Attributes:
        calendar: Event calendar
        event_bus: Event bus for notifications
        strategy_engine: Strategy engine to control
        risk_manager: Risk manager to adjust
        _check_interval_seconds: How often to check events
        _running: Whether engine is running
        _check_task: Background check task
        _callbacks: Event phase change callbacks
    """
    
    def __init__(
        self,
        calendar: EventCalendar | None = None,
        event_bus: EventBus | None = None,
        strategy_engine: StrategyEngine | None = None,
        risk_manager: RiskManager | None = None,
        check_interval_seconds: float = 10.0,
    ):
        """Initialize event engine.
        
        Args:
            calendar: Event calendar
            event_bus: Event bus
            strategy_engine: Strategy engine to control
            risk_manager: Risk manager to adjust
            check_interval_seconds: Event check interval
        """
        self.calendar = calendar or EventCalendar()
        self.event_bus = event_bus
        self.strategy_engine = strategy_engine
        self.risk_manager = risk_manager
        self._check_interval_seconds = check_interval_seconds
        
        # State
        self._running = False
        self._check_task: asyncio.Task | None = None
        self._callbacks: list[Callable[[Event, str], None]] = []
        
        # Current event context
        self._active_events: list[Event] = []
        self._last_check: datetime = datetime.utcnow()
        
        logger.info("Event engine initialized")
    
    def on_event_phase_change(self, callback: Callable[[Event, str], None]) -> None:
        """Register callback for event phase changes.
        
        Args:
            callback: Function(event, new_phase) to call
        """
        self._callbacks.append(callback)
    
    async def start(self) -> None:
        """Start the event engine."""
        if self._running:
            return
        
        self._running = True
        self._check_task = asyncio.create_task(self._event_check_loop())
        
        logger.info("Event engine started")
    
    async def stop(self) -> None:
        """Stop the event engine."""
        if not self._running:
            return
        
        self._running = False
        
        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Event engine stopped")
    
    async def _event_check_loop(self) -> None:
        """Background loop for checking events."""
        while self._running:
            try:
                await asyncio.sleep(self._check_interval_seconds)
                await self._check_events()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in event check loop", error=str(e))
    
    async def _check_events(self) -> None:
        """Check for event status changes."""
        now = datetime.utcnow()
        
        # Get upcoming events
        upcoming = self.calendar.get_upcoming_events(
            hours=1,
            min_impact=EventImpact.MEDIUM,
        )
        
        # Check for approaching events
        for event in upcoming:
            phase = event.get_current_phase(now)
            
            if phase == "pre" and event.status == EventStatus.SCHEDULED:
                # Event is approaching
                event.update_status(EventStatus.APPROACHING)
                await self._handle_event_approaching(event)
            
            elif phase == "active" and event.status in [EventStatus.SCHEDULED, EventStatus.APPROACHING]:
                # Event is active
                event.update_status(EventStatus.ACTIVE)
                await self._handle_event_active(event)
        
        # Check active events for completion
        for event in list(self._active_events):
            phase = event.get_current_phase(now)
            
            if phase == "none" and event.status != EventStatus.COMPLETED:
                # Event window ended
                event.update_status(EventStatus.COMPLETED)
                await self._handle_event_completed(event)
        
        self._last_check = now
    
    async def _handle_event_approaching(self, event: Event) -> None:
        """Handle event approaching.
        
        Args:
            event: Approaching event
        """
        logger.info(
            "Event approaching",
            event_id=event.event_id,
            event_name=event.name,
            minutes_until=(event.scheduled_time - datetime.utcnow()).total_seconds() / 60,
        )
        
        # Add to active events
        if event not in self._active_events:
            self._active_events.append(event)
        
        # Notify callbacks
        for callback in self._callbacks:
            try:
                callback(event, "approaching")
            except Exception as e:
                logger.error("Error in event callback", error=str(e))
        
        # Publish event
        if self.event_bus:
            await self.event_bus.publish(Event.create(
                event_type=BusEventType.SYSTEM_ALERT,
                source="event_engine",
                payload={
                    "alert_type": "event_approaching",
                    "event": event.to_dict(),
                },
            ))
    
    async def _handle_event_active(self, event: Event) -> None:
        """Handle event becoming active.
        
        Args:
            event: Active event
        """
        logger.info(
            "Event active",
            event_id=event.event_id,
            event_name=event.name,
            impact=event.impact.value,
        )
        
        # Apply event-specific trading adjustments
        if event.trading_disabled:
            logger.warning(
                "Trading disabled for event",
                event_id=event.event_id,
                event_name=event.name,
            )
        
        # Notify callbacks
        for callback in self._callbacks:
            try:
                callback(event, "active")
            except Exception as e:
                logger.error("Error in event callback", error=str(e))
        
        # Publish event
        if self.event_bus:
            await self.event_bus.publish(Event.create(
                event_type=BusEventType.SYSTEM_ALERT,
                source="event_engine",
                payload={
                    "alert_type": "event_active",
                    "event": event.to_dict(),
                },
            ))
    
    async def _handle_event_completed(self, event: Event) -> None:
        """Handle event completion.
        
        Args:
            event: Completed event
        """
        logger.info(
            "Event completed",
            event_id=event.event_id,
            event_name=event.name,
        )
        
        # Remove from active events
        if event in self._active_events:
            self._active_events.remove(event)
        
        # Notify callbacks
        for callback in self._callbacks:
            try:
                callback(event, "completed")
            except Exception as e:
                logger.error("Error in event callback", error=str(e))
        
        # Publish event
        if self.event_bus:
            await self.event_bus.publish(Event.create(
                event_type=BusEventType.SYSTEM_ALERT,
                source="event_engine",
                payload={
                    "alert_type": "event_completed",
                    "event": event.to_dict(),
                },
            ))
    
    def is_trading_allowed(self) -> tuple[bool, list[str]]:
        """Check if trading is allowed based on active events.
        
        Returns:
            Tuple of (allowed, blocking_event_ids)
        """
        return self.calendar.is_trading_allowed()
    
    def get_event_context(self) -> dict[str, Any]:
        """Get current event context for strategies.
        
        Returns:
            Event context dictionary
        """
        now = datetime.utcnow()
        
        active_windows = self.calendar.get_active_event_windows(now)
        upcoming = self.calendar.get_upcoming_events(hours=1, min_impact=EventImpact.MEDIUM)
        
        # Calculate position size adjustment
        size_reduction = 0.0
        spread_multiplier = 1.0
        
        for event in active_windows:
            size_reduction = max(size_reduction, event.size_reduction_pct)
            spread_multiplier = max(spread_multiplier, event.spread_filter_multiplier)
        
        return {
            "in_event_window": len(active_windows) > 0,
            "active_events": [e.to_dict() for e in active_windows],
            "upcoming_events": [e.to_dict() for e in upcoming[:3]],
            "position_size_reduction_pct": size_reduction,
            "spread_filter_multiplier": spread_multiplier,
            "trading_allowed": len([e for e in active_windows if e.trading_disabled]) == 0,
        }
    
    def get_adjusted_position_size(self, base_size: int) -> int:
        """Get position size adjusted for events.
        
        Args:
            base_size: Base position size
            
        Returns:
            Adjusted position size
        """
        context = self.get_event_context()
        reduction_pct = context.get("position_size_reduction_pct", 0.0)
        
        if reduction_pct > 0:
            adjusted = int(base_size * (1 - reduction_pct / 100))
            return max(1, adjusted)
        
        return base_size
    
    def get_adjusted_spread_filter(self, base_filter: float) -> float:
        """Get spread filter adjusted for events.
        
        Args:
            base_filter: Base spread filter
            
        Returns:
            Adjusted spread filter
        """
        context = self.get_event_context()
        multiplier = context.get("spread_filter_multiplier", 1.0)
        
        return base_filter * multiplier
    
    def should_enable_breakout_mode(self) -> bool:
        """Check if breakout mode should be enabled.
        
        Returns:
            True if breakout mode should be active
        """
        now = datetime.utcnow()
        active_windows = self.calendar.get_active_event_windows(now)
        
        # Enable breakout mode for high-impact events
        for event in active_windows:
            if event.impact in [EventImpact.HIGH, EventImpact.CRITICAL]:
                if event.event_type in [
                    EventType.EIA_CRUDE_INVENTORIES,
                    EventType.OPEC_MEETING,
                    EventType.FOMC_STATEMENT,
                ]:
                    return True
        
        return False
    
    def initialize_default_schedule(self, weeks: int = 4) -> None:
        """Initialize default event schedule.
        
        Args:
            weeks: Number of weeks to schedule
        """
        # Generate EIA schedule
        self.calendar.generate_eia_schedule(
            start_date=datetime.utcnow(),
            weeks=weeks,
        )
        
        logger.info(
            "Default event schedule initialized",
            weeks=weeks,
        )
    
    def add_manual_event(
        self,
        event_type: str,
        name: str,
        scheduled_time: datetime,
        impact: str = "high",
    ) -> Event:
        """Add a manual event.
        
        Args:
            event_type: Event type string
            name: Event name
            scheduled_time: Event time
            impact: Impact level
            
        Returns:
            Created event
        """
        from src.events.models import EventType, EventImpact
        
        event = Event(
            event_id=f"manual:{scheduled_time.timestamp()}",
            event_type=EventType(event_type),
            name=name,
            scheduled_time=scheduled_time,
            impact=EventImpact(impact),
        )
        
        self.calendar.add_event(event)
        return event
    
    def get_stats(self) -> dict[str, Any]:
        """Get event engine statistics.
        
        Returns:
            Statistics dictionary
        """
        return {
            "running": self._running,
            "active_events": len(self._active_events),
            "calendar_stats": self.calendar.get_stats(),
            "event_context": self.get_event_context(),
            "breakout_mode": self.should_enable_breakout_mode(),
        }