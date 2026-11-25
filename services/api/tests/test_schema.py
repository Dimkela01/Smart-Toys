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

#: DATA_MODEL.md §2.1 and §2.2
M1_TABLES = {
    "parents",
    "consents",
    "admins",
    "refresh_tokens",
    "audit_log",
    "children",
    "child_settings",
}

#: §2.3, apart from events and alerts, which belong to the safety layer in M3
M2_TABLES = {"sessions", "turns", "turn_metrics"}

#: each milestone creates its own tables, so these must still be absent
LATER_TABLES = {
    "events",
    "alerts",
    "memory_items",
    "activity_states",
    "models",
    "prompt_versions",
    "eval_runs",
    "eval_results",
    "ratings",
}


def test_the_milestone_s_tables_exist_and_no_others(sync_connection: psycopg.Connection) -> None:
    rows = sync_connection.execute(
        "select table_name from information_schema.tables where table_schema = 'public'"
    ).fetchall()
    present = {row[0] for row in rows}
    assert present >= M1_TABLES | M2_TABLES
    assert not LATER_TABLES & present


def test_no_table_can_hold_audio(sync_connection: psycopg.Connection) -> None:
    """Audio is never stored (docs/CLAUDE.md §2), so no column should invite it.

    A blunt check on purpose: the rule is easy to agree with and easy to break by adding
    one convenient bytea column during a debugging session.
    """
    rows = sync_connection.execute(
        "select table_name, column_name, data_type from information_schema.columns"
        " where table_schema = 'public'"
    ).fetchall()
    # a column has to be able to *hold* audio to be a problem: turn_metrics.first_audio_ms
    # is a millisecond count, not a waveform
    holds_bytes = {"bytea", "text", "character varying"}
    named_for_audio = ("audio", "pcm", "wav", "waveform", "recording", "speech")
    suspects = [
        f"{table}.{column} ({kind})"
        for table, column, kind in rows
        if kind in holds_bytes
        and (kind == "bytea" or any(word in column for word in named_for_audio))
        # the admin TOTP secret is encrypted at rest, which is why it is binary
        and f"{table}.{column}" != "admins.totp_secret_enc"
    ]
    assert suspects == [], f"audio is never stored: {suspects}"


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


@pytest.mark.parametrize(
    ("column", "value", "reason"),
    [
        ("end_reason", "'crashed'", "end_reason must be one of the four in DATA_MODEL.md §2.3"),
        ("duration_s", "-1", "a session cannot last a negative time"),
    ],
)
def test_session_constraints(
    sync_connection: psycopg.Connection, column: str, value: str, reason: str
) -> None:
    child = _a_child(sync_connection)
    with pytest.raises(psycopg.errors.CheckViolation), sync_connection.transaction():
        sync_connection.execute(
            f"insert into sessions (id, child_id, {column}) values (gen_random_uuid(), %s, {value})",
            (child,),
        )


@pytest.mark.parametrize(
    ("column", "value", "reason"),
    [
        ("language", "'de'", "only sr and en exist"),
        ("profile", "'cloud'", "only the server and device profiles exist (§4)"),
        ("router_decision", "'maybe'", "the decision set is fixed (SAFETY.md §2)"),
    ],
)
def test_turn_constraints(sync_connection: psycopg.Connection, column: str, value: str, reason: str) -> None:
    child = _a_child(sync_connection)
    session = sync_connection.execute(
        "insert into sessions (id, child_id) values (gen_random_uuid(), %s) returning id", (child,)
    ).fetchone()
    assert session is not None
    columns = {"language": "'sr'", "profile": "'server'", "router_decision": "'llm'"}
    columns[column] = value
    names = ", ".join(columns)
    values = ", ".join(columns.values())
    with pytest.raises(psycopg.errors.CheckViolation), sync_connection.transaction():
        sync_connection.execute(
            f"insert into turns (id, session_id, child_id, delete_after, {names})"
            f" values (gen_random_uuid(), %s, %s, now(), {values})",
            (session[0], child),
        )


def _a_child(connection: psycopg.Connection) -> object:
    """A parent and a child to hang a session off; truncated between tests."""
    parent = connection.execute(
        "insert into parents (id, email, password_hash, locale, token_version)"
        " values (gen_random_uuid(), 'schema@example.com', 'x', 'sr', 0) returning id"
    ).fetchone()
    assert parent is not None
    child = connection.execute(
        "insert into children (id, parent_id, nickname, age, language, interests, avatar_id,"
        " character_id) values (gen_random_uuid(), %s, 'Mila', 5, 'sr', '[]'::jsonb, 'a', 'bear')"
        " returning id",
        (parent[0],),
    ).fetchone()
    assert child is not None
    return child[0]
