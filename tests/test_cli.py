import argparse
import io
import json
import tomllib
from pathlib import Path
from unittest.mock import Mock

import pytest

from signaltrail.cli import build_parser, main
from signaltrail.commands import HANDLERS
from signaltrail.commands.common import print_json_file
from signaltrail.config import load_config
from signaltrail.utils import read_json, write_json
from signaltrail.workflow import (
    RunStatus,
)


@pytest.mark.parametrize("encoding", ["utf-8", "gbk"])
def test_saved_json_prints_losslessly_with_terminal_encoding(tmp_path, monkeypatch, encoding):
    payload = {"status": "accepted", "summary": "面积 2 m²，新闻已保存 📰"}
    result = write_json(tmp_path / "result.json", payload)
    buffer = io.BytesIO()
    with io.TextIOWrapper(buffer, encoding=encoding) as stdout:
        monkeypatch.setattr("sys.stdout", stdout)
        print_json_file(result)
        stdout.flush()
        output = buffer.getvalue().decode(encoding)
    assert json.loads(output) == payload
    assert read_json(result) == payload
    if encoding == "utf-8":
        assert payload["summary"] in output


@pytest.mark.parametrize("score_args,expected_score", [([], 0), (["--min-importance", "70"], 70)])
def test_slides_cli_prepares_bounded_batches(cli_data_root, monkeypatch, capsys,
                                           score_args, expected_score):
    prepare = Mock(return_value={"plan_path": "slides-plan.json", "news_count": 18})
    monkeypatch.setattr("signaltrail.commands.slides.prepare_slides", prepare)
    config = load_config()
    monkeypatch.setattr("signaltrail.cli.load_config", Mock(return_value=config))
    report, index = cli_data_root / "report.json", cli_data_root / "index.json"
    assert main(["slides", "prepare", "--report", str(report), "--index", str(index),
                 "--batch-size", "3", "--max-news", "22", "--item-id", "news-1",
                 *score_args]) == 0
    prepare.assert_called_once()
    assert prepare.call_args.args == (report, index, cli_data_root)
    options = prepare.call_args.kwargs
    assert options["min_importance"] == expected_score
    assert options["item_ids"] == ["news-1"]
    assert (options["batch_size"], options["max_news"]) == (3, 22)
    assert options["max_input_tokens"] is None
    assert options["config"] is config
    assert config.sources
    assert json.loads(capsys.readouterr().out)["news_count"] == 18


@pytest.mark.parametrize("language_args,expected", [([], "zh-CN"), (["--language", "en"], "en")])
def test_slides_cli_prepares_index_without_report(cli_data_root, monkeypatch, capsys,
                                                 language_args, expected):
    prepare = Mock(return_value={"reused_count": 2, "pending_news_count": 3})
    monkeypatch.setattr("signaltrail.commands.slides.prepare_slides", prepare)
    config = load_config()
    monkeypatch.setattr("signaltrail.cli.load_config", Mock(return_value=config))
    index, old_plan = cli_data_root / "index.json", cli_data_root / "old-plan.json"
    assert main(["slides", "prepare", "--index", str(index), "--reuse-plan", str(old_plan),
                 *language_args]) == 0
    prepare.assert_called_once()
    assert prepare.call_args.args == (None, index, cli_data_root)
    options = prepare.call_args.kwargs
    assert options["language"] == expected
    assert options["reuse_plan"] == old_plan
    assert options["max_input_tokens"] is None
    assert options["config"] is config
    assert config.sources
    assert json.loads(capsys.readouterr().out)["reused_count"] == 2


@pytest.mark.parametrize(("invalid", "expected"), [([], 0), ([1], 1)])
def test_slides_check_only_exit_code_tracks_invalid_batches(
    cli_data_root, monkeypatch, capsys, invalid, expected
):
    result = {"status": "partial" if invalid else "ready_to_submit", "check_only": True,
              "accepted": [], "pending": [1], "invalid": invalid}
    monkeypatch.setattr("signaltrail.commands.slides._submit_many", Mock(return_value=result))
    code = main(["slides", "submit", "--plan", str(cli_data_root / "plan.json"),
                 "--draft-dir", str(cli_data_root), "--check-only"])
    assert code == expected
    assert json.loads(capsys.readouterr().out) == result


def test_slides_cli_reports_missing_plan(cli_data_root, capsys):
    assert main(["slides", "status", "--plan", str(cli_data_root / "missing.json")]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "rejected"


@pytest.mark.parametrize("offline", [False, True])
def test_slides_render_explicitly_controls_image_fetching(cli_data_root, monkeypatch, offline):
    render = Mock(return_value={"news_count": 1})
    monkeypatch.setattr("signaltrail.commands.slides.render_slides", render)
    plan = cli_data_root / "plan.json"
    args = ["slides", "render", "--plan", str(plan)] + (["--offline"] if offline else [])
    assert main(args) == 0
    assert render.call_args.args == (plan, cli_data_root)
    assert render.call_args.kwargs["refresh_images"] is not offline
    assert render.call_args.kwargs["media_config"].enabled is True


def test_research_cli_prepares_before_a_report_with_explicit_approval(
    cli_data_root, monkeypatch, capsys
):
    questions = write_json(cli_data_root / "questions.json", {"questions": []})
    prepare = Mock(return_value=cli_data_root / "snapshot.json")
    monkeypatch.setattr("signaltrail.commands.research.prepare_research_snapshot", prepare)
    index = cli_data_root / "index.json"
    assert main(["research", "prepare", "--index", str(index), "--item-id", "item-1",
                 "--cutoff", "2026-09-20T09:00:00+08:00", "--questions", str(questions)]) == 0
    prepare.assert_called_once_with(index, ["item-1"], "2026-09-20T09:00:00+08:00", [],
                                     cli_data_root, previous_path=None, discovery_path=None)
    assert "snapshot.json" in json.loads(capsys.readouterr().out)["artifact_path"]


def test_research_cli_reports_unavailable_snapshot(cli_data_root, capsys):
    assert main(["research", "evaluate", "--snapshot", str(cli_data_root / "missing.json")]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "rejected"


def test_explainer_cli_dispatches_explicit_parent_and_preview_flag(
    cli_data_root, monkeypatch, capsys
):
    result = cli_data_root / "narratives/session/packet-r1.json"
    prepare = Mock(return_value=result)
    monkeypatch.setattr("signaltrail.commands.explainers.prepare_explainer", prepare)
    run = cli_data_root / "run.json"
    assert main(["explainer", "prepare", "--run", str(run), "--experimental"]) == 0
    prepare.assert_called_once_with(run, cli_data_root, experimental=True)
    assert json.loads(capsys.readouterr().out)["artifact_path"] == str(result)


def test_explainer_cli_reports_rejected_parent_without_changing_report(
    cli_data_root, monkeypatch, capsys
):
    prepare = Mock(side_effect=ValueError("Parent is not completed"))
    monkeypatch.setattr("signaltrail.commands.explainers.prepare_explainer", prepare)
    assert main(["explainer", "prepare", "--run", str(cli_data_root / "run.json")]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "rejected"


def test_regular_cli_ignores_hermes_environment_and_registry(monkeypatch, tmp_path, capsys):
    import signaltrail.runtime as runtime

    hermes_home = tmp_path / "hermes"
    (hermes_home / "state").mkdir(parents=True)
    (hermes_home / ".env").write_text("DAILY_INTEL_DATA_DIR=/wrong\n", encoding="utf-8")
    (hermes_home / "state" / "signaltrail-data-root.json").write_text(
        json.dumps({"data_root": str(tmp_path / "hermes-bound")}), encoding="utf-8"
    )
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "local"))
    monkeypatch.delenv("SIGNALTRAIL_DATA_DIR", raising=False)
    monkeypatch.delenv("DAILY_INTEL_DATA_DIR", raising=False)
    monkeypatch.setattr(
        "signaltrail.hermes_runner.load_hermes_environment",
        lambda: (_ for _ in ()).throw(AssertionError("regular CLI read Hermes.env")),
    )
    monkeypatch.setattr(
        "signaltrail.cli.bind_data_root",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("regular CLI wrote a data-root registry")
        ),
    )
    bound_roots = []
    real_load_bound = runtime.load_bound_data_root

    def record_native_registry(app_home):
        bound_roots.append(app_home.resolve())
        assert app_home.resolve() != hermes_home.resolve()
        return real_load_bound(app_home)

    monkeypatch.setattr(runtime, "load_bound_data_root", record_native_registry)
    monkeypatch.setitem(HANDLERS, "refresh-monitor", lambda _args, context: (
        print(json.dumps({"data_dir": str(context.data_dir)})) or 0
    ))

    assert main(["refresh-monitor"]) == 0
    result = json.loads(capsys.readouterr().out)
    app_home = tmp_path / "local" / "signaltrail"
    assert result["data_dir"] == str(app_home.resolve())
    assert bound_roots == [app_home.resolve()]
    assert not (app_home / "state" / "signaltrail-data-root.json").exists()


def test_regular_cli_runs_without_hermes_installation(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "missing-hermes"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "local"))
    monkeypatch.delenv("SIGNALTRAIL_DATA_DIR", raising=False)
    monkeypatch.delenv("DAILY_INTEL_DATA_DIR", raising=False)
    monkeypatch.setitem(HANDLERS, "refresh-monitor", lambda _args, _context: 0)
    assert main(["refresh-monitor"]) == 0


def test_data_root_adopt_and_status_use_signaltrail_app_home(monkeypatch, tmp_path, capsys):
    app_home = tmp_path / "local" / "signaltrail"
    data_root = tmp_path / "user-data"
    data_root.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "local"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.delenv("SIGNALTRAIL_DATA_DIR", raising=False)
    monkeypatch.delenv("DAILY_INTEL_DATA_DIR", raising=False)

    assert main(["--data-dir", str(data_root), "data-root", "adopt"]) == 0
    adopted = json.loads(capsys.readouterr().out)
    assert adopted["data_root"] == str(data_root.resolve())
    assert Path(adopted["registry_path"]) == (
        app_home / "state" / "signaltrail-data-root.json"
    ).resolve()

    assert main(["data-root", "status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status == {"status": "bound", "data_root": str(data_root.resolve())}
    override = tmp_path / "override"
    assert main(["--data-dir", str(override), "data-root", "status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["data_root"] == str(data_root.resolve())
    assert status["resolved_from_current_configuration"] == str(override.resolve())
    assert not (tmp_path / "hermes" / "state" / "signaltrail-data-root.json").exists()


@pytest.fixture
def cli_data_root(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("DAILY_INTEL_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def test_all_parser_commands_have_handlers_and_signaltrail_entrypoints():
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
    assert entries["signaltrail"] == "signaltrail.cli:main"
    assert "daily-intel" not in entries
    assert all(name.startswith("signaltrail") for name in entries)
    assert parser.prog == "signaltrail"


@pytest.mark.parametrize("command", ["serve", "serve-monitor"])
def test_monitor_server_aliases_forward_the_same_options(cli_data_root, monkeypatch, command):
    serve = Mock()
    monkeypatch.setattr("signaltrail.commands.monitor.serve_monitor", serve)
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
    missing = json.loads(capsys.readouterr().out)
    assert missing["status"] == "not_initialized"
    assert missing["next_action"] == "signaltrail refresh-monitor"
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
    monkeypatch.setattr(f"signaltrail.commands.sources.{operation}", worker)
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
    monkeypatch.setattr("signaltrail.commands.reports.validate_report", validate)
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
    monkeypatch.setattr("signaltrail.commands.reports.publish_report", publish)
    report = cli_data_root / "reports/report.json"
    assert main(["publish-notion", str(report), "--republish"]) == 0
    assert publish.call_args.kwargs["force"] is True
    assert json.loads(capsys.readouterr().out) == {"page_id": "page-1", "status": "published"}


def test_cli_exposes_two_stage_workflow():
    parser = build_parser()
    prepared = parser.parse_args(["run-edition", "--edition", "morning", "--language", "en"])
    enriched = parser.parse_args(["enrich-edition", "--run", "run.json"])
    finalized = parser.parse_args(
        ["finalize-edition", "--run", "run.json", "--report", "draft.json",
         "--evaluation-backend", "external"]
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
    assert parser.parse_args(["run-edition"]).edition == "daily"
    assert parser.parse_args(["collect"]).edition == "daily"
    assert parser.parse_args(["build-context", "--index", "INDEX"]).edition == "daily"
    assert verification.command == "verify-pending"
    assert evaluation.command == "finalize-evaluation"
    assert finalized.evaluate is False
    assert finalized.evaluation_backend == "external"
    for command, required in (
        ("finalize-edition", ["--report", "draft.json"]),
        ("complete-edition-tail", []),
    ):
        arguments = [command, "--run", "run.json", *required]
        assert parser.parse_args(arguments).evaluate is False
        assert parser.parse_args([*arguments, "--evaluate"]).evaluate is True
        assert parser.parse_args(
            [*arguments, "--evaluation-backend", "external"]
        ).evaluation_backend == "external"
        assert parser.parse_args(
            [*arguments, "--evaluation-backend", "hermes"]
        ).evaluation_backend == "hermes"
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
        "signaltrail.commands.editions.prepare_edition",
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
        "signaltrail.commands.editions.run_pending_verification",
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
        "signaltrail.commands.editions.prepare_edition",
        lambda **_kwargs: run_path,
    )

    def fail_if_opened(*_args, **_kwargs):
        raise AssertionError("verification must remain opt-in")

    monkeypatch.setattr(
        "signaltrail.commands.editions.run_pending_verification",
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


@pytest.mark.parametrize("compact", [False, True])
def test_edition_compact_receipt_keeps_recovery_paths_without_reprinting_briefs(
    cli_data_root, monkeypatch, capsys, compact,
):
    original = {
        "status": "accepted", "batch_id": "batch-1",
        "briefs": [{"title": "很长的新闻正文", "tldr": "正文" * 1000}],
        "coverage": {"total_tokens": {"known_batches": 1, "missing_batches": 2}},
        "batch_metrics": [{"batch_id": "batch-1", "total_tokens": 1234}],
        "next_action": "prepare-analysis", "result_path": "accepted.json",
    }
    output = write_json(cli_data_root / "accepted.json", original)
    monkeypatch.setattr("signaltrail.commands.editions.accept_authoring_batch",
                        Mock(return_value=output))
    argv = (["--compact"] if compact else []) + [
        "submit-authoring-batch", "--run", str(cli_data_root / "run.json"),
        "--batch-id", "batch-1", "--result", str(cli_data_root / "draft.json"),
    ]
    assert main(argv) == 0
    receipt = json.loads(capsys.readouterr().out)
    if compact:
        expected = {key: value for key, value in original.items()
                    if key not in {"briefs", "batch_metrics"}}
        assert receipt == expected | {"artifact_path": str(output)}
    else:
        assert receipt == original
    assert read_json(output) == original


def test_finalize_cli_forwards_explicit_slide_exclusions(cli_data_root, monkeypatch, capsys):
    output = write_json(cli_data_root / "run.json", {"status": "completed"})
    finalize = Mock(return_value=output)
    monkeypatch.setattr("signaltrail.commands.editions.finalize_edition", finalize)
    monkeypatch.setattr("signaltrail.commands.editions.get_edition_status",
                        Mock(return_value={"delivery_complete": False}))
    assert main(["--compact", "finalize-edition", "--run", str(output),
                 "--report", str(cli_data_root / "report.json"),
                 "--slides-exclude-event-id", "brief-a",
                 "--slides-exclude-event-id", "brief-b"]) == 0
    assert finalize.call_args.kwargs["slides_exclude_event_ids"] == ["brief-a", "brief-b"]
    assert json.loads(capsys.readouterr().out)["artifact_path"] == str(output)


def test_parallel_analysis_cli_dispatches_stages(cli_data_root, monkeypatch, capsys):
    run = write_json(cli_data_root / "run.json", {"artifacts": {}})
    packet = write_json(cli_data_root / "packet.json", {"large_evidence": "原文" * 500})
    prepare = Mock(return_value=packet)
    selection = Mock(return_value={"packet_path": str(packet), "result_path": "selection.json"})
    monkeypatch.setattr("signaltrail.commands.editions.prepare_authoring_analysis", prepare)
    monkeypatch.setattr("signaltrail.analysis_parallel.prepare_analysis_selection", selection)
    assert main(["--compact", "prepare-analysis", "--run", str(run), "--parallel"]) == 0
    selection.assert_called_once_with({"artifacts": {}}, cli_data_root)
    assert json.loads(capsys.readouterr().out)["packet_path"] == str(packet)
    for stage, function in [("domains", "prepare_analysis_domains"),
                            ("synthesis", "prepare_analysis_synthesis"),
                            ("assemble", "assemble_parallel_analysis")]:
        advance = Mock(return_value={"analysis_result_path": "analysis.json"})
        monkeypatch.setattr(f"signaltrail.analysis_parallel.{function}", advance)
        assert main(["--compact", "analysis-stage", "--run", str(run), "--stage", stage]) == 0
        advance.assert_called_once_with({"artifacts": {}}, cli_data_root)
        assert json.loads(capsys.readouterr().out)["analysis_result_path"] == "analysis.json"


@pytest.mark.parametrize("diagnostics", [
    {"deadline_exceeded": True, "remaining_seconds": -1, "expected_batches": 8,
     "recovered_batches": [{"batch_id": "brief-1", "reason": "accepted draft recovered"}]},
    {"errors": [{"path": "briefs.0.title", "message": "required"}],
     "warnings": [{"source": "example", "reason": "with_gaps"}],
     "usage": {"coverage": {"missing_batches": 1}, "reason": "unmetered", "cost_usd": None}},
])
def test_compact_keeps_deadline_and_structured_diagnostics(
    cli_data_root, monkeypatch, capsys, diagnostics,
):
    monkeypatch.setattr("signaltrail.commands.editions.get_authoring_status",
                        Mock(return_value={**diagnostics, "briefs": [{"tldr": "正文" * 100}]}))
    run = cli_data_root / "run.json"
    assert main(["--compact", "authoring-status", "--run", str(run)]) == 0
    assert json.loads(capsys.readouterr().out) == {"artifact_path": str(run), **diagnostics}
