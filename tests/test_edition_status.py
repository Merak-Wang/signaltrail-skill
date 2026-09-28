import json
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

from signaltrail.commands.editions import handle_edition_status
from signaltrail.commands.parser import build_parser
from signaltrail.narrative_store import save_artifact
from signaltrail.utils import write_json
from signaltrail.workflow import get_edition_status


def _run(tmp_path: Path, *, batches=(1,), tail="completed", fail=False):
    data = tmp_path / "data"
    report = write_json(data / "reports" / "r1.json", {
        "date": "2026-09-28", "edition": "morning", "revision": 1,
    })
    markdown = report.with_suffix(".md")
    markdown.write_text("# Report", encoding="utf-8")
    report_html = report.with_suffix(".html")
    report_html.write_text("<html>", encoding="utf-8")
    index = write_json(data / "indexes" / "i1.json", {})
    plan = save_artifact(data, "status-slides", "slides-plan", {
        "selection_policy": "report-admitted-importance-v1",
        "budget": {"max_news": 50},
    }, {"report": report, "index": index})
    html = report.with_name("morning-r1-slides.html")
    run = {
        "data_root": str(data.resolve()), "date": "2026-09-28", "edition": "morning",
        "status": "completed_partial", "evaluation_requested": False,
        "artifacts": {"json_path": str(report), "markdown_path": str(markdown),
                      "html_path": str(report_html), "index_path": str(index),
                      "slides": {"status": "failed" if fail else "prepared",
                                 "plan_path": str(plan), "packet_paths": ["p1", "p2"]}},
        "tail": {"status": tail, "requested_formats": []},
    }
    path = write_json(data / "runs" / "run.json", run)
    return data, path, plan, html


@pytest.mark.parametrize(("pending", "html_exists", "expected"), [
    ([1], False, "awaiting_authoring"), ([], False, "ready"), ([], True, "rendered"),
])
def test_edition_status_derives_slide_delivery(tmp_path, monkeypatch, pending,
                                               html_exists, expected):
    data, run, plan, html = _run(tmp_path)
    if html_exists:
        html.write_text("<html>", encoding="utf-8")
        deck = save_artifact(data, "status-slides", "slides-deck", {}, {"plan": plan})
        deck.with_suffix(".html").write_text("<html>", encoding="utf-8")
    monkeypatch.setattr("signaltrail.news_slides.slides_status", lambda *_: {
        "pending_batches": pending, "news_count": 2,
        "status": "awaiting_authoring" if pending else "ready",
    })
    status = get_edition_status(run, data)
    assert status["slides"]["status"] == expected
    assert status["delivery_complete"] is (expected == "rendered")
    assert status["report_status"] == "completed_partial"


def test_edition_status_tail_and_failed_prepare_block_delivery(tmp_path):
    data, run, *_ = _run(tmp_path, tail="partial", fail=True)
    manifest = json.loads(run.read_text(encoding="utf-8"))
    manifest["artifacts"]["slides"].pop("plan_path")
    run.write_text(json.dumps(manifest), encoding="utf-8")
    status = get_edition_status(run, data)
    assert status["tail_status"] == "partial"
    assert status["slides"]["status"] == "prepare_failed"
    assert "finalize-edition --run" in status["slides"]["next_action"]
    assert not status["delivery_complete"]


def test_requested_inline_pdf_missing_blocks_delivery(tmp_path, monkeypatch):
    data, run, *_ = _run(tmp_path)
    manifest = json.loads(run.read_text(encoding="utf-8"))
    manifest.pop("tail")
    manifest["artifacts"]["requested_formats"] = ["html", "pdf"]
    manifest["artifacts"]["slides"].pop("plan_path")
    run.write_text(json.dumps(manifest), encoding="utf-8")
    status = get_edition_status(run, data)
    assert "tail" in status["pending_steps"]


def test_finalize_retry_replaces_failed_slides_preparation(tmp_path, monkeypatch):
    from signaltrail.workflow import finalize_edition

    data, run, plan, _ = _run(tmp_path)
    manifest = json.loads(run.read_text(encoding="utf-8"))
    manifest["artifacts"]["slides"] = {
        "status": "failed", "error": "transient",
        "plan_path": str(data / "slides" / "missing-plan.json"),
    }
    run.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr("signaltrail.news_slides.prepare_slides", lambda *_args, **_kwargs: {
        "plan_path": str(plan), "packet_paths": ["packet.json"], "news_count": 1,
        "batch_count": 1,
    })
    monkeypatch.setattr("signaltrail.news_slides.slides_status", lambda *_: {
        "pending_batches": [1], "news_count": 1, "status": "awaiting_authoring",
    })
    finalize_edition(run, Path("unused.json"), data, defer_tail=True)
    status = get_edition_status(run, data)
    assert status["slides"]["status"] == "awaiting_authoring"
    assert "slides_prepare" not in status["pending_steps"]


def test_completed_inline_report_without_tail_does_not_wait_for_tail(tmp_path, monkeypatch):
    data, run, *_ = _run(tmp_path)
    manifest = json.loads(run.read_text(encoding="utf-8"))
    manifest["status"] = "completed"
    manifest.pop("tail")
    run.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr("signaltrail.news_slides.slides_status", lambda *_: {
        "pending_batches": [], "news_count": 2, "status": "ready",
    })
    status = get_edition_status(run, data)
    assert "tail" not in status["pending_steps"]


def test_failed_report_cannot_pass_delivery_with_saved_artifacts(tmp_path, monkeypatch):
    data, run, *_ = _run(tmp_path)
    manifest = json.loads(run.read_text(encoding="utf-8"))
    manifest["status"] = "failed"
    run.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr("signaltrail.news_slides.slides_status", lambda *_: {
        "pending_batches": [], "news_count": 2, "status": "ready",
    })
    assert "report" in get_edition_status(run, data)["pending_steps"]


def test_edition_status_require_complete_exit_code(tmp_path, monkeypatch, capsys):
    data, run, *_ = _run(tmp_path, tail="pending")
    monkeypatch.setattr("signaltrail.news_slides.slides_status", lambda *_: {
        "pending_batches": [1], "news_count": 2, "status": "awaiting_authoring",
    })
    context = SimpleNamespace(data_dir=data)
    assert handle_edition_status(Namespace(run=run, require_complete=False), context) == 0
    assert handle_edition_status(Namespace(run=run, require_complete=True), context) == 1
    assert capsys.readouterr().out.count('"delivery_complete": false') == 2


def test_require_complete_passes_for_rendered_read_only_delivery(tmp_path, monkeypatch, capsys):
    data, run, plan, html = _run(tmp_path)
    html.write_text("<html>", encoding="utf-8")
    deck = save_artifact(data, "status-slides", "slides-deck", {}, {"plan": plan})
    deck.with_suffix(".html").write_text("<html>", encoding="utf-8")
    monkeypatch.setattr("signaltrail.news_slides.slides_status", lambda *_: {
        "pending_batches": [], "news_count": 1, "status": "ready",
    })
    before = run.read_bytes()
    result = handle_edition_status(
        Namespace(run=run, require_complete=True), SimpleNamespace(data_dir=data)
    )
    assert result == 0
    assert json.loads(capsys.readouterr().out)["delivery_complete"] is True
    assert run.read_bytes() == before


def test_old_html_cannot_satisfy_changed_max_news_plan(tmp_path, monkeypatch):
    data, run, plan, html = _run(tmp_path)
    old_payload = {
        "selection_policy": "report-admitted-importance-v1", "budget": {"max_news": 30},
    }
    old_plan = save_artifact(data, "old-slides", "slides-plan", old_payload, {
        "report": data / "reports" / "r1.json", "index": data / "indexes" / "i1.json",
    })
    old_deck = save_artifact(data, "old-slides", "slides-deck", {}, {"plan": old_plan})
    old_deck.with_suffix(".html").write_text("old deck", encoding="utf-8")
    html.write_text("old deck", encoding="utf-8")
    manifest = json.loads(run.read_text(encoding="utf-8"))
    manifest["artifacts"]["slides"].update({"plan_path": str(old_plan), "max_news": 50})
    run.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr("signaltrail.news_slides.slides_status", lambda *_: {
        "pending_batches": [], "news_count": 30, "status": "ready",
    })

    status = get_edition_status(run, data)

    assert status["slides"]["status"] == "stale_plan"
    assert "slides_prepare" in status["pending_steps"]
    assert not status["delivery_complete"]

    new_plan = save_artifact(data, "new-slides", "slides-plan", {
        "selection_policy": "report-admitted-importance-v1", "budget": {"max_news": 50},
    }, {"report": data / "reports" / "r1.json", "index": data / "indexes" / "i1.json"})
    new_deck = save_artifact(data, "new-slides", "slides-deck", {}, {"plan": new_plan})
    new_deck.with_suffix(".html").write_text("new deck", encoding="utf-8")
    manifest = json.loads(run.read_text(encoding="utf-8"))
    manifest["artifacts"]["slides"].update({"plan_path": str(new_plan), "packet_paths": []})
    run.write_text(json.dumps(manifest), encoding="utf-8")
    status = get_edition_status(run, data)
    assert status["pending_steps"] == ["slides_render"]
    assert not status["delivery_complete"]

    html.write_text("new deck", encoding="utf-8")
    status = get_edition_status(run, data)
    assert status["delivery_complete"]


def test_edition_status_parser_requires_manifest_and_supports_gate():
    args = build_parser().parse_args([
        "edition-status", "--run", "run.json", "--require-complete",
    ])
    assert args.run == Path("run.json")
    assert args.require_complete

    finalize = build_parser().parse_args([
        "finalize-edition", "--run", "run.json", "--report", "report.json",
        "--slides-max-news", "20",
    ])
    assert finalize.slides_max_news == 20
