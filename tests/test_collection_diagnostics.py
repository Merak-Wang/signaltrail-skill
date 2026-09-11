import copy
import hashlib
from dataclasses import replace
from pathlib import Path

from daily_intelligence.collection_diagnostics import (
    content_gaps,
    enrichment_plan,
    has_local_content,
    source_coverage,
)
from daily_intelligence.config import SourceConfig, load_config
from daily_intelligence.context import build_context
from daily_intelligence.utils import read_json, write_json


def test_cache_checks_hashes_and_data_root_but_reads_legacy_files(tmp_path):
    body = tmp_path / "body.md"
    body.write_text("Article evidence", encoding="utf-8")
    item = {"content_status": "full_text", "content_path": "body.md"}
    assert has_local_content(item, tmp_path)
    item["metadata"] = {"content_artifacts": {
        "markdown_sha256": hashlib.sha256(body.read_bytes()).hexdigest(),
    }}
    assert has_local_content(item, tmp_path)
    body.write_text("Modified evidence", encoding="utf-8")
    assert not has_local_content(item, tmp_path)
    assert "missing_content_artifact" in content_gaps(item, tmp_path)
    item["content_path"] = str(tmp_path.parent / "outside.md")
    assert not has_local_content(item, tmp_path)


def test_structured_hash_cannot_point_outside_data_root(tmp_path):
    (tmp_path / "body.md").write_text("Text", encoding="utf-8")
    item = {"content_status": "full_text", "content_path": "body.md", "metadata": {
        "content_blocks_path": "../outside.json",
        "content_artifacts": {"blocks_sha256": "0" * 64},
    }}
    assert not has_local_content(item, tmp_path)


def test_plan_is_bounded_balanced_and_keeps_access_failures_explicit(tmp_path):
    sources = [SourceConfig(id=name, name=name, url=f"https://{name}.example") for name in "ab"]
    items = [{"item_id": f"{name}{i}", "source_id": name} for name in "ab" for i in range(5)]
    items.extend([
        {"item_id": "blocked", "source_id": "a", "content_status": "verification_required"},
        {"item_id": "limited", "source_id": "b", "content_status": "verification_required",
         "metadata": {"content_http_status": 429}},
    ])
    before = copy.deepcopy(items)
    plan = enrichment_plan(items, sources, tmp_path, 3)
    assert [action["item_id"] for action in plan["actions"]] == ["a0", "b0", "a1"]
    assert plan["deferred_count"] == 7
    assert plan["blocked_counts"] == {"verification_required": 1, "rate_limited": 1}
    assert plan["claim_sufficiency"] == "not_assessed"
    assert all(action["event_id"] is None for action in plan["actions"])
    assert all(action["cost_bound"]["model_calls"] == 0 for action in plan["actions"])
    assert items == before


def test_coverage_uses_root_current_items_and_does_not_invent_independence():
    a = SourceConfig(id="a", name="A", url="https://a.example", region="Asia", role="primary")
    b = replace(a, id="b", language="zh-CN")
    c = replace(a, id="c", region="Europe")
    d = replace(a, id="d", region="Africa")
    index = {
        "sources": [
            {"source_id": "a", "status": "success", "items": [{"item_id": "nested-only"}]},
            {"source_id": "b", "status": "rate_limited"},
            {"source_id": "c", "status": "failed"},
        ],
        "items": [
            {"item_id": "current", "source_id": "a"},
            {"item_id": "current", "source_id": "a"},
            {"item_id": "old", "source_id": "b",
             "metadata": {"retained_from_previous_snapshot": True}},
        ],
    }
    coverage = source_coverage(index, [a, b, c, d])
    asia, europe, africa = coverage["cells"]
    assert asia["item_count"] == 1
    assert asia["status"] == "partial"
    assert asia["source_statuses"]["b"] == "rate_limited"
    assert asia["languages"] == ["en", "zh-CN"]
    assert europe["source_statuses"] == {"c": "failed"}
    assert africa["source_statuses"] == {"d": "not_collected"}
    assert coverage["independent_corroboration"] == "not_assessed"


def test_context_exposes_gap_plan_without_reordering_or_expanding_candidates(tmp_path):
    config = load_config()
    config.sources = config.sources[:1]
    source = config.sources[0]
    index = {"date": "2026-09-11", "edition": "morning", "items": [
        {"item_id": f"id-{i}", "source_id": source.id, "title": f"Title {i}"}
        for i in range(30)
    ], "sources": [{"source_id": source.id, "status": "success"}]}
    path = write_json(tmp_path / "index.json", index)
    result = read_json(build_context(path, config, tmp_path, "morning"))
    assert [row["item_id"] for row in result["candidate_items"]] == [f"id-{i}" for i in range(25)]
    assert result["brief_plan"][0]["default_item_ids"] == [f"id-{i}" for i in range(15)]
    assert len(result["enrichment_plan"]["actions"]) == 12
    assert result["enrichment_plan"]["deferred_count"] == 13
    assert result["collection_coverage"]["cells"][0]["item_count"] == 30


def test_plan_does_not_repeat_exhausted_or_blocked_preserved_partial_content(tmp_path):
    items = [
        {"item_id": "partial", "content_status": "partial", "metadata": {
            "content_completion": {"stop_reason": "bounded_attempts_exhausted"},
        }},
        {"item_id": "blocked", "content_status": "partial", "metadata": {
            "content_completion": {"stop_reason": "verification_required",
                                   "unresolved": ["verification_required"]},
        }},
    ]
    plan = enrichment_plan(items, [], tmp_path, 12)
    assert plan["actions"] == []
    assert plan["stopped_counts"] == {"bounded_attempts_exhausted": 1}
    assert plan["blocked_counts"]["verification_required"] == 1


def test_quality_limits_reach_brief_and_analysis_inputs(tmp_path):
    from daily_intelligence.authoring import _analysis_candidates

    source = load_config().sources[0]
    item = {"item_id": "story", "source_id": source.id, "title": "Service update",
            "metadata": {"content_quality": {
                "extraction_status": "partial", "numeric_tables_without_headers": ["block-3"],
                "response_truncated": True, "key_fields_verified": None,
            }}}
    index = {"date": "2026-09-11", "edition": "morning", "items": [item]}
    result = read_json(build_context(write_json(tmp_path / "index.json", index), load_config(),
                                    tmp_path, "morning"))
    observations = result["candidate_items"][0]["content_observations"]
    assert observations["quality"]["response_truncated"] is True
    assert observations["quality"]["key_fields_verified"] is None
    assert observations["numeric_tables_without_headers"] == 1
    packet = read_json(Path(result["brief_authoring_batches"][0]["packet_path"]))
    assert packet["candidates"][0]["content_observations"] == observations
    selected = _analysis_candidates([{
        "id": f"{source.module}.{source.category}",
        "briefs": [{"item_id": "story", "importance": 70}],
    }], result, 1)
    assert selected[0]["content_observations"] == observations
