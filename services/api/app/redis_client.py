"""Shared Redis connection.

Redis holds only short-lived counters (failed logins, failed PINs, rate-limit windows).
Keys are derived from a hash of the email, never the address itself, and never contain
anything a child said.
"""

from __future__ import annotations

import logging

from redis.asyncio import Redis, from_url

from app.config import settings

logger = logging.getLogger("app.redis")

_client: Redis | None = None


def get_redis() -> Redis:
    global _client
    if _client is None:
        _client = from_url(settings.redis_url, decode_responses=True)
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
