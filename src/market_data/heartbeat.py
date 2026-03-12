"""Feed heartbeat and health monitoring system.

Provides continuous monitoring of feed health with configurable thresholds
for latency, message rate, and stale feed detection.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from src.core.logging_config import get_logger
from src.market_data.models.events import FeedHealth

logger = get_logger("market_data")


@dataclass
class HeartbeatThresholds:
    """Configuration thresholds for heartbeat monitoring."""
    
    max_latency_ms: float = 1000.0
    """Maximum acceptable latency in milliseconds."""
    
    min_messages_per_second: float = 1.0
    """Minimum acceptable message rate."""
    
    stale_threshold_ms: float = 5000.0
    """Milliseconds without message to be considered stale."""
    
    max_errors_per_minute: int = 10
    """Maximum errors before marking unhealthy."""
    
    max_reconnects_per_hour: int = 5
    """Maximum reconnections before marking unhealthy."""


@dataclass
class HeartbeatMetrics:
    """Metrics collected for heartbeat monitoring."""
    
    feed_id: str
    last_heartbeat: datetime = field(default_factory=datetime.utcnow)
    messages_received: int = 0
    messages_last_interval: int = 0
    avg_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    errors_count: int = 0
    errors_last_interval: int = 0
    reconnects_count: int = 0
    latency_samples: list[float] = field(default_factory=list)
    
    def record_message(self, latency_ms: float | None = None) -> None:
        """Record a message receipt.
        
        Args:
            latency_ms: Optional latency measurement
        """
        self.messages_received += 1
        self.messages_last_interval += 1
        self.last_heartbeat = datetime.utcnow()
        
        if latency_ms is not None:
            self.latency_samples.append(latency_ms)
            # Keep only recent samples
            if len(self.latency_samples) > 100:
                self.latency_samples = self.latency_samples[-100:]
            
            self.avg_latency_ms = sum(self.latency_samples) / len(self.latency_samples)
            self.max_latency_ms = max(self.latency_samples)
    
    def record_error(self) -> None:
        """Record an error."""
        self.errors_count += 1
        self.errors_last_interval += 1
    
    def record_reconnect(self) -> None:
        """Record a reconnection."""
        self.reconnects_count += 1
    
    def reset_interval_counters(self) -> None:
        """Reset interval-based counters."""
        self.messages_last_interval = 0
        self.errors_last_interval = 0
    
    def time_since_last_heartbeat_ms(self) -> float:
        """Get milliseconds since last heartbeat."""
        return (datetime.utcnow() - self.last_heartbeat).total_seconds() * 1000
    
    def is_stale(self, threshold_ms: float) -> bool:
        """Check if feed is stale."""
        return self.time_since_last_heartbeat_ms() > threshold_ms


class FeedHeartbeatMonitor:
    """Monitors feed health via heartbeat mechanism.
    
    Continuously monitors feed health by tracking message rates,
    latencies, and errors. Can trigger alerts and automatic actions.
    
    Attributes:
        feed_id: ID of feed being monitored
        thresholds: Health thresholds
        metrics: Current metrics
        on_unhealthy: Callback when feed becomes unhealthy
        on_stale: Callback when feed becomes stale
        _running: Whether monitoring is active
        _monitor_task: Background monitoring task
    """
    
    def __init__(
        self,
        feed_id: str,
        thresholds: HeartbeatThresholds | None = None,
        on_unhealthy: callable | None = None,
        on_stale: callable | None = None,
        check_interval_seconds: float = 5.0,
    ):
        """Initialize heartbeat monitor.
        
        Args:
            feed_id: Feed identifier
            thresholds: Health thresholds
            on_unhealthy: Callback when feed becomes unhealthy
            on_stale: Callback when feed becomes stale
            check_interval_seconds: How often to check health
        """
        self.feed_id = feed_id
        self.thresholds = thresholds or HeartbeatThresholds()
        self.metrics = HeartbeatMetrics(feed_id=feed_id)
        self.on_unhealthy = on_unhealthy
        self.on_stale = on_stale
        self.check_interval_seconds = check_interval_seconds
        
        self._running = False
        self._monitor_task: asyncio.Task | None = None
        self._health_status = FeedHealth.UNKNOWN
        self._status_history: list[tuple[datetime, FeedHealth, str]] = []
        
        logger.info(
            "Heartbeat monitor initialized",
            feed_id=feed_id,
            check_interval=check_interval_seconds,
        )
    
    async def start(self) -> None:
        """Start heartbeat monitoring."""
        if self._running:
            return
        
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        
        logger.info("Heartbeat monitor started", feed_id=self.feed_id)
    
    async def stop(self) -> None:
        """Stop heartbeat monitoring."""
        if not self._running:
            return
        
        self._running = False
        
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Heartbeat monitor stopped", feed_id=self.feed_id)
    
    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                await asyncio.sleep(self.check_interval_seconds)
                
                # Check health
                new_status, reason = self._check_health()
                
                if new_status != self._health_status:
                    await self._status_change(new_status, reason)
                
                # Reset interval counters
                self.metrics.reset_interval_counters()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    "Error in monitor loop",
                    feed_id=self.feed_id,
                    error=str(e),
                )
    
    def _check_health(self) -> tuple[FeedHealth, str]:
        """Check current health status.
        
        Returns:
            Tuple of (health_status, reason)
        """
        # Check stale
        if self.metrics.is_stale(self.thresholds.stale_threshold_ms):
            if self.on_stale:
                asyncio.create_task(self._trigger_callback(self.on_stale))
            return FeedHealth.DEGRADED, f"Stale for {self.metrics.time_since_last_heartbeat_ms():.0f}ms"
        
        # Check message rate
        interval_seconds = self.check_interval_seconds
        msg_rate = self.metrics.messages_last_interval / interval_seconds
        
        if msg_rate < self.thresholds.min_messages_per_second:
            return (
                FeedHealth.DEGRADED,
                f"Low message rate: {msg_rate:.2f}/s"
            )
        
        # Check latency
        if self.metrics.avg_latency_ms > self.thresholds.max_latency_ms:
            return (
                FeedHealth.DEGRADED,
                f"High latency: {self.metrics.avg_latency_ms:.2f}ms"
            )
        
        # Check errors
        error_rate = self.metrics.errors_last_interval / interval_seconds
        if error_rate > self.thresholds.max_errors_per_minute / 60:
            return (
                FeedHealth.UNHEALTHY,
                f"High error rate: {error_rate:.2f}/s"
            )
        
        return FeedHealth.HEALTHY, "All metrics within thresholds"
    
    async def _status_change(self, new_status: FeedHealth, reason: str) -> None:
        """Handle status change.
        
        Args:
            new_status: New health status
            reason: Reason for change
        """
        old_status = self._health_status
        self._health_status = new_status
        
        self._status_history.append((
            datetime.utcnow(),
            new_status,
            reason,
        ))
        
        logger.info(
            "Health status changed",
            feed_id=self.feed_id,
            old_status=old_status,
            new_status=new_status,
            reason=reason,
        )
        
        if new_status == FeedHealth.UNHEALTHY and self.on_unhealthy:
            await self._trigger_callback(self.on_unhealthy)
    
    async def _trigger_callback(self, callback: callable) -> None:
        """Trigger a callback safely.
        
        Args:
            callback: Callback function to trigger
        """
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(self.feed_id, self.metrics)
            else:
                callback(self.feed_id, self.metrics)
        except Exception as e:
            logger.error(
                "Error in callback",
                feed_id=self.feed_id,
                error=str(e),
            )
    
    def record_message(self, latency_ms: float | None = None) -> None:
        """Record a message receipt.
        
        Args:
            latency_ms: Optional latency measurement
        """
        self.metrics.record_message(latency_ms)
    
    def record_error(self) -> None:
        """Record an error."""
        self.metrics.record_error()
    
    def record_reconnect(self) -> None:
        """Record a reconnection."""
        self.metrics.record_reconnect()
    
    def get_status(self) -> dict[str, Any]:
        """Get current status summary.
        
        Returns:
            Status dictionary
        """
        return {
            "feed_id": self.feed_id,
            "health": self._health_status.value,
            "metrics": {
                "messages_received": self.metrics.messages_received,
                "messages_per_second": self.metrics.messages_last_interval / self.check_interval_seconds,
                "avg_latency_ms": self.metrics.avg_latency_ms,
                "max_latency_ms": self.metrics.max_latency_ms,
                "errors_count": self.metrics.errors_count,
                "reconnects_count": self.metrics.reconnects_count,
                "ms_since_last_message": self.metrics.time_since_last_heartbeat_ms(),
            },
            "thresholds": {
                "max_latency_ms": self.thresholds.max_latency_ms,
                "min_messages_per_second": self.thresholds.min_messages_per_second,
                "stale_threshold_ms": self.thresholds.stale_threshold_ms,
            },
        }
    
    def get_health(self) -> FeedHealth:
        """Get current health status.
        
        Returns:
            Current health status
        """
        return self._health_status
    
    def is_healthy(self) -> bool:
        """Check if feed is healthy.
        
        Returns:
            True if healthy
        """
        return self._health_status == FeedHealth.HEALTHY