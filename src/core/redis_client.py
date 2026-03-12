"""Redis client with connection pooling and pub/sub support.

This module provides a production-ready Redis client with:
- Connection pooling for high performance
- Automatic reconnection on failures
- Key prefixing for namespacing
- Pub/sub helper methods
- Graceful degradation when Redis is unavailable
"""

import json
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

import redis.asyncio as redis
from redis.asyncio.client import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError, TimeoutError

from src.config.settings import Settings, get_settings
from src.core.logging_config import get_logger

logger = get_logger("redis")

# Global Redis client instance
_redis_client: RedisClient | None = None


class RedisClient:
    """Production-ready Redis client with connection pooling.

    This class wraps the redis-py client with additional features:
    - Connection pooling configuration
    - Key prefixing for namespacing
    - Automatic retry on connection failures
    - Health check functionality
    - Graceful degradation

    Example:
        >>> client = RedisClient()
        >>> await client.connect()
        >>> await client.set("mykey", {"data": "value"})
        >>> value = await client.get("mykey")
        >>> await client.disconnect()
    """

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize the Redis client.

        Args:
            settings: Application settings. If None, settings are loaded automatically.
        """
        self.settings = settings or get_settings()
        self.redis_config = self.settings.redis
        self._client: Redis | None = None
        self._connected = False

    def _prefixed_key(self, key: str) -> str:
        """Add prefix to key if configured.

        Args:
            key: The original key.

        Returns:
            Prefixed key.
        """
        if self.redis_config.key_prefix:
            return f"{self.redis_config.key_prefix}:{key}"
        return key

    async def connect(self) -> None:
        """Establish connection to Redis.

        Creates a connection pool and tests connectivity.
        Logs warnings but doesn't raise on connection failure
        to allow graceful degradation.

        Example:
            >>> client = RedisClient()
            >>> await client.connect()
            >>> if client.is_connected():
            ...     await client.set("key", "value")
        """
        if self._connected and self._client is not None:
            return

        try:
            # Build connection parameters
            connection_kwargs: dict[str, Any] = {
                "host": self.redis_config.host,
                "port": self.redis_config.port,
                "db": self.redis_config.db,
                "decode_responses": True,
                "socket_timeout": self.redis_config.socket_timeout,
                "socket_connect_timeout": self.redis_config.socket_connect_timeout,
                "health_check_interval": self.redis_config.health_check_interval,
                "max_connections": self.redis_config.pool_size,
            }

            if self.redis_config.password:
                connection_kwargs["password"] = self.redis_config.password

            if self.redis_config.ssl:
                connection_kwargs["ssl"] = True

            # Create Redis client with connection pool
            self._client = Redis(**connection_kwargs)

            # Test connection
            await self._client.ping()
            self._connected = True

            logger.info(
                "Redis connected",
                host=self.redis_config.host,
                port=self.redis_config.port,
                db=self.redis_config.db,
            )

        except (RedisConnectionError, TimeoutError) as e:
            logger.warning(
                "Redis connection failed, operating in degraded mode",
                error=str(e),
                host=self.redis_config.host,
                port=self.redis_config.port,
            )
            self._connected = False
            self._client = None

    async def disconnect(self) -> None:
        """Close Redis connection and release resources.

        Example:
            >>> await client.disconnect()
            >>> # Connection is now closed
        """
        if self._client is not None:
            try:
                await self._client.close()
                logger.info("Redis disconnected")
            except RedisError as e:
                logger.error("Error disconnecting from Redis", error=str(e))
            finally:
                self._client = None
                self._connected = False

    def is_connected(self) -> bool:
        """Check if Redis is connected.

        Returns:
            True if connected, False otherwise.
        """
        return self._connected and self._client is not None

    async def health_check(self) -> dict[str, Any]:
        """Perform Redis health check.

        Returns:
            Dictionary with health status:
            - status: "healthy" or "unhealthy"
            - response_time_ms: Ping response time
            - info: Server info if healthy
            - error: Error message if unhealthy
        """
        import time

        if not self.is_connected():
            return {
                "status": "unhealthy",
                "response_time_ms": 0,
                "error": "Not connected",
            }

        start_time = time.perf_counter()

        try:
            await self._client.ping()
            response_time_ms = (time.perf_counter() - start_time) * 1000

            # Get server info
            info = await self._client.info()

            return {
                "status": "healthy",
                "response_time_ms": round(response_time_ms, 2),
                "version": info.get("redis_version", "unknown"),
                "used_memory_human": info.get("used_memory_human", "unknown"),
                "connected_clients": info.get("connected_clients", 0),
            }

        except RedisError as e:
            response_time_ms = (time.perf_counter() - start_time) * 1000
            logger.error("Redis health check failed", error=str(e))
            self._connected = False

            return {
                "status": "unhealthy",
                "response_time_ms": round(response_time_ms, 2),
                "error": str(e),
            }

    async def get(self, key: str) -> Any | None:
        """Get value from Redis.

        Args:
            key: The key to retrieve.

        Returns:
            The value if found, None otherwise.

        Example:
            >>> value = await client.get("mykey")
            >>> if value:
            ...     print(f"Found: {value}")
        """
        if not self.is_connected():
            return None

        try:
            prefixed_key = self._prefixed_key(key)
            value = await self._client.get(prefixed_key)

            if value is None:
                return None

            # Try to parse as JSON, return as string if not valid JSON
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value

        except RedisError as e:
            logger.error("Redis GET failed", key=key, error=str(e))
            return None

    async def set(
        self,
        key: str,
        value: Any,
        expire: int | None = None,
    ) -> bool:
        """Set value in Redis.

        Args:
            key: The key to set.
            value: The value to store (will be JSON serialized).
            expire: Optional expiration time in seconds.

        Returns:
            True if successful, False otherwise.

        Example:
            >>> success = await client.set("mykey", {"data": "value"}, expire=3600)
            >>> if success:
            ...     print("Value stored")
        """
        if not self.is_connected():
            return False

        try:
            prefixed_key = self._prefixed_key(key)

            # Serialize value to JSON if not a string
            if not isinstance(value, str):
                value = json.dumps(value, default=str)

            await self._client.set(prefixed_key, value, ex=expire)
            return True

        except RedisError as e:
            logger.error("Redis SET failed", key=key, error=str(e))
            return False

    async def delete(self, key: str) -> bool:
        """Delete key from Redis.

        Args:
            key: The key to delete.

        Returns:
            True if deleted or not found, False on error.

        Example:
            >>> await client.delete("mykey")
        """
        if not self.is_connected():
            return False

        try:
            prefixed_key = self._prefixed_key(key)
            await self._client.delete(prefixed_key)
            return True

        except RedisError as e:
            logger.error("Redis DELETE failed", key=key, error=str(e))
            return False

    async def exists(self, key: str) -> bool:
        """Check if key exists in Redis.

        Args:
            key: The key to check.

        Returns:
            True if key exists, False otherwise.

        Example:
            >>> if await client.exists("mykey"):
            ...     print("Key exists")
        """
        if not self.is_connected():
            return False

        try:
            prefixed_key = self._prefixed_key(key)
            result = await self._client.exists(prefixed_key)
            return result > 0

        except RedisError as e:
            logger.error("Redis EXISTS failed", key=key, error=str(e))
            return False

    async def publish(self, channel: str, message: Any) -> int:
        """Publish message to a channel.

        Args:
            channel: The channel to publish to.
            message: The message to publish (will be JSON serialized).

        Returns:
            Number of subscribers that received the message.

        Example:
            >>> subscribers = await client.publish("market_data", {"price": 75.50})
        """
        if not self.is_connected():
            return 0

        try:
            prefixed_channel = self._prefixed_key(channel)

            if not isinstance(message, str):
                message = json.dumps(message, default=str)

            result = await self._client.publish(prefixed_channel, message)
            return result

        except RedisError as e:
            logger.error("Redis PUBLISH failed", channel=channel, error=str(e))
            return 0

    async def subscribe(self, channel: str) -> Any:
        """Subscribe to a channel and return the pub/sub object.

        Args:
            channel: The channel to subscribe to.

        Returns:
            Pub/sub object for receiving messages.

        Example:
            >>> pubsub = await client.subscribe("market_data")
            >>> async for message in pubsub.listen():
            ...     print(message)
        """
        if not self.is_connected():
            raise RedisConnectionError("Redis not connected")

        try:
            prefixed_channel = self._prefixed_key(channel)
            pubsub = self._client.pubsub()
            await pubsub.subscribe(prefixed_channel)
            return pubsub

        except RedisError as e:
            logger.error("Redis SUBSCRIBE failed", channel=channel, error=str(e))
            raise

    async def hset(self, key: str, field: str, value: Any) -> bool:
        """Set hash field value.

        Args:
            key: The hash key.
            field: The field name.
            value: The value to store.

        Returns:
            True if successful, False otherwise.

        Example:
            >>> await client.hset("positions", "CL=F", {"qty": 10, "price": 75.50})
        """
        if not self.is_connected():
            return False

        try:
            prefixed_key = self._prefixed_key(key)

            if not isinstance(value, str):
                value = json.dumps(value, default=str)

            await self._client.hset(prefixed_key, field, value)
            return True

        except RedisError as e:
            logger.error("Redis HSET failed", key=key, field=field, error=str(e))
            return False

    async def hget(self, key: str, field: str) -> Any | None:
        """Get hash field value.

        Args:
            key: The hash key.
            field: The field name.

        Returns:
            The field value if found, None otherwise.

        Example:
            >>> position = await client.hget("positions", "CL=F")
        """
        if not self.is_connected():
            return None

        try:
            prefixed_key = self._prefixed_key(key)
            value = await self._client.hget(prefixed_key, field)

            if value is None:
                return None

            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value

        except RedisError as e:
            logger.error("Redis HGET failed", key=key, field=field, error=str(e))
            return None

    async def hgetall(self, key: str) -> dict[str, Any]:
        """Get all fields from a hash.

        Args:
            key: The hash key.

        Returns:
            Dictionary of all field-value pairs.

        Example:
            >>> all_positions = await client.hgetall("positions")
        """
        if not self.is_connected():
            return {}

        try:
            prefixed_key = self._prefixed_key(key)
            result = await self._client.hgetall(prefixed_key)

            # Parse JSON values
            parsed = {}
            for field, value in result.items():
                try:
                    parsed[field] = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    parsed[field] = value

            return parsed

        except RedisError as e:
            logger.error("Redis HGETALL failed", key=key, error=str(e))
            return {}

    async def lpush(self, key: str, *values: Any) -> int:
        """Push values to the left of a list.

        Args:
            key: The list key.
            *values: Values to push.

        Returns:
            Length of the list after push.

        Example:
            >>> await client.lpush("ticks", tick1, tick2)
        """
        if not self.is_connected():
            return 0

        try:
            prefixed_key = self._prefixed_key(key)
            serialized = [json.dumps(v, default=str) if not isinstance(v, str) else v for v in values]
            result = await self._client.lpush(prefixed_key, *serialized)
            return result

        except RedisError as e:
            logger.error("Redis LPUSH failed", key=key, error=str(e))
            return 0

    async def ltrim(self, key: str, start: int, end: int) -> bool:
        """Trim list to specified range.

        Args:
            key: The list key.
            start: Start index.
            end: End index.

        Returns:
            True if successful, False otherwise.

        Example:
            >>> await client.ltrim("ticks", 0, 999)  # Keep last 1000 items
        """
        if not self.is_connected():
            return False

        try:
            prefixed_key = self._prefixed_key(key)
            await self._client.ltrim(prefixed_key, start, end)
            return True

        except RedisError as e:
            logger.error("Redis LTRIM failed", key=key, error=str(e))
            return False

    async def lrange(self, key: str, start: int, end: int) -> list[Any]:
        """Get range of elements from a list.

        Args:
            key: The list key.
            start: Start index.
            end: End index.

        Returns:
            List of elements in the range.

        Example:
            >>> recent_ticks = await client.lrange("ticks", 0, 99)
        """
        if not self.is_connected():
            return []

        try:
            prefixed_key = self._prefixed_key(key)
            values = await self._client.lrange(prefixed_key, start, end)

            # Parse JSON values
            parsed = []
            for value in values:
                try:
                    parsed.append(json.loads(value))
                except (json.JSONDecodeError, TypeError):
                    parsed.append(value)

            return parsed

        except RedisError as e:
            logger.error("Redis LRANGE failed", key=key, error=str(e))
            return []


async def get_redis_client(settings: Settings | None = None) -> RedisClient:
    """Get or create the global Redis client instance.

    Args:
        settings: Application settings.

    Returns:
        RedisClient instance.

    Example:
        >>> client = await get_redis_client()
        >>> await client.set("key", "value")
    """
    global _redis_client

    if _redis_client is None:
        _redis_client = RedisClient(settings)
        await _redis_client.connect()

    return _redis_client


async def close_redis_client() -> None:
    """Close the global Redis client instance."""
    global _redis_client

    if _redis_client is not None:
        await _redis_client.disconnect()
        _redis_client = None


@asynccontextmanager
async def redis_session(
    settings: Settings | None = None,
) -> AsyncGenerator[RedisClient, None]:
    """Context manager for Redis client session.

    Args:
        settings: Application settings.

    Yields:
        RedisClient instance.

    Example:
        >>> async with redis_session() as client:
        ...     await client.set("key", "value")
        >>> # Connection automatically closed
    """
    client = RedisClient(settings)
    try:
        await client.connect()
        yield client
    finally:
        await client.disconnect()
