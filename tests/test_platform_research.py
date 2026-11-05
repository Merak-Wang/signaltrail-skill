import json
import sys
import time
from pathlib import Path

import pytest

from signaltrail.config import AppConfig, BrowserConfig
from signaltrail.events import get_event, save_event_research, set_follow, sync_monitor_snapshot
from signaltrail.platform_research import ResearchService


def _event(tmp_path, *, item_id="article-one", title="Company releases research model", body=None):
    path = tmp_path / f"{item_id}.md"
    path.write_text(body or "A company released a research model under an open license.", "utf-8")
    item = {
        "item_id": item_id, "source_id": "example", "source_name": "Example",
        "title": title, "url": f"https://example.com/{item_id}",
        "category": "news", "published_at": "2026-11-02T01:00:00Z",
        "content_status": "full_text", "content_path": str(path), "metadata": {},
    }
    sync_monitor_snapshot(tmp_path, {
        "generated_at": "2026-11-02T02:00:00Z", "items": [item], "sources": [],
        "clusters": [{"story_id": "event-one", "title": title, "category": "news",
                      "module": "technology", "item_ids": [item_id], "importance": 80}],
    })
    return item


def _service(tmp_path, command=None):
    config = AppConfig(timezone="Asia/Shanghai", browser=BrowserConfig(), sources=[])
    return ResearchService(config, tmp_path, worker_command=[] if command is None else command)


def _wait(service, job):
    until = time.monotonic() + 10
    while time.monotonic() < until:
        result = service.get(job["job_id"])
        if result["status"] in {"completed", "failed", "awaiting_model"}:
            return result
        time.sleep(0.02)
    raise AssertionError("research did not finish")


def _result(item_id="article-one"):
    return {
        "summary": "The release changes how developers can use this model.",
        "analyses": [{
            "domain": "ai_technology", "title": "Open model release",
            "summary": "The model is available under an open license.",
            "body": "The published license determines which applications are permitted.",
            "conditions": ["The license applies to the released weights."],
            "counterargument": "The report contains no deployment comparison.",
            "watch": ["Track the published license terms."],
            "sources": [{"item_id": item_id, "url": "https://invented.example/fake"}],
        }],
    }


@pytest.mark.parametrize("language", ["zh-CN", "en"])
def test_external_host_packet_and_completion_keep_evidence_and_daily_index(tmp_path, language):
    _event(tmp_path, body="Original evidence. " * 1000)
    indexes = tmp_path / "indexes"
    indexes.mkdir()
    latest = indexes / "latest.json"
    latest.write_text('{"edition":"daily"}', "utf-8")
    service = _service(tmp_path)
    try:
        job = _wait(service, service.submit(
            "event-one", "What changed for developers?", language=language,
        ))
        assert job["status"] == "awaiting_model"
        packet = json.loads(Path(job["packet_path"]).read_text("utf-8"))
        assert packet["language"] == language
        assert ("以英语回答" if language == "en" else "以中文回答") in packet["instructions"]
        assert packet["evidence"][0]["truncated"] is True
        assert len(packet["evidence"][0]["text"]) == 8000
        assert packet["evidence"][0]["content_status"] == "full_text"
        duplicate = service.submit("event-one", "What changed for developers?", language=language)
        assert duplicate["job_id"] == job["job_id"]
        complete = service.complete(job["job_id"], _result())
        assert complete["status"] == "completed"
        assert complete["result"]["analyses"][0]["language"] == language
        assert complete["result"]["sources"][0]["url"] == "https://example.com/article-one"
        assert complete["result"]["usage"]["tokens"] is None
        assert get_event(tmp_path, "event-one")["analyses"][0]["domain"] == "ai_technology"
        assert latest.read_text("utf-8") == '{"edition":"daily"}'
    finally:
        service.close()


@pytest.mark.parametrize("location", ["analysis", "root"])
def test_unknown_references_are_rejected_for_external_results(tmp_path, location):
    _event(tmp_path)
    service = _service(tmp_path)
    try:
        job = _wait(service, service.submit("event-one", "Analyze this release"))
        result = _result("unknown" if location == "analysis" else "article-one")
        if location == "root":
            result["sources"] = [{"item_id": "unknown"}]
        with pytest.raises(ValueError, match="不属于冻结材料"):
            service.complete(job["job_id"], result)
        assert service.get(job["job_id"])["status"] == "awaiting_model"
    finally:
        service.close()


@pytest.mark.parametrize("outcome", ["stdout", "file", "invalid_reference", "exit_failure"])
def test_worker_process_result_and_failure_states(tmp_path, outcome):
    _event(tmp_path)
    result = _result("unknown" if outcome == "invalid_reference" else "article-one")
    if outcome == "exit_failure":
        script = "raise SystemExit(7)"
    elif outcome == "file":
        script = ("import sys,pathlib; pathlib.Path(sys.argv[1]).write_text("
                  + repr(json.dumps(result)) + ",encoding='utf8')")
    else:
        script = "print(" + repr(json.dumps(result)) + ")"
    service = _service(tmp_path, [sys.executable, "-c", script, "{output}"])
    try:
        job = _wait(service, service.submit("event-one", "Analyze this release"))
        assert job["status"] == (
            "failed" if outcome in {"invalid_reference", "exit_failure"} else "completed"
        )
        if outcome == "exit_failure":
            assert "7" in job["error"]
        if outcome == "invalid_reference":
            assert "不属于冻结材料" in job["error"]
    finally:
        service.close()


def test_queued_research_is_restored_from_existing_packet(tmp_path):
    _event(tmp_path)
    service = _service(tmp_path)
    try:
        job = _wait(service, service.submit("event-one", "Analyze this release"))
    finally:
        service.close()
    job["status"] = "running"
    save_event_research(tmp_path, "event-one", job)
    restored = _service(tmp_path)
    try:
        assert _wait(restored, job)["status"] == "awaiting_model"
    finally:
        restored.close()


@pytest.mark.parametrize("cooldown", ["0", "6"])
def test_followed_events_trigger_on_new_evidence_and_respect_cooldown(
    monkeypatch, tmp_path, cooldown,
):
    monkeypatch.setenv("SIGNALTRAIL_RESEARCH_COOLDOWN_HOURS", cooldown)
    _event(tmp_path)
    set_follow(tmp_path, "event", "event-one", True)
    service = _service(tmp_path)
    try:
        job = _wait(service, service.submit("event-one", "Analyze this release"))
        service.complete(job["job_id"], _result())
        _event(tmp_path, item_id="reposted")
        assert service.schedule_followed() == []
        _event(tmp_path, item_id="new-evidence", body="The company changed its licensing terms.")
        jobs = service.schedule_followed()
        assert len(jobs) == (1 if cooldown == "0" else 0)
        if jobs:
            assert _wait(service, jobs[0])["status"] == "awaiting_model"
    finally:
        service.close()


def test_same_url_changed_feed_invalidates_research_body_not_observation_time(tmp_path):
    item = _event(tmp_path)
    service = _service(tmp_path)
    try:
        before = service._fingerprint(get_event(tmp_path, "event-one"))
        refreshed = {**item, "content_status": "not_fetched", "content_path": None,
                     "discovered_at": "2026-11-02T04:00:00Z"}
        snapshot = {"generated_at": "2026-11-02T04:00:00Z", "items": [refreshed],
                    "sources": [], "clusters": [{"story_id": "event-one", "title": item["title"],
                    "module": "technology", "category": "news", "item_ids": [item["item_id"]]}]}
        sync_monitor_snapshot(tmp_path, snapshot)
        assert service._fingerprint(get_event(tmp_path, "event-one")) == before
        refreshed["description"] = "The license now restricts commercial use."
        sync_monitor_snapshot(tmp_path, snapshot)
        detail = get_event(tmp_path, "event-one")
        assert detail["articles"][0]["metadata"]["content_needs_refresh"] is True
        assert service._article_body(detail["articles"][0]) == ""
        assert service._fingerprint(detail) != before
        assert Path(item["content_path"]).is_file()
    finally:
        service.close()


def test_prepare_replaces_expired_full_body_with_new_partial_in_archive(tmp_path, monkeypatch):
    from signaltrail import content
    from signaltrail.config import SourceConfig
    from signaltrail.content_extraction import ExtractedDocument

    item = _event(tmp_path, body="Old complete body.")
    updated = {**item, "content_path": None, "content_status": "not_fetched",
               "description": "New report stage with changed material."}
    sync_monitor_snapshot(tmp_path, {
        "generated_at": "2026-11-02T04:00:00Z", "items": [updated], "sources": [],
        "clusters": [{"story_id": "event-one", "title": item["title"],
                      "module": "technology", "category": "news", "item_ids": [item["item_id"]]}],
    })
    service = _service(tmp_path)
    source = SourceConfig(id="example", name="Example", url="https://example.com")
    service.config.sources = [source]
    calls = []

    async def fetch(targets, config, data_dir):
        calls.extend(target["item_id"] for target in targets)
        for target in targets:
            content._save_document(target, ExtractedDocument(
                text="New partial evidence with qualifications.", status="partial",
                blocks=[{"type": "paragraph", "text": "New partial evidence with qualifications."}],
                quality={"region": "specific"},
            ), source, config, data_dir)
        return []

    monkeypatch.setattr(content, "_run_http_extraction", fetch)
    try:
        packet = service._prepare({"event_id": "event-one", "question": "What changed?",
                                   "domain": None})
        assert calls == [item["item_id"]]
        article = get_event(tmp_path, "event-one")["articles"][0]
        assert article["content_status"] == "partial"
        assert article["metadata"]["content_needs_refresh"] is False
        assert service._article_body(article) == "New partial evidence with qualifications."
        assert packet["evidence"][0]["text"] == "New partial evidence with qualifications."
        assert "Old complete" not in packet["evidence"][0]["text"]
    finally:
        service.close()
