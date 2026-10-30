import json
import os
from pathlib import Path

from signaltrail.config import load_config
from signaltrail.reporting import report_content_hash
from signaltrail.runtime import data_root_registry_path
from signaltrail.utils import read_json, write_json
from tests.report_helpers import first_report_item, load_sample_report, write_report_index


def test_cli_external_evaluation_and_slides_complete_without_hermes(
    monkeypatch, tmp_path: Path, capsys
):
    from signaltrail import cli, workflow

    date = "2026-10-07"
    data_dir = tmp_path / "data"
    config = load_config(timezone="Asia/Shanghai")
    config.output.formats = ["html"]
    config.output.copy_html_to_desktop = False
    config.output.open_after_finalize = False
    report = load_sample_report(Path(__file__).resolve().parents[1])
    report["date"] = date
    report["generated_at"] = f"{date}T05:48:00+08:00"
    report_path = write_json(tmp_path / "agent-report-draft.json", report)
    selected_item_id = first_report_item(report)["source_refs"][0]["item_id"]

    app_data = tmp_path / "app-data"
    hermes_home = app_data / "hermes"
    hermes_home.mkdir(parents=True)
    (hermes_home / ".env").write_text(
        "SIGNALTRAIL_EVALUATION_BACKEND=hermes\n", encoding="utf-8"
    )
    app_home = app_data / "signaltrail"
    registry_path = data_root_registry_path(app_home)
    registry_bytes = write_json(registry_path, {
        "schema_version": "1.0",
        "data_root": str(tmp_path / "previous-data-root"),
        "timezone": "Asia/Shanghai",
        "updated_at": f"{date}T05:00:00+08:00",
    }).read_bytes()
    monkeypatch.setenv("LOCALAPPDATA", str(app_data))
    monkeypatch.setenv("XDG_DATA_HOME", str(app_data))
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("SIGNALTRAIL_DATA_DIR", str(data_dir))
    for name in (
        "DAILY_INTEL_DATA_DIR", "SIGNALTRAIL_EVALUATION_BACKEND",
        "SIGNALTRAIL_USAGE_LEDGER", "SIGNALTRAIL_USAGE_TASK",
        "SIGNALTRAIL_USAGE_ADAPTER", "SIGNALTRAIL_USAGE_PHASE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cli, "load_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr(workflow, "today_str", lambda _timezone: date)
    monkeypatch.setattr(
        workflow,
        "refresh_monitor",
        lambda _config, root: write_json(
            root / "monitor" / "snapshot.json",
            {"generated_at": f"{date}T05:45:00+08:00", "token_usage": None},
        ),
    )

    def collect_public_sources(**kwargs):
        return write_report_index(
            report,
            kwargs["data_dir"] / "indexes" / date / "morning-r1.json",
        )

    def build_context(index_path, _config, root, _edition, collection_window=None):
        return write_json(
            root / "context" / date / "morning-context.json",
            {"index_path": str(index_path), "collection_window": collection_window},
        )

    def extract_selected_items(**kwargs):
        index = read_json(kwargs["index_path"])
        index["revision"] = 2
        return write_json(
            kwargs["data_dir"] / "indexes" / date / "morning-r2.json", index
        )

    monkeypatch.setattr(workflow, "collect_sources", collect_public_sources)
    monkeypatch.setattr(workflow, "build_context", build_context)
    monkeypatch.setattr(workflow, "extract_content", extract_selected_items)
    monkeypatch.setattr(
        workflow,
        "schedule_independent_evaluation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("default evaluation must not launch Hermes")
        ),
    )

    assert cli.main(["run-edition", "--edition", "morning"]) == 0
    capsys.readouterr()
    run_path = data_dir / "runs" / date / "morning.json"
    assert cli.main([
        "enrich-edition", "--run", str(run_path),
        "--item-id", selected_item_id,
    ]) == 0
    capsys.readouterr()

    assert cli.main([
        "finalize-edition", "--run", str(run_path),
        "--report", str(report_path), "--evaluate",
    ]) == 0
    capsys.readouterr()
    run = read_json(run_path)
    assert run["status"] == "completed"
    assert run["evaluation_backend"] == "external"
    action = run["evaluation"]["scheduler"]
    assert action["status"] == "awaiting_external"
    assert Path(action["dossier_path"]).is_file()
    assert "finalize-evaluation" in action["finalize_command"]
    assert not (data_dir / "usage").exists()
    assert os.environ.get("SIGNALTRAIL_EVALUATION_BACKEND") is None
    assert registry_path.read_bytes() == registry_bytes

    saved_report = Path(run["artifacts"]["json_path"])
    dossier = read_json(Path(action["dossier_path"]))
    evaluation_path = Path(action["draft_path"])
    dimensions = dossier["evaluation_contract"]["dimensions"]
    evaluation_draft = {
        "evaluator_role": "independent",
        "evaluated_report_id": run["artifacts"]["report_id"],
        "evaluated_content_hash": report_content_hash(read_json(saved_report)),
        "dimensions": [
            {"id": dimension, "score": 4, "finding": "现有证据支持此项评分。"}
            for dimension in dimensions
        ],
        "total_score": 4 * len(dimensions),
        "main_defects": [],
        "insufficient_evidence": [],
        "improvements": [],
        "continuity_decision": "accept",
        "exclude_from_continuity": [],
    }
    write_json(evaluation_path, evaluation_draft)
    assert cli.main([
        "finalize-evaluation", "--report", str(saved_report),
        "--evaluation", str(evaluation_path),
    ]) == 0
    capsys.readouterr()

    slides = run["artifacts"]["slides"]
    for packet_path in slides["packet_paths"]:
        packet = read_json(Path(packet_path))["payload"]
        draft_path = Path(packet_path).with_name(
            f"batch-{packet['batch_id']}-draft.json"
        )
        narration = (
            "本段讲解只依据已保存日报中的事实和研判展开，保留材料尚未确认的部分，"
            "让读者先看清事件本身，再理解它与相关领域的联系。"
        )
        narration = (narration * 5)[:240]
        draft = {
            "slides": [
                {
                    "event_id": news["event_id"],
                    "narration": narration,
                    "video_tldr": "先说明已保存新闻的事实，再简述相关领域的影响。",
                    "perspectives": [
                        analysis["domain"] for analysis in news.get("analyses", [])
                    ],
                }
                for news in packet["model_input"]["news"]
            ]
        }
        write_json(draft_path, draft)
        assert cli.main([
            "slides", "submit", "--packet", packet_path,
            "--input", str(draft_path),
        ]) == 0
        capsys.readouterr()

    assert cli.main([
        "slides", "render", "--plan", slides["plan_path"],
        "--offline",
    ]) == 0
    capsys.readouterr()
    assert cli.main([
        "edition-status", "--run", str(run_path),
        "--require-complete",
    ]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["delivery_complete"] is True
    assert read_json(run_path)["evaluation"]["status"] == "completed"
