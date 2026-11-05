import json
import threading

import httpx

from signaltrail.dashboard import create_monitor_server
from signaltrail.edition_reader import list_editions, read_edition, read_edition_event
from signaltrail.events import get_event, sync_monitor_snapshot
from signaltrail.utils import write_json


def _report(tmp_path, date="2026-11-02", language="zh-CN", revision=1):
    report = {
        "schema_version": "2.0",
        "report_id": f"daily-{date}-daily-r{revision}",
        "date": date,
        "edition": "daily",
        "revision": revision,
        "language": language,
        "generated_at": f"{date}T10:{revision:02d}:00+08:00",
        "sections": [
            {
                "module": "information",
                "category": "international",
                "briefs": [],
                "items": [
                    {
                        "event_id": "EVT-one",
                        "title": "央行公布利率决议",
                        "tldr": "这是已经生成的中文日报摘要。",
                        "importance": 88,
                        "primary_source": {"id": "example", "name": "Example"},
                        "source_refs": [
                            {
                                "item_id": "article-one",
                                "title": "Central bank announces rates",
                                "url": "https://news.example/rates",
                            }
                        ],
                    }
                ],
            }
        ],
        "analyses": [
            {"domain": "markets", "claim": "日报中的市场判断", "evidence_event_ids": ["EVT-one"]}
        ],
    }
    if language == "en":
        report["sections"][0]["items"][0].update(
            title="Central bank announces rates",
            tldr="The central bank published its rate decision.",
        )
        report["analyses"][0]["claim"] = "The decision changes market expectations."
    path = tmp_path / "reports" / date / f"daily-r{revision}.json"
    write_json(path, report)
    return report, path


def test_home_uses_only_saved_editions_and_never_substitutes_news_or_old_language(tmp_path):
    write_json(tmp_path / "monitor/snapshot.json", {"items": [{"title": "Raw news"}]})
    assert read_edition(tmp_path)["status"] == "empty"
    _report(tmp_path, "2026-10-29", "en")
    report, path = _report(tmp_path)
    write_json(path.with_name("daily-r2-draft.json"), report)
    assert list_editions(tmp_path)["total"] == 2
    missing = read_edition(tmp_path, language="en")
    assert missing["status"] == "unavailable"
    assert missing["report"] is None
    assert missing["available_languages"] == ["zh-CN"]
    assert missing["selection"]["date"] == report["date"]
    assert missing["selection"]["edition"] == "daily"
    assert missing["available_editions"][0]["report_id"] == report["report_id"]
    unavailable_event = read_edition_event(tmp_path, report["report_id"], "EVT-one", language="en")
    assert unavailable_event["status"] == "unavailable"
    assert unavailable_event["report"] is None
    current = read_edition(tmp_path)
    assert current["report"]["report_id"] == report["report_id"]
    assert current["report"]["sections"][0]["items"][0] == {
        **report["sections"][0]["items"][0],
        "image_url": None,
    }
    assert current["events"][0]["title"] == "央行公布利率决议"
    detail = read_edition_event(tmp_path, report["report_id"], "EVT-one")
    assert detail["event"]["research_available"] is False
    assert detail["articles"][0]["url"] == "https://news.example/rates"


def test_requested_language_selects_real_issue_and_matching_event(tmp_path):
    chinese, _ = _report(tmp_path)
    english, _ = _report(tmp_path, language="en", revision=2)
    assert read_edition(tmp_path, language="")["report"]["report_id"] == chinese["report_id"]
    assert read_edition(tmp_path, language="zh-CN")["report"]["report_id"] == chinese["report_id"]
    selected = read_edition(tmp_path, language="en")
    assert selected["report"]["report_id"] == english["report_id"]
    assert selected["report"]["language"] == "en"
    assert selected["events"][0]["title"] == "Central bank announces rates"
    assert "title_zh" not in selected["report"]["sections"][0]["items"][0]
    detail = read_edition_event(tmp_path, chinese["report_id"], "EVT-one", language="en")
    assert detail["report_id"] == english["report_id"]
    assert detail["event"]["title"] == "Central bank announces rates"
    assert detail["report_language"] == "en"


def test_report_event_context_and_artifact_streaming(tmp_path):
    report, path = _report(tmp_path)
    local = tmp_path / "media/images/article.jpg"
    local.parent.mkdir(parents=True)
    local.write_bytes(b"cached article photo")
    report["sections"][0]["briefs"] = [
        {
            "item_id": "article-one",
            "title": "Central bank announces rates",
            "image": {
                "source_url": "https://news.example/article.jpg",
                "local_path": "media/images/article.jpg",
                "width": 800,
                "height": 450,
            },
        }
    ]
    write_json(path, report)
    sync_monitor_snapshot(
        tmp_path,
        {
            "generated_at": report["generated_at"],
            "sources": [],
            "items": [
                {
                    "item_id": "article-one",
                    "title": "Central bank announces rates",
                    "url": "https://news.example/rates",
                    "canonical_url": "https://news.example/rates",
                    "published_at": report["generated_at"],
                    "source_id": "example",
                    "module": "information",
                    "category": "international",
                }
            ],
            "clusters": [{"story_id": "story-one", "item_ids": ["article-one"]}],
        },
    )
    path.with_name("daily-r1-video.mp4").write_bytes(b"0123456789")
    server = create_monitor_server(tmp_path, port=0, quiet=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        with httpx.Client(base_url=f"http://{host}:{port}") as client:
            edition = client.get("/api/edition").json()
            card = edition["events"][0]
            assert card["event_id"] == "story-one"
            assert card["image_url"] == "/files/media/images/article.jpg"
            assert edition["report"]["sections"][0]["briefs"][0]["image_url"] == card["image_url"]
            detail = client.get(card["detail_url"].replace("/events/", "/api/events/")).json()
            assert detail["event"]["title"] == "央行公布利率决议"
            assert detail["analyses"][0]["language"] == "zh-CN"
            video = client.get(edition["artifacts"]["mp4"], headers={"Range": "bytes=2-5"})
            assert video.status_code == 206
            assert video.content == b"2345"
            assert client.get("/files/platform/events.sqlite").status_code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert get_event(tmp_path, "story-one")["event"]["title"] == "Central bank announces rates"
    assert json.loads(path.read_text(encoding="utf-8")) == report


def test_daily_projection_never_fills_missing_saved_images_from_archive(tmp_path):
    report, path = _report(tmp_path)
    report["sections"][0]["briefs"] = [
        {"item_id": "article-one", "title": "Central bank announces rates"}
    ]
    write_json(path, report)
    stock = "https://news.example/headerimage/generated-stock.jpg"
    sync_monitor_snapshot(
        tmp_path,
        {
            "generated_at": report["generated_at"],
            "sources": [],
            "items": [
                {
                    "item_id": "article-one",
                    "title": "Central bank announces rates",
                    "url": "https://news.example/rates",
                    "canonical_url": "https://news.example/rates",
                    "published_at": report["generated_at"],
                    "source_id": "example",
                    "module": "information",
                    "category": "international",
                    "image_url": stock,
                }
            ],
            "clusters": [{"story_id": "story-one", "item_ids": ["article-one"]}],
        },
    )
    selected = read_edition(tmp_path)
    assert selected["report"]["sections"][0]["briefs"][0]["image_url"] is None
    assert selected["report"]["sections"][0]["items"][0]["image_url"] is None
    assert selected["events"][0]["image_url"] is None
    assert (
        read_edition_event(tmp_path, report["report_id"], "EVT-one")["event"]["image_url"] is None
    )
    assert get_event(tmp_path, "story-one")["event"]["image_url"] == stock
    assert json.loads(path.read_text(encoding="utf-8")) == report
