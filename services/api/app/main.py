"""FastAPI application.

Parent, child-mode and admin REST routers, plus the turn WebSocket from M2. Metrics and
model names are admin-only and never appear in a parent or child response.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from sqlalchemy import text

from app.config import settings
from app.db import engine
from app.redis_client import close_redis
from app.routers import admin, auth, child_mode, children, meta, turns

logger = logging.getLogger("app")

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logging.basicConfig(level=settings.log_level.upper())
    for problem in settings.check_production_safety():
        logger.warning("unsafe configuration for a pilot: %s", problem)
    yield
    await close_redis()
    await engine.dispose()


app = FastAPI(
    title="Bruno MVP API",
    version="0.1.0",
    description="Backend for the Bruno learning-toy web app. Metrics and model data are admin only.",
    lifespan=lifespan,
    # the child client never receives model text; see ARCHITECTURE.md §7
    openapi_url="/api/v1/openapi.json",
    docs_url="/docs",
)


app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(auth.pin_router, prefix=API_PREFIX)
app.include_router(children.router, prefix=API_PREFIX)
app.include_router(child_mode.router, prefix=API_PREFIX)
app.include_router(meta.router, prefix=API_PREFIX)
app.include_router(admin.router, prefix=API_PREFIX)
# the turn WebSocket; its own authentication, because a browser cannot set a header on
# a WebSocket (see app/routers/turns.py)
app.include_router(turns.router, prefix=API_PREFIX)


@app.get("/healthz", tags=["meta"])
async def healthz() -> dict[str, str]:
    """Liveness: the process is up. Used by the container health check."""
    return {"status": "ok", "environment": settings.environment}


@app.get("/readyz", tags=["meta"])
async def readyz() -> dict[str, Any]:
    """Readiness: the database answers."""
    database_ok = True
    try:
        async with engine.connect() as connection:
            await connection.execute(text("select 1"))
    except Exception as error:
        database_ok = False
        logger.error("database not ready: %s", type(error).__name__)
    return {"status": "ok" if database_ok else "degraded", "database": database_ok}
