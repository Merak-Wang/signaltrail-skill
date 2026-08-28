from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from daily_intelligence.llm_usage import UsageLedger
from daily_intelligence.usage_cli import build_parser, main


def _start_task(data_dir: Path, task_id: str = "task-cli") -> UsageLedger:
    """处理：为 CLI 测试创建一个不调用模型的本地计量任务。
    输入：pytest 临时数据根和可选安全 task ID。
    输出：已经写入 task.started 事件的 UsageLedger。
    """

    ledger = UsageLedger(data_dir)
    ledger.start_task(
        "hermes",
        task_id=task_id,
        source_tag="pytest",
        started_at="2026-08-23T08:00:00+00:00",
    )
    return ledger


def _hermes_receipt(secret: str = "RAW-RECEIPT-MUST-NOT-LEAK") -> dict:
    """处理：构造含敏感诱饵文本和精确 usage 的 Hermes 测试回执。
    输入：只用于断言不回显的诱饵字符串。
    输出：适配器可消费且 raw 文本不应进入 stdout/ledger 的字典。
    """

    return {
        "request_id": "request-1",
        "provider": "openrouter",
        "model": "example/model",
        "prompt": secret,
        "response": {"content": secret},
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 3,
            "total_tokens": 15,
        },
    }


def test_start_outputs_only_task_identity_and_path(tmp_path: Path, capsys):
    assert (
        main(
            [
                "start",
                "--ledger",
                str(tmp_path),
                "--agent",
                "hermes",
                "--task-id",
                "task-start",
                "--source-tag",
                "daily-report",
                "--started-at",
                "2026-08-23T08:00:00+00:00",
            ]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "date": "2026-08-23",
        "path": str(tmp_path / "usage" / "2026-08-23" / "task-start"),
        "task_id": "task-start",
    }
    assert (Path(output["path"]) / "events").is_dir()


def test_hook_reads_stdin_and_environment_without_stdout(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    ledger = _start_task(tmp_path, "task-hook")
    secret = "HOOK-RAW-MUST-NOT-LEAK"
    monkeypatch.setenv("SIGNALTRAIL_USAGE_LEDGER", str(tmp_path))
    monkeypatch.setenv("SIGNALTRAIL_USAGE_TASK", "task-hook")
    monkeypatch.setenv("SIGNALTRAIL_USAGE_ADAPTER", "hermes")
    monkeypatch.setenv("SIGNALTRAIL_USAGE_PHASE", "brief-authoring")
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(json.dumps(_hermes_receipt(secret))),
    )

    assert main(["hook"]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""

    summary = ledger.summarize_task("task-hook")
    assert summary["observation_count"] == 1
    assert summary["tokens"]["reported_total"]["value"] == 15
    event_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "usage").rglob("*.json")
    )
    assert secret not in event_text


def test_import_outputs_only_safe_event_metadata(tmp_path: Path, capsys):
    _start_task(tmp_path, "task-import")
    secret = "IMPORT-RAW-MUST-NOT-LEAK"
    receipt = tmp_path / "hermes-usage.json"
    receipt.write_text(json.dumps(_hermes_receipt(secret)), encoding="utf-8")

    assert (
        main(
            [
                "import",
                "--ledger",
                str(tmp_path),
                "--task-id",
                "task-import",
                "--adapter",
                "hermes",
                "--phase",
                "analysis",
                str(receipt),
            ]
        )
        == 0
    )

    output_text = capsys.readouterr().out
    output = json.loads(output_text)
    assert output["task_id"] == "task-import"
    assert output["event_count"] == 1
    assert len(output["paths"]) == 1
    assert secret not in output_text
    assert receipt.read_text(encoding="utf-8").find(secret) >= 0


def test_summary_uses_environment_task_and_preserves_unknowns(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    ledger = _start_task(tmp_path, "task-summary")
    ledger.ingest_hook("task-summary", "hermes", _hermes_receipt())
    monkeypatch.setenv("SIGNALTRAIL_USAGE_LEDGER", str(tmp_path))
    monkeypatch.setenv("SIGNALTRAIL_USAGE_TASK", "task-summary")

    assert main(["summary"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["task_id"] == "task-summary"
    assert output["tokens"]["reported_total"]["value"] == 15
    assert output["tokens"]["reasoning_output"]["value"] is None
    assert output["tokens"]["reasoning_output"]["quality"] == "unobservable"


def test_finalize_outputs_path_and_seals_task(tmp_path: Path, capsys):
    ledger = _start_task(tmp_path, "task-finalize")
    ledger.ingest_hook("task-finalize", "hermes", _hermes_receipt())

    assert (
        main(
            [
                "finalize",
                "--ledger",
                str(tmp_path),
                "--task-id",
                "task-finalize",
                "--status",
                "completed",
                "--completed-at",
                "2026-08-23T09:00:00+00:00",
            ]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert output["task_id"] == "task-finalize"
    finalized_path = Path(output["path"])
    assert finalized_path.is_file()
    with pytest.raises(RuntimeError, match="already finalized"):
        ledger.ingest_hook("task-finalize", "hermes", _hermes_receipt())


def test_import_parser_does_not_accept_inline_payload():
    parser = build_parser()

    with pytest.raises(ValueError, match="invalid command arguments"):
        parser.parse_args(
            [
                "import",
                "--ledger",
                "usage",
                "--task-id",
                "task-1",
                "--payload",
                '{"secret":"must-not-be-accepted"}',
                "receipt.json",
            ]
        )


def test_main_argument_errors_do_not_echo_inline_values(capsys):
    secret = "sk-proj-INLINESECRET123"

    assert main(["summary", "--payload", secret]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert secret not in captured.err
    assert json.loads(captured.err) == {
        "error": "usage_command_failed",
        "error_type": "ValueError",
    }


def test_failures_emit_only_safe_error_json(tmp_path: Path, capsys):
    secret = "MISSING-TASK-RAW-MUST-NOT-LEAK"

    assert (
        main(
            [
                "summary",
                "--ledger",
                str(tmp_path / secret),
                "--task-id",
                "missing-task",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error == {
        "error": "usage_command_failed",
        "error_type": "FileNotFoundError",
    }
    assert secret not in captured.err
