"""Event bus implementation for internal pub/sub.

Provides both in-memory and Redis-backed event distribution for
communication between system components.
"""

import asyncio
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from src.core.logging_config import get_logger
from src.core.redis_client import RedisClient
from src.event_bus.events import Event, EventType

logger = get_logger("event_bus")


class EventBus:
    """Event bus for internal pub/sub communication.
    
    Supports both in-memory (fast, single-process) and Redis-backed
    (cross-process) event distribution. Subscribers can filter by
    event type or receive all events.
    
    Attributes:
        redis: Optional Redis client for cross-process pub/sub
        _subscribers: In-memory subscribers by event type
        _global_subscribers: Subscribers receiving all events
        _running: Whether event bus is running
        _publish_queue: Queue for async publishing
    """
    
    def __init__(self, redis: RedisClient | None = None):
        """Initialize event bus.
        
        Args:
            redis: Optional Redis client for cross-process pub/sub
        """
        self.redis = redis
        self._subscribers: dict[EventType, list[Callable[[Event], None]]] = defaultdict(list)
        self._global_subscribers: list[Callable[[Event], None]] = []
        self._running = False
        self._publish_queue: asyncio.Queue[Event] | None = None
        self._publish_task: asyncio.Task | None = None
        
        logger.info("Event bus initialized", has_redis=redis is not None)
    
    async def start(self) -> None:
        """Start the event bus."""
        if self._running:
            return
        
        self._running = True
        self._publish_queue = asyncio.Queue()
        self._publish_task = asyncio.create_task(self._publish_loop())
        
        # Start Redis subscriber if available
        if self.redis:
            asyncio.create_task(self._redis_subscribe_loop())
        
        logger.info("Event bus started")
    
    async def stop(self) -> None:
        """Stop the event bus."""
        if not self._running:
            return
        
        self._running = False
        
        if self._publish_task:
            self._publish_task.cancel()
            try:
                await self._publish_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Event bus stopped")
    
    def subscribe(
        self,
        callback: Callable[[Event], None],
        event_type: EventType | None = None,
    ) -> None:
        """Subscribe to events.
        
        Args:
            callback: Function to call when event is received
            event_type: Optional specific event type to filter
        """
        if event_type:
            self._subscribers[event_type].append(callback)
            logger.debug(
                "Subscribed to event type",
                event_type=event_type.value,
                callback=callback.__name__ if hasattr(callback, "__name__") else "anonymous",
            )
        else:
            self._global_subscribers.append(callback)
            logger.debug(
                "Subscribed to all events",
                callback=callback.__name__ if hasattr(callback, "__name__") else "anonymous",
            )
    
    def unsubscribe(
        self,
        callback: Callable[[Event], None],
        event_type: EventType | None = None,
    ) -> None:
        """Unsubscribe from events.
        
        Args:
            callback: Callback to remove
            event_type: Optional specific event type
        """
        if event_type:
            if callback in self._subscribers[event_type]:
                self._subscribers[event_type].remove(callback)
        else:
            if callback in self._global_subscribers:
                self._global_subscribers.remove(callback)
    
    async def publish(self, event: Event) -> None:
        """Publish an event.
        
        Args:
            event: Event to publish
        """
        if not self._running:
            logger.warning("Event bus not running, dropping event", event_type=event.event_type.value)
            return
        
        # Queue for async processing
        if self._publish_queue:
            await self._publish_queue.put(event)
        
        # Also publish to Redis if available
        if self.redis:
            try:
                await self.redis.publish(
                    f"events:{event.event_type.value}",
                    event.model_dump_json(),
                )
            except Exception as e:
                logger.error("Failed to publish to Redis", error=str(e))
    
    async def publish_immediate(self, event: Event) -> None:
        """Publish event immediately without queuing.
        
        Args:
            event: Event to publish
        """
        await self._dispatch(event)
    
    async def _publish_loop(self) -> None:
        """Background loop for processing publish queue."""
        while self._running:
            try:
                event = await self._publish_queue.get()
                await self._dispatch(event)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in publish loop", error=str(e))
    
    async def _dispatch(self, event: Event) -> None:
        """Dispatch event to all subscribers.
        
        Args:
            event: Event to dispatch
        """
        # Dispatch to type-specific subscribers
        callbacks = self._subscribers.get(event.event_type, [])
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    asyncio.create_task(callback(event))
                else:
                    callback(event)
            except Exception as e:
                logger.error(
                    "Error in event callback",
                    event_type=event.event_type.value,
                    error=str(e),
                )
        
        # Dispatch to global subscribers
        for callback in self._global_subscribers:
            try:
                if asyncio.iscoroutinefunction(callback):
                    asyncio.create_task(callback(event))
                else:
                    callback(event)
            except Exception as e:
                logger.error(
                    "Error in global event callback",
                    event_type=event.event_type.value,
                    error=str(e),
                )
    
    async def _redis_subscribe_loop(self) -> None:
        """Background loop for Redis pub/sub."""
        if not self.redis:
            return
        
        # Subscribe to all event channels
        channels = [f"events:{et.value}" for et in EventType]
        
        try:
            async for message in self.redis.subscribe(channels):
                if not self._running:
                    break
                
                try:
                    # Parse event from Redis message
                    event_data = message.get("data", {})
                    event = Event.parse_raw(event_data)
                    await self._dispatch(event)
                except Exception as e:
                    logger.error("Error processing Redis message", error=str(e))
        except Exception as e:
            logger.error("Redis subscribe loop error", error=str(e))
    
    def get_subscriber_counts(self) -> dict[str, int]:
        """Get subscriber counts by event type.
        
        Returns:
            Dictionary of event type -> subscriber count
        """
        counts = {et.value: len(subs) for et, subs in self._subscribers.items()}
        counts["__global__"] = len(self._global_subscribers)
        return counts


# Global event bus instance
_event_bus: EventBus | None = None


def get_event_bus(redis: RedisClient | None = None) -> EventBus:
    """Get or create global event bus instance.
    
    Args:
        redis: Optional Redis client
        
    Returns:
        EventBus instance
    """
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus(redis=redis)
    return _event_bus


def reset_event_bus() -> None:
    """Reset global event bus (for testing)."""
    global _event_bus
    _event_bus = None