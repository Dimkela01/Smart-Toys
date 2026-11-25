"""Test fixtures.

Every run drops and recreates the test database and applies all migrations, which is also
the "new migrations apply on an empty database" check from docs/MILESTONES.md.

The database must be reachable; `make test-api` starts postgres and redis first.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import psycopg
import pytest
import redis
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app import db
from app.config import settings
from app.db import get_session
from app.main import app
from app.redis_client import close_redis
from app.services import email as email_service

API_DIR = Path(__file__).resolve().parents[1]

#: tables truncated between tests; parents cascades to children, consents and settings
ROOT_TABLES = ("parents", "admins", "refresh_tokens", "audit_log")


def _target_url() -> str:
    if settings.test_database_url:
        return settings.test_database_url
    base, _, _ = settings.database_url.rpartition("/")
    return f"{base}/bruno_test"


def _sync_dsn(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://")


@pytest.fixture(scope="session")
def database_url() -> str:
    url = _target_url()
    dsn = _sync_dsn(url)
    admin_dsn, _, name = dsn.rpartition("/")

    try:
        with psycopg.connect(f"{admin_dsn}/postgres", autocommit=True) as connection:
            connection.execute(f'drop database if exists "{name}" with (force)')
            connection.execute(f'create database "{name}"')
    except psycopg.OperationalError as error:
        pytest.skip(f"postgres is not reachable ({error}); run: make dev")

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=API_DIR,
        check=True,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
    )
    return url


@pytest.fixture(scope="session", autouse=True)
def _test_settings() -> Iterator[None]:
    """Keep tests off the development Redis database and out of the rate limiter's way."""
    if settings.test_redis_url:
        settings.redis_url = settings.test_redis_url
    else:
        base, _, _ = settings.redis_url.rpartition("/")
        settings.redis_url = f"{base}/15"
    settings.auth_rate_limit_per_minute = 10_000
    settings.email_print_links = False
    yield


@pytest.fixture(autouse=True)
def _clean_tables(database_url: str, _test_settings: None) -> None:
    with psycopg.connect(_sync_dsn(database_url), autocommit=True) as connection:
        connection.execute(f"truncate {', '.join(ROOT_TABLES)} restart identity cascade")
    try:
        with redis.Redis.from_url(settings.redis_url) as client:
            client.flushdb()
    except redis.RedisError:  # pragma: no cover - redis is optional for schema tests
        pass


@pytest.fixture(autouse=True)
async def _fresh_redis_client() -> AsyncIterator[None]:
    """Each test runs in its own event loop, so the shared async client cannot be reused."""
    yield
    await close_redis()


@pytest.fixture
def sent_emails(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    """Capture outgoing mail instead of sending it, and expose the links it contains."""
    captured: list[dict[str, str]] = []

    async def fake_send(*, to: str, subject: str, body: str) -> None:
        captured.append({"to": to, "subject": subject, "body": body})

    monkeypatch.setattr(email_service, "send_email", fake_send)
    return captured


DEFAULT_PASSWORD = "dovoljno-duga-sifra"
DEFAULT_PIN = "4821"


async def create_parent(
    client: AsyncClient,
    sent_emails: list[dict[str, str]],
    *,
    email: str,
    password: str = DEFAULT_PASSWORD,
    pin: str | None = DEFAULT_PIN,
    locale: str = "sr",
) -> dict[str, str]:
    """Register, verify and (unless pin is None) set the PIN. Returns auth headers."""
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "adult_confirmed": True,
            "consent_accepted": True,
            "locale": locale,
        },
    )
    assert registered.status_code == 202, registered.text

    verified = await client.post("/api/v1/auth/verify", json={"token": token_from_email(sent_emails[-1])})
    assert verified.status_code == 200, verified.text
    headers = {"Authorization": f"Bearer {verified.json()['access_token']}"}

    if pin is not None:
        pinned = await client.post("/api/v1/auth/pin", json={"pin": pin, "pin_repeat": pin}, headers=headers)
        assert pinned.status_code == 200, pinned.text
    return headers


@pytest.fixture
async def parent_headers(client: AsyncClient, sent_emails: list[dict[str, str]]) -> dict[str, str]:
    """A parent who has finished setup: verified address and a PIN."""
    return await create_parent(client, sent_emails, email="parent-one@example.com")


def token_from_email(message: dict[str, str]) -> str:
    """Pull the one-shot token out of a verification or reset link."""
    match = re.search(r"token=([A-Za-z0-9._\-]+)", message["body"])
    assert match, f"no token in email: {message['subject']}"
    return match.group(1)


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    created = create_async_engine(database_url)
    yield created
    await created.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def session(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with session_factory() as opened:
        yield opened


@pytest.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    async def override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as opened:
            try:
                yield opened
                await opened.commit()
            except Exception:
                await opened.rollback()
                raise

    app.dependency_overrides[get_session] = override
    # The turn WebSocket outlives a request, so it opens its own short transactions
    # through db.session_scope() instead of the dependency. Point that at the test
    # database too, or a test would quietly write into the development one.
    monkeypatch.setattr(db, "SessionFactory", session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
        yield opened
    app.dependency_overrides.clear()


@pytest.fixture
def sync_connection(database_url: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(_sync_dsn(database_url)) as connection:
        yield connection
