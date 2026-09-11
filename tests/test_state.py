from copy import deepcopy
from pathlib import Path

import pytest

from daily_intelligence.authoring import _project_analysis_state
from daily_intelligence.state import thesis_identity, update_continuity_state
from daily_intelligence.storage import exclusive_lock
from daily_intelligence.utils import read_json
from tests.report_helpers import load_sample_report


def _report():
    report = load_sample_report(Path(__file__).resolve().parents[1])
    report["quality_evaluation"] = {"exclude_from_continuity": []}
    return report


def _rows(path, name):
    return read_json(path / "state" / f"{name}.json")["items"]


def _next_report(report):
    changed = deepcopy(report)
    changed["generated_at"] = "2026-07-13T18:00:00+08:00"
    changed["date"] = "2026-07-13"
    changed["report_id"] += "-next"
    return changed


def test_same_domain_distinct_theses_keep_history_and_watchers(tmp_path):
    report = _report()
    update_continuity_state(report, tmp_path)
    first = deepcopy(_rows(tmp_path, "theses")[0])
    first_watches = deepcopy(_rows(tmp_path, "watchlist"))
    changed = _next_report(report)
    changed["analyses"][0]["claim"] = "机器人部署进入新的工厂自动化阶段。"
    changed["analyses"][0]["evidence_event_ids"] = ["EVENT-ROBOTICS"]
    changed["analyses"][0]["watch_signals"] = ["观察工厂部署数量。"]
    update_continuity_state(changed, tmp_path)
    theses = _rows(tmp_path, "theses")
    assert len(theses) == 2
    assert next(row for row in theses if row["thesis_id"] == first["thesis_id"]) == first
    assert len({row["analysis_id"] for row in theses}) == 1
    assert len({row["thesis_id"] for row in theses}) == 2
    watches = _rows(tmp_path, "watchlist")
    assert all(watch in watches for watch in first_watches)
    assert all(watch["status"] == "active" for watch in watches)
    assert _rows(tmp_path, "analysis-domains")[0]["claim"] == changed["analyses"][0]["claim"]


def test_omitted_watch_is_not_closed_and_formatting_does_not_duplicate_it(tmp_path):
    report = _report()
    report["analyses"][0]["watch_signals"] = ["Track reactor output", "Observe commissioning date"]
    update_continuity_state(report, tmp_path)
    original = {row["watch_id"]: row for row in _rows(tmp_path, "watchlist")}
    changed = _next_report(report)
    changed["analyses"][0]["watch_signals"] = ["Track  reactor\noutput"]
    update_continuity_state(changed, tmp_path)
    watches = _rows(tmp_path, "watchlist")
    assert {row["watch_id"] for row in watches} == set(original)
    assert all(row["status"] == "active" for row in watches)
    assert all(
        row["first_seen_at"] == original[row["watch_id"]]["first_seen_at"] for row in watches
    )


def test_explicit_closure_only_affects_matching_thesis_and_late_report_cannot_reopen(tmp_path):
    report = _report()
    update_continuity_state(report, tmp_path)
    first_id = thesis_identity(report["analyses"][0])
    other = _next_report(report)
    other["analyses"][0]["claim"] = "不同议题的独立判断。"
    update_continuity_state(other, tmp_path)
    closed = _next_report(report)
    closed["analyses"][0]["state_change"] = "closed"
    update_continuity_state(closed, tmp_path)
    update_continuity_state(report, tmp_path)
    theses = _rows(tmp_path, "theses")
    assert next(row for row in theses if row["thesis_id"] == first_id)["status"] == "closed"
    assert next(row for row in theses if row["thesis_id"] != first_id)["status"] == "active"
    watches = _rows(tmp_path, "watchlist")
    assert all(row["status"] == "closed" for row in watches if row["thesis_id"] == first_id)
    assert all(row["status"] == "active" for row in watches if row["thesis_id"] != first_id)


def test_repeated_state_update_preserves_identity_and_single_report_history(tmp_path):
    report = _report()
    update_continuity_state(report, tmp_path)
    expected = _rows(tmp_path, "theses")
    report["analyses"][0]["evidence_event_ids"].reverse()
    update_continuity_state(report, tmp_path)
    actual = _rows(tmp_path, "theses")
    assert actual[0]["thesis_id"] == expected[0]["thesis_id"]
    assert len(actual[0]["history"]) == 1


def test_excluded_analysis_does_not_close_or_replace_state(tmp_path):
    report = _report()
    update_continuity_state(report, tmp_path)
    expected = {name: _rows(tmp_path, name) for name in ("theses", "watchlist", "analysis-domains")}
    changed = _next_report(report)
    changed["quality_evaluation"]["exclude_from_continuity"] = ["analyses"]
    changed["analyses"][0]["state_change"] = "invalidated"
    update_continuity_state(changed, tmp_path)
    assert {name: _rows(tmp_path, name) for name in expected} == expected


def test_analysis_packet_preserves_thesis_identity_with_shared_domain(tmp_path):
    report = _report()
    update_continuity_state(report, tmp_path)
    changed = _next_report(report)
    changed["analyses"][0]["claim"] = "不同议题的独立判断。"
    update_continuity_state(changed, tmp_path)
    projection = _project_analysis_state({
        "active_theses": _rows(tmp_path, "theses"),
        "active_watchlist": _rows(tmp_path, "watchlist"),
    })
    ids = {row["thesis_id"] for row in projection["active_theses"]}
    assert len(ids) == 2
    assert {row["thesis_id"] for row in projection["active_watchlist"]} == ids


def test_shared_continuity_lock_rejects_parallel_updates_without_writing(tmp_path):
    with (
        exclusive_lock(tmp_path / "state" / ".continuity.lock", {}),
        pytest.raises(RuntimeError, match="Another run holds"),
    ):
        update_continuity_state(_report(), tmp_path)
    assert not (tmp_path / "state" / "theses.json").exists()
