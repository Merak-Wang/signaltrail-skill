from copy import deepcopy
from pathlib import Path

import pytest

from signaltrail.narrative_store import load_artifact, save_artifact
from signaltrail.news_slides import _model_input, prepare_slides, slides_status, submit_slides
from signaltrail.slide_reuse import reusable_slides
from signaltrail.utils import read_json, write_json


@pytest.fixture
def accepted_plan(tmp_path):
    news = {"event_id": "event-1", "title": "标题", "summary": "事实摘要",
            "why_it_matters": "影响", "evidence_notes": [], "analyses": [],
            "sources": [{"name": "原文", "title": "标题", "url": "https://example.com/1",
                         "published_at": "2026-10-07", "access": "full_text"}], "images": []}
    model_input = _model_input([news], "风格", "zh-CN")
    plan = save_artifact(tmp_path, "old", "slides-plan", {
        "news": [news], "model_input_template": {**model_input, "news": []},
    }, {})
    packet = save_artifact(tmp_path, "old", "slides-packet-1", {
        "batch_id": 1, "model_input": model_input,
        "budget": {"max_output_tokens": 4000},
    }, {"plan": plan})
    draft = {"slides": [{"event_id": "event-1", "narration": "这是来源已经确认的变化。" * 20,
        "video_tldr": "来源已经确认这项变化。",
                         "perspectives": []}]}
    submit_slides(packet, draft, tmp_path)
    return tmp_path, plan, model_input, draft


@pytest.mark.parametrize("field", ["title", "summary", "why_it_matters", "evidence_notes",
                                  "sources", "analyses"])
def test_any_changed_writing_evidence_requires_new_narration(accepted_plan, field):
    root, plan, model_input, _ = accepted_plan
    changed = deepcopy(model_input)
    changed["news"][0][field] = "different evidence"
    assert reusable_slides(plan, {"event-1": changed}, root) == []


@pytest.mark.parametrize("field", ["language", "style", "instructions", "output_schema"])
def test_changed_writing_contract_requires_new_narration(accepted_plan, field):
    root, plan, model_input, _ = accepted_plan
    changed = deepcopy(model_input)
    changed[field] = "changed contract"
    assert reusable_slides(plan, {"event-1": changed}, root) == []


def test_matching_text_reuses_a_copy_without_images(accepted_plan):
    root, plan, model_input, draft = accepted_plan
    reused = reusable_slides(plan, {"event-1": model_input}, root)
    assert reused == draft["slides"]
    reused[0]["narration"] = "edited copy"
    assert reusable_slides(plan, {"event-1": model_input}, root) == draft["slides"]


def test_unaccepted_packet_is_not_reused(tmp_path):
    news = {"event_id": "unaccepted", "analyses": []}
    model_input = _model_input([news], "style", "en")
    plan = save_artifact(tmp_path, "pending", "slides-plan", {"news": [news]}, {})
    save_artifact(tmp_path, "pending", "slides-packet-1", {
        "model_input": model_input,
    }, {"plan": plan})
    assert reusable_slides(plan, {"unaccepted": model_input}, tmp_path) == []


def test_inherited_reused_narration_needs_no_packet_parent_chain(accepted_plan):
    root, _, model_input, draft = accepted_plan
    plan = save_artifact(root, "all-reused", "slides-plan", {
        "news": model_input["news"], "model_input_template": {**model_input, "news": []},
        "reused_slides": draft["slides"],
    }, {})
    assert reusable_slides(plan, {"event-1": model_input}, root) == draft["slides"]


def _report_case(root):
    source = {"id": "example", "name": "来源", "url": "https://example.com"}
    ref = {"item_id": "item-1", "title": "报道", "url": "https://example.com/1",
           "access": "full_text", "role": "primary"}
    report = {"report_id": "daily-2026-10-07-morning-r1", "title": "日报",
              "date": "2026-10-07", "edition": "morning", "revision": 1,
              "language": "zh-CN", "generated_at": "2026-10-07T09:00:00+08:00",
              "analyses": [], "sections": [{"items": [], "briefs": [{
                  "item_id": "item-1", "title": "报道", "tldr": "来源提供的事实摘要。",
                  "importance": 80, "primary_source": source, "source_ref": ref,
              }]}]}
    index = {"date": report["date"], "edition": report["edition"], "items": [{
        "item_id": "item-1", "source_name": "来源", "url": ref["url"],
        "published_at": "2026-10-07T08:00:00+08:00",
    }]}
    return write_json(root / "reports/r1.json", report), write_json(root / "indexes/i1.json", index)


def test_revision_and_image_change_reuse_all_and_replay_stably(tmp_path):
    report, index = _report_case(tmp_path)
    old = prepare_slides(report, index, tmp_path)
    packet = Path(old["packet_paths"][0])
    event_id = load_artifact(packet, tmp_path)["payload"]["model_input"]["news"][0]["event_id"]
    submit_slides(packet, {"slides": [{"event_id": event_id,
        "narration": "这是来源已经确认的变化。" * 20,
        "video_tldr": "来源已经确认这项变化。", "perspectives": []}]}, tmp_path)
    revised = read_json(report)
    revised.update({"revision": 2, "report_id": "daily-2026-10-07-morning-r2"})
    report2 = write_json(tmp_path / "reports/r2.json", revised)
    enriched = read_json(index)
    enriched["items"][0]["images"] = [{"url": "https://example.com/new.jpg"}]
    index2 = write_json(tmp_path / "indexes/i2.json", enriched)
    result = prepare_slides(report2, index2, tmp_path, reuse_plan=Path(old["plan_path"]))
    assert result["plan_path"] != old["plan_path"]
    assert result["batch_count"] == 0
    assert result["packet_paths"] == []
    assert slides_status(Path(result["plan_path"]), tmp_path)["pending_batches"] == []
    assert prepare_slides(report2, index2, tmp_path, reuse_plan=Path(old["plan_path"])) == result


@pytest.mark.parametrize("location", ["slides", "previous_report"])
def test_workflow_prepares_new_revision_with_the_known_old_plan(tmp_path, location):
    from signaltrail.workflow import _prepare_edition_slides

    report, index = _report_case(tmp_path)
    old = prepare_slides(report, index, tmp_path)
    packet = Path(old["packet_paths"][0])
    event_id = load_artifact(packet, tmp_path)["payload"]["model_input"]["news"][0]["event_id"]
    submit_slides(packet, {"slides": [{"event_id": event_id,
        "narration": "这是来源已经确认的变化。" * 20,
        "video_tldr": "来源已经确认这项变化。", "perspectives": []}]}, tmp_path)
    revised = read_json(report)
    revised.update({"revision": 2, "report_id": "daily-2026-10-07-morning-r2"})
    report2 = write_json(tmp_path / "reports/r2.json", revised)
    run = {"status": "finalizing", "date": revised["date"], "edition": revised["edition"],
           "data_root": str(tmp_path), "artifacts": {
               "json_path": str(report2), "index_path": str(index),
           }}
    run["artifacts"][location] = old if location == "slides" else {"slides": old}
    run_path = write_json(tmp_path / "runs/morning.json", run)
    _prepare_edition_slides(run, run_path, tmp_path)
    assert run["artifacts"]["slides"]["plan_path"] != old["plan_path"]
    plan = load_artifact(Path(run["artifacts"]["slides"]["plan_path"]), tmp_path)
    assert plan["payload"]["report_id"] == revised["report_id"]
    assert len(plan["payload"]["reused_slides"]) == 1
    assert run["artifacts"]["slides"]["packet_paths"] == []


@pytest.mark.parametrize("location", ["slides", "previous_report"])
@pytest.mark.parametrize("broken", ["missing", "invalid"])
def test_workflow_rebuilds_when_optional_old_plan_is_unavailable(tmp_path, location, broken):
    from signaltrail.workflow import _prepare_edition_slides

    report, index = _report_case(tmp_path)
    old_plan = tmp_path / "narratives/old/slides-plan-r1.json"
    if broken == "invalid":
        old_plan.parent.mkdir(parents=True)
        old_plan.write_text("{}", encoding="utf-8")
    old = {"plan_path": str(old_plan)}
    run = {"status": "finalizing", "date": "2026-10-07", "edition": "morning",
           "data_root": str(tmp_path), "artifacts": {
               "json_path": str(report), "index_path": str(index),
               location: old if location == "slides" else {"slides": old},
           }}
    run_path = write_json(tmp_path / "runs/morning.json", run)
    _prepare_edition_slides(run, run_path, tmp_path)
    result = run["artifacts"]["slides"]
    assert result["status"] == "prepared"
    assert result["plan_path"] != str(old_plan)
    assert len(result["packet_paths"]) == 1


def test_images_reuse_requires_matching_evidence(accepted_plan):
    from signaltrail.slide_reuse import reusable_images

    root, plan, model_input, _ = accepted_plan
    save_artifact(root, "old", "slides-deck", {"slides": [
        {"event_id": "event-1", "images": [{"url": "https://example.com/image.jpg"}]}
    ]}, {"plan": plan})
    news = deepcopy(model_input["news"])
    assert reusable_images(plan, news, root)["event-1"][0]["url"].endswith("image.jpg")
    news[0]["existing_narration"] = "原讲解"
    assert "event-1" in reusable_images(plan, news, root)
    news[0]["summary"] = "changed"
    assert reusable_images(plan, news, root) == {}


def test_missing_video_script_reuses_only_matching_old_narration(tmp_path):
    from signaltrail.slide_reuse import previous_narrations

    news = {"event_id": "one", "summary": "fact", "images": []}
    slide = {"event_id": "one", "narration": "完整讲解", "perspectives": []}
    plan = save_artifact(tmp_path, "old", "slides-plan", {
        "news": [news], "model_input_template": {"style": "style", "language": "zh-CN"},
        "reused_slides": [slide],
    }, {})
    assert previous_narrations(plan, [news], tmp_path, "style", "zh-CN") == {"one": "完整讲解"}
    assert previous_narrations(plan, [news], tmp_path, "changed", "zh-CN") == {}
    assert previous_narrations(plan, [{**news, "summary": "changed"}], tmp_path,
                               "style", "zh-CN") == {}
