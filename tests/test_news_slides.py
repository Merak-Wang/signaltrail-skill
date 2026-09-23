from copy import deepcopy
from pathlib import Path

import pytest

from daily_intelligence.narrative_store import load_artifact
from daily_intelligence.news_slides import (
    estimate_tokens,
    prepare_slides,
    render_slides,
    select_news,
    slides_status,
    submit_slides,
)
from daily_intelligence.utils import write_json
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
    _, _, _, report, _ = slide_case
    events = select_news(report)
    assert len(events) == 16
    assert events[0]["event_id"] == "event-0"
    assert sum(r["item_id"] == "item-0" for e in events for r in e["source_refs"]) == 1
    assert [e["event_id"] for e in select_news(report, item_ids=["item-15"])] == ["brief-item-15"]
    assert len(select_news(report, min_importance=90)) == 1
    with pytest.raises(ValueError, match="not in this report"):
        select_news(report, item_ids=["unknown"])


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
    output = render_slides(plan, root)
    assert render_slides(plan, root) == output
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
