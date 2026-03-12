"""Service health monitoring and status tracking.

This module provides health monitoring for various services including:
- Database connectivity
- Redis connectivity
- Market data feeds
- External APIs

It tracks health status over time and can trigger alerts when
services become unhealthy.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, ClassVar

from src.config.settings import Settings, get_settings
from src.core.logging_config import get_logger

logger = get_logger("system")


class ServiceStatus(str, Enum):
    """Service health status enumeration."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ServiceHealth:
    """Individual service health information."""

    name: str
    status: ServiceStatus = ServiceStatus.UNKNOWN
    last_check: datetime | None = None
    last_success: datetime | None = None
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    response_time_ms: float = 0.0
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def record_success(self, response_time_ms: float, metadata: dict | None = None) -> None:
        """Record a successful health check.

        Args:
            response_time_ms: Response time in milliseconds.
            metadata: Optional metadata about the check.
        """
        self.status = ServiceStatus.HEALTHY
        self.last_check = datetime.utcnow()
        self.last_success = datetime.utcnow()
        self.consecutive_failures = 0
        self.consecutive_successes += 1
        self.response_time_ms = response_time_ms
        self.error_message = None
        if metadata:
            self.metadata.update(metadata)

    def record_failure(self, error: str, response_time_ms: float = 0) -> None:
        """Record a failed health check.

        Args:
            error: Error message.
            response_time_ms: Response time in milliseconds.
        """
        self.last_check = datetime.utcnow()
        self.consecutive_failures += 1
        self.consecutive_successes = 0
        self.response_time_ms = response_time_ms
        self.error_message = error

        # Determine status based on consecutive failures
        if self.consecutive_failures >= 5:
            self.status = ServiceStatus.UNHEALTHY
        elif self.consecutive_failures >= 2:
            self.status = ServiceStatus.DEGRADED

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation.

        Returns:
            Dictionary with health information.
        """
        return {
            "name": self.name,
            "status": self.status.value,
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "last_success": self.last_success.isoformat() if self.last_success else None,
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
            "response_time_ms": round(self.response_time_ms, 2),
            "error_message": self.error_message,
            "metadata": self.metadata,
        }


class ServiceHealthMonitor:
    """Monitor and track health of system services.

    This class provides centralized health monitoring for all system
    services. It tracks health status over time and can run periodic
    health checks.

    Example:
        >>> monitor = ServiceHealthMonitor()
        >>> monitor.register_service("database")
        >>> monitor.update_health("database", ServiceStatus.HEALTHY)
        >>> status = monitor.get_status()
    """

    _instance: ClassVar["ServiceHealthMonitor | None"] = None
    _lock: ClassVar[asyncio.Lock] = asyncio.Lock()

    def __new__(cls, *args: Any, **kwargs: Any) -> "ServiceHealthMonitor":
        """Singleton pattern to ensure single monitor instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize the health monitor.

        Args:
            settings: Application settings.
        """
        # Only initialize once
        if hasattr(self, "_initialized"):
            return

        self.settings = settings or get_settings()
        self._services: dict[str, ServiceHealth] = {}
        self._check_task: asyncio.Task | None = None
        self._running = False
        self._initialized = True

        # Register default services
        self.register_service("database")
        self.register_service("redis")
        self.register_service("market_data_feed")

    def register_service(self, name: str) -> ServiceHealth:
        """Register a new service for health monitoring.

        Args:
            name: Service name.

        Returns:
            ServiceHealth instance for the registered service.
        """
        if name not in self._services:
            self._services[name] = ServiceHealth(name=name)
            logger.info(f"Registered service for health monitoring: {name}")
        return self._services[name]

    def unregister_service(self, name: str) -> None:
        """Unregister a service from health monitoring.

        Args:
            name: Service name.
        """
        if name in self._services:
            del self._services[name]
            logger.info(f"Unregistered service from health monitoring: {name}")

    def update_health(
        self,
        name: str,
        status: ServiceStatus,
        response_time_ms: float = 0,
        error: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Update health status for a service.

        Args:
            name: Service name.
            status: New health status.
            response_time_ms: Response time in milliseconds.
            error: Error message if unhealthy.
            metadata: Optional metadata.
        """
        if name not in self._services:
            self.register_service(name)

        service = self._services[name]

        if status == ServiceStatus.HEALTHY:
            service.record_success(response_time_ms, metadata)
        else:
            service.record_failure(error or "Unknown error", response_time_ms)

        # Log status changes
        if service.consecutive_failures == 1:
            logger.warning(f"Service {name} health check failed", error=error)
        elif service.consecutive_failures == 5:
            logger.error(f"Service {name} marked as unhealthy", error=error)

    def get_service_health(self, name: str) -> ServiceHealth | None:
        """Get health information for a specific service.

        Args:
            name: Service name.

        Returns:
            ServiceHealth instance or None if not found.
        """
        return self._services.get(name)

    def get_status(self) -> dict[str, Any]:
        """Get health status for all registered services.

        Returns:
            Dictionary with health status for all services.
        """
        return {
            "overall": self._get_overall_status(),
            "services": {
                name: health.to_dict() for name, health in self._services.items()
            },
            "checked_at": datetime.utcnow().isoformat(),
        }

    def _get_overall_status(self) -> str:
        """Calculate overall system health status.

        Returns:
            Overall status string.
        """
        if not self._services:
            return ServiceStatus.UNKNOWN.value

        statuses = [s.status for s in self._services.values()]

        if any(s == ServiceStatus.UNHEALTHY for s in statuses):
            return ServiceStatus.UNHEALTHY.value
        elif any(s == ServiceStatus.DEGRADED for s in statuses):
            return ServiceStatus.DEGRADED.value
        elif all(s == ServiceStatus.HEALTHY for s in statuses):
            return ServiceStatus.HEALTHY.value
        else:
            return ServiceStatus.UNKNOWN.value

    async def start_periodic_checks(self, interval_seconds: int | None = None) -> None:
        """Start periodic health checks.

        Args:
            interval_seconds: Check interval in seconds. Uses settings default if None.
        """
        if self._running:
            logger.warning("Periodic health checks already running")
            return

        interval = interval_seconds or self.settings.health.check_interval
        self._running = True

        logger.info(f"Starting periodic health checks (interval: {interval}s)")

        self._check_task = asyncio.create_task(
            self._run_periodic_checks(interval)
        )

    async def stop_periodic_checks(self) -> None:
        """Stop periodic health checks."""
        if not self._running:
            return

        self._running = False

        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
            self._check_task = None

        logger.info("Stopped periodic health checks")

    async def _run_periodic_checks(self, interval_seconds: int) -> None:
        """Run periodic health checks loop.

        Args:
            interval_seconds: Check interval in seconds.
        """
        from src.core.database import check_database_health
        from src.core.redis_client import get_redis_client

        while self._running:
            try:
                # Check database health
                try:
                    db_health = await check_database_health()
                    if db_health.get("status") == "healthy":
                        self.update_health(
                            "database",
                            ServiceStatus.HEALTHY,
                            db_health.get("response_time_ms", 0),
                        )
                    else:
                        self.update_health(
                            "database",
                            ServiceStatus.UNHEALTHY,
                            db_health.get("response_time_ms", 0),
                            db_health.get("error"),
                        )
                except Exception as e:
                    self.update_health(
                        "database",
                        ServiceStatus.UNHEALTHY,
                        error=str(e),
                    )

                # Check Redis health
                try:
                    redis_client = await get_redis_client(self.settings)
                    redis_health = await redis_client.health_check()
                    if redis_health.get("status") == "healthy":
                        self.update_health(
                            "redis",
                            ServiceStatus.HEALTHY,
                            redis_health.get("response_time_ms", 0),
                            metadata={
                                "version": redis_health.get("version"),
                                "connected_clients": redis_health.get("connected_clients"),
                            },
                        )
                    else:
                        self.update_health(
                            "redis",
                            ServiceStatus.UNHEALTHY,
                            redis_health.get("response_time_ms", 0),
                            redis_health.get("error"),
                        )
                except Exception as e:
                    self.update_health(
                        "redis",
                        ServiceStatus.UNHEALTHY,
                        error=str(e),
                    )

                # Wait for next check
                await asyncio.sleep(interval_seconds)

            except asyncio.CancelledError:
                logger.info("Health check loop cancelled")
                break
            except Exception as e:
                logger.error("Error in health check loop", error=str(e))
                await asyncio.sleep(interval_seconds)

    def is_healthy(self) -> bool:
        """Check if all services are healthy.

        Returns:
            True if all services are healthy, False otherwise.
        """
        return self._get_overall_status() == ServiceStatus.HEALTHY.value

    def get_unhealthy_services(self) -> list[str]:
        """Get list of unhealthy service names.

        Returns:
            List of service names that are not healthy.
        """
        return [
            name for name, health in self._services.items()
            if health.status in (ServiceStatus.UNHEALTHY, ServiceStatus.DEGRADED)
        ]


# Global health monitor instance
_health_monitor: ServiceHealthMonitor | None = None


def get_health_monitor(settings: Settings | None = None) -> ServiceHealthMonitor:
    """Get or create the global health monitor instance.

    Args:
        settings: Application settings.

    Returns:
        ServiceHealthMonitor instance.
    """
    global _health_monitor

    if _health_monitor is None:
        _health_monitor = ServiceHealthMonitor(settings)

    return _health_monitor


def reset_health_monitor() -> None:
    """Reset the global health monitor instance."""
    global _health_monitor
    _health_monitor = None
    ServiceHealthMonitor._instance = None
