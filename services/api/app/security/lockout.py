"""Failed-attempt lockouts (UC-02 AC: 5 logins -> 15 min; UC-21 AC: 5 PINs -> 5 min).

Counters live in Redis and expire on their own. If Redis is unreachable the lockout fails
open (the attempt is allowed) and an error is logged: a broken counter must not lock every
parent out of their own account. The password check itself never depends on Redis.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from redis.exceptions import RedisError

from app.config import settings
from app.redis_client import get_redis

logger = logging.getLogger("app.lockout")


@dataclass(frozen=True)
class LockoutPolicy:
    name: str
    max_attempts: int
    lock_seconds: int


LOGIN = LockoutPolicy("login", settings.login_max_attempts, settings.login_lock_minutes * 60)
PIN = LockoutPolicy("pin", settings.pin_max_attempts, settings.pin_lock_minutes * 60)
#: team accounts, same thresholds as a parent login
ADMIN_LOGIN = LockoutPolicy("admin_login", settings.login_max_attempts, settings.login_lock_minutes * 60)


def _identity(value: str) -> str:
    """Hash the identity, so no email address is stored in Redis."""
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()[:32]


def _keys(policy: LockoutPolicy, value: str) -> tuple[str, str]:
    marker = _identity(value)
    return f"lock:{policy.name}:{marker}", f"fail:{policy.name}:{marker}"


async def seconds_remaining(policy: LockoutPolicy, value: str) -> int:
    """How long the identity stays locked; 0 when it is not locked."""
    lock_key, _ = _keys(policy, value)
    try:
        ttl = await get_redis().ttl(lock_key)
    except RedisError as error:
        logger.error("lockout check failed, allowing attempt: %s", type(error).__name__)
        return 0
    return max(ttl, 0)


async def register_failure(policy: LockoutPolicy, value: str) -> int:
    """Count a failed attempt and lock the identity once the limit is reached.

    Returns the number of attempts left before the lock engages (0 once locked).
    """
    lock_key, fail_key = _keys(policy, value)
    try:
        client = get_redis()
        attempts = await client.incr(fail_key)
        if attempts == 1:
            await client.expire(fail_key, policy.lock_seconds)
        if attempts >= policy.max_attempts:
            await client.set(lock_key, "1", ex=policy.lock_seconds)
            await client.delete(fail_key)
            return 0
    except RedisError as error:
        logger.error("lockout counter failed: %s", type(error).__name__)
        return policy.max_attempts
    return max(policy.max_attempts - attempts, 0)


async def reset(policy: LockoutPolicy, value: str) -> None:
    """Clear the counters after a successful attempt."""
    lock_key, fail_key = _keys(policy, value)
    try:
        await get_redis().delete(lock_key, fail_key)
    except RedisError as error:
        logger.error("lockout reset failed: %s", type(error).__name__)
