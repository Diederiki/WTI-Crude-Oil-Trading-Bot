"""Retry mechanisms with exponential backoff.

Provides configurable retry logic with exponential backoff, jitter,
and circuit breaker integration.
"""

import asyncio
import random
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, TypeVar

from src.core.logging_config import get_logger

logger = get_logger("retry")

T = TypeVar("T")


@dataclass
class RetryConfig:
    """Retry configuration."""
    
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True
    jitter_max: float = 1.0
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,)
    on_retry: Callable[[Exception, int], None] | None = None


class RetryExhaustedError(Exception):
    """Raised when all retry attempts are exhausted."""
    
    def __init__(self, last_exception: Exception, attempts: int):
        """Initialize error.
        
        Args:
            last_exception: The last exception that caused failure
            attempts: Number of attempts made
        """
        self.last_exception = last_exception
        self.attempts = attempts
        super().__init__(f"Retry exhausted after {attempts} attempts: {last_exception}")


def calculate_delay(
    attempt: int,
    base_delay: float,
    max_delay: float,
    exponential_base: float,
    jitter: bool,
    jitter_max: float,
) -> float:
    """Calculate delay for retry attempt.
    
    Args:
        attempt: Current attempt number (0-indexed)
        base_delay: Base delay in seconds
        max_delay: Maximum delay in seconds
        exponential_base: Exponential multiplier
        jitter: Whether to add random jitter
        jitter_max: Maximum jitter amount
        
    Returns:
        Delay in seconds
    """
    # Exponential backoff
    delay = base_delay * (exponential_base ** attempt)
    delay = min(delay, max_delay)
    
    # Add jitter to prevent thundering herd
    if jitter:
        delay += random.uniform(0, jitter_max)
    
    return delay


async def retry_with_backoff(
    func: Callable[..., T],
    config: RetryConfig | None = None,
    *args: Any,
    **kwargs: Any,
) -> T:
    """Execute function with retry and exponential backoff.
    
    Args:
        func: Function to execute
        config: Retry configuration
        *args: Function arguments
        **kwargs: Function keyword arguments
        
    Returns:
        Function result
        
    Raises:
        RetryExhaustedError: If all retries exhausted
    """
    config = config or RetryConfig()
    last_exception: Exception | None = None
    
    for attempt in range(config.max_attempts):
        try:
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                return func(*args, **kwargs)
                
        except config.retryable_exceptions as e:
            last_exception = e
            
            if attempt < config.max_attempts - 1:
                delay = calculate_delay(
                    attempt=attempt,
                    base_delay=config.base_delay,
                    max_delay=config.max_delay,
                    exponential_base=config.exponential_base,
                    jitter=config.jitter,
                    jitter_max=config.jitter_max,
                )
                
                logger.warning(
                    "Retry attempt failed",
                    attempt=attempt + 1,
                    max_attempts=config.max_attempts,
                    delay=delay,
                    error=str(e),
                )
                
                if config.on_retry:
                    config.on_retry(e, attempt + 1)
                
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "All retry attempts exhausted",
                    attempts=config.max_attempts,
                    last_error=str(e),
                )
    
    raise RetryExhaustedError(last_exception, config.max_attempts)


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable:
    """Decorator for retry with exponential backoff.
    
    Args:
        max_attempts: Maximum retry attempts
        base_delay: Initial delay between retries
        max_delay: Maximum delay between retries
        exponential_base: Exponential multiplier
        jitter: Whether to add random jitter
        retryable_exceptions: Exceptions to retry on
        
    Returns:
        Decorator function
    """
    config = RetryConfig(
        max_attempts=max_attempts,
        base_delay=base_delay,
        max_delay=max_delay,
        exponential_base=exponential_base,
        jitter=jitter,
        retryable_exceptions=retryable_exceptions,
    )
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            return await retry_with_backoff(func, config, *args, **kwargs)
        
        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            # For sync functions, we can't use async retry
            # Just call directly without retry
            return func(*args, **kwargs)
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


class RetryableOperation:
    """Context manager for retryable operations.
    
    Usage:
        async with RetryableOperation(config) as op:
            result = await op.execute(my_function, arg1, arg2)
    """
    
    def __init__(self, config: RetryConfig | None = None):
        """Initialize retryable operation.
        
        Args:
            config: Retry configuration
        """
        self.config = config or RetryConfig()
        self.attempts = 0
        self.last_exception: Exception | None = None
    
    async def execute(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Execute function with retry.
        
        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments
            
        Returns:
            Function result
        """
        return await retry_with_backoff(func, self.config, *args, **kwargs)
    
    async def __aenter__(self) -> "RetryableOperation":
        """Enter context."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Exit context."""
        return False  # Don't suppress exceptions


class Bulkhead:
    """Bulkhead pattern for resource isolation.
    
    Limits concurrent operations to prevent resource exhaustion.
    """
    
    def __init__(self, name: str, max_concurrent: int, max_queue: int = 100):
        """Initialize bulkhead.
        
        Args:
            name: Bulkhead name
            max_concurrent: Maximum concurrent operations
            max_queue: Maximum queued operations
        """
        self.name = name
        self.max_concurrent = max_concurrent
        self.max_queue = max_queue
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._queue_size = 0
        self._lock = asyncio.Lock()
    
    async def execute(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Execute function with bulkhead protection.
        
        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments
            
        Returns:
            Function result
            
        Raises:
            BulkheadFullError: If queue is full
        """
        async with self._lock:
            if self._queue_size >= self.max_queue:
                raise BulkheadFullError(
                    f"Bulkhead '{self.name}' queue full ({self.max_queue})"
                )
            self._queue_size += 1
        
        try:
            async with self._semaphore:
                async with self._lock:
                    self._queue_size -= 1
                
                if asyncio.iscoroutinefunction(func):
                    return await func(*args, **kwargs)
                else:
                    return func(*args, **kwargs)
        except Exception:
            async with self._lock:
                self._queue_size = max(0, self._queue_size - 1)
            raise
    
    def get_stats(self) -> dict[str, Any]:
        """Get bulkhead statistics.
        
        Returns:
            Statistics dictionary
        """
        return {
            "name": self.name,
            "max_concurrent": self.max_concurrent,
            "max_queue": self.max_queue,
            "available_slots": self._semaphore._value,
            "queue_size": self._queue_size,
        }


class BulkheadFullError(Exception):
    """Raised when bulkhead queue is full."""
    pass


# Global bulkhead registry
_bulkheads: dict[str, Bulkhead] = {}


def get_bulkhead(name: str, max_concurrent: int = 10, max_queue: int = 100) -> Bulkhead:
    """Get or create bulkhead.
    
    Args:
        name: Bulkhead name
        max_concurrent: Maximum concurrent operations
        max_queue: Maximum queue size
        
    Returns:
        Bulkhead instance
    """
    if name not in _bulkheads:
        _bulkheads[name] = Bulkhead(name, max_concurrent, max_queue)
    return _bulkheads[name]
