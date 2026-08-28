from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from daily_intelligence.llm_usage import ObservationQuality, TokenRelation
from daily_intelligence.llm_usage.adapters.openclaw import OpenClawAdapter


def _create_current_agent_db(
    path: Path,
    *,
    user_version: int = 17,
    metadata_version: int | None = None,
    role: str = "agent",
) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE schema_meta (
                meta_key TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                schema_version INTEGER NOT NULL,
                agent_id TEXT,
                app_version TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );
            CREATE TABLE session_nodes (
                session_key TEXT PRIMARY KEY,
                current_session_id TEXT NOT NULL,
                parent_session_key TEXT,
                spawned_by TEXT
            );
            CREATE TABLE session_windows (
                session_id TEXT PRIMARY KEY,
                session_key TEXT NOT NULL,
                model_provider TEXT,
                model TEXT,
                parent_session_key TEXT,
                spawned_by TEXT
            );
            CREATE TABLE transcript_events (
                session_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                event_json TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                PRIMARY KEY (session_id, seq)
            );
            """
        )
        connection.execute(f"PRAGMA user_version = {user_version}")
        connection.execute(
            """
            INSERT INTO schema_meta (
                meta_key, role, schema_version, agent_id, app_version,
                created_at, updated_at
            ) VALUES ('primary', ?, ?, 'agent-secret', '2026.8.23', 1, 1)
            """,
            (role, metadata_version if metadata_version is not None else user_version),
        )


def _insert_session(
    path: Path,
    *,
    session_key: str,
    session_id: str,
    parent_session_key: str | None,
    header: dict,
    event: dict,
) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            INSERT INTO session_nodes (
                session_key, current_session_id, parent_session_key, spawned_by
            ) VALUES (?, ?, ?, NULL)
            """,
            (session_key, session_id, parent_session_key),
        )
        connection.execute(
            """
            INSERT INTO session_windows (
                session_id, session_key, model_provider, model,
                parent_session_key, spawned_by
            ) VALUES (?, ?, 'openai', 'gpt-5.5', ?, NULL)
            """,
            (session_id, session_key, parent_session_key),
        )
        connection.executemany(
            """
            INSERT INTO transcript_events (session_id, seq, event_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                (session_id, 0, json.dumps(header), 1787443200000),
                (session_id, 1, json.dumps(event), 1787443201000),
            ),
        )


def test_current_sqlite_import_preserves_session_lineage_and_unknown_calls(
    tmp_path: Path,
) -> None:
    database = tmp_path / "openclaw-agent.sqlite"
    _create_current_agent_db(database)
    usage_event = {
        "type": "message",
        "id": "same-event-id",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "toolCall",
                    "name": "read",
                    "arguments": {"credential": "sk-do-not-persist"},
                }
            ],
            "usage": {
                "input": 10,
                "output": 4,
                "cacheRead": 3,
                "cacheWrite": 0,
                "total": 17,
                "cost": {"total": "0", "currency": "USD"},
            },
        },
    }
    _insert_session(
        database,
        session_key="parent-key",
        session_id="parent-session",
        parent_session_key=None,
        header={
            "type": "session",
            "id": "parent-session",
            "agentId": "agent-secret",
        },
        event=usage_event,
    )
    _insert_session(
        database,
        session_key="child-key",
        session_id="child-session",
        parent_session_key="parent-key",
        header={
            "type": "session",
            "id": "child-session",
            "agentId": "agent-secret",
            "parentTranscriptScope": {
                "agentId": "agent-secret",
                "sessionId": "parent-session",
            },
        },
        event=usage_event,
    )

    records = OpenClawAdapter().from_path(database, phase="author")

    assert len(records) == 2
    assert records[0].dedupe_key != records[1].dedupe_key
    child = next(
        record.observation
        for record in records
        if record.observation.parent_session_id_hash is not None
    )
    parent = next(
        record.observation
        for record in records
        if record.observation.parent_session_id_hash is None
    )
    assert parent.source_kind == "agent_sqlite_transcript"
    assert parent.provider == "openai"
    assert parent.requested_model == "gpt-5.5"
    assert parent.session_id_hash != child.session_id_hash
    assert child.parent_session_id_hash == parent.session_id_hash
    assert parent.covered_call_count.value is None
    assert parent.covered_call_count.quality is ObservationQuality.UNOBSERVABLE
    assert parent.granularity == "aggregate"
    assert parent.tokens.cached_input_relation is TokenRelation.ADDITIONAL
    assert parent.tokens.cache_write_input_relation is TokenRelation.ADDITIONAL
    assert parent.tokens.accounted_total().value == 17
    assert parent.tool_call_count.value == 1
    assert parent.cost.amount == "0"
    assert parent.completed_at == "2026-08-23T00:00:01+00:00"

    persisted_shape = json.dumps([record.observation.to_dict() for record in records])
    for secret in (
        "sk-do-not-persist",
        "same-event-id",
        "agent-secret",
        "parent-session",
        "child-session",
        "arguments",
    ):
        assert secret not in persisted_shape

    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (17,)
        assert connection.execute("SELECT COUNT(*) FROM transcript_events").fetchone() == (4,)


@pytest.mark.parametrize(
    ("user_version", "metadata_version", "role"),
    (
        (18, 18, "agent"),
        (17, 16, "agent"),
        (17, 17, "global"),
    ),
)
def test_sqlite_import_fails_closed_for_unknown_schema_or_role(
    tmp_path: Path,
    user_version: int,
    metadata_version: int,
    role: str,
) -> None:
    database = tmp_path / f"unknown-{user_version}-{metadata_version}-{role}.sqlite"
    _create_current_agent_db(
        database,
        user_version=user_version,
        metadata_version=metadata_version,
        role=role,
    )

    with pytest.raises(ValueError, match="schema"):
        OpenClawAdapter().from_path(database)


def test_sqlite_import_fails_closed_when_required_columns_are_missing(
    tmp_path: Path,
) -> None:
    database = tmp_path / "drifted.sqlite"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE schema_meta (
                meta_key TEXT PRIMARY KEY,
                role TEXT,
                schema_version INTEGER,
                agent_id TEXT,
                app_version TEXT,
                created_at INTEGER,
                updated_at INTEGER
            );
            CREATE TABLE session_nodes (
                session_key TEXT,
                current_session_id TEXT,
                parent_session_key TEXT,
                spawned_by TEXT
            );
            CREATE TABLE session_windows (
                session_id TEXT,
                session_key TEXT,
                model_provider TEXT,
                model TEXT,
                parent_session_key TEXT,
                spawned_by TEXT
            );
            CREATE TABLE transcript_events (
                session_id TEXT,
                seq INTEGER,
                event_json TEXT
            );
            INSERT INTO schema_meta VALUES (
                'primary', 'agent', 17, 'agent-a', '2026.8.23', 1, 1
            );
            PRAGMA user_version = 17;
            """
        )

    with pytest.raises(ValueError, match="columns"):
        OpenClawAdapter().from_path(database)


def test_legacy_jsonl_inherits_header_and_scopes_identical_event_ids(
    tmp_path: Path,
) -> None:
    adapter = OpenClawAdapter()
    records = []
    for suffix, session_id in (("a", "child-a"), ("b", "child-b")):
        path = tmp_path / f"session-{suffix}.jsonl"
        rows = [
            {
                "type": "session",
                "id": session_id,
                "parentSession": "shared-parent",
            },
            {
                "type": "message",
                "id": "same-message-id",
                "message": {
                    "role": "assistant",
                    "usage": {"input": 2, "output": 1, "total": 3},
                },
            },
        ]
        path.write_text(
            "".join(f"{json.dumps(row)}\n" for row in rows),
            encoding="utf-8",
        )
        records.extend(adapter.from_path(path))

    assert len(records) == 2
    left, right = (record.observation for record in records)
    assert records[0].dedupe_key != records[1].dedupe_key
    assert left.source_kind == right.source_kind == "legacy_session_jsonl"
    assert left.session_id_hash != right.session_id_hash
    assert left.parent_session_id_hash == right.parent_session_id_hash
    assert left.turn_id_hash != right.turn_id_hash
    assert left.covered_call_count.value is None


def test_hook_source_and_explicit_zero_are_distinct_from_unknown() -> None:
    adapter = OpenClawAdapter()
    zero = adapter.from_hook(
        {
            "sessionId": "session-a",
            "api_calls": 0,
            "message": {
                "usage": {
                    "input": 0,
                    "output": 0,
                    "cacheRead": 0,
                    "cacheWrite": 0,
                    "total": 0,
                }
            },
        },
        source_event_id="zero-event",
    )[0].observation
    unknown = adapter.from_hook(
        {
            "sessionId": "session-a",
            "message": {"usage": {"input": 1, "output": 1, "total": 2}},
        },
        source_event_id="unknown-event",
    )[0].observation

    assert zero.source_kind == "usage_hook"
    assert zero.covered_call_count.value == 0
    assert zero.covered_call_count.quality is ObservationQuality.EXACT
    assert zero.tokens.cached_input.value == 0
    assert zero.tokens.accounted_total().value == 0
    assert unknown.covered_call_count.value is None
    assert unknown.covered_call_count.quality is ObservationQuality.UNOBSERVABLE
    assert unknown.tokens.cached_input.value is None
