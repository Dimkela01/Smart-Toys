"""Fixed-window rate limiting (NFR-06: auth 10/min/IP, ARCHITECTURE.md §9).

Turn endpoints get their own limit in M2 (20/min per child).
"""

from __future__ import annotations

import logging
import time

from fastapi import Request
from redis.exceptions import RedisError

from app.config import settings
from app.errors import api_error
from app.redis_client import get_redis

logger = logging.getLogger("app.ratelimit")


def client_ip(request: Request) -> str:
    """Caller address. Behind Caddy the first X-Forwarded-For entry is the real client."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimit:
    """FastAPI dependency: `Depends(RateLimit("auth"))`."""

    def __init__(self, bucket: str, per_minute: int | None = None) -> None:
        self.bucket = bucket
        self._per_minute = per_minute

    @property
    def per_minute(self) -> int:
        # read at call time, so the limit stays configurable after import
        return self._per_minute or settings.auth_rate_limit_per_minute

    async def __call__(self, request: Request) -> None:
        window = int(time.time() // 60)
        key = f"rl:{self.bucket}:{client_ip(request)}:{window}"
        try:
            client = get_redis()
            count = await client.incr(key)
            if count == 1:
                await client.expire(key, 60)
        except RedisError as error:
            # fail open: a broken counter must not take the app down
            logger.error("rate limit check failed, allowing request: %s", type(error).__name__)
            return
        if count > self.per_minute:
            raise api_error(429, "rate_limited", "Too many requests. Please wait a minute.")
