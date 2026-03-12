"""Circuit breaker pattern for fault tolerance.

Implements the circuit breaker pattern to prevent cascading failures
when external services are unavailable or experiencing issues.
"""

import asyncio
import time
from enum import Enum, auto
from functools import wraps
from typing import Any, Callable, TypeVar

from src.core.logging_config import get_logger

logger = get_logger("circuit_breaker")

T = TypeVar("T")


class CircuitState(Enum):
    """Circuit breaker states."""
    
    CLOSED = auto()      # Normal operation, requests pass through
    OPEN = auto()        # Failure threshold reached, requests blocked
    HALF_OPEN = auto()   # Testing if service has recovered


class CircuitBreaker:
    """Circuit breaker for external service calls.
    
    Prevents cascading failures by blocking requests to failing services
    and allowing them to recover.
    
    Attributes:
        name: Circuit breaker identifier
        failure_threshold: Number of failures before opening
        recovery_timeout: Seconds before attempting recovery
        half_open_max_calls: Max calls in half-open state
    """
    
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 3,
        expected_exception: type[Exception] = Exception,
    ):
        """Initialize circuit breaker.
        
        Args:
            name: Circuit breaker name
            failure_threshold: Failures before opening circuit
            recovery_timeout: Seconds before half-open attempt
            half_open_max_calls: Max calls in half-open state
            expected_exception: Exception type to count as failure
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.expected_exception = expected_exception
        
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float | None = None
        self._half_open_calls = 0
        self._lock = asyncio.Lock()
        
        logger.info(
            "Circuit breaker initialized",
            name=name,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
        )
    
    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        return self._state
    
    @property
    def is_open(self) -> bool:
        """Check if circuit is open (blocking requests)."""
        return self._state == CircuitState.OPEN
    
    @property
    def is_closed(self) -> bool:
        """Check if circuit is closed (allowing requests)."""
        return self._state == CircuitState.CLOSED
    
    async def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Execute function with circuit breaker protection.
        
        Args:
            func: Function to execute
            *args: Positional arguments
            **kwargs: Keyword arguments
            
        Returns:
            Function result
            
        Raises:
            CircuitBreakerOpenError: If circuit is open
            Exception: Original exception from function
        """
        async with self._lock:
            await self._update_state()
            
            if self._state == CircuitState.OPEN:
                raise CircuitBreakerOpenError(
                    f"Circuit '{self.name}' is OPEN - service unavailable"
                )
            
            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.half_open_max_calls:
                    raise CircuitBreakerOpenError(
                        f"Circuit '{self.name}' is HALF_OPEN - max calls reached"
                    )
                self._half_open_calls += 1
        
        # Execute outside lock
        try:
            result = await func(*args, **kwargs)
            await self._record_success()
            return result
        except self.expected_exception as e:
            await self._record_failure()
            raise
    
    async def _update_state(self) -> None:
        """Update circuit state based on time and failures."""
        if self._state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            if self._last_failure_time and \
               (time.monotonic() - self._last_failure_time) >= self.recovery_timeout:
                logger.info(
                    "Circuit breaker transitioning to HALF_OPEN",
                    name=self.name,
                )
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                self._success_count = 0
    
    async def _record_success(self) -> None:
        """Record successful call."""
        async with self._lock:
            self._success_count += 1
            
            if self._state == CircuitState.HALF_OPEN:
                # If enough successes in half-open, close the circuit
                if self._success_count >= self.half_open_max_calls:
                    logger.info(
                        "Circuit breaker CLOSED - service recovered",
                        name=self.name,
                    )
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    self._half_open_calls = 0
    
    async def _record_failure(self) -> None:
        """Record failed call."""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            
            if self._state == CircuitState.HALF_OPEN:
                # Back to open if failure in half-open
                logger.warning(
                    "Circuit breaker OPEN - recovery failed",
                    name=self.name,
                )
                self._state = CircuitState.OPEN
                self._half_open_calls = 0
            elif self._failure_count >= self.failure_threshold:
                # Open circuit if threshold reached
                logger.warning(
                    "Circuit breaker OPEN - failure threshold reached",
                    name=self.name,
                    failure_count=self._failure_count,
                )
                self._state = CircuitState.OPEN
    
    def get_stats(self) -> dict[str, Any]:
        """Get circuit breaker statistics.
        
        Returns:
            Statistics dictionary
        """
        return {
            "name": self.name,
            "state": self._state.name,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
            "last_failure_time": self._last_failure_time,
            "half_open_calls": self._half_open_calls,
        }
    
    async def reset(self) -> None:
        """Manually reset circuit breaker to closed state."""
        async with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._half_open_calls = 0
            self._last_failure_time = None
            
            logger.info("Circuit breaker manually reset", name=self.name)


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open."""
    pass


class CircuitBreakerRegistry:
    """Registry for managing multiple circuit breakers."""
    
    def __init__(self):
        """Initialize registry."""
        self._breakers: dict[str, CircuitBreaker] = {}
    
    def register(self, breaker: CircuitBreaker) -> None:
        """Register a circuit breaker.
        
        Args:
            breaker: Circuit breaker to register
        """
        self._breakers[breaker.name] = breaker
    
    def get(self, name: str) -> CircuitBreaker | None:
        """Get circuit breaker by name.
        
        Args:
            name: Circuit breaker name
            
        Returns:
            Circuit breaker or None
        """
        return self._breakers.get(name)
    
    def get_all_stats(self) -> dict[str, dict[str, Any]]:
        """Get statistics for all circuit breakers.
        
        Returns:
            Dictionary of breaker stats
        """
        return {
            name: breaker.get_stats()
            for name, breaker in self._breakers.items()
        }
    
    async def reset_all(self) -> None:
        """Reset all circuit breakers."""
        for breaker in self._breakers.values():
            await breaker.reset()


# Global registry
_registry: CircuitBreakerRegistry | None = None


def get_circuit_breaker_registry() -> CircuitBreakerRegistry:
    """Get global circuit breaker registry.
    
    Returns:
        Circuit breaker registry
    """
    global _registry
    if _registry is None:
        _registry = CircuitBreakerRegistry()
    return _registry


def circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: float = 60.0,
    half_open_max_calls: int = 3,
    expected_exception: type[Exception] = Exception,
) -> Callable:
    """Decorator for circuit breaker protection.
    
    Args:
        name: Circuit breaker name
        failure_threshold: Failures before opening
        recovery_timeout: Seconds before recovery attempt
        half_open_max_calls: Max calls in half-open state
        expected_exception: Exception type to count as failure
        
    Returns:
        Decorator function
    """
    registry = get_circuit_breaker_registry()
    
    # Create or get circuit breaker
    breaker = registry.get(name)
    if breaker is None:
        breaker = CircuitBreaker(
            name=name,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            half_open_max_calls=half_open_max_calls,
            expected_exception=expected_exception,
        )
        registry.register(breaker)
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            return await breaker.call(func, *args, **kwargs)
        
        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            # For sync functions, run in executor
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(breaker.call(func, *args, **kwargs))
        
        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator
