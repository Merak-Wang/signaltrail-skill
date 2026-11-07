from datetime import UTC, datetime

import pytest

from signaltrail.authoring import _analysis_candidates
from signaltrail.collector import collect_sources
from signaltrail.config import AppConfig, BrowserConfig, SourceConfig
from signaltrail.context import build_context
from signaltrail.models import ArticleItem, SourceResult
from signaltrail.utils import read_json

_START = datetime(2026, 11, 1, 6, tzinfo=UTC)
_END = datetime(2026, 11, 2, 6, tzinfo=UTC)


def _source(source_id, domain):
    return SourceConfig(
        id=source_id, name=source_id, url=f"https://{source_id}.example/",
        report_target=0, report_max=0, role="discovery",
        module="technology" if domain == "technology" else "information",
        category="news" if domain == "technology" else (
            "market" if domain == "markets" else "international"
        ),
    )


def _item(source, number):
    return ArticleItem(
        item_id=f"{source.id}-{number}", source_id=source.id, source_name=source.name,
        title=f"Public policy research from {source.id} announces decision number {number}",
        url=f"{source.url}article/{number}", canonical_url=f"{source.url}article/{number}",
        discovered_at="2026-11-02T05:30:00+00:00", published_at="2026-11-02T05:00:00+00:00",
        module=source.module, category=source.category,
        description=f"Source {source.id} reports documented policy decision {number}.",
        metadata={"source_rank": number, "language": "en", "role": source.role},
    )


def _result(source, items):
    return SourceResult(
        source_id=source.id, source_name=source.name, source_url=source.url, status="success",
        collected_at="2026-11-02T05:30:00+00:00", module=source.module,
        category=source.category, items=items,
    )


@pytest.mark.parametrize("filtered", [False, True])
def test_collection_and_authoring_use_only_actual_shared_allocations(
    monkeypatch, tmp_path, filtered,
):
    core = SourceConfig(id="core", name="Core", url="https://core.example/")
    sources = [_source(domain, domain) for domain in ("international", "markets", "technology")]
    config = AppConfig(
        timezone="Asia/Shanghai", browser=BrowserConfig(), sources=[core],
        monitor_sources=sources,
    )
    results = {core.id: _result(core, [_item(core, n) for n in range(1, 16)])}
    results.update({source.id: _result(source, [_item(source, n) for n in range(1, 5)])
                    for source in sources})
    for source_result in results.values():
        for item in source_result.items:
            if item.metadata.get("role") == "discovery":
                item.metadata["content_source"] = {"published_at": item.published_at}
    monkeypatch.setattr("signaltrail.collector.load_monitor_results", lambda *_args: results)
    index_path = collect_sources(
        config, tmp_path, "daily", False,
        only_source_ids={"core"} if filtered else None,
        profile_dir=tmp_path / "profile", date_value="2026-11-02",
        collection_window={"start": _START.isoformat(), "end": _END.isoformat()},
    )
    index = read_json(index_path)
    expected = 0 if filtered else 12
    assert len(index["items"]) == 15 + expected
    assert len([item for row in index["sources"] for item in row["items"]]) == 15 + expected
    assert index["source_policies"]["core"]["report_target"] == 15
    assert core.report_target == 15
    assert all(source.report_target == source.report_max == 0 for source in sources)
    allocated = {key: policy for key, policy in index["source_policies"].items()
                 if key != "core"}
    assert sum(policy["report_target"] for policy in allocated.values()) == expected
    assert all(policy["selection_scope"] == "all_today" for policy in allocated.values())
    context = read_json(build_context(index_path, config, tmp_path, "daily"))
    plans = {row["source_id"]: row for row in context["brief_plan"]}
    assert plans["core"]["target_count"] == 15
    assert sum(row["target_count"] for key, row in plans.items() if key != "core") == expected
    assert all(plans[key]["target_count"] == policy["report_target"]
               for key, policy in allocated.items())
    if expected:
        sections = [{"id": "information.international", "briefs": [
            {"item_id": item["item_id"], "title": item["title"], "tldr": item["description"],
             "importance": 80, "status": "NEW"}
            for item in index["items"] if item["source_id"] != "core"
        ]}]
        candidates = _analysis_candidates(sections, context, 18)
        assert {row["source_id"] for row in candidates} == set(allocated)


def test_unselected_core_tail_does_not_exclude_discovery_brief(monkeypatch, tmp_path):
    core = SourceConfig(id="core", name="Core", url="https://core.example/",
                        report_target=1, report_max=1, max_items=2)
    discovery = _source("world", "international")
    config = AppConfig(timezone="Asia/Shanghai", browser=BrowserConfig(),
                       sources=[core], monitor_sources=[discovery])
    first, tail = [_item(core, n) for n in (1, 2)]
    duplicate = _item(discovery, 1)
    duplicate.metadata["content_source"] = {"published_at": duplicate.published_at}
    duplicate.title = tail.title
    duplicate.canonical_url = tail.canonical_url
    results = {core.id: _result(core, [first, tail]),
               discovery.id: _result(discovery, [duplicate])}
    monkeypatch.setattr("signaltrail.collector.load_monitor_results", lambda *args: results)
    path = collect_sources(config, tmp_path, "daily", False,
                           profile_dir=tmp_path / "profile", date_value="2026-11-02",
                           collection_window={"start": _START.isoformat(),
                                              "end": _END.isoformat()})
    index = read_json(path)
    assert index["source_policies"][discovery.id]["report_target"] == 1
    assert duplicate.item_id in {item["item_id"] for item in index["items"]}


def test_discovery_dedup_uses_unique_core_refill_not_unused_alias(monkeypatch, tmp_path):
    a = SourceConfig(id="core-a", name="A", url="https://a.example/",
                     report_target=1, report_max=1, max_items=2)
    b = SourceConfig(id="core-b", name="B", url="https://b.example/",
                     report_target=1, report_max=1, max_items=2)
    discovery = _source("world", "international")
    first = _item(a, 1)
    alias, refill = [_item(b, n) for n in (1, 2)]
    alias.canonical_url = first.canonical_url
    duplicate, independent = [_item(discovery, n) for n in (1, 2)]
    for item in (duplicate, independent):
        item.metadata["content_source"] = {"published_at": item.published_at}
    duplicate.canonical_url = refill.canonical_url
    independent.title = alias.title
    config = AppConfig(timezone="Asia/Shanghai", browser=BrowserConfig(),
                       sources=[a, b], monitor_sources=[discovery])
    results = {a.id: _result(a, [first]), b.id: _result(b, [alias, refill]),
               discovery.id: _result(discovery, [duplicate, independent])}
    monkeypatch.setattr("signaltrail.collector.load_monitor_results", lambda *args: results)
    path = collect_sources(config, tmp_path, "daily", False,
                           profile_dir=tmp_path / "profile", date_value="2026-11-02",
                           collection_window={"start": _START.isoformat(),
                                              "end": _END.isoformat()})
    index = read_json(path)
    assert [i["item_id"] for i in index["items"] if i["source_id"] == discovery.id] == [
        duplicate.item_id, independent.item_id,
    ]
    assert {i["item_id"] for i in index["items"] if i["source_id"] == b.id} == {
        alias.item_id, refill.item_id,
    }
