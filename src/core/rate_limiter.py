"""Rate limiting for API protection.

Implements token bucket and sliding window rate limiting algorithms
to protect API endpoints from abuse.
"""

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from src.core.logging_config import get_logger
from src.core.redis_client import get_redis_client

logger = get_logger("rate_limiter")


@dataclass
class RateLimitConfig:
    """Rate limit configuration."""
    
    requests_per_second: float = 10.0
    burst_size: int = 20
    window_seconds: float = 60.0


class TokenBucket:
    """Token bucket rate limiter.
    
    Allows bursts up to bucket size while maintaining average rate.
    """
    
    def __init__(
        self,
        rate: float,
        capacity: int,
    ):
        """Initialize token bucket.
        
        Args:
            rate: Tokens added per second
            capacity: Maximum bucket size
        """
        self.rate = rate
        self.capacity = capacity
        self._tokens = capacity
        self._last_update = time.monotonic()
        self._lock = asyncio.Lock()
    
    async def acquire(self, tokens: int = 1) -> bool:
        """Try to acquire tokens from bucket.
        
        Args:
            tokens: Number of tokens to acquire
            
        Returns:
            True if tokens acquired
        """
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_update
            
            # Add tokens based on elapsed time
            self._tokens = min(
                self.capacity,
                self._tokens + elapsed * self.rate
            )
            self._last_update = now
            
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            
            return False
    
    async def wait_time(self, tokens: int = 1) -> float:
        """Calculate wait time for tokens.
        
        Args:
            tokens: Number of tokens needed
            
        Returns:
            Seconds to wait (0 if available now)
        """
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_update
            current_tokens = min(
                self.capacity,
                self._tokens + elapsed * self.rate
            )
            
            if current_tokens >= tokens:
                return 0.0
            
            needed = tokens - current_tokens
            return needed / self.rate


class SlidingWindow:
    """Sliding window rate limiter.
    
    Tracks requests in a time window and rejects if limit exceeded.
    """
    
    def __init__(
        self,
        limit: int,
        window_seconds: float,
    ):
        """Initialize sliding window.
        
        Args:
            limit: Maximum requests in window
            window_seconds: Window duration
        """
        self.limit = limit
        self.window_seconds = window_seconds
        self._requests: list[float] = []
        self._lock = asyncio.Lock()
    
    async def allow(self) -> bool:
        """Check if request is allowed.
        
        Returns:
            True if request allowed
        """
        async with self._lock:
            now = time.monotonic()
            cutoff = now - self.window_seconds
            
            # Remove old requests
            self._requests = [t for t in self._requests if t > cutoff]
            
            if len(self._requests) < self.limit:
                self._requests.append(now)
                return True
            
            return False
    
    async def remaining(self) -> int:
        """Get remaining requests in current window.
        
        Returns:
            Remaining request count
        """
        async with self._lock:
            now = time.monotonic()
            cutoff = now - self.window_seconds
            self._requests = [t for t in self._requests if t > cutoff]
            return max(0, self.limit - len(self._requests))
    
    async def reset_after(self) -> float:
        """Get time until window resets.
        
        Returns:
            Seconds until reset
        """
        async with self._lock:
            if not self._requests:
                return 0.0
            oldest = min(self._requests)
            return max(0.0, (oldest + self.window_seconds) - time.monotonic())


class RateLimiter:
    """Rate limiter with multiple strategies.
    
    Supports token bucket for smooth rate limiting and sliding window
    for strict limits.
    """
    
    def __init__(self):
        """Initialize rate limiter."""
        self._buckets: dict[str, TokenBucket] = {}
        self._windows: dict[str, SlidingWindow] = {}
        self._lock = asyncio.Lock()
    
    async def check_rate_limit(
        self,
        key: str,
        config: RateLimitConfig,
    ) -> tuple[bool, dict[str, Any]]:
        """Check if request is within rate limit.
        
        Args:
            key: Rate limit key (e.g., IP address, user ID)
            config: Rate limit configuration
            
        Returns:
            Tuple of (allowed, metadata)
        """
        async with self._lock:
            # Initialize bucket if needed
            if key not in self._buckets:
                self._buckets[key] = TokenBucket(
                    rate=config.requests_per_second,
                    capacity=config.burst_size,
                )
            
            if key not in self._windows:
                self._windows[key] = SlidingWindow(
                    limit=int(config.requests_per_second * config.window_seconds),
                    window_seconds=config.window_seconds,
                )
        
        bucket = self._buckets[key]
        window = self._windows[key]
        
        # Check both limiters
        bucket_allowed = await bucket.acquire()
        window_allowed = await window.allow()
        
        allowed = bucket_allowed and window_allowed
        
        metadata = {
            "allowed": allowed,
            "bucket_tokens": bucket._tokens,
            "window_remaining": await window.remaining(),
            "window_reset_after": await window.reset_after(),
        }
        
        if not allowed:
            wait_time = await bucket.wait_time()
            metadata["retry_after"] = max(wait_time, await window.reset_after())
        
        return allowed, metadata
    
    async def reset(self, key: str) -> None:
        """Reset rate limit for key.
        
        Args:
            key: Rate limit key
        """
        async with self._lock:
            self._buckets.pop(key, None)
            self._windows.pop(key, None)


class DistributedRateLimiter:
    """Distributed rate limiter using Redis.
    
    For multi-instance deployments where rate limits must be
    shared across all instances.
    """
    
    def __init__(self, key_prefix: str = "ratelimit"):
        """Initialize distributed rate limiter.
        
        Args:
            key_prefix: Redis key prefix
        """
        self.key_prefix = key_prefix
    
    async def check_rate_limit(
        self,
        key: str,
        config: RateLimitConfig,
    ) -> tuple[bool, dict[str, Any]]:
        """Check distributed rate limit.
        
        Args:
            key: Rate limit key
            config: Rate limit configuration
            
        Returns:
            Tuple of (allowed, metadata)
        """
        redis = await get_redis_client()
        if not redis:
            # Fallback to local rate limiter
            local_limiter = RateLimiter()
            return await local_limiter.check_rate_limit(key, config)
        
        redis_key = f"{self.key_prefix}:{key}"
        now = time.time()
        window_start = now - config.window_seconds
        
        try:
            # Use Redis sorted set for sliding window
            pipe = redis.pipeline()
            
            # Remove old entries
            pipe.zremrangebyscore(redis_key, 0, window_start)
            
            # Count current entries
            pipe.zcard(redis_key)
            
            # Add current request
            pipe.zadd(redis_key, {str(now): now})
            
            # Set expiry
            pipe.expire(redis_key, int(config.window_seconds) + 1)
            
            results = await pipe.execute()
            current_count = results[1]
            
            limit = int(config.requests_per_second * config.window_seconds)
            allowed = current_count <= limit
            
            metadata = {
                "allowed": allowed,
                "current_count": current_count,
                "limit": limit,
                "window_seconds": config.window_seconds,
            }
            
            if not allowed:
                # Get oldest entry for retry-after
                oldest = await redis.zrange(redis_key, 0, 0, withscores=True)
                if oldest:
                    retry_after = (oldest[0][1] + config.window_seconds) - now
                    metadata["retry_after"] = max(0, retry_after)
            
            return allowed, metadata
            
        except Exception as e:
            logger.error("Redis rate limit error", error=str(e))
            # Allow request on error (fail open)
            return True, {"allowed": True, "error": str(e)}


# Global rate limiter instance
_rate_limiter: RateLimiter | None = None
_distributed_limiter: DistributedRateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    """Get global rate limiter instance.
    
    Returns:
        Rate limiter instance
    """
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter


def get_distributed_rate_limiter() -> DistributedRateLimiter:
    """Get global distributed rate limiter instance.
    
    Returns:
        Distributed rate limiter instance
    """
    global _distributed_limiter
    if _distributed_limiter is None:
        _distributed_limiter = DistributedRateLimiter()
    return _distributed_limiter
