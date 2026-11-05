from collections import Counter
from datetime import UTC, datetime

import pytest

from signaltrail.authoring import _analysis_candidates
from signaltrail.collector import collect_sources
from signaltrail.config import AppConfig, BrowserConfig, SourceConfig, load_config
from signaltrail.context import build_context
from signaltrail.discovery_selection import _domain, select_discovery_items
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


def test_shared_pool_covers_domains_and_caps_each_source_at_two():
    sources = [_source(f"{domain}{number}", domain)
               for domain, count in (("international", 8), ("markets", 3), ("technology", 6))
               for number in range(count)]
    results = {source.id: _result(source, [_item(source, n) for n in range(1, 5)])
               for source in sources}
    selected = select_discovery_items(results, sources, [], limit=30, start=_START, end=_END)
    assert sum(map(len, selected.values())) == 30
    assert all(len(items) <= 2 for items in selected.values())
    counts = Counter(domain for domain in ("international", "markets", "technology")
                     for source in sources if source.id.startswith(domain)
                     for _ in selected.get(source.id, []))
    assert counts == {"international": 15, "markets": 6, "technology": 9}
    assert select_discovery_items(results, sources, [], limit=0, start=_START, end=_END) == {}


def test_domestic_news_does_not_fill_international_slots():
    domestic = _source("domestic", "international")
    domestic.category = "domestic"
    international = _source("world", "international")
    military = _source("military", "international")
    military.category = "military"
    sources = [domestic, international, military]
    results = {source.id: _result(source, [_item(source, 1)]) for source in sources}
    selected = select_discovery_items(results, sources, [], limit=30, start=_START, end=_END)
    assert set(selected) == {"world", "military"}
    assert selected["military"][0].category == "military"
    assert _domain(domestic) is None
    for category in ("market", "markets", "economy"):
        market = _source("finance", "markets")
        market.category = category
        assert _domain(market) == "markets"


def test_shared_pool_skips_core_duplicates_old_future_and_stale_items():
    source = _source("international", "international")
    core = _item(source, 1)
    candidates = [_item(source, n) for n in range(1, 10)]
    candidates[1].canonical_url = core.canonical_url
    candidates[2].title = core.title
    candidates[3].published_at = "2026-10-30T05:00:00+00:00"
    candidates[4].published_at = "2026-11-03T05:00:00+00:00"
    candidates[5].metadata["feed_stale"] = True
    candidates[6].metadata["retained_from_previous_snapshot"] = True
    candidates[7].published_at = None
    result = select_discovery_items(
        {source.id: _result(source, candidates)}, [source], [core],
        limit=30, start=_START, end=_END,
    )
    assert [item.item_id for item in result[source.id]] == ["international-3", "international-9"]


def test_old_paper_needs_observed_rank_signal_and_stays_watch():
    source = _source("papers", "technology")
    source.category = "papers"
    items = [_item(source, number) for number in range(1, 5)]
    for item in items:
        item.published_at = "2025-01-01"
    items[0].metadata.update(discovery_signal="bootstrap_watch", signal_at=_END.isoformat())
    items[1].metadata.update(discovery_signal="rank_rise", signal_at=_START.isoformat())
    items[2].metadata.update(discovery_signal="rank_rise", signal_at="2026-10-29")
    items[3].published_at = "2026-11-03"
    items[3].metadata.update(discovery_signal="new_listing", signal_at=_END.isoformat())
    selected = select_discovery_items(
        {source.id: _result(source, items)}, [source], [], limit=30, start=_START, end=_END,
    )[source.id]
    assert {item.item_id for item in selected} == {"papers-1", "papers-2"}
    assert all(item.metadata["suggested_status"] == "WATCH" for item in selected)
    assert all(item.published_at == "2025-01-01" for item in selected)


@pytest.mark.parametrize("limit,filtered", [(6, False), (0, False), (6, True)])
def test_collection_and_authoring_use_only_actual_shared_allocations(
    monkeypatch, tmp_path, limit, filtered,
):
    core = SourceConfig(id="core", name="Core", url="https://core.example/")
    sources = [_source(domain, domain) for domain in ("international", "markets", "technology")]
    config = AppConfig(
        timezone="Asia/Shanghai", browser=BrowserConfig(), sources=[core],
        monitor_sources=sources,
    )
    config.collection.discovery_brief_limit = limit
    results = {core.id: _result(core, [_item(core, n) for n in range(1, 16)])}
    results.update({source.id: _result(source, [_item(source, n) for n in range(1, 5)])
                    for source in sources})
    monkeypatch.setattr("signaltrail.collector.load_monitor_results", lambda *_args: results)
    index_path = collect_sources(
        config, tmp_path, "daily", False,
        only_source_ids={"core"} if filtered else None,
        profile_dir=tmp_path / "profile", date_value="2026-11-02",
        collection_window={"start": _START.isoformat(), "end": _END.isoformat()},
    )
    index = read_json(index_path)
    expected = 6 if limit and not filtered else 0
    assert len(index["items"]) == 15 + expected
    assert len([item for row in index["sources"] for item in row["items"]]) == 15 + expected
    assert index["source_policies"]["core"]["report_target"] == 15
    assert core.report_target == 15
    assert all(source.report_target == source.report_max == 0 for source in sources)
    allocated = {key: policy for key, policy in index["source_policies"].items()
                 if policy.get("selection_scope") == "discovery_shared"}
    assert sum(policy["report_target"] for policy in allocated.values()) == expected
    assert all(policy["report_target"] == policy["report_max"] <= 2
               for policy in allocated.values())
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


def test_shared_pool_config_defaults_and_rejects_invalid_limits(tmp_path):
    assert load_config().collection.discovery_brief_limit == 30
    path = tmp_path / "sources.yaml"
    path.write_text("collection:\n  discovery_brief_limit: -1\nsources: []\n", "utf-8")
    with pytest.raises(ValueError, match="discovery_brief_limit"):
        load_config(path)


def test_unselected_core_tail_does_not_exclude_discovery_brief(monkeypatch, tmp_path):
    core = SourceConfig(id="core", name="Core", url="https://core.example/",
                        report_target=1, report_max=1, max_items=2)
    discovery = _source("world", "international")
    config = AppConfig(timezone="Asia/Shanghai", browser=BrowserConfig(),
                       sources=[core], monitor_sources=[discovery])
    first, tail = [_item(core, n) for n in (1, 2)]
    duplicate = _item(discovery, 1)
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
        independent.item_id,
    ]
    assert {i["item_id"] for i in index["items"] if i["source_id"] == b.id} == {
        alias.item_id, refill.item_id,
    }
