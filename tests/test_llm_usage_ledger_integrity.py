from __future__ import annotations

import json
import multiprocessing
import threading
from pathlib import Path
from typing import Any

import pytest

import daily_intelligence.llm_usage.ledger as ledger_module
from daily_intelligence.llm_usage import CallHandle, TaskHandle, UsageLedger
from daily_intelligence.llm_usage.adapters.base import canonical_digest


def _usage_payload(request_id: str = "request-1") -> dict[str, Any]:
    """处理：构造不含正文且带精确总量的 Hermes 回执。
    输入：仅用于调用关联且不会落盘明文的 request ID。
    输出：可由 Hermes adapter 转为一次 usage observation 的测试映射。
    """

    return {
        "hook_event_name": "post_api_request",
        "extra": {
            "api_request_id": request_id,
            "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
        },
    }


def _hold_process_task_guard(
    data_dir: str,
    task_id: str,
    entered: Any,
    release: Any,
) -> None:
    """处理：在子进程持有真实 OS task 锁直到父进程放行。
    输入：data 根、task ID 以及跨进程 entered/release 同步事件。
    输出：没有业务返回值；用于证明另一进程无法越过同一 task 临界区。
    """

    ledger = UsageLedger(data_dir)
    task = ledger.resolve_task(task_id)
    with ledger._task_guard(task):
        entered.set()
        if not release.wait(10):
            raise TimeoutError("parent did not release process task guard")


def _finalize_in_process(
    data_dir: str,
    task_id: str,
    attempted: Any,
    completed: Any,
) -> None:
    """处理：在独立进程尝试封存 task 并报告调用边界。
    输入：data 根、task ID 以及 attempted/completed 跨进程同步事件。
    输出：没有业务返回值；异常通过子进程 exit code 暴露给测试。
    """

    attempted.set()
    try:
        UsageLedger(data_dir).finalize_task(
            task_id,
            completed_at="2026-08-23T00:00:02+00:00",
        )
    finally:
        completed.set()


def test_finalize_waits_for_inflight_observation_and_seals_same_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = UsageLedger(tmp_path)
    task = ledger.start_task(
        "hermes",
        task_id="race-task",
        started_at="2026-08-23T00:00:00+00:00",
    )
    writer_entered = threading.Event()
    release_writer = threading.Event()
    finalizer_started = threading.Event()
    finalizer_done = threading.Event()
    errors: list[BaseException] = []
    finalized_paths: list[Path] = []
    original_write = ledger._write_event_unlocked

    def gated_write(
        selected_task: TaskHandle,
        event_type: str,
        *,
        dedupe_key: str,
        data: dict[str, Any],
    ) -> Path:
        if event_type == "usage.observed":
            writer_entered.set()
            if not release_writer.wait(5):
                raise TimeoutError("test did not release observation writer")
        return original_write(
            selected_task,
            event_type,
            dedupe_key=dedupe_key,
            data=data,
        )

    monkeypatch.setattr(ledger, "_write_event_unlocked", gated_write)

    def write_observation() -> None:
        try:
            ledger.ingest_hook(task, "hermes", _usage_payload())
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    def finalize() -> None:
        finalizer_started.set()
        try:
            finalized_paths.append(
                ledger.finalize_task(
                    task,
                    completed_at="2026-08-23T00:00:02+00:00",
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)
        finally:
            finalizer_done.set()

    writer = threading.Thread(target=write_observation)
    finalizer = threading.Thread(target=finalize)
    writer.start()
    assert writer_entered.wait(5)
    finalizer.start()
    assert finalizer_started.wait(5)
    assert not finalizer_done.wait(0.2)
    release_writer.set()
    writer.join(5)
    finalizer.join(5)

    assert not errors
    assert len(finalized_paths) == 1
    frozen = json.loads(finalized_paths[0].read_text(encoding="utf-8"))["data"][
        "summary"
    ]
    assert frozen["observation_count"] == 1
    assert frozen["tokens"]["accounted_total"]["value"] == 5
    with pytest.raises(RuntimeError, match="already finalized"):
        ledger.ingest_hook(task, "hermes", _usage_payload("late-request"))


def test_task_guard_serializes_independent_processes(tmp_path: Path) -> None:
    ledger = UsageLedger(tmp_path)
    task = ledger.start_task(
        "hermes",
        task_id="process-lock",
        started_at="2026-08-23T00:00:00+00:00",
    )
    context = multiprocessing.get_context("spawn")
    holder_entered = context.Event()
    release_holder = context.Event()
    finalizer_attempted = context.Event()
    finalizer_completed = context.Event()
    holder = context.Process(
        target=_hold_process_task_guard,
        args=(str(tmp_path), task.task_id, holder_entered, release_holder),
    )
    finalizer = context.Process(
        target=_finalize_in_process,
        args=(str(tmp_path), task.task_id, finalizer_attempted, finalizer_completed),
    )

    holder.start()
    assert holder_entered.wait(10)
    finalizer.start()
    assert finalizer_attempted.wait(10)
    assert not finalizer_completed.wait(0.2)
    release_holder.set()
    holder.join(10)
    finalizer.join(10)

    assert holder.exitcode == 0
    assert finalizer.exitcode == 0
    assert finalizer_completed.is_set()
    assert ledger.summarize_task(task)["timing"]["completed_at"] == (
        "2026-08-23T00:00:02+00:00"
    )


def test_start_task_without_explicit_time_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = UsageLedger(tmp_path)
    first = ledger.start_task("hermes", task_id="idempotent-start")
    started_at = ledger.summarize_task(first)["timing"]["started_at"]
    original_timestamp = ledger_module._timestamp

    def shifted_timestamp(value: str | None) -> str:
        if value is None:
            return "2099-01-01T00:00:00+00:00"
        return original_timestamp(value)

    monkeypatch.setattr(ledger_module, "_timestamp", shifted_timestamp)
    replayed = ledger.start_task("hermes", task_id="idempotent-start")

    assert replayed == first
    assert ledger.summarize_task(replayed)["timing"]["started_at"] == started_at
    assert len(list((first.path / "events").glob("*.json"))) == 1


def test_payload_tampering_is_detected_before_summary(tmp_path: Path) -> None:
    ledger = UsageLedger(tmp_path)
    task = ledger.start_task("hermes", task_id="tampered-payload")
    event_path = ledger.ingest_hook(task, "hermes", _usage_payload())[0]
    event = json.loads(event_path.read_text(encoding="utf-8"))
    event["data"]["observation"]["tokens"]["reported_total"]["value"] = 999
    event_path.write_text(json.dumps(event), encoding="utf-8")

    with pytest.raises(RuntimeError, match="payload hash mismatch"):
        ledger.summarize_task(task)


def test_event_filename_and_identity_tampering_is_detected(tmp_path: Path) -> None:
    ledger = UsageLedger(tmp_path)
    task = ledger.start_task("hermes", task_id="tampered-identity")
    event_path = ledger.ingest_hook(task, "hermes", _usage_payload())[0]
    renamed = event_path.with_name(f"{'0' * 64}.json")
    event_path.rename(renamed)

    with pytest.raises(RuntimeError, match="Invalid LLM usage event structure"):
        ledger.summarize_task(task)


def test_call_lifecycle_and_usage_coverage_remain_separate(tmp_path: Path) -> None:
    ledger = UsageLedger(tmp_path)
    task = ledger.start_task(
        "hermes",
        task_id="failed-call",
        started_at="2026-08-23T00:00:00+00:00",
    )
    call = ledger.start_call(
        task,
        "author",
        call_id="call-1",
        started_at="2026-08-23T00:00:01+00:00",
    )
    ledger.ingest_hook(task, "hermes", _usage_payload(), call_id=call.call_id)
    ledger.finish_call(
        call,
        status="failed",
        completed_at="2026-08-23T00:00:02+00:00",
    )

    summary = ledger.summarize_task(task)
    assert summary["call_lifecycle"] == {
        "attempted_call_count": 1,
        "finished_call_count": 1,
        "failed_call_count": 1,
        "unclosed_call_count": 0,
        "orphan_finished_call_count": 0,
    }
    assert summary["usage_coverage"] == {
        "usage_covered_call_count": {
            "value": 1,
            "quality": "exact",
            "known_value": 1,
            "unobservable_observations": 0,
        },
        "calls_with_observation_count": 1,
        "calls_with_accounted_tokens_count": 1,
        "calls_without_observation_count": 0,
        "calls_without_accounted_tokens_count": 0,
        "orphan_usage_call_count": 0,
        "unlinked_observation_count": 0,
    }
    assert summary["tokens"]["accounted_total"]["value"] == 5
    finalized = ledger.finalize_task(
        task,
        status="failed",
        completed_at="2026-08-23T00:00:03+00:00",
    )
    frozen = json.loads(finalized.read_text(encoding="utf-8"))["data"]["summary"]
    assert frozen["call_lifecycle"] == summary["call_lifecycle"]


def test_completed_finalize_rejects_unclosed_call_but_failure_preserves_it(
    tmp_path: Path,
) -> None:
    ledger = UsageLedger(tmp_path)
    task = ledger.start_task(
        "hermes",
        task_id="unclosed-call",
        started_at="2026-08-23T00:00:00+00:00",
    )
    ledger.start_call(
        task,
        "author",
        call_id="call-open",
        started_at="2026-08-23T00:00:01+00:00",
    )

    with pytest.raises(RuntimeError, match="unclosed calls"):
        ledger.finalize_task(
            task,
            status="completed",
            completed_at="2026-08-23T00:00:02+00:00",
        )
    finalized = ledger.finalize_task(
        task,
        status="failed",
        completed_at="2026-08-23T00:00:02+00:00",
    )
    summary = json.loads(finalized.read_text(encoding="utf-8"))["data"]["summary"]
    assert summary["call_lifecycle"]["unclosed_call_count"] == 1
    assert summary["usage_coverage"]["calls_without_observation_count"] == 1
    assert summary["tokens"]["accounted_total"]["value"] is None


def test_finalize_replay_rejects_an_explicitly_different_completion_time(
    tmp_path: Path,
) -> None:
    ledger = UsageLedger(tmp_path)
    task = ledger.start_task(
        "hermes",
        task_id="finalize-time-conflict",
        started_at="2026-08-23T00:00:00+00:00",
    )
    finalized = ledger.finalize_task(
        task,
        completed_at="2026-08-23T00:00:02+00:00",
    )

    assert ledger.finalize_task(task) == finalized
    with pytest.raises(RuntimeError, match="another completion time"):
        ledger.finalize_task(
            task,
            completed_at="2026-08-23T00:00:03+00:00",
        )


def test_finish_call_rejects_missing_local_start(tmp_path: Path) -> None:
    ledger = UsageLedger(tmp_path)
    task = ledger.start_task(
        "hermes",
        task_id="orphan-finish",
        started_at="2026-08-23T00:00:00+00:00",
    )
    orphan = CallHandle(
        task,
        "call-missing",
        "author",
        "2026-08-23T00:00:01+00:00",
    )

    with pytest.raises(RuntimeError, match="without call.started"):
        ledger.finish_call(
            orphan,
            completed_at="2026-08-23T00:00:02+00:00",
        )
    assert ledger.summarize_task(task)["call_lifecycle"] == {
        "attempted_call_count": 0,
        "finished_call_count": 0,
        "failed_call_count": 0,
        "unclosed_call_count": 0,
        "orphan_finished_call_count": 0,
    }


def test_forged_task_handle_cannot_read_or_write_outside_usage_root(
    tmp_path: Path,
) -> None:
    ledger = UsageLedger(tmp_path)
    task = ledger.start_task("hermes", task_id="real-task")
    outside = tmp_path / "outside-task"
    forged = TaskHandle(task.data_dir, task.task_id, task.date, outside)

    with pytest.raises(ValueError, match="path does not match"):
        ledger.summarize_task(forged)
    forged_call = CallHandle(
        forged,
        "call-forged",
        "author",
        "2026-08-23T00:00:00+00:00",
    )
    with pytest.raises(ValueError, match="path does not match"):
        ledger.finish_call(forged_call)
    assert not (outside / "events").exists()


def test_historical_offset_timestamps_remain_readable_without_rewriting(
    tmp_path: Path,
) -> None:
    ledger = UsageLedger(tmp_path)
    task = ledger.start_task(
        "hermes",
        task_id="historical-offset",
        started_at="2026-08-23T00:00:00+00:00",
    )
    event_path = next((task.path / "events").glob("*.json"))
    event = json.loads(event_path.read_text(encoding="utf-8"))
    event["recorded_at"] = "2026-08-23T08:00:00+08:00"
    event["data"]["started_at"] = "2026-08-23T08:00:00+08:00"
    event["payload_hash"] = f"sha256:{canonical_digest(event['data'])}"
    event_path.write_text(
        json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    summary = ledger.summarize_task(task)

    assert summary["timing"]["started_at"] == "2026-08-23T00:00:00+00:00"
