from copy import deepcopy
from datetime import UTC, datetime

from signaltrail.article_time import in_window, normalize_time, observe_items


def test_source_dates_preserve_precision_and_frozen_window_overlap():
    assert normalize_time("2026/11/02") == "2026-11-02"
    assert normalize_time("Mon, 02 Nov 2026 06:00:00 GMT") == "2026-11-02T06:00:00+00:00"
    assert normalize_time("2026-11-02 06:00:00", "Asia/Shanghai") == "2026-11-02T06:00:00+08:00"
    start, end = datetime(2026, 11, 1, 6, tzinfo=UTC), datetime(2026, 11, 2, 6, tzinfo=UTC)
    assert in_window("2026/11/02", start, end)
    assert not in_window("2026/11/03", start, end)
    assert not in_window(None, start, end)


def test_rank_observation_keeps_first_seen_and_signal_until_real_change():
    item = {"item_id": "paper", "category": "papers", "discovered_at": "2026-11-01T06:00:00+00:00",
            "published_at": "2025-01-01", "metadata": {"role": "discovery", "source_rank": 10}}
    observe_items({}, [item], item["discovered_at"])
    assert item["metadata"]["discovery_signal"] == "bootstrap_watch"
    previous = {"generated_at": item["discovered_at"], "items": [deepcopy(item)]}
    item["discovered_at"] = "2026-11-02T06:00:00+00:00"
    observe_items(previous, [item], item["discovered_at"])
    assert item["metadata"]["first_discovered_at"] == "2026-11-01T06:00:00+00:00"
    assert item["metadata"]["signal_at"] == "2026-11-01T06:00:00+00:00"
    item["metadata"]["source_rank"] = 2
    observe_items(previous, [item], item["discovered_at"])
    assert item["metadata"]["discovery_signal"] == "rank_rise"
    assert item["metadata"]["signal_at"] == item["discovered_at"]


def test_reappearance_requires_successful_previous_listing_check():
    item = {"item_id": "paper", "source_id": "feed", "category": "papers",
            "discovered_at": "2026-11-02T06:00:00+00:00",
            "metadata": {"role": "discovery", "source_rank": 1}}
    old = deepcopy(item)
    old["metadata"].update(retained_from_previous_snapshot=True)
    previous = {"items": [old], "sources": [{"source_id": "feed", "status": "failed"}]}
    observe_items(previous, [item], item["discovered_at"])
    assert "discovery_signal" not in item["metadata"]
    previous["sources"][0]["status"] = "success"
    observe_items(previous, [item], item["discovered_at"])
    assert item["metadata"]["discovery_signal"] == "reappeared"
    newly_listed = deepcopy(item)
    newly_listed["item_id"] = "new-paper"
    observe_items(previous, [newly_listed], item["discovered_at"])
    assert newly_listed["metadata"]["discovery_signal"] == "new_listing"


def test_url_alias_keeps_first_seen_and_collector_preserves_monitor_signal():
    old = {"item_id": "a", "source_id": "a", "url": "https://example.org/paper?utm_source=a",
           "discovered_at": "2026-11-01T06:00:00+00:00", "metadata": {}}
    current = {"item_id": "b", "source_id": "b", "url": "https://example.org/paper",
               "category": "papers", "discovered_at": "2026-11-02T06:00:00+00:00",
               "metadata": {"role": "discovery", "source_rank": 1,
                            "discovery_signal": "rank_rise",
                            "signal_at": "2026-11-02T05:00:00+00:00"}}
    observe_items({"items": [old]}, [current], current["discovered_at"], preserve_signals=True)
    assert current["metadata"]["first_discovered_at"] == old["discovered_at"]
    assert current["metadata"]["discovery_signal"] == "rank_rise"
    assert current["metadata"]["signal_at"] == "2026-11-02T05:00:00+00:00"
