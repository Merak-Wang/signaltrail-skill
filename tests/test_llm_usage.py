from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from daily_intelligence.llm_usage import (
    ObservationQuality,
    TokenRelation,
    TokenUsage,
    UsageLedger,
    exact,
    ingest_hook_from_env,
    unobservable,
)

ROOT = Path(__file__).resolve().parents[1]


def _events(task_path: Path) -> list[dict]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((task_path / "events").glob("*.json"))
    ]


def test_unknown_is_not_zero_and_output_subsets_are_not_double_counted() -> None:
    unknown = unobservable("host_did_not_expose_field")
    assert unknown.value is None
    assert unknown.quality is ObservationQuality.UNOBSERVABLE
    usage = TokenUsage(
        input=exact(100, "test"),
        cached_input=exact(25, "test"),
        cache_write_input=exact(5, "test"),
        output=exact(50, "test"),
        reasoning_output=exact(20, "test"),
        tool_call_output=exact(10, "test"),
        reported_total=unknown,
        cached_input_relation=TokenRelation.SUBSET,
        cache_write_input_relation=TokenRelation.SUBSET,
    )

    assert usage.accounted_total().value == 150


def test_hermes_extra_hook_is_idempotent_safe_and_tracks_lineage(tmp_path: Path) -> None:
    ledger = UsageLedger(tmp_path)
    task = ledger.start_task("hermes", task_id="daily-20260823")
    payload = {
        "hook_event_name": "post_api_request",
        "session_id": "opaque-session",
        "tool_input": {"api_key": "sk-do-not-store", "prompt": "private"},
        "extra": {
            "api_request_id": "opaque-request",
            "turn_id": "opaque-turn",
            "task_id": "opaque-host-task",
            "provider": "openai",
            "model": "gpt-5",
            "assistant_tool_call_count": 2,
            "usage": {
                "input_tokens": 100,
                "cached_input_tokens": 25,
                "output_tokens": 40,
                "reasoning_tokens": 10,
                "tool_call_tokens": 5,
                "total_tokens": 140,
            },
        },
    }

    first = ledger.ingest_hook(task, "hermes", payload, phase="author")
    second = ledger.ingest_hook(task, "hermes", payload, phase="author")
    assert first == second
    summary = ledger.summarize_task(task)
    assert summary["raw_observation_count"] == 1
    assert summary["tokens"]["accounted_total"]["value"] == 140
    assert summary["tool_call_count"]["value"] == 2
    observation = summary["observations"][0]
    assert observation["session_id_hash"].startswith("sha256:")
    assert observation["turn_id_hash"].startswith("sha256:")
    assert observation["host_task_id_hash"].startswith("sha256:")

    persisted = "".join(
        path.read_text(encoding="utf-8")
        for path in (task.path / "events").glob("*.json")
    )
    for forbidden in (
        "sk-do-not-store",
        "private",
        "opaque-session",
        "opaque-request",
        "opaque-turn",
        "opaque-host-task",
        "tool_input",
        "prompt",
    ):
        assert forbidden not in persisted


def test_hermes_pre_and_error_hooks_preserve_unknown_usage(tmp_path: Path) -> None:
    ledger = UsageLedger(tmp_path)
    task = ledger.start_task("hermes", task_id="failed-run")
    base = {
        "session_id": "session-secret",
        "extra": {"api_request_id": "request-secret", "provider": "anthropic"},
    }
    ledger.ingest_hook(task, "hermes", {**base, "hook_event_name": "pre_api_request"})
    ledger.ingest_hook(
        task,
        "hermes",
        {**base, "hook_event_name": "api_request_error", "error": "secret error"},
    )

    summary = ledger.summarize_task(task)
    assert summary["raw_observation_count"] == 2
    assert summary["observation_count"] == 1
    assert summary["tokens"]["accounted_total"]["value"] is None
    assert summary["call_lifecycle"] == {
        "attempted_call_count": 1,
        "finished_call_count": 1,
        "failed_call_count": 1,
        "unclosed_call_count": 0,
        "orphan_finished_call_count": 0,
    }
    assert summary["usage_coverage"]["calls_with_observation_count"] == 1
    assert summary["usage_coverage"]["calls_without_observation_count"] == 0
    persisted = "".join(
        path.read_text(encoding="utf-8")
        for path in (task.path / "events").glob("*.json")
    )
    assert "secret error" not in persisted


def test_hermes_shell_hook_pre_post_lifecycle_is_linked_and_idempotent(
    tmp_path: Path,
) -> None:
    ledger = UsageLedger(tmp_path)
    task = ledger.start_task("hermes", task_id="shell-hook-run")
    common = {
        "session_id": "private-session",
        "extra": {
            "task_id": "private-host-task",
            "turn_id": "private-turn",
            "api_request_id": "private-api-request",
            "provider": "opencode-go",
            "model": "deepseek-v4-flash",
        },
    }
    pre = {
        **common,
        "hook_event_name": "pre_api_request",
        "extra": {
            **common["extra"],
            "approx_input_tokens": 2000,
            "started_at": 1234.5,
            "request": {"messages": [{"content": "不可信正文不能落盘"}]},
        },
    }
    post = {
        **common,
        "hook_event_name": "post_api_request",
        "extra": {
            **common["extra"],
            "api_duration": 2.5,
            "started_at": 1234.5,
            "ended_at": 1237.0,
            "finish_reason": "stop",
            "usage": {
                "input_tokens": 1900,
                "output_tokens": 100,
                "total_tokens": 2000,
            },
            "response": {"content": "模型正文不能落盘"},
        },
    }

    first_pre = ledger.ingest_hook(task, "hermes", pre, phase="acceptance")
    assert ledger.ingest_hook(task, "hermes", pre, phase="acceptance") == first_pre
    first_post = ledger.ingest_hook(task, "hermes", post, phase="acceptance")
    assert ledger.ingest_hook(task, "hermes", post, phase="acceptance") == first_post

    summary = ledger.summarize_task(task)
    assert summary["raw_observation_count"] == 2
    assert summary["observation_count"] == 1
    assert summary["tokens"]["accounted_total"]["value"] == 2000
    assert summary["call_lifecycle"] == {
        "attempted_call_count": 1,
        "finished_call_count": 1,
        "failed_call_count": 0,
        "unclosed_call_count": 0,
        "orphan_finished_call_count": 0,
    }
    assert summary["usage_coverage"]["calls_with_observation_count"] == 1
    assert summary["usage_coverage"]["calls_without_observation_count"] == 0
    ledger.finalize_task(task)
    persisted = "".join(
        path.read_text(encoding="utf-8")
        for path in (task.path / "events").glob("*.json")
    )
    for forbidden in (
        "private-session",
        "private-host-task",
        "private-turn",
        "private-api-request",
        "不可信正文不能落盘",
        "模型正文不能落盘",
    ):
        assert forbidden not in persisted


def test_hermes_usage_file_is_aggregate_and_drops_summary(tmp_path: Path) -> None:
    usage_file = tmp_path / "usage.json"
    usage_file.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "batch_id": "batch-1",
                        "api_calls": 4,
                        "tokens": {"input": 1200, "output": 340, "total": 1540},
                        "summary": "do not persist this prose",
                        "tool_trace": {"arguments": "secret"},
                    }
                ],
                "totals": {"total_tokens": 999999},
            }
        ),
        encoding="utf-8",
    )
    ledger = UsageLedger(tmp_path / "data")
    task = ledger.start_task("hermes", task_id="aggregate-run")
    ledger.import_usage_file(task, "hermes", usage_file, phase="author")

    summary = ledger.summarize_task(task)
    assert summary["covered_call_count"]["value"] == 4
    assert summary["tokens"]["accounted_total"]["value"] == 1540
    persisted = "".join(
        path.read_text(encoding="utf-8")
        for path in (task.path / "events").glob("*.json")
    )
    assert "do not persist this prose" not in persisted
    assert "secret" not in persisted
    assert "999999" not in persisted


def test_codex_and_openclaw_jsonl_adapters_count_tools_without_args(
    tmp_path: Path,
) -> None:
    codex_path = tmp_path / "rollout.jsonl"
    codex_path.write_text(
        json.dumps(
            {
                "id": "codex-event",
                "meta": {"session_id": "codex-session"},
                "payload": {
                    "last_token_usage": {
                        "input_tokens": 20,
                        "cached_input_tokens": 5,
                        "output_tokens": 8,
                        "reasoning_output_tokens": 3,
                    }
                },
                "response": {
                    "output": [
                        {"type": "function_call", "arguments": "top secret"}
                    ]
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    openclaw_path = tmp_path / "session.jsonl"
    openclaw_path.write_text(
        json.dumps(
            {
                "id": "openclaw-event",
                "provider": "anthropic",
                "message": {
                    "content": [
                        {"type": "tool_use", "input": {"secret": "do not store"}}
                    ],
                    "usage": {
                        "input": 10,
                        "cacheRead": 3,
                        "cacheWrite": 2,
                        "output": 4,
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    ledger = UsageLedger(tmp_path / "data")
    task = ledger.start_task("codex", task_id="multi-host")
    ledger.import_usage_file(task, "codex", codex_path)
    ledger.import_usage_file(task, "openclaw", openclaw_path)

    summary = ledger.summarize_task(task)
    assert summary["tool_call_count"]["value"] == 2
    assert summary["tokens"]["reasoning_output"]["known_value"] == 3
    persisted = "".join(
        path.read_text(encoding="utf-8")
        for path in (task.path / "events").glob("*.json")
    )
    assert "top secret" not in persisted
    assert "do not store" not in persisted
    assert "codex-session" not in persisted


def test_env_hook_finalize_and_schema_validation(tmp_path: Path) -> None:
    ledger = UsageLedger(tmp_path)
    task = ledger.start_task(
        "hermes",
        task_id="env-run",
        started_at="2026-08-23T08:00:00+08:00",
    )
    hook = {
        "hook_event_name": "post_api_request",
        "extra": {
            "api_request_id": "request-id",
            "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
        },
    }
    env = {
        "SIGNALTRAIL_USAGE_LEDGER": str(tmp_path),
        "SIGNALTRAIL_USAGE_TASK": task.task_id,
        "SIGNALTRAIL_USAGE_ADAPTER": "hermes",
        "SIGNALTRAIL_USAGE_PHASE": "author",
        "SIGNALTRAIL_USAGE_BATCH": "brief-batch-2",
        "SIGNALTRAIL_USAGE_AGENT_ROLE": "brief-worker",
        "SIGNALTRAIL_USAGE_RUN_ATTEMPT": "3",
        "SIGNALTRAIL_USAGE_REPAIR_ATTEMPT": "1",
        "SIGNALTRAIL_USAGE_EVALUATION_ATTEMPT": "0",
        "SIGNALTRAIL_USAGE_PARENT_SESSION": "private-parent-session",
    }
    paths = ingest_hook_from_env(environ=env, stdin=io.StringIO(json.dumps(hook)))
    assert len(paths) == 1
    open_summary = ledger.summarize_task(task)
    open_timing = open_summary["timing"]
    observation = open_summary["observations"][0]
    assert observation["batch_id"] == "brief-batch-2"
    assert observation["agent_role"] == "brief-worker"
    assert observation["run_attempt"] == 3
    assert observation["repair_attempt"] == 1
    assert observation["evaluation_attempt"] == 0
    assert observation["parent_session_id_hash"].startswith("sha256:")
    assert (
        open_summary["lineage_coverage"]["fields"]["parent_session_id_hash"]
        == {"present": 1, "missing": 0}
    )
    assert "private-parent-session" not in paths[0].read_text(encoding="utf-8")
    assert open_timing["started_at"] == "2026-08-23T00:00:00+00:00"
    assert open_timing["completed_at"] is None
    assert open_timing["wall_ms"] == {
        "value": None,
        "quality": "unobservable",
        "reason": "task_not_finalized",
        "known_value": None,
        "unobservable_observations": 1,
    }
    finalized = ledger.finalize_task(task, completed_at="2026-08-23T09:00:00+08:00")
    assert ledger.finalize_task(task) == finalized
    finalized_event = json.loads(finalized.read_text(encoding="utf-8"))
    final_timing = finalized_event["data"]["summary"]["timing"]
    assert final_timing == {
        "started_at": "2026-08-23T00:00:00+00:00",
        "completed_at": "2026-08-23T01:00:00+00:00",
        "wall_ms": {
            "value": 3_600_000,
            "quality": "exact",
            "known_value": 3_600_000,
            "unobservable_observations": 0,
        },
    }
    assert ledger.summarize_task(task)["timing"] == final_timing
    with pytest.raises(RuntimeError, match="already finalized"):
        ledger.ingest_hook(task, "hermes", hook)

    schema = json.loads(
        (ROOT / "schemas" / "llm-usage.schema.json").read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for event in _events(task.path):
        validator.validate(event)


def test_old_finalized_summary_without_timing_remains_readable(tmp_path: Path) -> None:
    ledger = UsageLedger(tmp_path)
    task = ledger.start_task(
        "hermes",
        task_id="old-finalized",
        started_at="2026-08-23T00:00:00+00:00",
    )
    finalized = ledger.finalize_task(
        task,
        completed_at="2026-08-23T00:00:02+00:00",
    )
    old_event = json.loads(finalized.read_text(encoding="utf-8"))
    old_event["data"]["summary"].pop("timing")
    finalized.write_text(json.dumps(old_event), encoding="utf-8")

    schema = json.loads(
        (ROOT / "schemas" / "llm-usage.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(old_event)
    rebuilt = ledger.summarize_task(task)
    assert rebuilt["timing"]["wall_ms"]["value"] == 2_000
    assert rebuilt["timing"]["wall_ms"]["quality"] == "exact"
