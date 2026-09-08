from pathlib import Path

import pytest

from daily_intelligence.config import OutputConfig, load_config
from daily_intelligence.llm_usage import UsageLedger
from daily_intelligence.utils import read_json, write_json
from daily_intelligence.workflow import (
    RunStatus,
    _active_usage_binding,
    _attach_usage_binding,
    adopt_index_for_run,
    complete_edition_tail,
    enrich_edition,
    finalize_edition,
    prepare_edition,
)
from tests.report_helpers import load_sample_report, write_report_index


def test_active_usage_binding_links_only_the_matching_data_root(
    monkeypatch,
    tmp_path: Path,
):
    data_dir = tmp_path / "data"
    task = UsageLedger(data_dir).start_task(
        "hermes",
        task_id="task-test-run-binding",
    )
    monkeypatch.setenv("SIGNALTRAIL_USAGE_LEDGER", str(data_dir))
    monkeypatch.setenv("SIGNALTRAIL_USAGE_TASK", task.task_id)
    monkeypatch.setenv("SIGNALTRAIL_USAGE_ADAPTER", "hermes")
    monkeypatch.setenv("SIGNALTRAIL_USAGE_PHASE", "daily-report")

    binding = _active_usage_binding(data_dir)

    assert binding == {
        "task_id": task.task_id,
        "adapter": "hermes",
        "phase": "daily-report",
        "event_dir": str((task.path / "events").resolve()),
    }
    with pytest.raises(RuntimeError, match="different SignalTrail data root"):
        _active_usage_binding(tmp_path / "other-data")
    UsageLedger(data_dir).finalize_task(task)
    with pytest.raises(RuntimeError, match="already finalized"):
        _active_usage_binding(data_dir)


def test_usage_bindings_preserve_attempt_history():
    old_binding = {
        "task_id": "task-attempt-1",
        "adapter": "hermes",
        "phase": "daily-report",
        "event_dir": "C:/safe/usage/attempt-1/events",
        "run_attempt": 1,
    }
    run = {
        "attempt": 2,
        "llm_usage": {
            "schema_version": "1.0",
            "authority": "immutable_usage_events",
            "tasks": [old_binding],
        },
    }

    assert _attach_usage_binding(
        run,
        {
            "task_id": "task-attempt-2",
            "adapter": "hermes",
            "phase": "daily-report",
            "event_dir": "C:/safe/usage/attempt-2/events",
        },
    )
    assert [row["run_attempt"] for row in run["llm_usage"]["tasks"]] == [1, 2]


def test_two_stage_run_reaches_completed(monkeypatch, tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    config = load_config(timezone="Asia/Shanghai")
    report = load_sample_report(root)
    report["date"] = "2026-07-11"
    report["generated_at"] = "2026-07-11T05:48:00+08:00"
    draft = write_json(tmp_path / "draft.json", report)

    def fake_collect_sources(**kwargs):
        output = kwargs["data_dir"] / "indexes" / "2026-07-11" / "morning-r1.json"
        return write_report_index(report, output)

    context_calls = []

    def fake_build_context(index_path, _config, data_dir, edition, collection_window=None):
        context_calls.append(str(index_path))
        output = data_dir / "context" / f"{edition}-{len(context_calls)}.json"
        return write_json(
            output,
            {
                "index_path": str(index_path),
                "collection_window": collection_window,
            },
        )

    extraction_calls = []

    def fake_extract_content(**kwargs):
        extraction_calls.append(kwargs["selected_ids"])
        source = read_json(kwargs["index_path"])
        source["revision"] = 2
        output = kwargs["data_dir"] / "indexes" / "2026-07-11" / "morning-r2.json"
        return write_json(output, source)

    monkeypatch.setattr("daily_intelligence.workflow.today_str", lambda _timezone: "2026-07-11")
    monkeypatch.setattr(
        "daily_intelligence.workflow.refresh_monitor",
        lambda _config, data_dir: write_json(
            data_dir / "monitor" / "snapshot.json",
            {"generated_at": "2026-07-11T05:45:00+08:00", "token_usage": 0},
        ),
    )
    monkeypatch.setattr("daily_intelligence.workflow.collect_sources", fake_collect_sources)
    monkeypatch.setattr("daily_intelligence.workflow.build_context", fake_build_context)
    monkeypatch.setattr("daily_intelligence.workflow.extract_content", fake_extract_content)
    monkeypatch.setattr(
        "daily_intelligence.workflow.schedule_independent_evaluation",
        lambda *_args, **_kwargs: {"status": "scheduled", "detail": "local-eval"},
    )

    run_path = prepare_edition(config, tmp_path / "data", "morning")
    assert read_json(run_path)["status"] == RunStatus.AWAITING_SELECTION

    enrich_edition(
        run_path,
        config,
        tmp_path / "data",
        selected_ids=["example_news-001"],
        max_items=40,
    )
    enriched = read_json(run_path)
    assert enriched["status"] == RunStatus.AWAITING_AUTHORING
    assert enriched["artifacts"]["index_path"].endswith("morning-r2.json")

    enrich_edition(
        run_path,
        config,
        tmp_path / "data",
        selected_ids=["second-item"],
        max_items=40,
    )
    enriched = read_json(run_path)
    assert enriched["artifacts"]["selected_item_ids"] == [
        "example_news-001",
        "second-item",
    ]
    assert extraction_calls == [["example_news-001"], ["second-item"]]

    finalize_edition(
        run_path,
        draft,
        tmp_path / "data",
        output_config=OutputConfig(formats=["html"]),
    )
    completed = read_json(run_path)
    assert completed["status"] == RunStatus.COMPLETED
    assert Path(completed["artifacts"]["markdown_path"]).exists()
    assert completed["artifacts"]["collection_metrics"]["candidate_count"] == 1
    assert "phase_durations_seconds" in completed["metrics"]
    assert completed["metrics"]["phase_durations_seconds"]["collection"] >= 0
    assert completed["evaluation"]["scheduler"]["status"] == "scheduled"
    assert completed["publication"] is None
    assert [row["status"] for row in completed["stage_history"]].count(RunStatus.COMPLETED) == 1


def test_prepare_reuses_fresh_monitor_snapshot_without_refresh(
    monkeypatch,
    tmp_path: Path,
):
    config = load_config(timezone="Asia/Shanghai")
    data_dir = tmp_path / "data"
    snapshot_path = write_json(
        data_dir / "monitor" / "snapshot.json",
        {
            "schema_version": "2.0",
            "generated_at": "2026-07-24T05:50:00+08:00",
            "token_usage": 0,
            "sources": [],
            "items": [],
        },
    )

    def fake_collect_sources(**kwargs):
        return write_json(
            kwargs["data_dir"] / "indexes" / "2026-07-24" / "morning-r1.json",
            {
                "date": "2026-07-24",
                "edition": "morning",
                "items": [],
                "sources": [],
            },
        )

    def fake_build_context(index_path, _config, target_dir, edition, **_kwargs):
        return write_json(
            target_dir / "context" / f"{edition}-r1.json",
            {"index_path": str(index_path), "brief_plan": []},
        )

    monkeypatch.setattr(
        "daily_intelligence.workflow.today_str",
        lambda _timezone: "2026-07-24",
    )
    monkeypatch.setattr(
        "daily_intelligence.workflow.fresh_monitor_snapshot_path",
        lambda *_args, **_kwargs: snapshot_path,
    )
    monkeypatch.setattr(
        "daily_intelligence.workflow.refresh_monitor",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("fresh snapshot must avoid refresh")
        ),
    )
    monkeypatch.setattr(
        "daily_intelligence.workflow.collect_sources",
        fake_collect_sources,
    )
    monkeypatch.setattr(
        "daily_intelligence.workflow.build_context",
        fake_build_context,
    )

    run = read_json(prepare_edition(config, data_dir, "morning"))

    metrics = run["artifacts"]["collection_metrics"]
    assert metrics["monitor_refresh"] is False
    assert metrics["monitor_snapshot_reused"] is True
    assert run["artifacts"]["monitor_snapshot_path"] == str(snapshot_path)


def test_enrich_edition_records_only_ids_accepted_under_hard_cap(monkeypatch, tmp_path: Path):
    config = load_config()
    data_dir = tmp_path / "data"
    run_path = data_dir / "runs" / "2026-07-14" / "morning.json"
    index_path = write_json(
        data_dir / "indexes" / "2026-07-14" / "morning-r1.json",
        {"date": "2026-07-14", "edition": "morning", "items": [], "sources": []},
    )
    write_json(
        run_path,
        {
            "date": "2026-07-14",
            "edition": "morning",
            "status": RunStatus.AWAITING_SELECTION,
            "collection_window": {},
            "artifacts": {"index_path": str(index_path)},
        },
    )
    extraction_calls = []

    def fake_extract_content(**kwargs):
        extraction_calls.append(kwargs["selected_ids"])
        return kwargs["index_path"]

    def fake_build_context(index, _config, data, edition, collection_window=None):
        return write_json(data / "context" / f"{edition}.json", {"index": str(index)})

    monkeypatch.setattr("daily_intelligence.workflow.extract_content", fake_extract_content)
    monkeypatch.setattr("daily_intelligence.workflow.build_context", fake_build_context)
    requested = [f"item-{position}" for position in range(20)]

    enrich_edition(run_path, config, data_dir, requested, max_items=None)

    run = read_json(run_path)
    assert extraction_calls == [requested[:12]]
    assert run["artifacts"]["selected_item_ids"] == requested[:12]
    enrichment = run["artifacts"]["enrichment"]
    assert enrichment == {
        "requested": 20,
        "accepted": 12,
        "hard_cap": 12,
        "global_concurrency": 3,
        "per_domain_concurrency": 1,
        "successful_item_ids": [],
        "full_text_item_ids": [],
        "partial_item_ids": [],
        "unsuccessful_item_ids": requested[:12],
    }


def test_existing_run_rejects_silent_output_language_change(monkeypatch, tmp_path: Path):
    config = load_config()
    config.output.language = "en"
    data_dir = tmp_path / "data"
    write_json(
        data_dir / "runs" / "2026-07-25" / "morning.json",
        {
            "date": "2026-07-25",
            "edition": "morning",
            "output_language": "zh-CN",
            "status": RunStatus.AWAITING_SELECTION,
        },
    )
    monkeypatch.setattr("daily_intelligence.workflow.today_str", lambda _timezone: "2026-07-25")

    with pytest.raises(RuntimeError, match="--restart"):
        prepare_edition(config, data_dir, "morning")


def test_verified_index_reopens_published_run_as_a_report_revision(monkeypatch, tmp_path: Path):
    data_dir = tmp_path / "data"
    index_path = write_json(
        data_dir / "indexes" / "2026-07-15" / "morning-r2.json",
        {"date": "2026-07-15", "edition": "morning", "items": [], "sources": []},
    )
    old_report = data_dir / "reports" / "2026-07-15" / "morning-r1.json"
    old_index = data_dir / "indexes" / "2026-07-15" / "morning-r1.json"
    run_path = write_json(
        data_dir / "runs" / "2026-07-15" / "morning.json",
        {
            "date": "2026-07-15",
            "edition": "morning",
            "output_language": "en",
            "status": RunStatus.COMPLETED_PARTIAL,
            "artifacts": {
                "index_path": str(old_index),
                "report_id": "daily-2026-07-15-morning-r1",
                "json_path": str(old_report),
                "markdown_path": str(old_report.with_suffix(".md")),
                "content_hash": "abc123",
            },
            "publication": {"page_id": "notion-page", "status": "published"},
            "evaluation": {"status": "completed"},
        },
    )
    context_path = data_dir / "context" / "2026-07-15" / "morning-r2.json"
    captured: dict[str, str] = {}

    def fake_build_context(_index_path, config, *_args, **_kwargs):
        captured["language"] = config.output.language
        return context_path

    monkeypatch.setattr("daily_intelligence.workflow.build_context", fake_build_context)

    adopt_index_for_run(load_config(), data_dir, index_path)

    run = read_json(run_path)
    assert run["status"] == RunStatus.AWAITING_SELECTION
    assert run["revision_reason"] == "verified_source_supplement"
    assert run["artifacts"]["previous_report"]["report_id"].endswith("-r1")
    assert captured["language"] == "en"
    assert "publication" not in run
    assert "evaluation" not in run


def test_deferred_tail_returns_after_html_then_finishes_pdf_notion_and_evaluation(
    monkeypatch, tmp_path: Path
):
    data_dir = tmp_path / "data"
    date = "2026-07-25"
    index_path = write_json(
        data_dir / "indexes" / date / "morning-r1.json",
        {"date": date, "edition": "morning", "items": [], "sources": []},
    )
    report_input = write_json(
        data_dir / "drafts" / "morning.json",
        {"date": date, "edition": "morning"},
    )
    saved_report_path = data_dir / "reports" / date / "morning-r1.json"
    html_path = data_dir / "reports" / date / "morning-r1.html"
    run_path = write_json(
        data_dir / "runs" / date / "morning.json",
        {
            "schema_version": "1.0",
            "run_id": f"run-{date}-morning",
            "data_root": str(data_dir.resolve()),
            "date": date,
            "edition": "morning",
            "timezone": "Asia/Shanghai",
            "status": RunStatus.AWAITING_AUTHORING,
            "created_at": f"{date}T05:50:00+08:00",
            "updated_at": f"{date}T05:50:00+08:00",
            "deadline_at": f"{date}T06:00:00+08:00",
            "artifacts": {"index_path": str(index_path)},
            "pending_sources": [],
        },
    )

    def fake_save(*_args, output_config, **_kwargs):
        write_json(
            saved_report_path,
            {
                "schema_version": "2.0",
                "report_id": f"daily-{date}-morning-r1",
                "date": date,
                "edition": "morning",
                "revision": 1,
            },
        )
        return {
            "report_id": f"daily-{date}-morning-r1",
            "json_path": str(saved_report_path),
            "markdown_path": str(saved_report_path.with_suffix(".md")),
            "html_path": str(html_path),
            "content_hash": "abc123",
            "save_metrics": {"total_seconds": 1.0},
            "requested_formats": output_config.formats,
        }

    monkeypatch.setattr("daily_intelligence.workflow.save_report", fake_save)
    monkeypatch.setattr(
        "daily_intelligence.workflow.publish_report",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Notion must not block local delivery")
        ),
    )
    monkeypatch.setattr(
        "daily_intelligence.workflow.schedule_independent_evaluation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("evaluation must wait for the tail worker")
        ),
    )

    finalize_edition(
        run_path,
        report_input,
        data_dir,
        publish=True,
        defer_tail=True,
        output_config=OutputConfig(formats=["html", "pdf"]),
    )

    run = read_json(run_path)
    assert run["status"] == RunStatus.COMPLETED
    assert run["tail"]["status"] == "pending"
    assert run["tail"]["publish_requested"] is True
    assert run["evaluation"]["scheduler"]["status"] == "deferred_until_tail"
    assert run["artifacts"]["requested_formats"] == ["html"]
    assert "--publish" in run["tail"]["command"]

    monkeypatch.setattr(
        "daily_intelligence.workflow.write_local_outputs",
        lambda *_args, **_kwargs: {
            "html_path": str(html_path),
            "pdf_path": str(saved_report_path.with_suffix(".pdf")),
            "pdf_engine": "reportlab",
            "local_index_path": str(data_dir / "reports" / "index.html"),
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "daily_intelligence.workflow.publish_report",
        lambda *_args, **_kwargs: ("notion-page", "published"),
    )
    monkeypatch.setattr(
        "daily_intelligence.workflow.schedule_independent_evaluation",
        lambda *_args, **_kwargs: {"status": "scheduled", "detail": "evaluation-job"},
    )

    complete_edition_tail(
        run_path,
        data_dir,
        publish=True,
        output_config=OutputConfig(formats=["html", "pdf"]),
    )

    run = read_json(run_path)
    assert run["tail"]["status"] == "completed"
    assert run["publication"]["page_id"] == "notion-page"
    assert run["evaluation"]["scheduler"]["status"] == "scheduled"
    assert run["artifacts"]["pdf_engine"] == "reportlab"
    assert run["metrics"]["pdf_projection_seconds"] >= 0


def test_schema_20_context_rejects_legacy_draft_before_persistence(monkeypatch, tmp_path: Path):
    data_dir = tmp_path / "data"
    date = "2026-07-25"
    index_path = write_json(
        data_dir / "indexes" / date / "morning-r1.json",
        {"date": date, "edition": "morning", "items": [], "sources": []},
    )
    context_path = write_json(
        data_dir / "context" / date / "morning-r1.json",
        {"schema_version": "2.0", "date": date, "edition": "morning"},
    )
    draft_path = write_json(
        data_dir / "drafts" / "morning.json",
        {"schema_version": "1.5", "date": date, "edition": "morning"},
    )
    run_path = write_json(
        data_dir / "runs" / date / "morning.json",
        {
            "schema_version": "1.0",
            "run_id": f"run-{date}-morning",
            "data_root": str(data_dir.resolve()),
            "date": date,
            "edition": "morning",
            "timezone": "Asia/Shanghai",
            "status": RunStatus.AWAITING_AUTHORING,
            "artifacts": {
                "index_path": str(index_path),
                "context_path": str(context_path),
            },
            "pending_sources": [],
        },
    )
    monkeypatch.setattr(
        "daily_intelligence.workflow.save_report",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("legacy draft must be rejected before persistence")
        ),
    )

    with pytest.raises(ValueError, match="legacy 1.5 drafts cannot bypass"):
        finalize_edition(run_path, draft_path, data_dir)


def test_deferred_tail_records_projection_failure_without_retracting_html(
    monkeypatch, tmp_path: Path
):
    data_dir = tmp_path / "data"
    date = "2026-07-25"
    report_path = write_json(
        data_dir / "reports" / date / "morning-r1.json",
        {
            "schema_version": "2.0",
            "report_id": f"daily-{date}-morning-r1",
            "date": date,
            "edition": "morning",
            "revision": 1,
        },
    )
    index_path = write_json(
        data_dir / "indexes" / date / "morning-r1.json",
        {"date": date, "edition": "morning", "items": [], "sources": []},
    )
    html_path = data_dir / "reports" / date / "morning-r1.html"
    run_path = write_json(
        data_dir / "runs" / date / "morning.json",
        {
            "schema_version": "1.0",
            "run_id": f"run-{date}-morning",
            "data_root": str(data_dir.resolve()),
            "date": date,
            "edition": "morning",
            "timezone": "Asia/Shanghai",
            "status": RunStatus.COMPLETED,
            "artifacts": {
                "json_path": str(report_path),
                "index_path": str(index_path),
                "html_path": str(html_path),
                "report_id": f"daily-{date}-morning-r1",
                "content_hash": "abc123",
            },
            "tail": {
                "status": "pending",
                "requested_formats": ["html", "pdf"],
                "publish_requested": False,
            },
            "evaluation": {
                "status": "pending",
                "scheduler": {"status": "deferred_until_tail"},
            },
        },
    )
    monkeypatch.setattr(
        "daily_intelligence.workflow.write_local_outputs",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("edge unavailable")),
    )
    monkeypatch.setattr(
        "daily_intelligence.workflow.schedule_independent_evaluation",
        lambda *_args, **_kwargs: {"status": "scheduled", "detail": "evaluation-job"},
    )

    complete_edition_tail(
        run_path,
        data_dir,
        output_config=OutputConfig(formats=["html", "pdf"]),
    )

    run = read_json(run_path)
    assert run["status"] == RunStatus.COMPLETED
    assert run["artifacts"]["html_path"] == str(html_path)
    assert run["tail"]["status"] == "partial"
    assert "Local PDF projection failed" in run["tail"]["errors"][0]
    assert run["evaluation"]["scheduler"]["status"] == "scheduled"


def test_finalize_validation_failure_returns_to_awaiting_authoring(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    run_path = data_dir / "runs" / "2026-07-12" / "morning.json"
    index_path = data_dir / "indexes" / "2026-07-12" / "morning-r1.json"
    report_path = tmp_path / "draft.json"
    write_json(index_path, {"date": "2026-07-12", "edition": "morning"})
    write_json(report_path, {"date": "2026-07-12", "edition": "morning"})
    write_json(
        run_path,
        {
            "date": "2026-07-12",
            "edition": "morning",
            "status": RunStatus.AWAITING_AUTHORING,
            "artifacts": {"index_path": str(index_path)},
        },
    )
    monkeypatch.setattr(
        "daily_intelligence.workflow.save_report",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad access")),
    )

    with pytest.raises(ValueError, match="bad access"):
        finalize_edition(run_path, report_path, data_dir)

    run = read_json(run_path)
    assert run["status"] == RunStatus.AWAITING_AUTHORING
    assert "bad access" in run["error"]


def test_finalize_rejects_an_index_that_lost_successful_enrichment(tmp_path):
    data_dir = tmp_path / "data"
    run_path = data_dir / "runs" / "2026-07-17" / "morning.json"
    index_path = write_json(
        data_dir / "indexes" / "2026-07-17" / "morning-r2.json",
        {
            "date": "2026-07-17",
            "edition": "morning",
            "items": [
                {
                    "item_id": "bbc-lost",
                    "content_status": "metadata_only",
                    "content_path": None,
                }
            ],
        },
    )
    draft = write_json(tmp_path / "draft.json", {"date": "2026-07-17", "edition": "morning"})
    write_json(
        run_path,
        {
            "data_root": str(data_dir.resolve()),
            "date": "2026-07-17",
            "edition": "morning",
            "status": RunStatus.AWAITING_AUTHORING,
            "artifacts": {
                "index_path": str(index_path),
                "enrichment": {"successful_item_ids": ["bbc-lost"]},
            },
        },
    )

    with pytest.raises(ValueError, match="lost previously successful full-text enrichment"):
        finalize_edition(run_path, draft, data_dir)
