"""Core module providing infrastructure services."""

from src.core.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitBreakerRegistry,
    circuit_breaker,
    get_circuit_breaker_registry,
)
from src.core.database import get_async_session, init_database, close_database
from src.core.logging_config import configure_logging, get_logger
from src.core.rate_limiter import (
    DistributedRateLimiter,
    RateLimiter,
    RateLimitConfig,
    get_rate_limiter,
    get_distributed_rate_limiter,
)
from src.core.redis_client import get_redis_client, RedisClient
from src.core.retry import (
    RetryConfig,
    RetryExhaustedError,
    RetryableOperation,
    retry,
    retry_with_backoff,
    Bulkhead,
    get_bulkhead,
)
from src.core.secrets import (
    SecretsManager,
    get_secrets_manager,
    get_secret,
    init_secrets_manager,
)

__all__ = [
    # Database
    "get_async_session",
    "init_database",
    "close_database",
    # Logging
    "configure_logging",
    "get_logger",
    # Redis
    "get_redis_client",
    "RedisClient",
    # Circuit Breaker
    "CircuitBreaker",
    "CircuitBreakerOpenError",
    "CircuitBreakerRegistry",
    "circuit_breaker",
    "get_circuit_breaker_registry",
    # Rate Limiter
    "DistributedRateLimiter",
    "RateLimiter",
    "RateLimitConfig",
    "get_rate_limiter",
    "get_distributed_rate_limiter",
    # Retry
    "RetryConfig",
    "RetryExhaustedError",
    "RetryableOperation",
    "retry",
    "retry_with_backoff",
    "Bulkhead",
    "get_bulkhead",
    # Secrets
    "SecretsManager",
    "get_secrets_manager",
    "get_secret",
    "init_secrets_manager",
]
