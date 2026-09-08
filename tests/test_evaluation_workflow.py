import base64
import json
from pathlib import Path

import pytest

from daily_intelligence.config import OutputConfig
from daily_intelligence.notion import (
    evaluation_to_blocks,
)
from daily_intelligence.reporting import report_content_hash, validate_report_data
from daily_intelligence.reports import save_evaluation, save_report
from daily_intelligence.storage import exclusive_lock
from daily_intelligence.utils import read_json, write_json
from daily_intelligence.workflow import (
    RunStatus,
    evaluation_preflight,
    finalize_edition,
    reconcile_evaluation_scheduler,
    schedule_independent_evaluation,
)
from tests.report_helpers import first_report_item, load_sample_report, write_report_index


def test_v15_report_publishes_before_evaluation_and_state_waits(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    report = load_sample_report(root)
    report["schema_version"] = "1.5"
    report.pop("quality_evaluation")
    base_analysis = report["analyses"][0]
    report["analyses"] = []
    for position, domain in enumerate(("geopolitics", "ai_technology", "markets"), start=1):
        analysis = json.loads(json.dumps(base_analysis))
        analysis["analysis_id"] = f"ANALYSIS-{position}"
        analysis["domain"] = domain
        report["analyses"].append(analysis)
    for section in report["sections"]:
        section["briefs"] = []
    event = first_report_item(report)
    section = next(section for section in report["sections"] if section["items"])
    section["briefs"] = [
        {
            "item_id": event["source_refs"][0]["item_id"],
            "title": event["title"],
            "tldr": event["tldr"],
            "importance": event["importance"],
            "status": "NEW",
            "featured_event_id": event["event_id"],
        }
    ]
    draft = write_json(tmp_path / "draft-v15.json", report)
    index_path = write_report_index(report, tmp_path / "index-v15.json")
    index = read_json(index_path)
    index["sources"] = [
        {
            "source_id": event["primary_source"]["id"],
            "source_name": event["primary_source"]["name"],
            "source_url": event["primary_source"]["url"],
            "status": "success",
        }
    ]
    index["items"][0]["content_status"] = "not_fetched"
    index["items"][0]["metadata"] = {"role": "discovery"}
    write_json(index_path, index)

    artifacts = save_report(
        draft,
        index_path,
        tmp_path / "data",
        output_config=OutputConfig(formats=["html"]),
    )

    assert artifacts["evaluation_status"] == "pending"
    assert not (tmp_path / "data" / "state" / "theses.json").exists()
    assert validate_report_data(read_json(Path(artifacts["json_path"])))[0] == []
    saved_report = read_json(Path(artifacts["json_path"]))
    dimensions = [
        "coverage",
        "importance_ordering",
        "factual_reliability",
        "summary_accuracy",
        "analysis_traceability",
        "historical_continuity",
        "readability",
        "timeliness",
        "compliance_boundaries",
    ]
    evaluation = {
        "evaluator_role": "independent",
        "evaluated_report_id": saved_report["report_id"],
        "evaluated_content_hash": report_content_hash(saved_report),
        "dimensions": [
            {"id": dimension, "score": 4, "finding": "该项整体合格，后续继续改进。"}
            for dimension in dimensions
        ],
        "total_score": 36,
        "main_defects": ["来源覆盖仍有提升空间。"],
        "insufficient_evidence": ["部分判断缺少交叉来源。"],
        "improvements": ["下一版补充更多高价值来源。"],
        "continuity_decision": "accept",
        "exclude_from_continuity": [],
    }
    evaluation_input = write_json(tmp_path / "evaluation.json", evaluation)
    run_path = write_json(
        tmp_path / "data" / "runs" / report["date"] / "morning.json",
        {
            "status": "completed",
            "artifacts": {
                "report_id": saved_report["report_id"],
                "content_hash": report_content_hash(saved_report),
            },
            "evaluation": {"status": "pending"},
        },
    )

    evaluated = save_evaluation(
        evaluation_input,
        Path(artifacts["json_path"]),
        tmp_path / "data",
        output_config=OutputConfig(formats=["html"]),
    )

    assert Path(evaluated["evaluation_path"]).exists()
    assert (tmp_path / "data" / "state" / "theses.json").exists()
    assert read_json(run_path)["evaluation"]["status"] == "completed"
    assert read_json(run_path)["evaluation"]["report_id"] == saved_report["report_id"]
    refreshed_html = Path(artifacts["html_path"]).read_text(encoding="utf-8")
    assert "<strong>36</strong><span>/ 45</span>" in refreshed_html
    assert evaluated["local_outputs"]["html_path"] == artifacts["html_path"]
    assert "独立评估结果" in json.dumps(
        evaluation_to_blocks(read_json(Path(evaluated["evaluation_path"]))),
        ensure_ascii=False,
    )

    replayed = save_evaluation(
        evaluation_input,
        Path(artifacts["json_path"]),
        tmp_path / "data",
        output_config=OutputConfig(formats=["html"]),
    )
    assert replayed["status"] == "already_completed"
    assert replayed["evaluation_path"] == evaluated["evaluation_path"]
    assert len(list((tmp_path / "data" / "evaluations" / report["date"]).glob("*.json"))) == 1

    changed_evaluation = json.loads(json.dumps(evaluation))
    changed_evaluation["dimensions"][0]["score"] = 3
    changed_evaluation["total_score"] = 35
    for revision in range(2, 11):
        payload = changed_evaluation if revision % 2 == 0 else evaluation
        write_json(evaluation_input, payload)
        result = save_evaluation(
            evaluation_input,
            Path(artifacts["json_path"]),
            tmp_path / "data",
            output_config=OutputConfig(formats=["html"]),
        )
        assert result["evaluation_id"].endswith(f"-r{revision}")

    # r10 and earlier even revisions have the same semantics. Replay must select the
    # numerically latest current decision, not lexicographic r8, and create no r11.
    write_json(evaluation_input, changed_evaluation)
    replayed_r10 = save_evaluation(
        evaluation_input,
        Path(artifacts["json_path"]),
        tmp_path / "data",
        output_config=OutputConfig(formats=["html"]),
    )
    assert replayed_r10["status"] == "already_completed"
    assert replayed_r10["evaluation_id"].endswith("-r10")
    latest = read_json(tmp_path / "data" / "evaluations" / "latest-morning.json")
    assert latest["evaluation_id"].endswith("-r10")
    assert read_json(run_path)["evaluation"]["evaluation_id"].endswith("-r10")
    assert len(list((tmp_path / "data" / "evaluations" / report["date"]).glob("*.json"))) == 10

    interrupted_run = read_json(run_path)
    interrupted_run["evaluation"] = {
        "status": "pending",
        "report_id": saved_report["report_id"],
        "content_hash": report_content_hash(saved_report),
    }
    write_json(run_path, interrupted_run)
    recovered_r10 = save_evaluation(
        evaluation_input,
        Path(artifacts["json_path"]),
        tmp_path / "data",
        output_config=OutputConfig(formats=["html"]),
    )
    assert recovered_r10["evaluation_id"].endswith("-r10")
    assert read_json(run_path)["evaluation"]["status"] == "completed"
    assert len(list((tmp_path / "data" / "evaluations" / report["date"]).glob("*.json"))) == 10

    lock_path = tmp_path / "data" / "locks" / f"{report['date']}-morning.lock"
    with (
        exclusive_lock(lock_path, {"test": "concurrent evaluator"}),
        pytest.raises(RuntimeError, match="Another run holds"),
    ):
        save_evaluation(
            evaluation_input,
            Path(artifacts["json_path"]),
            tmp_path / "data",
            output_config=OutputConfig(formats=["html"]),
        )

    latest_before_stale = read_json(tmp_path / "data" / "evaluations" / "latest-morning.json")
    theses_before_stale = (tmp_path / "data" / "state" / "theses.json").read_bytes()
    html_before_stale = Path(artifacts["html_path"]).read_bytes()
    current_run = read_json(run_path)
    current_run["artifacts"]["report_id"] = "daily-current-newer-report"
    current_run["artifacts"]["content_hash"] = "sha256:current-newer-report"
    current_run["evaluation"] = {"status": "pending"}
    write_json(run_path, current_run)
    write_json(evaluation_input, evaluation)

    stale = save_evaluation(
        evaluation_input,
        Path(artifacts["json_path"]),
        tmp_path / "data",
        output_config=OutputConfig(formats=["html"]),
    )

    assert stale["status"] == "stale_report"
    assert stale["evaluation_id"].endswith("-r11")
    assert Path(stale["evaluation_path"]).is_file()
    assert (
        read_json(tmp_path / "data" / "evaluations" / "latest-morning.json") == latest_before_stale
    )
    assert (tmp_path / "data" / "state" / "theses.json").read_bytes() == theses_before_stale
    assert Path(artifacts["html_path"]).read_bytes() == html_before_stale
    assert read_json(run_path) == current_run


def test_post_publication_evaluation_uses_bounded_retries(monkeypatch, tmp_path: Path):
    calls = []

    class Completed:
        returncode = 0
        stdout = "Created job: eval-1"
        stderr = ""

    monkeypatch.setattr(
        "daily_intelligence.workflow.subprocess.run",
        lambda command, **kwargs: calls.append((command, kwargs)) or Completed(),
    )
    monkeypatch.setattr("daily_intelligence.workflow.project_root", lambda: tmp_path)
    dossier_path = tmp_path / "data" / "evaluations" / "dossiers" / "report.json"
    dossier_path.parent.mkdir(parents=True)
    dossier_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "daily_intelligence.workflow.build_evaluation_dossier",
        lambda *_args: dossier_path,
    )

    result = schedule_independent_evaluation(
        tmp_path / "report.json",
        tmp_path / "index.json",
        tmp_path / "data",
        "daily-2026-07-15-morning-r1",
        "abc123",
    )

    command = calls[0][0]
    assert result["status"] == "scheduled"
    assert command[:4] == ["hermes", "cron", "create", "2m"]
    assert command[command.index("--repeat") + 1] == "1"
    assert command[command.index("--skill") + 1] == "signaltrail"
    assert "不得要求用户点击" in command[4]
    assert "runpy.run_module('daily_intelligence.cli', run_name='__main__')" in command[4]
    encoded_source = base64.urlsafe_b64encode(str(tmp_path / "src").encode("utf-8")).decode("ascii")
    assert encoded_source in command[4]
    assert str(dossier_path) in command[4]
    assert str(tmp_path / "templates" / "report-contract.md") not in command[4]
    assert "不得要求普通 brief 按 importance 二次重排" in command[4]
    assert "$env:PYTHONPATH" not in command[4]
    assert "PYTHONPATH=" not in command[4]
    assert "daily-intel --data-dir" not in command[4]
    assert "--publish" not in command[4]
    assert result["job_id"] == "eval-1"
    assert result["attempts"] == 1

    schedule_independent_evaluation(
        tmp_path / "report.json",
        tmp_path / "index.json",
        tmp_path / "data",
        "daily-2026-07-15-morning-r1",
        "abc123",
        publish_notion=True,
    )
    assert "--publish" in calls[1][0][4]


def test_evaluation_preflight_matches_report_and_content_hash(tmp_path: Path):
    data_dir = tmp_path / "data"
    report_id = "daily-2026-07-15-morning-r1"
    content_hash = "abc123"
    report_path = write_json(
        data_dir / "reports" / "2026-07-15" / "morning-r1.json",
        {"date": "2026-07-15", "edition": "morning"},
    )
    write_json(
        data_dir / "runs" / "2026-07-15" / "morning.json",
        {
            "artifacts": {"report_id": report_id, "content_hash": content_hash},
            "evaluation": {
                "status": "completed",
                "content_hash": content_hash,
                "evaluation_id": "eval-1",
                "evaluation_path": "evaluation.json",
            },
        },
    )

    assert (
        evaluation_preflight(
            report_path,
            data_dir,
            report_id,
            content_hash,
        )["status"]
        == "already_completed"
    )
    assert evaluation_preflight(
        report_path,
        data_dir,
        report_id,
        "different",
    ) == {"status": "evaluation_required", "reason": "no_matching_completion"}


def test_scheduler_reconciliation_is_read_only_and_sanitized(monkeypatch):
    class Completed:
        returncode = 0
        stdout = (
            "  eval-1 [completed]\n"
            "    Last run: 2026-08-23T18:00:00+08:00 ok\n"
            "    Prompt: private evaluator instructions\n"
        )
        stderr = ""

    calls = []
    monkeypatch.setattr(
        "daily_intelligence.workflow.subprocess.run",
        lambda command, **kwargs: calls.append((command, kwargs)) or Completed(),
    )

    receipt = reconcile_evaluation_scheduler(
        {"status": "scheduled", "job_id": "eval-1", "attempt": 1},
        checked_at="2026-08-23T18:01:00+08:00",
    )

    assert calls[0][0] == ["hermes", "cron", "list", "--all"]
    assert receipt["status"] == "completed"
    assert receipt["last_result"] == "ok"
    assert "private evaluator instructions" not in str(receipt)


def test_finalize_publish_records_automatic_evaluator_schedule(monkeypatch, tmp_path: Path):
    data_dir = tmp_path / "data"
    report_path = write_json(
        data_dir / "reports" / "2026-07-15" / "morning-r1.json",
        {"date": "2026-07-15", "edition": "morning"},
    )
    index_path = write_json(
        data_dir / "indexes" / "2026-07-15" / "morning-r1.json",
        {"date": "2026-07-15", "edition": "morning"},
    )
    run_path = write_json(
        data_dir / "runs" / "2026-07-15" / "morning.json",
        {
            "date": "2026-07-15",
            "edition": "morning",
            "timezone": "Asia/Shanghai",
            "status": RunStatus.FINALIZING,
            "pending_sources": [],
            "artifacts": {
                "index_path": str(index_path),
                "json_path": str(report_path),
                "report_id": "daily-2026-07-15-morning-r1",
                "content_hash": "abc123",
            },
        },
    )
    monkeypatch.setattr(
        "daily_intelligence.workflow.publish_report",
        lambda *_args, **_kwargs: ("notion-page", "published"),
    )
    monkeypatch.setattr(
        "daily_intelligence.workflow.schedule_independent_evaluation",
        lambda *_args, **_kwargs: {"status": "scheduled", "detail": "job-1"},
    )

    finalize_edition(run_path, report_path, data_dir, publish=True)

    run = read_json(run_path)
    assert run["status"] == RunStatus.COMPLETED
    assert run["evaluation"]["scheduler"]["status"] == "scheduled"
    assert run["evaluation"]["scheduler"]["detail"] == "job-1"
    assert run["evaluation"]["scheduler"]["attempt"] == 1
    assert run["evaluation"]["scheduler"]["max_attempts"] == 2
    assert run["evaluation"]["scheduler"]["usage_task_id"].startswith("task-signaltrail-eval-")


def test_finalize_retries_missing_evaluator_schedule_after_completed_publish(
    monkeypatch, tmp_path: Path
):
    data_dir = tmp_path / "data"
    report_path = write_json(data_dir / "reports" / "report.json", {})
    index_path = write_json(data_dir / "indexes" / "index.json", {})
    run_path = write_json(
        data_dir / "runs" / "2026-07-15" / "morning.json",
        {
            "date": "2026-07-15",
            "edition": "morning",
            "timezone": "Asia/Shanghai",
            "status": RunStatus.COMPLETED,
            "publication": {"page_id": "page-1", "status": "published"},
            "artifacts": {
                "json_path": str(report_path),
                "index_path": str(index_path),
                "report_id": "daily-2026-07-15-morning-r1",
                "content_hash": "abc123",
            },
            "evaluation": {"status": "pending"},
        },
    )
    monkeypatch.setattr(
        "daily_intelligence.workflow.schedule_independent_evaluation",
        lambda *_args, **_kwargs: {"status": "scheduled", "detail": "job-recovered"},
    )

    finalize_edition(run_path, report_path, data_dir, publish=True)

    run = read_json(run_path)
    assert run["evaluation"]["scheduler"]["detail"] == "job-recovered"
