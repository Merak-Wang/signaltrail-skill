import copy
import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from signaltrail.dashboard import create_monitor_server
from signaltrail.events import (
    get_event,
    get_research_job,
    list_events,
    list_research_jobs,
    save_event_research,
    set_follow,
    sync_monitor_snapshot,
    update_event_articles,
)


def _snapshot(
    item_id="one",
    url="https://example.com/one",
    story_id="story-one",
    title="Company launches new research model",
    day=1,
):
    timestamp = f"2026-11-{day:02d}T10:00:00+00:00"
    return {
        "generated_at": timestamp,
        "sources": [{"source_id": "example", "source_name": "Example"}],
        "items": [
            {
                "item_id": item_id,
                "url": url,
                "title": title,
                "published_at": timestamp,
                "discovered_at": timestamp,
                "source_id": "example",
                "category": "technology",
                "description": "Article description",
            }
        ],
        "clusters": [
            {
                "story_id": story_id,
                "title": title,
                "category": "technology",
                "module": "technology",
                "importance": 75,
                "item_ids": [item_id],
                "published_at": timestamp,
            }
        ],
    }


def test_event_retains_history_deduplicates_urls_and_preserves_research(tmp_path):
    sync_monitor_snapshot(tmp_path, _snapshot())
    save_event_research(tmp_path, "story-one", {"id": "research-one", "status": "complete"})
    sync_monitor_snapshot(tmp_path, _snapshot("new-id", story_id="story-new"))
    detail = get_event(tmp_path, "story-one")
    assert detail["event"]["article_count"] == 1
    assert detail["articles"][0]["item_ids"] == ["new-id", "one"]
    assert detail["research"][0]["id"] == "research-one"
    sync_monitor_snapshot(
        tmp_path,
        _snapshot("two", "https://example.com/two", "story-other", "Unrelated election result", 2),
    )
    assert len(list_events(tmp_path)["events"]) == 2
    assert get_event(tmp_path, "story-one")["articles"][0]["url"] == "https://example.com/one"


def test_event_sync_reuses_monitor_groups_and_does_not_mutate_snapshot(monkeypatch, tmp_path):
    snapshot = _snapshot()
    second = _snapshot("two", "https://example.com/two", title="Unrelated election results")
    snapshot["items"].extend(second["items"])
    snapshot["clusters"][0]["item_ids"].append("two")
    snapshot["items"][0]["metadata"] = {"story_id": "story-one", "story_phase": "updated"}
    original = copy.deepcopy(snapshot)

    def unexpected_cluster(*args, **kwargs):
        raise AssertionError("Complete monitor groups must be reused")

    monkeypatch.setattr("signaltrail.events.cluster_articles", unexpected_cluster)
    sync_monitor_snapshot(tmp_path, snapshot)
    assert snapshot == original
    detail = get_event(tmp_path, "story-one")
    assert detail["event"]["article_count"] == 2
    assert detail["articles"][0].get("metadata", {}) == original["items"][0]["metadata"]


def test_event_sync_reclusters_only_filtered_and_uncovered_groups(monkeypatch, tmp_path):
    from signaltrail.clustering import cluster_articles

    snapshot = _snapshot()
    second = _snapshot("two", "https://example.com/two", title="Scientists study seabird flights")
    navigation = _snapshot("nav", "https://example.com/nav", title="overlay link")
    snapshot["items"].extend(second["items"] + navigation["items"])
    snapshot["clusters"].extend(navigation["clusters"])
    snapshot["clusters"][1]["item_ids"].append("two")
    original = copy.deepcopy(snapshot)
    calls = []

    def recorded_cluster(items, generated_at):
        calls.append([item["item_id"] for item in items])
        return cluster_articles(items, generated_at)

    monkeypatch.setattr("signaltrail.events.cluster_articles", recorded_cluster)
    sync_monitor_snapshot(tmp_path, snapshot)
    assert calls == [["two"]]
    assert snapshot == original
    assert list_events(tmp_path)["total"] == 2


def test_explicit_snapshot_does_not_mark_another_disk_snapshot_as_synced(tmp_path):
    path = tmp_path / "monitor" / "snapshot.json"
    path.parent.mkdir()
    disk = _snapshot("two", "https://example.com/two", "story-two",
                     "Scientists study seabird flights")
    path.write_text(json.dumps(disk), encoding="utf-8")
    supplied = _snapshot()
    sync_monitor_snapshot(tmp_path, supplied)
    sync_monitor_snapshot(tmp_path, supplied)
    assert list_events(tmp_path)["total"] == 2


def test_title_continuation_and_follow_filters(tmp_path):
    sync_monitor_snapshot(tmp_path, _snapshot())
    sync_monitor_snapshot(tmp_path, _snapshot("two", "https://example.com/two", "story-two"))
    assert list_events(tmp_path)["total"] == 1
    assert get_event(tmp_path, "story-one")["event"]["article_count"] == 2
    set_follow(tmp_path, "source", "example", True)
    assert list_events(tmp_path, following=True)["total"] == 1
    set_follow(tmp_path, "source", "example", False)
    assert list_events(tmp_path, following=True)["total"] == 0


def test_event_http_routes_and_cross_origin_write_rejected(tmp_path):
    sync_monitor_snapshot(tmp_path, _snapshot())
    job = {"job_id": "job-one", "status": "queued"}
    research = Mock()
    research.submit.return_value = job
    research.get.return_value = job
    server = create_monitor_server(tmp_path, port=0, quiet=True, research_service=research)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        with httpx.Client(base_url=f"http://{host}:{port}") as client:
            assert client.get("/api/events").json()["total"] == 1
            assert client.get("/api/events/story-one").json()["event"]["title"]
            assert client.get("/events/story-one").status_code == 200
            payload = {"kind": "event", "target": "story-one", "following": True}
            for _ in range(30):
                response = client.post(
                    "/api/follows", json=payload, headers={"Origin": "https://other.example"}
                )
                assert response.status_code == 403
                assert response.json()["error"] == "origin_not_allowed"
            assert client.get("/api/follows").json()["events"] == []
            assert client.post("/api/follows", json=payload).json()["events"] == ["story-one"]
            assert client.get("/api/events?following=1").json()["total"] == 1
            response = client.post(
                "/api/events/story-one/research", json={"question": "What changed?"}
            )
            assert response.status_code == 202
            assert response.json()["job"] == job
            assert client.get("/api/research/job-one").json()["job"] == job
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    research.close.assert_called_once()


@pytest.mark.parametrize("headers,length", [
    ({"Content-Length": "8192"}, 8192),
    ({"Content-Length": "8193"}, None),
    ({"Content-Length": "-1"}, None),
    ({"Content-Length": "invalid"}, None),
    ({"Content-Length": "20", "Transfer-Encoding": "chunked"}, None),
])
def test_cross_origin_rejection_discards_only_bounded_short_bodies(tmp_path, headers, length):
    from signaltrail.dashboard import _handler_factory

    handler_type = _handler_factory(tmp_path, tmp_path, quiet=True)
    connection = Mock()
    connection.gettimeout.return_value = None
    handler = SimpleNamespace(headers=headers, connection=connection, rfile=Mock())
    handler_type._discard_short_body(handler)
    if length is None:
        handler.rfile.read.assert_not_called()
        connection.settimeout.assert_not_called()
    else:
        handler.rfile.read.assert_called_once_with(length)
        assert connection.settimeout.call_args_list[0].args == (0.25,)
        assert connection.settimeout.call_args_list[-1].args == (None,)


def test_report_analysis_only_matches_its_evidence_and_jobs_upsert(tmp_path):
    sync_monitor_snapshot(tmp_path, _snapshot())
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "daily-r1.json").write_text(
        json.dumps(
            {
                "report_id": "daily-r1",
                "sections": [
                    {
                        "items": [
                            {
                                "event_id": "report-event",
                                "source_refs": [{"item_id": "one"}],
                            }
                        ]
                    }
                ],
                "analyses": [
                    {
                        "domain": "markets",
                        "claim": "Related",
                        "evidence_event_ids": ["report-event"],
                    },
                    {
                        "domain": "geopolitics",
                        "claim": "Unrelated",
                        "evidence_event_ids": ["other"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    assert [row["claim"] for row in get_event(tmp_path, "story-one")["analyses"]] == ["Related"]
    save_event_research(tmp_path, "story-one", {"job_id": "job-one", "status": "queued"})
    save_event_research(tmp_path, "story-one", {"job_id": "job-one", "status": "awaiting_model"})
    assert len(get_event(tmp_path, "story-one")["research"]) == 1
    assert get_research_job(tmp_path, "job-one")["status"] == "awaiting_model"
    assert len(list_research_jobs(tmp_path, "awaiting_model")) == 1
    assert list_events(tmp_path, limit=1, offset=1)["events"] == []


def test_navigation_future_dates_and_unknown_refresh_do_not_take_over_feed(tmp_path):
    navigation = _snapshot(title="overlay link")
    sync_monitor_snapshot(tmp_path, navigation)
    assert list_events(tmp_path)["total"] == 0
    current = _snapshot()
    current["items"][0]["module"] = "technology"
    current["items"][0]["category"] = "news"
    current["clusters"][0]["category"] = "news"
    sync_monitor_snapshot(tmp_path, current)
    future = _snapshot(
        "two", "https://example.com/two", "story-two", "Company plans a separate public forum"
    )
    future["items"][0]["published_at"] = "2099-11-05"
    future["items"][0]["discovered_at"] = "2026-11-02T10:00:00+00:00"
    sync_monitor_snapshot(tmp_path, future)
    assert list_events(tmp_path)["events"][0]["event_id"] == "story-one"
    assert get_event(tmp_path, "story-two")["articles"][0]["published_at"] == "2099-11-05"
    assert list_events(tmp_path, category="technology")["total"] == 2
    update_event_articles(
        tmp_path,
        "story-one",
        [{**current["items"][0], "content_path": "body.md", "body": "Full article"}],
    )
    current["generated_at"] = "2026-11-02T11:00:00+00:00"
    current["items"][0]["content_path"] = None
    sync_monitor_snapshot(tmp_path, current)
    assert get_event(tmp_path, "story-one")["articles"][0]["body"] == "Full article"


def test_later_shared_evidence_merges_archives_and_keeps_old_links(tmp_path):
    first = _snapshot()
    second = _snapshot(
        "two", "https://example.com/two", "story-two", "Scientists study distant seabird flights", 2
    )
    sync_monitor_snapshot(tmp_path, first)
    sync_monitor_snapshot(tmp_path, second)
    set_follow(tmp_path, "event", "story-two", True)
    save_event_research(tmp_path, "story-two", {"job_id": "job-two", "status": "awaiting_model"})
    second["items"][0]["title"] = first["items"][0]["title"]
    combined = {**second, "items": first["items"] + second["items"], "clusters": []}
    sync_monitor_snapshot(tmp_path, combined)
    assert list_events(tmp_path)["total"] == 1
    assert get_event(tmp_path, "story-two")["event"]["event_id"] == "story-one"
    assert list_events(tmp_path, following=True)["total"] == 1
    save_event_research(tmp_path, "story-two", {"job_id": "job-two", "status": "failed"})
    assert get_research_job(tmp_path, "job-two")["event_id"] == "story-one"
