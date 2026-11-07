"""采集材料回收范围与失败保留行为。"""

import json
import os
from datetime import UTC, datetime, timedelta

import pytest

from signaltrail import retention


def _old_file(path, value="evidence"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    old = (datetime.now(UTC) - timedelta(days=9)).timestamp()
    os.utime(path, (old, old))
    return path


def test_cleanup_protects_active_evidence_and_retains_report_and_media(tmp_path, monkeypatch):
    active = _old_file(tmp_path / "content/source/active/body.md")
    index = _old_file(tmp_path / "indexes/old/daily-r1.json", json.dumps({
        "items": [{"content_path": str(active)}]}))
    _old_file(tmp_path / "runs/old/daily.json", json.dumps({
        "status": "awaiting_authoring", "artifacts": {"index_path": str(index)}}))
    disposable = _old_file(tmp_path / "content/source/expired/body.md")
    report = _old_file(tmp_path / "reports/old/daily-r1.html")
    media = _old_file(tmp_path / "media/shared.jpg")
    recent = tmp_path / "content/source/recent.md"
    recent.write_text("current", encoding="utf-8")
    seen = []
    monkeypatch.setattr(retention, "_recycle", lambda path: seen.append(path))
    preview = retention.cleanup_collection(tmp_path)
    assert seen == [] and preview["dry_run"]
    assert preview["candidate_paths"] == [str(disposable.parent)]
    result = retention.cleanup_collection(tmp_path, apply=True)
    assert seen == [disposable.parent] and result["recycled_count"] == 1
    assert all(path.exists() for path in (active, index, report, media, recent))


def test_cleanup_failure_keeps_file_and_reports_reason(tmp_path, monkeypatch):
    old = _old_file(tmp_path / "monitor/snapshot.json", "{}")

    def fail(path):
        raise OSError("Recycle bin unavailable")

    monkeypatch.setattr(retention, "_recycle", fail)
    result = retention.cleanup_collection(tmp_path, apply=True)
    assert result["recycled_count"] == 0 and old.exists()
    assert result["failures"] == [{"path": str(old), "reason": "OSError: Recycle bin unavailable"}]


def test_saved_report_with_pending_delivery_keeps_collection(tmp_path):
    index = _old_file(tmp_path / "indexes/old/daily-r1.json", "{}")
    run = _old_file(tmp_path / "runs/old/daily.json", json.dumps({
        "status": "completed_partial", "tail": {"status": "pending"},
        "artifacts": {"index_path": str(index)}}))
    assert retention.cleanup_collection(tmp_path)["candidate_count"] == 0
    run.write_text(json.dumps({"status": "completed", "tail": {"status": "completed"},
                              "artifacts": {"index_path": str(index),
                                            "slides": {"status": "review_required"}}}),
                   encoding="utf-8")
    assert retention.cleanup_collection(tmp_path)["candidate_count"] == 0
    run.write_text(json.dumps({"status": "completed", "tail": {"status": "completed"},
                              "artifacts": {"index_path": str(index),
                                            "slides": {"status": "rendered"}}}), encoding="utf-8")
    assert retention.cleanup_collection(tmp_path)["candidate_count"] == 1


@pytest.mark.parametrize("recycle_fails", [False, True])
def test_unused_old_images_recycle_without_breaking_reports_narration_or_active_run(
    tmp_path, monkeypatch, recycle_fails,
):
    files = {name: _old_file(tmp_path / f"media/images/{name}.jpg")
             for name in ("report", "narration", "active", "orphan")}
    _old_file(tmp_path / "reports/old/daily-r1.json", json.dumps({
        "image": {"local_path": "media/images/report.jpg"},
        "title": "media/images/orphan.jpg",
    }))
    _old_file(tmp_path / "narratives/slides/slides-deck-r1.json", json.dumps({
        "slides": [{"images": [{"local_path": "media/images/narration.jpg"}]}],
    }))
    _old_file(tmp_path / "runs/old/daily.json", json.dumps({
        "status": "awaiting_authoring", "image": {"local_path": "media/images/active.jpg"},
    }))
    recent = tmp_path / "media/images/recent.jpg"
    recent.write_text("recent", encoding="utf-8")
    cache_path = tmp_path / "media/image-cache.json"
    cache_path.write_text(json.dumps({"entries": {
        "https://example.com/" + name: {"status": "success",
                                      "local_path": path.relative_to(tmp_path).as_posix()}
        for name, path in files.items()
    }}), encoding="utf-8")
    recycled = tmp_path / "recycled"
    recycled.mkdir()

    def recycle(path):
        if recycle_fails:
            raise OSError("Recycle bin unavailable")
        path.rename(recycled / path.name)

    monkeypatch.setattr(retention, "_recycle", recycle)
    preview = retention.cleanup_collection(tmp_path)
    assert preview["candidate_paths"] == [str(files["orphan"])]
    assert cache_path.read_text(encoding="utf-8").count("https://example.com/") == 4
    result = retention.cleanup_collection(tmp_path, apply=True)
    assert all(files[name].is_file() for name in ("report", "narration", "active"))
    assert recent.is_file()
    entries = json.loads(cache_path.read_text(encoding="utf-8"))["entries"]
    assert files["orphan"].exists() == recycle_fails
    assert ("https://example.com/orphan" in entries) == recycle_fails
    assert result["image_cache_entries_removed"] == (0 if recycle_fails else 1)
