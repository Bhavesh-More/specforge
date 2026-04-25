"""Async Redis client with specforge key namespace."""

import redis.asyncio as redis
from redis.asyncio import Redis

from src.core.config import get_config

REDIS_KEY_PREFIX = "specforge"


class RedisClient:
    """Async Redis client wrapper.

    Attributes:
        redis_url: DSN URL for Redis connection.
    """

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._client: Redis | None = None

    async def connect(self) -> None:
        """Open the Redis connection."""
        if self._client is None:
            self._client = redis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
            )

    async def close(self) -> None:
        """Close the Redis connection."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _key(self, entity: str, identifier: str) -> str:
        """Build a namespaced key: specforge:{entity}:{identifier}."""
        return f"{REDIS_KEY_PREFIX}:{entity}:{identifier}"

    async def get(self, key: str) -> str | None:
        """Get a value from Redis."""
        if self._client is None:
            await self.connect()
        return await self._client.get(key)  # type: ignore

    async def set(
        self,
        key: str,
        value: str,
        ex: int | None = None,
    ) -> None:
        """Set a value in Redis with optional TTL in seconds."""
        if self._client is None:
            await self.connect()
        await self._client.set(key, value, ex=ex)  # type: ignore

    async def sadd(self, key: str, *values: str) -> None:
        """Add values to a Redis set."""
        if self._client is None:
            await self.connect()
        await self._client.sadd(key, *values)  # type: ignore

    async def smembers(self, key: str) -> list[str]:
        """Get all members of a Redis set."""
        if self._client is None:
            await self.connect()
        members = await self._client.smembers(key)  # type: ignore
        return list(members)

    async def delete(self, key: str) -> None:
        """Delete a key from Redis."""
        if self._client is None:
            await self.connect()
        await self._client.delete(key)  # type: ignore

    async def exists(self, key: str) -> bool:
        """Check if a key exists in Redis."""
        if self._client is None:
            await self.connect()
        return await self._client.exists(key) > 0  # type: ignore


# Module-level singleton getter
_redis_client: RedisClient | None = None


async def get_redis_client() -> RedisClient:
    """Return the cached RedisClient singleton."""
    global _redis_client
    if _redis_client is None:
        cfg = get_config()
        _redis_client = RedisClient(redis_url=str(cfg.redis_url))
        await _redis_client.connect()
    return _redis_client
