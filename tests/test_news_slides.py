from copy import deepcopy
from pathlib import Path

import pytest

from signaltrail.narrative_store import load_artifact
from signaltrail.news_slides import (
    estimate_tokens,
    prepare_slides,
    render_slides,
    select_news,
    slides_status,
    submit_slides,
)
from signaltrail.utils import write_json
from tests.report_helpers import load_sample_report, write_report_index


@pytest.fixture
def slide_case(tmp_path):
    source = {"id": "example", "name": "示例报", "url": "https://example.com"}
    briefs, indexed = [], []
    for number in range(16):
        item_id = f"item-{number}"
        ref = {"item_id": item_id, "title": f"新闻 {number}",
               "url": f"https://example.com/{number}", "access": "full_text", "role": "primary"}
        briefs.append({"item_id": item_id, "title": ref["title"], "tldr": "已有报道的事实摘要。",
                       "importance": 90 - number, "primary_source": source, "source_ref": ref})
        indexed.append({"item_id": item_id, "source_name": source["name"],
                        "published_at": "2026-09-23T08:00:00+08:00", "url": ref["url"]})
    report = {
        "title": "合成图文演示", "report_id": "daily-2026-09-23-morning-r1",
        "date": "2026-09-23", "edition": "morning", "revision": 1, "language": "zh-CN",
        "generated_at": "2026-09-23T09:00:00+08:00", "analyses": [],
        "sections": [{"items": [{"event_id": "event-0", "title": "精选新闻",
                                  "tldr": "精选事件摘要。", "importance": 95,
                                  "primary_source": source,
                                  "source_refs": [briefs[0]["source_ref"]]}], "briefs": briefs}],
    }
    index = {"date": report["date"], "edition": report["edition"], "items": indexed}
    report_path = write_json(tmp_path / "reports/morning-r1.json", report)
    index_path = write_json(tmp_path / "indexes/morning-r1.json", index)
    return tmp_path, report_path, index_path, report, index


def author_packet(path, root):
    packet = load_artifact(Path(path), root)["payload"]
    return {"slides": [{"event_id": c["event_id"], "narration": "这是来源中已经确认的变化。" * 18,
                        "perspectives": []} for c in packet["model_input"]["news"]]}


def test_selection_includes_more_than_twelve_and_manual_ids_override(slide_case):
    _, _, _, report, index = slide_case
    events = select_news(report, index)
    assert len(events) == 16
    assert events[0]["event_id"] == "event-0"
    assert sum(r["item_id"] == "item-0" for e in events for r in e["source_refs"]) == 1
    assert [e["event_id"] for e in select_news(report, index, item_ids=["item-15"])] == [
        "brief-item-15"
    ]
    assert len(select_news(report, index, min_importance=90)) == 1
    with pytest.raises(ValueError, match="not in this report"):
        select_news(report, index, item_ids=["unknown"])


def test_selection_merges_single_source_reposts_by_original_url(slide_case):
    _, _, _, report, index = slide_case
    lower, higher = report["sections"][0]["briefs"][1:3]
    lower_url = "http://www.righto.com/2026/09/story.html?id=1&utm_source=lobsters#comments"
    higher_url = "https://righto.com/2026/09/story.html?id=1&ref=frontpage"
    lower["source_ref"].update({"url": lower_url, "published_at": "2026-09-23T02:00:00+08:00"})
    higher["source_ref"].update({"url": higher_url, "published_at": "2026-09-23T03:00:00+08:00"})
    lower.update({"title": "较低分标题", "tldr": "较低分摘要。", "importance": 60})
    higher.update({"title": "较高分标题", "tldr": "较高分摘要。", "importance": 90})

    selected = select_news(report, index, item_ids=[lower["item_id"], higher["item_id"]])

    assert len(selected) == 1
    assert selected[0]["event_id"] == f"brief-{higher['item_id']}"
    assert selected[0]["title"] == "较高分标题"
    assert selected[0]["tldr"] == "较高分摘要。"
    assert [ref["item_id"] for ref in selected[0]["source_refs"]] == [
        higher["item_id"], lower["item_id"],
    ]
    assert {ref["published_at"] for ref in selected[0]["source_refs"]} == {
        "2026-09-23T02:00:00+08:00", "2026-09-23T03:00:00+08:00",
    }


def test_selection_keeps_distinct_article_query_ids_separate(slide_case):
    _, _, _, report, index = slide_case
    first, second = report["sections"][0]["briefs"][3:5]
    first["source_ref"]["url"] = "https://righto.com/story?id=1"
    second["source_ref"]["url"] = "http://www.righto.com/story?id=2"

    selected = select_news(report, index, item_ids=[first["item_id"], second["item_id"]])

    assert {event["event_id"] for event in selected} == {
        f"brief-{first['item_id']}", f"brief-{second['item_id']}",
    }


def test_selection_does_not_merge_multi_source_event_with_single_source_story(slide_case):
    _, _, _, report, index = slide_case
    sections = report["sections"][0]
    event = sections["items"][0]
    first_ref = deepcopy(sections["briefs"][1]["source_ref"])
    second_ref = deepcopy(sections["briefs"][2]["source_ref"])
    first_ref["url"] = "https://righto.com/story?id=1"
    second_ref["url"] = "https://example.org/other-story"
    event["source_refs"] = [first_ref, second_ref]
    brief = sections["briefs"][3]
    brief["source_ref"]["url"] = "http://www.righto.com/story?id=1"

    selected = select_news(
        report, index, item_ids=[first_ref["item_id"], second_ref["item_id"], brief["item_id"]],
    )

    assert len(selected) == 2
    assert selected[0]["event_id"] == event["event_id"]
    assert len(selected[0]["source_refs"]) == 2
    assert selected[1]["event_id"] == f"brief-{brief['item_id']}"


def test_selection_covers_report_dates_and_preserves_unknown_publication(slide_case):
    _, _, _, report, index = slide_case
    before = deepcopy(report)
    values = [
        "2026-09-22T16:00:00Z",  # 北京时间当天零点，保留精选。
        "2026-09-22T15:59:59Z",  # 当天前一秒，即使高分也排除。
        "2026-09-23T15:59:59Z",  # 北京时间当天最后一秒。
        "2026-09-23T16:00:00Z",  # 下一天，排除。
        None, "bad-date", "2026-09-23", "2026-09-22",
    ]
    index["items"] = index["items"][:len(values)]
    report["sections"][0]["briefs"] = report["sections"][0]["briefs"][:len(values)]
    for item, published in zip(index["items"], values, strict=True):
        item["published_at"] = published
        item["collected_at"] = "2026-09-23T09:00:00+08:00"
    # 图文流只消费权威日报入选集合，展示日期来自索引且未知仍未知。
    report["sections"][0]["briefs"][4]["source_ref"]["published_at"] = "2026-09-23"
    selected = select_news(report, index)
    assert {e["event_id"] for e in selected} == {
        "event-0", *(f"brief-item-{i}" for i in range(1, 8)),
    }
    assert [e["event_id"] for e in select_news(report, index, item_ids=["item-1"])] == [
        "brief-item-1",
    ]
    assert index["items"][4]["published_at"] is None
    root, report_path, index_path, _, _ = slide_case
    write_json(report_path, report)
    write_json(index_path, index)
    prepared = prepare_slides(report_path, index_path, root, item_ids=["item-4"])
    plan = load_artifact(Path(prepared["plan_path"]), root)["payload"]
    assert plan["news"][0]["sources"][0]["published_at"] is None
    assert report["sections"][0]["items"] == before["sections"][0]["items"]


def test_default_plan_includes_low_score_and_imageless_news_in_score_order(slide_case):
    root, report_path, index_path, report, index = slide_case
    briefs = report["sections"][0]["briefs"]
    briefs[1]["importance"], briefs[2]["importance"] = 15, 0
    index["items"][3]["published_at"] = "2026-09-22"
    write_json(report_path, report)
    write_json(index_path, index)

    selected = select_news(report, index)
    assert [e["event_id"] for e in selected][-2:] == ["brief-item-1", "brief-item-2"]
    assert "brief-item-3" in {e["event_id"] for e in selected}
    assert len(select_news(report, index, min_importance=70)) == 14
    assert sum(ref["item_id"] == "item-0" for e in selected for ref in e["source_refs"]) == 1

    prepared = prepare_slides(report_path, index_path, root)
    plan = load_artifact(Path(prepared["plan_path"]), root)["payload"]
    assert prepared["news_count"] == 16
    assert [n["event_id"] for n in plan["news"]] == [e["event_id"] for e in selected]
    assert all(n["images"] == [] for n in plan["news"])
    assert len(prepared["packet_paths"]) == 4


def test_old_featured_events_do_not_hide_todays_briefs(slide_case):
    _, _, _, report, index = slide_case
    index["items"][0]["published_at"] = "2026-09-22"
    index["items"][1]["published_at"] = "2026-09-23"
    report["sections"][0]["items"][0]["source_refs"].append(
        report["sections"][0]["briefs"][1]["source_ref"]
    )
    selected = select_news(report, index)
    event = next(e for e in selected if e["event_id"] == "event-0")
    assert [ref["item_id"] for ref in event["source_refs"]] == ["item-0", "item-1"]
    assert not any(e["event_id"] == "brief-item-1" for e in selected)


def test_discovery_and_unknown_dates_are_retained_with_index_dates(slide_case):
    root, report_path, index_path, report, index = slide_case
    for item, published in zip(
        index["items"][:3], ["2026-09-19", None, "2026-09-23"], strict=True,
    ):
        item["metadata"] = {"role": "discovery", "content_source": {"published_at": published}}
    index["items"][2]["published_at"] = "2026-09-22T23:00:00+08:00"
    selected = select_news(report, index)
    assert {"event-0", "brief-item-1", "brief-item-2"} <= {
        e["event_id"] for e in selected
    }
    assert [e["event_id"] for e in select_news(report, index, item_ids=["item-2"])] == [
        "brief-item-2",
    ]
    # 聚合条目保留平台发布日期，原文元信息不覆盖；其他来源不伪造日期。
    write_json(index_path, index)
    prepared = prepare_slides(report_path, index_path, root, item_ids=["item-0"])
    plan = load_artifact(Path(prepared["plan_path"]), root)["payload"]
    assert plan["news"][0]["sources"][0]["published_at"] == "2026-09-23T08:00:00+08:00"
    for packet in prepared["packet_paths"]:
        submit_slides(Path(packet), author_packet(packet, root), root)
    output = render_slides(Path(prepared["plan_path"]), root, refresh_images=False)
    assert output["news_count"] == 1


def test_selection_limits_after_importance_sort_and_deduplication(slide_case):
    _, _, _, report, index = slide_case
    report["sections"][0]["briefs"][0]["source_ref"]["url"] = "https://same.test/story"
    report["sections"][0]["briefs"][1]["source_ref"]["url"] = "https://same.test/story"
    report["sections"][0]["briefs"][1]["importance"] = 100

    selected = select_news(report, index, max_news=3)

    assert len(selected) == 3
    assert [event["importance"] for event in selected] == sorted(
        (event["importance"] for event in selected), reverse=True
    )
    assert len(selected[0]["source_refs"]) == 2


def test_selection_defaults_to_fifty_and_accepts_custom_limit(slide_case):
    _, _, _, report, index = slide_case
    for number in range(16, 55):
        brief = deepcopy(report["sections"][0]["briefs"][0])
        brief["item_id"] = f"extra-{number}"
        brief["event_id"] = f"brief-extra-{number}"
        brief["importance"] = 100 - number
        brief["source_ref"] = {**brief["source_ref"], "item_id": brief["item_id"],
                               "url": f"https://example.com/{number}"}
        report["sections"][0]["briefs"].append(brief)
        index["items"].append({"item_id": brief["item_id"], "published_at": None,
                                "url": brief["source_ref"]["url"]})

    assert len(select_news(report, index)) == 50
    assert len(select_news(report, index, max_news=7)) == 7
    with pytest.raises(ValueError, match="max_news must be positive"):
        select_news(report, index, max_news=0)


def test_max_news_is_part_of_immutable_plan_identity(slide_case):
    root, report_path, index_path, _, _ = slide_case

    ten = prepare_slides(report_path, index_path, root, max_news=10)
    eleven = prepare_slides(report_path, index_path, root, max_news=11)

    assert ten["plan_path"] != eleven["plan_path"]
    assert prepare_slides(report_path, index_path, root, max_news=10) == ten
    payload = load_artifact(Path(ten["plan_path"]), root)["payload"]
    assert payload["budget"]["max_news"] == 10
    assert payload["selection_policy"] == "report-admitted-importance-v1"


def test_prepare_batches_by_size_and_budget_and_reuses_inputs(slide_case):
    root, report, index, _, _ = slide_case
    before = report.read_bytes(), index.read_bytes()
    result = prepare_slides(report, index, root, batch_size=3, max_output_tokens=1400)
    assert (result["news_count"], result["batch_count"]) == (16, 8)
    assert prepare_slides(report, index, root, batch_size=3, max_output_tokens=1400) == result
    for packet_path in result["packet_paths"]:
        packet = load_artifact(Path(packet_path), root)["payload"]
        assert len(packet["model_input"]["news"]) == 2
        assert "images" not in packet["model_input"]["news"][0]
        assert packet["budget"]["estimated_input_tokens"] <= 12000
        assert packet["budget"]["reserved_output_tokens"] <= 1400
        assert packet["budget"]["input_tokens"] is None
    with pytest.raises(ValueError, match="cannot fit"):
        prepare_slides(report, index, root, max_input_tokens=1)
    with pytest.raises(ValueError, match="cannot fit"):
        prepare_slides(report, index, root, max_output_tokens=699)
    assert before == (report.read_bytes(), index.read_bytes())


def test_submit_rejects_missing_events_invented_perspectives_and_bad_lengths(slide_case):
    root, report, index, _, _ = slide_case
    result = prepare_slides(report, index, root)
    packet = Path(result["packet_paths"][0])
    draft = author_packet(packet, root)
    invalid = deepcopy(draft)
    invalid["slides"].pop()
    with pytest.raises(ValueError, match="exactly once"):
        submit_slides(packet, invalid, root)
    invalid = deepcopy(draft)
    invalid["slides"][0]["perspectives"] = ["markets"]
    with pytest.raises(ValueError, match="supplied analyses"):
        submit_slides(packet, invalid, root)
    invalid = deepcopy(draft)
    invalid["slides"][0]["narration"] = "太短"
    with pytest.raises(ValueError, match="200–350"):
        submit_slides(packet, invalid, root)
    invalid = deepcopy(draft)
    invalid["slides"][0]["caption"] = "invented"
    with pytest.raises(ValueError, match="Invalid slide draft"):
        submit_slides(packet, invalid, root)
    accepted = submit_slides(packet, draft, root)
    assert submit_slides(packet, draft, root) == accepted
    changed = deepcopy(draft)
    changed["slides"][0]["narration"] += "补充。"
    with pytest.raises(ValueError, match="already accepted"):
        submit_slides(packet, changed, root)


def test_all_batches_required_then_render_preserves_original_report(slide_case):
    root, report, index, _, _ = slide_case
    before = report.read_bytes()
    result = prepare_slides(report, index, root, batch_size=2)
    plan = Path(result["plan_path"])
    packet = Path(result["packet_paths"][0])
    submit_slides(packet, author_packet(packet, root), root)
    status = slides_status(plan, root)
    assert status["pending_batches"] == list(range(2, 9))
    assert status["usage"]["input_tokens"] is None
    with pytest.raises(ValueError, match="Pending slide batches"):
        render_slides(plan, root)
    for packet_path in result["packet_paths"][1:]:
        packet = Path(packet_path)
        submit_slides(packet, author_packet(packet, root), root)
    output = render_slides(plan, root, refresh_images=False)
    assert render_slides(plan, root, refresh_images=False) == output
    assert output["news_count"] == 16
    deck = load_artifact(Path(output["json_path"]), root)["payload"]
    assert len(deck["slides"]) == 16
    assert deck["slides"][0]["summary"] == "精选事件摘要。"
    assert "精选新闻" in Path(output["html_path"]).read_text(encoding="utf-8")
    report_html = report.with_suffix(".html").read_text(encoding="utf-8")
    assert 'class="news-slides-link" href="morning-r1-slides.html"' in report_html
    assert Path(output["html_path"]).name == "morning-r1-slides.html"
    assert "示例报" in Path(output["markdown_path"]).read_text(encoding="utf-8")
    assert report.read_bytes() == before


def test_render_fetches_images_once_and_offline_reuses_them(slide_case, monkeypatch):
    root, report, index, _, _ = slide_case
    result = prepare_slides(report, index, root, item_ids=["item-0"])
    for packet in result["packet_paths"]:
        submit_slides(Path(packet), author_packet(packet, root), root)
    calls = []

    def enrich(news, data_dir, config):
        calls.append([n["event_id"] for n in news])
        news[0]["images"] = [{"url": "https://example.com/high.jpg", "caption": "原始图注",
                              "source_url": "https://example.com/0", "width": 1400}]
        return news, {"sources_fetched": 1}

    monkeypatch.setattr("signaltrail.slide_images.enrich_slide_images", enrich)
    plan = Path(result["plan_path"])
    output = render_slides(plan, root)
    replay = render_slides(plan, root, refresh_images=False)
    assert replay == output
    assert calls == [["event-0"]]
    deck = load_artifact(Path(output["json_path"]), root)["payload"]
    assert deck["slides"][0]["images"][0]["width"] == 1400
    assert deck["image_enrichment"] == {"sources_fetched": 1}


def test_render_legacy_plan_keeps_old_and_unknown_sources(slide_case, monkeypatch):
    from signaltrail.narrative_store import save_artifact

    root, report, index_path, _, index = slide_case
    result = prepare_slides(report, index_path, root)
    plan = load_artifact(Path(result["plan_path"]), root)
    index["items"][0]["published_at"] = "2026-09-22"
    index["items"][1]["published_at"] = None
    legacy_index = write_json(root / "indexes/legacy.json", index)
    legacy_plan = save_artifact(root, "legacy-slides", "slides-plan", plan["payload"],
                               {"report": report, "index": legacy_index})
    # 重建旧计划的已接受讲稿，避免通过新 prepare 筛选掩盖渲染端回归。
    completed = []
    for packet in result["packet_paths"]:
        completed.append(str(submit_slides(Path(packet), author_packet(packet, root), root)))
    monkeypatch.setattr("signaltrail.news_slides.slides_status", lambda *args: {
        "pending_batches": [], "completed_paths": completed, "usage": {},
    })
    output = render_slides(legacy_plan, root, refresh_images=False)
    deck = load_artifact(Path(output["json_path"]), root)["payload"]
    assert len(deck["slides"]) == 16
    assert {s["event_id"] for s in deck["slides"]} >= {"event-0", "brief-item-1"}


def test_images_keep_original_caption_and_collapse_responsive_versions(slide_case):
    root, report_path, index_path, report, index = slide_case
    report["sections"][0]["briefs"][0]["image"] = {
        "source_url": "https://example.com/a.jpg", "caption": "网站原始图注 A",
        "local_path": "media/images/a.jpg", "content_type": "image/jpeg", "credit": "作者甲",
    }
    index["items"][0]["metadata"] = {"image_candidate_details": [
        {"url": "https://example.com/a.jpg", "caption": "网站原始图注 A", "position": 0,
         "provenance": "article_body", "alt": "ALT 不是图注"},
        {"url": "https://example.com/a-small.jpg", "caption": "网站原始图注 A", "position": 0,
         "provenance": "article_body"},
        {"url": "https://example.com/b.jpg", "caption": "", "alt": "不能冒充caption",
         "position": 1, "provenance": "article_body"},
    ]}
    write_json(report_path, report)
    write_json(index_path, index)
    result = prepare_slides(report_path, index_path, root)
    plan = load_artifact(Path(result["plan_path"]), root)["payload"]
    images = plan["news"][0]["images"]
    assert len(images) == 2
    assert images[0]["caption"] == "网站原始图注 A"
    assert images[0]["credit"] == "作者甲"
    assert images[0]["source_url"] == "https://example.com/0"
    assert images[1]["caption"] is None


def test_images_merge_cover_metadata_and_all_body_positions_preferring_clear_variant(slide_case):
    root, report_path, index_path, report, index = slide_case
    report["sections"][0]["briefs"][0]["image"] = {
        "source_url": "https://example.com/body-0-small.jpg",
        "resolved_url": "https://cdn.example.com/body-0-small.jpg",
        "local_path": "media/images/body-0-small.jpg",
        "content_type": "image/jpeg", "width": 320, "height": 180,
        "caption": "正文原图注", "credit": "原作者",
    }
    indexed = index["items"][0]
    indexed["image_url"] = "https://example.com/cover.jpg"
    indexed["image_candidates"] = ["https://example.com/cover-large.jpg"]
    indexed["metadata"] = {
        "image_candidates": ["https://example.com/page-meta.jpg"],
        "image_candidate_details": [
            {"url": "https://example.com/cover.jpg", "provenance": "page_metadata",
             "purpose": "publisher_selected", "caption": "封面原图注", "credit": "图片社",
             "declared_width": "1200", "declared_height": "675"},
            {"url": "https://example.com/cover-large.jpg", "provenance": "page_metadata",
             "purpose": "publisher_selected", "caption": "高清封面图注",
             "declared_width": "2400", "declared_height": "1350"},
            {"url": "https://example.com/page-meta.jpg", "provenance": "page_metadata",
             "purpose": "publisher_selected", "caption": "页面元数据图注"},
            {"url": "https://example.com/body-0-small.jpg", "provenance": "article_body",
             "purpose": "article_illustration", "caption": "正文原图注", "position": 0,
             "variant": 1, "declared_width": "320", "declared_height": "180"},
            {"url": "https://example.com/body-0-large.jpg", "provenance": "article_body",
             "purpose": "article_illustration", "caption": "正文高清图注", "position": 0,
             "variant": 0, "declared_width": "1600", "declared_height": "900"},
            *[
                {"url": f"https://example.com/body-{position}.jpg",
                 "provenance": "article_body", "purpose": "article_illustration",
                 "caption": f"正文图注 {position}" if position % 2 else "",
                 "position": position, "relevance_score": 8 - position}
                for position in range(1, 8)
            ],
            {"url": "https://example.com/assets/site-logo.png", "provenance": "page_metadata",
             "purpose": "publisher_selected", "alt": "Publisher logo", "caption": ""},
        ],
    }
    write_json(report_path, report)
    write_json(index_path, index)

    result = prepare_slides(report_path, index_path, root, item_ids=["item-0"])
    plan = load_artifact(Path(result["plan_path"]), root)["payload"]
    images = plan["news"][0]["images"]
    by_url = {image["url"]: image for image in images}

    assert len(images) == 11
    assert images[0]["url"] == "https://example.com/cover-large.jpg"
    assert by_url["https://example.com/cover.jpg"]["caption"] == "封面原图注"
    assert by_url["https://example.com/page-meta.jpg"]["caption"] == "页面元数据图注"
    assert "https://example.com/assets/site-logo.png" not in by_url
    assert "https://example.com/body-0-small.jpg" not in by_url
    high_resolution = by_url["https://example.com/body-0-large.jpg"]
    assert high_resolution["caption"] == "正文高清图注"
    assert high_resolution["credit"] == "示例报"
    assert "local_path" not in high_resolution
    assert all(image["source_url"] == "https://example.com/0" for image in images)
    assert by_url["https://example.com/body-2.jpg"]["caption"] is None


def test_images_unwrap_explicit_next_original_and_drop_proxy_cache(slide_case):
    root, report_path, index_path, report, index = slide_case
    proxy_3840 = (
        "https://news.example.com/_next/image?url="
        "https%3A%2F%2Fcdn.example.com%2Fstory%2Fphoto.png&w=3840&q=75"
    )
    proxy_1920 = (
        "https://news.example.com/_next/image?url="
        "https%3A%2F%2Fcdn.example.com%2Fstory%2Fphoto.png&w=1920&q=75"
    )
    report["sections"][0]["briefs"][0]["image"] = {
        "source_url": proxy_3840, "resolved_url": proxy_3840,
        "local_path": "media/images/proxy.webp", "width": 800, "height": 450,
        "caption": "原文配图说明", "credit": "通讯社",
    }
    indexed = index["items"][0]
    indexed["image_url"] = proxy_3840
    indexed["metadata"] = {"image_candidate_details": [
        {"url": proxy_3840, "provenance": "page_metadata", "caption": "原文配图说明"},
        {"url": proxy_1920, "provenance": "page_metadata", "caption": "原文配图说明"},
        {"url": "https://cdn.example.com/transform?url=https%3A%2F%2Fother.example%2Fp.png",
         "provenance": "article_body", "position": 0},
    ]}
    write_json(report_path, report)
    write_json(index_path, index)

    result = prepare_slides(report_path, index_path, root, item_ids=["item-0"])
    plan = load_artifact(Path(result["plan_path"]), root)["payload"]
    images = plan["news"][0]["images"]
    by_url = {image["url"]: image for image in images}

    original = "https://cdn.example.com/story/photo.png"
    assert list(by_url).count(original) == 1
    assert by_url[original]["caption"] == "原文配图说明"
    assert by_url[original]["credit"] == "通讯社"
    assert "local_path" not in by_url[original]
    assert "https://cdn.example.com/transform?url=https%3A%2F%2Fother.example%2Fp.png" in by_url
    assert all("/_next/image" not in image["url"] for image in images)


def test_images_collapse_known_cdn_size_variants_and_keep_body_caption(slide_case):
    root, report_path, index_path, report, index = slide_case
    report["sections"][0]["briefs"][0]["image"] = {
        "source_url": "https://image.cnbcfm.com/api/v1/image/108234567-hero.jpg?v=1&w=800&h=450",
        "resolved_url": "https://image.cnbcfm.com/api/v1/image/108234567-hero.jpg?v=1&w=800&h=450",
        "local_path": "media/images/old-small.jpg", "width": 800, "height": 450,
        "caption": "旧缓存错图注",
    }
    indexed = index["items"][0]
    indexed["image_candidates"] = [
        "https://image.cnbcfm.com/api/v1/image/108234567-hero.jpg?v=1&w=1200&h=675",
        "https://image.cnbcfm.com/api/v1/image/108234567-hero.jpg?v=1&w=1920&h=1080",
        "https://images.ctfassets.net/space/id/hero.png?w=1200&q=70",
        "https://images.ctfassets.net/space/id/hero.png?w=2400&q=90",
        "https://i.abcnewsfe.com/a/b/news.jpg?w=480&h=270",
        "https://i.abcnewsfe.com/a/b/news.jpg?w=1200&h=675",
        "https://ichef.bbci.co.uk/ace/standard/240/cpsprodpb/ad23/live/abc-123.jpg",
        "https://ichef.bbci.co.uk/ace/branded_news/1200/cpsprodpb/ad23/live/abc-123.jpg",
        "https://theaviationist.com/wp-content/uploads/2026/09/jet-460x259.jpg",
        "https://theaviationist.com/wp-content/uploads/2026/09/jet.jpg",
        "https://unlisted.example.com/hero.jpg?w=1200",
        "https://unlisted.example.com/hero.jpg?w=2400",
    ]
    indexed["metadata"] = {"image_candidate_details": [
        {"url": indexed["image_candidates"][0], "provenance": "page_metadata"},
        {"url": indexed["image_candidates"][1], "provenance": "page_metadata"},
        {"url": indexed["image_candidates"][2], "provenance": "page_metadata"},
        {"url": indexed["image_candidates"][3], "provenance": "page_metadata"},
        *[{"url": url, "provenance": "page_metadata"} for url in indexed["image_candidates"][4:10]],
        {"url": "https://image.cnbcfm.com/api/v1/image/108234567-hero.jpg?v=1&w=800&h=450",
         "provenance": "article_body", "position": 0, "caption": "图注来自正文同图"},
        {"url": "https://s.w.org/images/core/emoji/17/72x72/emoji.png",
         "provenance": "page_metadata"},
    ]}
    for detail in indexed["metadata"]["image_candidate_details"]:
        if "jet-460x259" in detail["url"]:
            detail.update(declared_width="460", declared_height="259")
        elif detail["url"].endswith("/jet.jpg"):
            detail.update(declared_width="1600", declared_height="900")
    write_json(report_path, report)
    write_json(index_path, index)

    result = prepare_slides(report_path, index_path, root, item_ids=["item-0"])
    plan = load_artifact(Path(result["plan_path"]), root)["payload"]
    images = plan["news"][0]["images"]
    urls = [image["url"] for image in images]

    assert urls.count(indexed["image_candidates"][1]) == 1
    assert "https://image.cnbcfm.com/api/v1/image/108234567-hero.jpg?v=1&w=800&h=450" not in urls
    cnbc = next(image for image in images if "108234567-hero.jpg" in image["url"])
    assert cnbc["caption"] == "图注来自正文同图"
    assert "local_path" not in cnbc
    assert cnbc["url"].endswith("w=1920&h=1080")
    assert "https://images.ctfassets.net/space/id/hero.png?w=2400&q=90" in urls
    assert "https://images.ctfassets.net/space/id/hero.png?w=1200&q=70" not in urls
    assert len([url for url in urls if "unlisted.example.com/hero.jpg" in url]) == 2
    assert "https://i.abcnewsfe.com/a/b/news.jpg?w=1200&h=675" in urls
    assert "https://i.abcnewsfe.com/a/b/news.jpg?w=480&h=270" not in urls
    assert "https://ichef.bbci.co.uk/ace/branded_news/1200/cpsprodpb/ad23/live/abc-123.jpg" in urls
    assert "https://ichef.bbci.co.uk/ace/standard/240/cpsprodpb/ad23/live/abc-123.jpg" not in urls
    assert "https://theaviationist.com/wp-content/uploads/2026/09/jet.jpg" in urls
    assert "https://theaviationist.com/wp-content/uploads/2026/09/jet-460x259.jpg" not in urls
    assert "https://s.w.org/images/core/emoji/17/72x72/emoji.png" not in urls


def test_usni_wordpress_responsive_sizes_keep_largest_existing_image(slide_case):
    root, report_path, index_path, report, index = slide_case
    base_url = "https://news.usni.org/wp-content/uploads/2026/09/ship.jpeg"
    variants = [
        (base_url, 1200, 800),
        (base_url.replace(".jpeg", "-320x214.jpeg"), 320, 214),
        (base_url.replace(".jpeg", "-150x100.jpeg"), 150, 100),
        (base_url.replace(".jpeg", "-60x40.jpeg"), 60, 40),
    ]
    index["items"][0]["image_candidates"] = [url for url, _, _ in variants]
    index["items"][0]["metadata"] = {"image_candidate_details": [
        {"url": url, "declared_width": width, "declared_height": height,
         "provenance": "page_metadata"}
        for url, width, height in variants
    ]}
    write_json(report_path, report)
    write_json(index_path, index)

    prepared = prepare_slides(report_path, index_path, root, item_ids=["item-0"])
    plan = load_artifact(Path(prepared["plan_path"]), root)["payload"]
    urls = [image["url"] for image in plan["news"][0]["images"]]

    assert urls == [base_url]
    assert all("-320x214" not in url and "-150x100" not in url and "-60x40" not in url
               for url in urls)


def test_related_perspectives_are_optional_and_fact_text_is_not_truncated(slide_case):
    root, report_path, index_path, report, _ = slide_case
    report["analyses"] = [{"domain": "markets", "claim": "如果成立才有影响",
                           "narrative": "这是有条件推断，不是已发生的市场走势。",
                           "evidence_event_ids": ["event-0"]}]
    write_json(report_path, report)
    result = prepare_slides(report_path, index_path, root, item_ids=["item-0"])
    packet = Path(result["packet_paths"][0])
    draft = author_packet(packet, root)
    draft["slides"][0]["perspectives"] = ["markets"]
    assert submit_slides(packet, draft, root).is_file()
    content = load_artifact(packet, root)["payload"]["model_input"]
    assert content["news"][0]["analyses"][0]["narrative"] == report["analyses"][0]["narrative"]
    assert estimate_tokens(content) > 0


def test_slides_inherit_report_language_and_preserve_mixed_language_sources(slide_case):
    root, report_path, index_path, report, index = slide_case
    chinese_ref = dict(report["sections"][0]["items"][0]["source_refs"][0])
    chinese_ref.update({
        "title": "央行维持政策利率不变",
        "published_at": "2026-09-28T08:00:00+08:00",
        "access": "metadata_only",
    })
    english_ref = dict(report["sections"][0]["briefs"][1]["source_ref"])
    english_ref.update({
        "title": "Central bank holds policy rate",
        "published_at": "2026-09-28T08:10:00+00:00",
        "access": "full_text",
    })
    report["sections"][0]["items"][0]["source_refs"] = [chinese_ref, english_ref]
    index["items"][0].update({
        "source_name": "新华社",
        "published_at": chinese_ref["published_at"],
    })
    index["items"][1].update({
        "source_name": "Reuters",
        "published_at": english_ref["published_at"],
    })
    write_json(index_path, index)

    for language, title, summary in (
        ("zh-CN", "央行维持政策利率不变", "央行在最新决议中维持政策利率不变。"),
        ("en", "Central bank holds policy rate", "The central bank held its policy rate."),
    ):
        report["language"] = language
        event = report["sections"][0]["items"][0]
        event["title"] = title
        event["tldr"] = summary
        write_json(report_path, report)
        prepared = prepare_slides(report_path, index_path, root, item_ids=["item-0"])
        payload = load_artifact(Path(prepared["plan_path"]), root)["payload"]
        packet = load_artifact(Path(prepared["packet_paths"][0]), root)["payload"]
        sources = payload["news"][0]["sources"]

        assert payload["language"] == language
        assert packet["model_input"]["language"] == language
        assert [(s["name"], s["title"], s["published_at"], s["access"]) for s in sources] == [
            ("新华社", "央行维持政策利率不变", chinese_ref["published_at"], "metadata_only"),
            ("Reuters", "Central bank holds policy rate", english_ref["published_at"], "full_text"),
        ]


def test_legacy_saved_report_can_prepare_without_briefs(tmp_path):
    report = load_sample_report(Path(__file__).resolve().parents[1])
    report_path = write_json(tmp_path / "reports/legacy-r1.json", report)
    index_path = write_report_index(report, tmp_path / "indexes/legacy-r1.json")
    result = prepare_slides(report_path, index_path, tmp_path)
    plan = load_artifact(Path(result["plan_path"]), tmp_path)["payload"]
    assert result["news_count"] == 1
    news = plan["news"][0]
    assert news["event_id"] == "TECH-20260712-001"
    assert news["sources"][0]["access"] == "metadata_only"
    assert news["images"] == []
    assert news["analyses"][0]["domain"] == "ai_technology"


def test_guardian_high_density_variant_beats_cached_140px_thumbnail(slide_case):
    root, report_path, index_path, report, index = slide_case
    article_url = (
        "https://www.theguardian.com/us-news/2026/sep/23/"
        "trump-xi-jinping-china-us-state-visit"
    )
    thumbnail = (
        "https://i.guim.co.uk/img/media/example/master/2935.jpg?width=140&dpr=1"
    )
    medium = (
        "https://i.guim.co.uk/img/media/example/master/2935.jpg?width=460&dpr=1"
    )
    high_density = (
        "https://i.guim.co.uk/img/media/example/master/2935.jpg?width=700&dpr=2"
    )
    brief = report["sections"][0]["briefs"][0]
    brief["source_ref"]["url"] = article_url
    brief["image"] = {
        "source_url": thumbnail, "resolved_url": thumbnail,
        "local_path": "media/images/old-thumbnail.webp", "width": 140, "height": 112,
        "content_type": "image/webp", "caption": "原图注",
    }
    indexed = index["items"][0]
    indexed["url"] = article_url
    indexed["image_url"] = thumbnail
    indexed["metadata"] = {
        "image_candidates": [thumbnail, medium, high_density],
        "image_candidate_details": [{
            "url": high_density, "provenance": "page_metadata",
            "declared_width": "465", "declared_height": "372",
        }],
    }
    write_json(report_path, report)
    write_json(index_path, index)

    result = prepare_slides(report_path, index_path, root, item_ids=["item-0"])
    plan = load_artifact(Path(result["plan_path"]), root)["payload"]
    images = plan["news"][0]["images"]

    guardian_image = next(image for image in images if "guim.co.uk" in image["url"])
    assert guardian_image["url"] == high_density
    assert "local_path" not in guardian_image


def test_duplicate_image_details_keep_cached_file_size_and_caption():
    from signaltrail.news_slides import _news_images

    url = "https://example.com/photo.jpg?width=1400"
    event = {"source_refs": [{"item_id": "item-0", "url": "https://example.com/story"}]}

    def indexed(details):
        return {"item-0": {"url": "https://example.com/story", "source_name": "示例报",
                           "metadata": {"image_candidate_details": details}}}

    cached = {"url": url, "provenance": "article_body", "position": 0,
              "local_path": "media/images/photo.jpg", "sha256": "abc",
              "width": 1400, "height": 933, "caption": "正文原图注"}
    page = {"url": url, "provenance": "page_metadata", "declared_width": "1400",
            "declared_height": "933", "caption": ""}
    for details in ([cached, page], [page, cached]):
        images = _news_images(event, {}, indexed([dict(row) for row in details]))
        assert len(images) == 1
        assert images[0]["local_path"] == "media/images/photo.jpg"
        assert (images[0]["width"], images[0]["height"]) == (1400, 933)
        assert images[0]["caption"] == "正文原图注"


def test_page_metadata_cannot_replace_measured_cache_or_body_caption():
    from signaltrail.news_slides import _news_images

    url = "https://example.com/photo.jpg"
    event = {"source_refs": [{"item_id": "item-0", "url": "https://example.com/story"}]}
    details = [
        {"url": url, "provenance": "article_body", "position": 0,
         "caption": "正文原图注", "local_path": "media/images/photo.jpg",
         "sha256": "abc", "width": 1400, "height": 933, "byte_size": 1234,
         "content_type": "image/jpeg"},
        {"url": url, "provenance": "page_metadata", "caption": "",
         "declared_width": "465", "declared_height": "310"},
    ]
    indexed = {"item-0": {"url": "https://example.com/story",
                           "metadata": {"image_candidate_details": details}}}

    images = _news_images(event, {}, indexed)

    assert len(images) == 1
    assert images[0]["local_path"] == "media/images/photo.jpg"
    assert images[0]["width"] == 1400 and images[0]["height"] == 933
    assert images[0]["caption"] == "正文原图注"
    assert images[0]["provenance"] == "article_body" and images[0]["position"] == 0


def test_guardian_responsive_crops_collapse_to_high_resolution_with_body_caption():
    from signaltrail.news_slides import _news_images

    hero = (
        "https://i.guim.co.uk/img/media/205a3d6cb96fec1fecb84ab6537d3ac02b0651e0/"
        "181_0_1500_1200/master/1500.jpg?width=1200&height=630&quality=85&auto=format"
        "&fit=crop&precrop=40:21&overlay-align=bottom%2Cleft&enable=upscale"
    )
    body = (
        "https://i.guim.co.uk/img/media/205a3d6cb96fec1fecb84ab6537d3ac02b0651e0/"
        "26_0_1738_1200/master/1738.jpg?width=1300&dpr=2&s=none&crop=none"
    )
    other_asset = (
        "https://i.guim.co.uk/img/media/f41609563a2b6b9472f7c3b63b26ce0151a27d7b/"
        "260_0_6091_4615/master/6091.jpg?width=620&dpr=2&s=none&crop=none"
    )
    event = {"source_refs": [{"item_id": "guardian", "url": "https://example.com/story"}]}
    indexed = {"guardian": {
        "url": "https://example.com/story", "source_name": "Guardian",
        "metadata": {"image_candidate_details": [
            {"url": hero, "provenance": "page_metadata", "purpose": "publisher_selected"},
            {"url": body, "provenance": "article_body", "position": 0,
             "caption": "US forces intercepted the Ecuadorian vessel Manta."},
            {"url": other_asset, "provenance": "article_body", "position": 1,
             "caption": "Ecuador’s president presents Marco Rubio with an award."},
        ]},
    }}

    images = _news_images(event, {}, indexed)

    assert len(images) == 2
    assert images[0]["url"] == body
    assert images[0]["caption"] == "US forces intercepted the Ecuadorian vessel Manta."
    assert images[1]["url"] == other_asset


@pytest.mark.parametrize("small,large", [
    ("https://ichef.bbci.co.uk/ace/standard/624/cpsprodpb/123/live/photo.jpg.webp",
     "https://ichef.bbci.co.uk/ace/standard/745/cpsprodpb/123/live/photo.jpg"),
    ("https://i.guim.co.uk/img/media/photo.jpg?w=320",
     "https://i.guim.co.uk/img/media/photo.jpg?w=1400"),
])
def test_explicit_variant_size_outweighs_shared_html_display_size(small, large):
    from signaltrail.news_slides import _news_images

    event = {"source_refs": [{"item_id": "item", "url": "https://example.com/story"}]}
    details = [{
        "url": url, "provenance": "article_body", "position": 0, "variant": variant,
        "declared_width": "745", "declared_height": "418", "caption": "原图注",
    } for variant, url in enumerate([small, large])]
    indexed = {"item": {"url": "https://example.com/story",
                        "metadata": {"image_candidate_details": details}}}

    images = _news_images(event, {}, indexed)

    assert [image["url"] for image in images] == [large]
    assert images[0]["caption"] == "原图注"


def test_images_collapse_same_asset_variants_and_prefer_the_clearer_one(slide_case):
    root, report_path, index_path, report, index = slide_case
    article = "https://www.channelnewsasia.com/world/australia-openai-agent-breach"
    hero = (
        "https://dam.mediacorp.sg/image/upload/s--7LkFLh0E--/c_crop,h_1332,w_1666,x_166,y_0/"
        "c_fill,g_center,h_598,w_747/f_auto,q_auto/v1/mediacorp/cna/image/2026/09/24/breach.jpg"
    )
    cover = (
        "https://dam.mediacorp.sg/image/upload/s--F34rAgWg--/c_crop,h_1125,w_2000,x_0,y_104/"
        "c_fill,g_auto,h_676,w_1200/f_auto,q_auto/v1/mediacorp/cna/image/2026/09/24/breach.jpg"
    )
    brief = report["sections"][0]["briefs"][0]
    brief["source_ref"]["url"] = article
    indexed = index["items"][0]
    indexed["url"] = article
    indexed["metadata"] = {"image_candidate_details": [
        {"url": "https://ichef.bbci.co.uk/ace/branded_news/1200/cpsprodpb/f010/live/"
                 "69f3ee00-b795-11f1-a430-4d16ee157c41.jpg",
         "provenance": "page_metadata", "caption": "Image caption, Albanese said it took time."},
        {"url": "https://ichef.bbci.co.uk/ace/standard/976/cpsprodpb/f010/live/"
                 "69f3ee00-b795-11f1-a430-4d16ee157c41.jpg.webp",
         "provenance": "article_body", "position": 0},
        {"url": cover, "provenance": "page_metadata", "purpose": "publisher_selected",
         "caption": ""},
        {"url": hero, "provenance": "article_body", "position": 0,
         "caption": "Australia's Prime Minister Anthony Albanese speaks."},
    ]}
    write_json(report_path, report)
    write_json(index_path, index)

    result = prepare_slides(report_path, index_path, root, item_ids=["item-0"])
    plan = load_artifact(Path(result["plan_path"]), root)["payload"]
    images = plan["news"][0]["images"]

    assert [image["url"] for image in images if "bbci" in image["url"]] == [indexed["metadata"][
        "image_candidate_details"
    ][0]["url"]]
    assert [image["url"] for image in images if "mediacorp" in image["url"]] == [cover]
    assert next(image for image in images if image["url"] == cover)["caption"] == (
        "Australia's Prime Minister Anthony Albanese speaks."
    )
