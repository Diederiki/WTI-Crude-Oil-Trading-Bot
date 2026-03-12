"""Health check endpoints for monitoring and observability.

This module provides comprehensive health check endpoints for:
- Overall system health
- Kubernetes/Docker readiness and liveness probes
- Database connectivity checks
- Redis connectivity checks
- Service dependency health
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.config.settings import Settings, get_settings
from src.core.database import check_database_health
from src.core.logging_config import get_logger
from src.core.redis_client import get_redis_client
from src.services.health_monitor import ServiceHealthMonitor, get_health_monitor

logger = get_logger("api")
router = APIRouter()


class HealthStatus(BaseModel):
    """Health status response model."""

    status: str = Field(..., description="Overall health status: healthy, degraded, or unhealthy")
    timestamp: str = Field(..., description="ISO timestamp of the health check")
    version: str = Field(..., description="Application version")
    environment: str = Field(..., description="Deployment environment")
    checks: dict[str, Any] = Field(default_factory=dict, description="Individual health checks")


class ReadinessStatus(BaseModel):
    """Readiness probe response model."""

    ready: bool = Field(..., description="Whether the service is ready to accept traffic")
    timestamp: str = Field(..., description="ISO timestamp of the check")
    dependencies: dict[str, bool] = Field(
        default_factory=dict,
        description="Status of required dependencies",
    )


class LivenessStatus(BaseModel):
    """Liveness probe response model."""

    alive: bool = Field(..., description="Whether the service is alive")
    timestamp: str = Field(..., description="ISO timestamp of the check")
    uptime_seconds: float = Field(..., description="Service uptime in seconds")


class DatabaseHealthStatus(BaseModel):
    """Database health check response model."""

    status: str = Field(..., description="Database health status")
    response_time_ms: float = Field(..., description="Query response time in milliseconds")
    error: str | None = Field(None, description="Error message if unhealthy")


class RedisHealthStatus(BaseModel):
    """Redis health check response model."""

    status: str = Field(..., description="Redis health status")
    response_time_ms: float = Field(..., description="Ping response time in milliseconds")
    version: str | None = Field(None, description="Redis server version")
    connected_clients: int | None = Field(None, description="Number of connected clients")
    error: str | None = Field(None, description="Error message if unhealthy")


# Track application start time for uptime calculation
_start_time = datetime.utcnow()


@router.get(
    "/",
    response_model=HealthStatus,
    summary="Overall system health",
    description="Returns comprehensive health status of all system components.",
    responses={
        200: {"description": "System is healthy or degraded"},
        503: {"description": "System is unhealthy"},
    },
)
async def get_health(
    settings: Settings = Depends(get_settings),
    health_monitor: ServiceHealthMonitor = Depends(get_health_monitor),
) -> HealthStatus:
    """Get overall system health status.

    This endpoint performs comprehensive health checks on all system
    components including database, Redis, and external dependencies.

    Args:
        settings: Application settings.
        health_monitor: Health monitoring service.

    Returns:
        HealthStatus with detailed health information.

    Raises:
        HTTPException: If system is unhealthy (503).
    """
    timestamp = datetime.utcnow().isoformat()
    checks: dict[str, Any] = {}

    # Check database health
    try:
        db_health = await check_database_health()
        checks["database"] = db_health
    except Exception as e:
        logger.error("Database health check failed", error=str(e))
        checks["database"] = {"status": "unhealthy", "error": str(e)}

    # Check Redis health
    try:
        redis_client = await get_redis_client(settings)
        redis_health = await redis_client.health_check()
        checks["redis"] = redis_health
    except Exception as e:
        logger.error("Redis health check failed", error=str(e))
        checks["redis"] = {"status": "unhealthy", "error": str(e)}

    # Get health monitor status
    checks["services"] = health_monitor.get_status()

    # Determine overall status
    all_healthy = all(
        check.get("status") == "healthy"
        for check in checks.values()
        if isinstance(check, dict) and "status" in check
    )

    any_unhealthy = any(
        check.get("status") == "unhealthy"
        for check in checks.values()
        if isinstance(check, dict) and "status" in check
    )

    if any_unhealthy:
        overall_status = "unhealthy"
    elif not all_healthy:
        overall_status = "degraded"
    else:
        overall_status = "healthy"

    response = HealthStatus(
        status=overall_status,
        timestamp=timestamp,
        version=settings.app_version,
        environment=settings.environment,
        checks=checks,
    )

    # Return 503 if unhealthy
    if overall_status == "unhealthy":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=response.model_dump(),
        )

    return response


@router.get(
    "/ready",
    response_model=ReadinessStatus,
    summary="Readiness probe",
    description="Kubernetes/Docker readiness probe endpoint.",
    responses={
        200: {"description": "Service is ready"},
        503: {"description": "Service is not ready"},
    },
)
async def get_readiness(
    settings: Settings = Depends(get_settings),
) -> ReadinessStatus:
    """Check if the service is ready to accept traffic.

    This endpoint is used by Kubernetes/Docker to determine if the
    service is ready to receive requests. It checks all required
    dependencies.

    Args:
        settings: Application settings.

    Returns:
        ReadinessStatus indicating if service is ready.

    Raises:
        HTTPException: If service is not ready (503).
    """
    timestamp = datetime.utcnow().isoformat()
    dependencies: dict[str, bool] = {}

    # Check database
    try:
        db_health = await check_database_health()
        dependencies["database"] = db_health.get("status") == "healthy"
    except Exception:
        dependencies["database"] = False

    # Check Redis (optional - service can work without it)
    try:
        redis_client = await get_redis_client(settings)
        redis_health = await redis_client.health_check()
        dependencies["redis"] = redis_health.get("status") == "healthy"
    except Exception:
        dependencies["redis"] = False

    # Service is ready if database is available
    is_ready = dependencies.get("database", False)

    response = ReadinessStatus(
        ready=is_ready,
        timestamp=timestamp,
        dependencies=dependencies,
    )

    if not is_ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=response.model_dump(),
        )

    return response


@router.get(
    "/live",
    response_model=LivenessStatus,
    summary="Liveness probe",
    description="Kubernetes/Docker liveness probe endpoint.",
)
async def get_liveness() -> LivenessStatus:
    """Check if the service is alive.

    This endpoint is used by Kubernetes/Docker to determine if the
    service process is still running. It should return quickly and
    indicate if the service needs to be restarted.

    Returns:
        LivenessStatus indicating if service is alive.
    """
    timestamp = datetime.utcnow()
    uptime = (timestamp - _start_time).total_seconds()

    return LivenessStatus(
        alive=True,
        timestamp=timestamp.isoformat(),
        uptime_seconds=uptime,
    )


@router.get(
    "/db",
    response_model=DatabaseHealthStatus,
    summary="Database health check",
    description="Check database connectivity and performance.",
    responses={
        200: {"description": "Database is healthy"},
        503: {"description": "Database is unhealthy"},
    },
)
async def get_db_health() -> DatabaseHealthStatus:
    """Get database health status.

    Performs a simple query to verify database connectivity
    and measures response time.

    Returns:
        DatabaseHealthStatus with connectivity information.

    Raises:
        HTTPException: If database is unhealthy (503).
    """
    try:
        health = await check_database_health()
        response = DatabaseHealthStatus(
            status=health.get("status", "unknown"),
            response_time_ms=health.get("response_time_ms", 0),
            error=health.get("error"),
        )

        if response.status != "healthy":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=response.model_dump(),
            )

        return response

    except Exception as e:
        logger.error("Database health check failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "unhealthy",
                "response_time_ms": 0,
                "error": str(e),
            },
        )


@router.get(
    "/redis",
    response_model=RedisHealthStatus,
    summary="Redis health check",
    description="Check Redis connectivity and performance.",
    responses={
        200: {"description": "Redis is healthy"},
        503: {"description": "Redis is unhealthy"},
    },
)
async def get_redis_health(
    settings: Settings = Depends(get_settings),
) -> RedisHealthStatus:
    """Get Redis health status.

    Performs a ping to verify Redis connectivity and retrieves
    server information.

    Args:
        settings: Application settings.

    Returns:
        RedisHealthStatus with connectivity information.

    Raises:
        HTTPException: If Redis is unhealthy (503).
    """
    try:
        redis_client = await get_redis_client(settings)
        health = await redis_client.health_check()

        response = RedisHealthStatus(
            status=health.get("status", "unknown"),
            response_time_ms=health.get("response_time_ms", 0),
            version=health.get("version"),
            connected_clients=health.get("connected_clients"),
            error=health.get("error"),
        )

        if response.status != "healthy":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=response.model_dump(),
            )

        return response

    except Exception as e:
        logger.error("Redis health check failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "unhealthy",
                "response_time_ms": 0,
                "error": str(e),
            },
        )
