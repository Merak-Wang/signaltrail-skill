import json
from copy import deepcopy
from pathlib import Path

import pytest

from signaltrail.narrative_store import load_artifact
from signaltrail.news_slides import (
    prepare_slides,
    render_slides,
    select_index_news,
    slides_status,
    submit_slides,
)
from signaltrail.utils import write_json


def index_case(root, count=8):
    items = []
    for number in range(count):
        body = root / "content" / f"item-{number}.md"
        body.parent.mkdir(exist_ok=True)
        body.write_text("Original evidence about a planned event. " * 20, encoding="utf-8")
        items.append({"item_id": f"item-{number}", "title": f"Original title {number}",
                      "url": f"https://example.com/{number}", "source_name": "Original source",
                      "description": "The company plans a launch; it has not happened yet.",
                      "content_status": "full_text", "content_path": str(body),
                      "published_at": None, "metadata": {"source_rank": number % 4 + 1}})
    return write_json(root / "indexes" / "index.json", {
        "date": "2026-10-07", "edition": "morning", "generated_at": None, "items": items})


def write_packets(prepared, root):
    for path in prepared["packet_paths"]:
        packet = load_artifact(Path(path), root)["payload"]
        draft = {"slides": [{"event_id": item["event_id"], "title": "目标语言标题",
                             "summary": "来源明确说明这是计划中的变化。",
                             "narration": "来源明确说明这是计划中的变化。" * 18,
                             "video_tldr": "来源明确说明这是计划中的变化。",
                             "perspectives": []} for item in packet["model_input"]["news"]]}
        submit_slides(Path(path), draft, root)


def test_index_selection_preserves_manual_order_and_merges_original_urls(tmp_path):
    path = index_case(tmp_path)
    index = json.loads(path.read_text(encoding="utf-8"))
    index["items"][4]["url"] = "https://www.example.com/0?utm_source=feed"
    selected = select_index_news(index, max_news=3)
    assert [item["event_id"] for item in selected] == ["index-item-0", "index-item-1",
                                                     "index-item-5"]
    assert len(selected[0]["source_refs"]) == 2
    manual = select_index_news(index, item_ids=["item-6", "item-2", "item-6"], max_news=1)
    assert manual[0]["event_id"] == "index-item-6"
    with pytest.raises(ValueError, match="no importance"):
        select_index_news(index, min_importance=10)


def test_standalone_author_render_and_unknown_fields(tmp_path, monkeypatch):
    path = index_case(tmp_path)
    monkeypatch.setattr("signaltrail.local_output.refresh_report_slides_entry",
                        lambda *args: pytest.fail("Standalone must not update a report"))
    prepared = prepare_slides(None, path, tmp_path)
    assert prepared["batch_count"] == 2
    assert prepared["pending_news_count"] == 8
    assert prepared["reserved_output_tokens"] == 8000
    plan = load_artifact(Path(prepared["plan_path"]), tmp_path)
    assert set(plan["parents"]) == {"index"}
    assert plan["payload"]["report_id"] is None
    assert plan["payload"]["as_of"] is None
    packet = load_artifact(Path(prepared["packet_paths"][0]), tmp_path)["payload"]
    assert len(packet["model_input"]["news"]) == 4
    assert "Original evidence" in packet["model_input"]["news"][0]["evidence"][0]["body"]
    assert "images" not in packet["model_input"]["news"][0]
    write_packets(prepared, tmp_path)
    assert slides_status(Path(prepared["plan_path"]), tmp_path)["pending_news_count"] == 0
    output = render_slides(Path(prepared["plan_path"]), tmp_path, refresh_images=False)
    deck = load_artifact(Path(output["json_path"]), tmp_path)["payload"]
    assert deck["slides"][0]["title"] == "目标语言标题"
    assert deck["slides"][0]["sources"][0]["title"] == "Original title 0"
    assert deck["slides"][0]["sources"][0]["published_at"] is None
    assert all(value is None for value in deck["usage"].values())
    assert output["html_path"] == output["artifact_html_path"]
    assert "As of: 未知" in Path(output["markdown_path"]).read_text(encoding="utf-8")


def test_index_only_reads_selected_body_and_never_truncates(tmp_path):
    path = index_case(tmp_path)
    index = json.loads(path.read_text(encoding="utf-8"))
    index["items"][1]["content_path"] = str(tmp_path / "missing.md")
    write_json(path, index)
    prepared = prepare_slides(None, path, tmp_path, item_ids=["item-0"], language="en")
    packet = load_artifact(Path(prepared["packet_paths"][0]), tmp_path)["payload"]
    assert packet["model_input"]["language"] == "en"
    body = "正文" * 20000
    Path(index["items"][0]["content_path"]).write_text(body, encoding="utf-8")
    with pytest.raises(ValueError, match="increase token limits"):
        prepare_slides(None, path, tmp_path, item_ids=["item-0"], max_input_tokens=12000)
    prepared = prepare_slides(None, path, tmp_path, item_ids=["item-0"])
    packet = load_artifact(Path(prepared["packet_paths"][0]), tmp_path)["payload"]
    assert packet["model_input"]["news"][0]["evidence"][0]["body"] == body


@pytest.mark.parametrize("field", ["sources", "images", "caption"])
def test_index_draft_cannot_rewrite_python_fields(tmp_path, field):
    prepared = prepare_slides(None, index_case(tmp_path, 1), tmp_path)
    path = Path(prepared["packet_paths"][0])
    packet = load_artifact(path, tmp_path)["payload"]
    slide = {"event_id": packet["model_input"]["news"][0]["event_id"], "title": "标题",
             "summary": "摘要", "narration": "来源明确说明这是计划中的变化。" * 18,
                             "video_tldr": "来源明确说明这是计划中的变化。",
             "perspectives": []}
    invalid = deepcopy(slide)
    invalid[field] = "invented"
    with pytest.raises(ValueError, match="Invalid slide draft"):
        submit_slides(path, {"slides": [invalid]}, tmp_path)


def test_plain_cli_standalone_lifecycle_and_all_reused_render(tmp_path, monkeypatch, capsys):
    from signaltrail.cli import main

    app_data = tmp_path / "app-data"
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(app_data))
    monkeypatch.setenv("XDG_DATA_HOME", str(app_data))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "unused-hermes"))
    monkeypatch.setenv("SIGNALTRAIL_DATA_DIR", str(root))
    monkeypatch.delenv("DAILY_INTEL_DATA_DIR", raising=False)
    index_path = index_case(root, 2)
    assert main(["slides", "prepare", "--index", str(index_path)]) == 0
    prepared = json.loads(capsys.readouterr().out)
    for number, path in enumerate(prepared["packet_paths"]):
        packet = load_artifact(Path(path), root)["payload"]
        draft = {"slides": [{"event_id": item["event_id"], "title": "目标语言标题",
                             "summary": "来源说明事件仍在计划中。",
                             "narration": "来源明确说明这是计划中的变化。" * 18,
                             "video_tldr": "来源明确说明这是计划中的变化。",
                             "perspectives": []} for item in packet["model_input"]["news"]]}
        draft_path = write_json(root / "drafts" / f"batch-{number}.json", draft)
        assert main(["slides", "submit", "--packet", path, "--input", str(draft_path)]) == 0
        assert Path(json.loads(capsys.readouterr().out)["artifact_path"]).is_file()
    plan_path = prepared["plan_path"]
    assert main(["slides", "status", "--plan", plan_path]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ready"
    assert main(["slides", "render", "--plan", plan_path, "--offline"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert all(Path(first[key]).is_file() for key in ("html_path", "json_path", "markdown_path"))
    assert not (root / "reports").exists()

    next_index = write_json(root / "indexes" / "next-revision.json",
                            json.loads(index_path.read_text(encoding="utf-8")))
    assert main(["slides", "prepare", "--index", str(next_index),
                 "--reuse-plan", plan_path]) == 0
    reused = json.loads(capsys.readouterr().out)
    assert reused["packet_paths"] == []
    assert reused["reused_count"] == 2
    assert reused["pending_news_count"] == 0
    assert reused["estimated_input_tokens"] == 0
    assert main(["slides", "render", "--plan", reused["plan_path"], "--offline"]) == 0
    output = json.loads(capsys.readouterr().out)
    deck = load_artifact(Path(output["json_path"]), root)["payload"]
    assert len(deck["slides"]) == 2
    assert deck["slides"][0]["title"] == "目标语言标题"
    assert not (root / "reports").exists()
