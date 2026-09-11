import argparse
import json
import tomllib
from pathlib import Path
from unittest.mock import Mock

import pytest

from daily_intelligence.cli import build_parser, main
from daily_intelligence.commands import HANDLERS
from daily_intelligence.utils import read_json, write_json
from daily_intelligence.workflow import (
    RunStatus,
)


def test_explainer_cli_dispatches_explicit_parent_and_preview_flag(
    cli_data_root, monkeypatch, capsys
):
    result = cli_data_root / "narratives/session/packet-r1.json"
    prepare = Mock(return_value=result)
    monkeypatch.setattr("daily_intelligence.commands.explainers.prepare_explainer", prepare)
    run = cli_data_root / "run.json"
    assert main(["explainer", "prepare", "--run", str(run), "--experimental"]) == 0
    prepare.assert_called_once_with(run, cli_data_root, experimental=True)
    assert json.loads(capsys.readouterr().out)["artifact_path"] == str(result)


def test_explainer_cli_reports_rejected_parent_without_changing_report(
    cli_data_root, monkeypatch, capsys
):
    prepare = Mock(side_effect=ValueError("Parent is not completed"))
    monkeypatch.setattr("daily_intelligence.commands.explainers.prepare_explainer", prepare)
    assert main(["explainer", "prepare", "--run", str(cli_data_root / "run.json")]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "rejected"


@pytest.fixture
def cli_data_root(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("DAILY_INTEL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr("daily_intelligence.cli.load_hermes_environment", lambda: None)
    return tmp_path / "data"


def test_all_parser_commands_have_handlers_and_entrypoint_names_are_compatible():
    parser = build_parser()
    commands = next(
        action.choices
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    assert set(commands) == {*HANDLERS, "data-root"}
    project = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )
    entries = project["project"]["scripts"]
    assert entries["signaltrail"] == entries["daily-intel"] == "daily_intelligence.cli:main"


@pytest.mark.parametrize("command", ["serve", "serve-monitor"])
def test_monitor_server_aliases_forward_the_same_options(cli_data_root, monkeypatch, command):
    serve = Mock()
    monkeypatch.setattr("daily_intelligence.commands.monitor.serve_monitor", serve)
    assert main([command, "--port", "8766", "--refresh-minutes", "30", "--open"]) == 0
    args, kwargs = serve.call_args
    assert args[1] == cli_data_root
    assert kwargs == {
        "host": "127.0.0.1",
        "port": 8766,
        "open_browser": True,
        "allow_remote": False,
        "refresh_minutes": 30,
    }


def test_monitor_status_reports_absence_then_reads_saved_snapshot(cli_data_root, capsys):
    assert main(["monitor-status"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "not_initialized"
    write_json(
        cli_data_root / "monitor/snapshot.json",
        {
            "generated_at": "2026-09-08T06:00:00+08:00",
            "token_usage": 0,
            "summary": {"items": 3},
        },
    )
    assert main(["monitor-status"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert (payload["status"], payload["items"], payload["token_usage"]) == ("ready", 3, 0)


@pytest.mark.parametrize(
    ("arguments", "operation"),
    [
        (["collect", "--edition", "morning", "--source", "reuters"], "collect_sources"),
        (["build-context", "--index", "INDEX", "--edition", "evening"], "build_context"),
        (["extract-content", "--index", "INDEX", "--item-id", "item-1"], "extract_content"),
    ],
)
def test_source_commands_dispatch_and_keep_path_output(
    cli_data_root, monkeypatch, capsys, arguments, operation
):
    output = cli_data_root / "result.json"
    worker = Mock(return_value=output)
    monkeypatch.setattr(f"daily_intelligence.commands.sources.{operation}", worker)
    arguments = [
        str(cli_data_root / "indexes/test.json") if arg == "INDEX" else arg for arg in arguments
    ]
    assert main(arguments) == 0
    assert capsys.readouterr().out.strip() == str(output)
    worker.assert_called_once()
    if operation == "collect_sources":
        assert worker.call_args.kwargs["only_source_ids"] == {"reuters"}
    elif operation == "extract_content":
        assert worker.call_args.kwargs["selected_ids"] == ["item-1"]


def test_validation_exit_code_stderr_and_data_root_guard(cli_data_root, monkeypatch, capsys):
    validate = Mock(return_value=(["invalid evidence"], ["missing time"]))
    monkeypatch.setattr("daily_intelligence.commands.reports.validate_report", validate)
    arguments = ["validate-report", "draft.json", "--index", str(cli_data_root / "index.json")]
    assert main(arguments) == 1
    captured = capsys.readouterr()
    assert captured.err == "ERROR: invalid evidence\n"
    assert captured.out.splitlines()[0] == "WARNING: missing time"
    assert json.loads(captured.out.splitlines()[-1]) == {"errors": 1, "warnings": 1}
    validate.reset_mock()
    arguments[-1] = str(cli_data_root.parent / "foreign-index.json")
    with pytest.raises(ValueError, match="outside the active"):
        main(arguments)
    validate.assert_not_called()


def test_notion_publication_dispatch_preserves_explicit_republish(
    cli_data_root, monkeypatch, capsys
):
    publish = Mock(return_value=("page-1", "published"))
    monkeypatch.setattr("daily_intelligence.commands.reports.publish_report", publish)
    report = cli_data_root / "reports/report.json"
    assert main(["publish-notion", str(report), "--republish"]) == 0
    assert publish.call_args.kwargs["force"] is True
    assert json.loads(capsys.readouterr().out) == {"page_id": "page-1", "status": "published"}


def test_cli_exposes_two_stage_workflow():
    parser = build_parser()
    prepared = parser.parse_args(["run-edition", "--edition", "morning", "--language", "en"])
    enriched = parser.parse_args(["enrich-edition", "--run", "run.json"])
    finalized = parser.parse_args(
        ["finalize-edition", "--run", "run.json", "--report", "draft.json"]
    )
    verification = parser.parse_args(["verify-pending", "--index", "index.json"])
    evaluation = parser.parse_args(
        ["finalize-evaluation", "--report", "report.json", "--evaluation", "eval.json"]
    )
    assert (prepared.command, enriched.command, finalized.command) == (
        "run-edition",
        "enrich-edition",
        "finalize-edition",
    )
    assert prepared.language == "en"
    assert verification.command == "verify-pending"
    assert evaluation.command == "finalize-evaluation"
    assert prepared.open_verification is False
    assert (
        parser.parse_args(
            ["run-edition", "--edition", "morning", "--open-verification"]
        ).open_verification
        is True
    )
    assert (
        parser.parse_args(["run-edition", "--edition", "morning", "--unattended"]).open_verification
        is False
    )


def test_run_edition_can_open_interactive_verification_after_collection(
    monkeypatch, tmp_path: Path, capsys
):
    data_dir = tmp_path / "data"
    index_path = write_json(
        data_dir / "indexes" / "2026-07-17" / "morning-r1.json",
        {"date": "2026-07-17", "edition": "morning", "items": [], "sources": []},
    )
    run_path = write_json(
        data_dir / "runs" / "2026-07-17" / "morning.json",
        {
            "date": "2026-07-17",
            "edition": "morning",
            "status": RunStatus.AWAITING_SELECTION,
            "artifacts": {"index_path": str(index_path)},
        },
    )
    calls = []

    monkeypatch.setattr(
        "daily_intelligence.commands.editions.prepare_edition",
        lambda **_kwargs: run_path,
    )

    def fake_verification(
        index,
        _config,
        data,
        profile_dir=None,
        browser_channel=None,
        timeout_seconds=300,
    ):
        calls.append(
            {
                "index": index,
                "data": data,
                "profile_dir": profile_dir,
                "browser_channel": browser_channel,
                "timeout_seconds": timeout_seconds,
            }
        )
        return {"status": "completed_without_capture", "captured_pages": 0}

    monkeypatch.setattr(
        "daily_intelligence.commands.editions.run_pending_verification",
        fake_verification,
    )

    exit_code = main(
        [
            "--data-dir",
            str(data_dir),
            "run-edition",
            "--edition",
            "morning",
            "--open-verification",
            "--verification-timeout-seconds",
            "17",
            "--profile-dir",
            str(tmp_path / "profile"),
            "--browser-channel",
            "msedge",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["automatic_verification"]["status"] == "completed_without_capture"
    assert read_json(run_path)["automatic_verification"]["captured_pages"] == 0
    assert calls == [
        {
            "index": index_path,
            "data": data_dir.resolve(),
            "profile_dir": tmp_path / "profile",
            "browser_channel": "msedge",
            "timeout_seconds": 17,
        }
    ]


def test_run_edition_does_not_open_verification_by_default(monkeypatch, tmp_path: Path, capsys):
    data_dir = tmp_path / "data"
    index_path = write_json(
        data_dir / "indexes" / "2026-07-17" / "morning-r1.json",
        {"date": "2026-07-17", "edition": "morning", "items": [], "sources": []},
    )
    run_path = write_json(
        data_dir / "runs" / "2026-07-17" / "morning.json",
        {
            "date": "2026-07-17",
            "edition": "morning",
            "status": RunStatus.AWAITING_SELECTION,
            "artifacts": {"index_path": str(index_path)},
        },
    )
    monkeypatch.setattr(
        "daily_intelligence.commands.editions.prepare_edition",
        lambda **_kwargs: run_path,
    )

    def fail_if_opened(*_args, **_kwargs):
        raise AssertionError("verification must remain opt-in")

    monkeypatch.setattr(
        "daily_intelligence.commands.editions.run_pending_verification",
        fail_if_opened,
    )

    exit_code = main(
        [
            "--data-dir",
            str(data_dir),
            "run-edition",
            "--edition",
            "morning",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert "automatic_verification" not in output
    assert "automatic_verification" not in read_json(run_path)


def test_republish_name_is_explicit_and_legacy_force_alias_remains():
    parser = build_parser()

    current = parser.parse_args(
        ["finalize-edition", "--run", "run.json", "--report", "draft.json", "--republish"]
    )
    legacy = parser.parse_args(
        [
            "finalize-edition",
            "--run",
            "run.json",
            "--report",
            "draft.json",
            "--force-publish",
        ]
    )

    assert current.force_publish is True
    assert legacy.force_publish is True


def test_verification_commands_have_noninteractive_visible_wait_timeout():
    parser = build_parser()

    source = parser.parse_args(["verify-source", "reuters"])
    pending = parser.parse_args(["verify-pending", "--index", "index.json"])
    automatic = parser.parse_args(["run-edition", "--edition", "morning", "--open-verification"])

    assert source.timeout_seconds == 300
    assert pending.timeout_seconds == 300
    assert automatic.open_verification is True
    assert automatic.verification_timeout_seconds == 180
