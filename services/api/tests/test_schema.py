"""The migration must apply on an empty database and match the models exactly.

A drift between app/models/ and app/migrations/ is the cheapest bug to catch and the most
expensive to find later, so it is asserted on every test run.
"""

from __future__ import annotations

import psycopg
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from app.models import Base

M1_TABLES = {
    "parents",
    "consents",
    "admins",
    "refresh_tokens",
    "audit_log",
    "children",
    "child_settings",
}


def test_m1_tables_exist(sync_connection: psycopg.Connection) -> None:
    rows = sync_connection.execute(
        "select table_name from information_schema.tables where table_schema = 'public'"
    ).fetchall()
    present = {row[0] for row in rows}
    assert present >= M1_TABLES
    # tables belonging to later milestones must not exist yet (DATA_MODEL.md §2.3-§2.5)
    assert not {"turns", "sessions", "turn_metrics", "eval_runs"} & present


def test_models_match_migration(database_url: str) -> None:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection, opts={"compare_type": True, "compare_server_default": True}
            )
            differences = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()
    assert differences == [], f"models and migration disagree: {differences}"


@pytest.mark.parametrize(
    ("statement", "reason"),
    [
        (
            "insert into parents (id, email, password_hash, locale, token_version)"
            " values (gen_random_uuid(), 'a@b.co', 'x', 'de', 0)",
            "locale must be sr or en",
        ),
    ],
)
def test_account_constraints(sync_connection: psycopg.Connection, statement: str, reason: str) -> None:
    with pytest.raises(psycopg.errors.CheckViolation), sync_connection.transaction():
        sync_connection.execute(statement)
