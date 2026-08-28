from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from daily_intelligence.llm_usage import UsageLedger
from daily_intelligence.llm_usage.adapters.codex import CodexAdapter


def _usage(
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
    reasoning_output_tokens: int = 0,
) -> dict[str, int]:
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "cache_write_input_tokens": 0,
        "output_tokens": output_tokens,
        "reasoning_output_tokens": reasoning_output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


def _session_meta(
    child_id: str,
    *,
    root_id: str = "root-session",
    parent_id: str = "parent-thread",
) -> dict[str, Any]:
    return {
        "timestamp": "2026-08-23T08:00:00Z",
        "type": "session_meta",
        "payload": {
            "id": child_id,
            "session_id": root_id,
            "parent_thread_id": parent_id,
            "model_provider": "openai",
            "model": "gpt-5.6-codex",
            "base_instructions": "private header content must never be persisted",
        },
    }


def _token_count(
    timestamp: str,
    *,
    last: dict[str, int] | None,
    total: dict[str, int] | None,
) -> dict[str, Any]:
    info = None
    if last is not None or total is not None:
        info = {
            "total_token_usage": total,
            "last_token_usage": last,
            "model_context_window": 200_000,
        }
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": info,
            "rate_limits": {"primary": {"used_percent": 12.5}},
        },
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    return path


def test_official_token_count_uses_delta_skips_no_growth_and_handles_reset(
    tmp_path: Path,
) -> None:
    first = _usage(10, 4, 3, 1)
    second_last = _usage(20, 10, 5, 2)
    second_total = _usage(35, 20, 10, 4)
    reset = _usage(7, 2, 4, 1)
    after_reset_last = _usage(3, 1, 2)
    after_reset_total = _usage(10, 3, 6, 1)
    second_event = _token_count(
        "2026-08-23T08:00:03Z",
        last=second_last,
        total=second_total,
    )
    rollout = _write_jsonl(
        tmp_path / "rollout.jsonl",
        [
            _session_meta("child-alpha"),
            _token_count("2026-08-23T08:00:00Z", last=None, total=None),
            _token_count("2026-08-23T08:00:01Z", last=first, total=first),
            _token_count("2026-08-23T08:00:02Z", last=first, total=first),
            second_event,
            second_event,
            _token_count("2026-08-23T08:00:04Z", last=reset, total=reset),
            _token_count("2026-08-23T08:00:05Z", last=reset, total=reset),
            _token_count(
                "2026-08-23T08:00:06Z",
                last=after_reset_last,
                total=after_reset_total,
            ),
        ],
    )

    records = CodexAdapter().from_path(rollout, phase="codex-test")

    assert len(records) == 4
    assert [record.observation.tokens.reported_total.value for record in records] == [
        13,
        32,
        11,
        5,
    ]
    assert all(record.observation.source_kind == "rollout_cumulative_delta" for record in records)
    assert all(record.observation.covered_call_count.value == 1 for record in records)
    assert len({record.observation.session_id_hash for record in records}) == 1
    assert all(record.observation.parent_session_id_hash is not None for record in records)
    assert all(record.observation.provider == "openai" for record in records)
    assert all(record.observation.requested_model == "gpt-5.6-codex" for record in records)

    ledger = UsageLedger(tmp_path / "data")
    task = ledger.start_task("codex", task_id="codex-cumulative")
    ledger.import_usage_file(task, "codex", rollout, phase="codex-test")
    summary = ledger.summarize_task(task)

    assert summary["covered_call_count"]["value"] == 4
    assert summary["tokens"]["input"]["value"] == 45
    assert summary["tokens"]["cached_input"]["value"] == 23
    assert summary["tokens"]["cache_write_input"]["value"] == 0
    assert summary["tokens"]["output"]["value"] == 16
    assert summary["tokens"]["reasoning_output"]["value"] == 5
    assert summary["tokens"]["reported_total"]["value"] == 61
    persisted = "".join(
        event.read_text(encoding="utf-8") for event in (task.path / "events").glob("*.json")
    )
    assert "child-alpha" not in persisted
    assert "root-session" not in persisted
    assert "parent-thread" not in persisted
    assert "private header content" not in persisted


def test_overlapping_imports_of_one_session_are_idempotent(tmp_path: Path) -> None:
    first = _usage(6, 2, 2)
    second_last = _usage(9, 4, 3, 1)
    second_total = _usage(15, 6, 5, 1)
    third_last = _usage(4, 1, 1)
    third_total = _usage(19, 7, 6, 1)
    second_event = _token_count(
        "2026-08-23T09:00:02Z",
        last=second_last,
        total=second_total,
    )
    first_export = _write_jsonl(
        tmp_path / "first.jsonl",
        [
            _session_meta("child-overlap"),
            _token_count("2026-08-23T09:00:01Z", last=first, total=first),
            second_event,
        ],
    )
    overlapping_export = _write_jsonl(
        tmp_path / "overlap.jsonl",
        [
            _session_meta("child-overlap"),
            second_event,
            _token_count("2026-08-23T09:00:02.5Z", last=second_last, total=second_total),
            _token_count(
                "2026-08-23T09:00:03Z",
                last=third_last,
                total=third_total,
            ),
        ],
    )

    ledger = UsageLedger(tmp_path / "data")
    task = ledger.start_task("codex", task_id="codex-overlap")
    ledger.import_usage_file(task, "codex", first_export, phase="author")
    ledger.import_usage_file(task, "codex", overlapping_export, phase="author")
    ledger.import_usage_file(task, "codex", first_export, phase="author")
    summary = ledger.summarize_task(task)

    assert summary["observation_count"] == 3
    assert summary["raw_observation_count"] == 3
    assert summary["covered_call_count"]["value"] == 3
    assert summary["tokens"]["input"]["value"] == 19
    assert summary["tokens"]["output"]["value"] == 6
    assert summary["tokens"]["reported_total"]["value"] == 25
    assert summary["conflicts"] == []
    assert len({item["correlation_id_hash"] for item in summary["observations"]}) == 3


def test_identical_usage_in_two_child_sessions_keeps_distinct_lineage(
    tmp_path: Path,
) -> None:
    usage = _usage(6, 2, 2, 1)
    identical_event = _token_count(
        "2026-08-23T10:00:01Z",
        last=usage,
        total=usage,
    )
    first_session = _write_jsonl(
        tmp_path / "child-a.jsonl",
        [_session_meta("child-a", parent_id="parent-root"), identical_event],
    )
    second_session = _write_jsonl(
        tmp_path / "child-b.jsonl",
        [_session_meta("child-b", parent_id="parent-root"), identical_event],
    )

    adapter = CodexAdapter()
    first_record = adapter.from_path(first_session)[0]
    second_record = adapter.from_path(second_session)[0]
    assert first_record.dedupe_key != second_record.dedupe_key
    assert first_record.observation.correlation_id_hash != (
        second_record.observation.correlation_id_hash
    )
    assert first_record.observation.session_id_hash != second_record.observation.session_id_hash
    assert first_record.observation.parent_session_id_hash == (
        second_record.observation.parent_session_id_hash
    )
    assert "child-a" not in first_record.dedupe_key
    assert "child-b" not in second_record.dedupe_key

    ledger = UsageLedger(tmp_path / "data")
    task = ledger.start_task("codex", task_id="codex-two-children")
    ledger.import_usage_file(task, "codex", first_session)
    ledger.import_usage_file(task, "codex", second_session)
    ledger.import_usage_file(task, "codex", first_session)
    summary = ledger.summarize_task(task)

    assert summary["observation_count"] == 2
    assert summary["covered_call_count"]["value"] == 2
    assert summary["tokens"]["reported_total"]["value"] == 16
    assert len({item["session_id_hash"] for item in summary["observations"]}) == 2
    assert len({item["correlation_id_hash"] for item in summary["observations"]}) == 2
    persisted = "".join(
        event.read_text(encoding="utf-8") for event in (task.path / "events").glob("*.json")
    )
    for raw_value in (
        "child-a",
        "child-b",
        "root-session",
        "parent-root",
        "private header content",
    ):
        assert raw_value not in persisted


def test_hook_identity_is_scoped_by_hashed_session() -> None:
    usage = _usage(5, 1, 2)
    base = {
        "event_id": "same-event-id",
        "payload": {"last_token_usage": usage},
    }
    first = CodexAdapter().from_hook(
        {**base, "meta": {"session_id": "child-hook-a"}}
    )[0]
    second = CodexAdapter().from_hook(
        {**base, "meta": {"session_id": "child-hook-b"}}
    )[0]

    assert first.dedupe_key != second.dedupe_key
    assert first.observation.correlation_id_hash != second.observation.correlation_id_hash
    assert first.observation.session_id_hash != second.observation.session_id_hash
    assert "same-event-id" not in first.dedupe_key
    assert "child-hook-a" not in first.dedupe_key
