from pathlib import Path

import pytest

from daily_intelligence.config import load_config
from daily_intelligence.context import build_context
from daily_intelligence.reporting import compile_report_data
from daily_intelligence.semantics import (
    finalize_semantic_cache_evaluation,
    load_semantic_cache,
    reusable_semantic_brief,
    semantic_fingerprint,
    tldr_quality_issue,
    update_semantic_cache_from_report,
)
from daily_intelligence.utils import read_json, write_json


def _item(description: str = "公开摘要") -> dict:
    return {
        "item_id": "bbc_world-cache",
        "source_id": "bbc_world",
        "source_name": "BBC",
        "title": "A sufficiently detailed English headline",
        "url": "https://www.bbc.com/news/articles/cache",
        "canonical_url": "https://bbc.com/news/articles/cache",
        "description": description,
        "published_at": "2026-07-17T05:00:00+08:00",
        "discovered_at": "2026-07-17T05:30:00+08:00",
        "module": "information",
        "category": "international",
        "content_status": "not_fetched",
        "metadata": {"source_rank": 1, "role": "evidence"},
    }


def _brief() -> dict:
    return {
        "item_id": "bbc_world-cache",
        "title": "A sufficiently detailed English headline",
        "title_zh": "一条足够具体的英文新闻标题",
        "tldr": "这是一条基于公开摘要撰写的中文简要说明。",
        "importance": 70,
        "status": "NEW",
    }


def _approve(report_id: str, data_dir: Path) -> None:
    finalize_semantic_cache_evaluation(
        {
            "evaluation_id": "evaluation-1",
            "evaluated_report_id": report_id,
            "continuity_decision": "accept",
            "dimensions": [
                {"id": "summary_accuracy", "score": 4},
                {"id": "factual_reliability", "score": 4},
                {"id": "compliance_boundaries", "score": 4},
            ],
        },
        data_dir,
    )


def test_semantic_fingerprint_invalidates_when_evidence_changes():
    original = semantic_fingerprint(_item("摘要A"))

    assert semantic_fingerprint(_item("摘要A")) == original
    assert semantic_fingerprint(_item("摘要B")) != original


def test_evaluated_semantics_are_reused_in_context_and_compiler(tmp_path: Path):
    data_dir = tmp_path / "data"
    item = _item()
    report_id = "daily-2026-07-17-morning-r1"
    report = {
        "report_id": report_id,
        "generated_at": "2026-07-17T06:00:00+08:00",
        "sections": [{"briefs": [_brief()]}],
    }
    index = {
        "date": "2026-07-17",
        "edition": "evening",
        "timezone": "Asia/Shanghai",
        "source_policies": {"bbc_world": {"report_target": 1, "report_max": 15}},
        "sources": [
            {
                "source_id": "bbc_world",
                "source_name": "BBC",
                "source_url": "https://www.bbc.com/news",
                "status": "success",
            }
        ],
        "items": [item],
    }
    update_semantic_cache_from_report(report, index, data_dir)
    _approve(report_id, data_dir)
    index_path = write_json(
        data_dir / "indexes" / "2026-07-17" / "evening-r1.json", index
    )

    context = read_json(build_context(index_path, load_config(), data_dir, "evening"))

    assert context["reusable_briefs"][0]["tldr"] == _brief()["tldr"]
    assert context["semantic_cache_metrics"]["approved_and_reused"] == 1
    assert context["semantic_cache_metrics"]["outside_current_plan"] == 0
    assert context["brief_plan"][0]["reuse_item_ids"] == [item["item_id"]]
    assert context["brief_plan"][0]["author_item_ids"] == []
    assert context["brief_authoring_batches"] == []

    draft = {"sections": [], "analyses": []}
    warnings = compile_report_data(
        draft,
        index,
        load_semantic_cache(data_dir),
        brief_plan_item_ids={"bbc_world": [item["item_id"]]},
    )
    compiled = next(
        brief
        for section in draft["sections"]
        for brief in section["briefs"]
        if brief["item_id"] == item["item_id"]
    )
    assert compiled["semantic_cache_reused"] is True
    assert any("reused approved semantic cache" in warning for warning in warnings)
    assert reusable_semantic_brief(
        item, load_semantic_cache(data_dir), "en"
    ) is None


def test_cache_persists_only_stable_semantics_and_recomputes_run_fields(
    tmp_path: Path,
):
    data_dir = tmp_path / "data"
    item = _item()
    report_id = "daily-dynamic-fields"
    update_semantic_cache_from_report(
        {
            "report_id": report_id,
            "generated_at": "2026-07-17T06:00:00+08:00",
            "sections": [{"briefs": [_brief()]}],
        },
        {"items": [item]},
        data_dir,
    )
    _approve(report_id, data_dir)

    entry = load_semantic_cache(data_dir)[item["item_id"]]
    assert "importance" not in entry["brief"]
    assert "status" not in entry["brief"]

    current = dict(item)
    current["metadata"] = {**item["metadata"], "source_rank": 12}
    current["previously_reported"] = True
    reused = reusable_semantic_brief(
        current,
        load_semantic_cache(data_dir),
        "zh-CN",
        reference_date="2026-07-17",
    )

    assert reused is not None
    assert reused["status"] == "UPD"
    assert reused["importance"] != _brief()["importance"]


def test_approved_cache_does_not_reuse_operational_placeholder_tldr(tmp_path: Path):
    data_dir = tmp_path / "data"
    item = _item()
    report_id = "daily-placeholder"
    brief = _brief()
    brief["tldr"] = "数据包未提供摘要，因此当前只能记录该新闻标题。"
    update_semantic_cache_from_report(
        {
            "report_id": report_id,
            "generated_at": "2026-07-17T06:00:00+08:00",
            "sections": [{"briefs": [brief]}],
        },
        {"items": [item]},
        data_dir,
    )
    _approve(report_id, data_dir)

    assert reusable_semantic_brief(
        item,
        load_semantic_cache(data_dir),
        "zh-CN",
    ) is None


def test_context_persists_versioned_targeted_cache_invalidation(tmp_path: Path):
    data_dir = tmp_path / "data"
    item = _item()
    report_id = "daily-invalidated-cache"
    update_semantic_cache_from_report(
        {
            "report_id": report_id,
            "generated_at": "2026-07-17T06:00:00+08:00",
            "sections": [{"briefs": [_brief()]}],
        },
        {"items": [item]},
        data_dir,
    )
    _approve(report_id, data_dir)
    cache = load_semantic_cache(data_dir)
    cache[item["item_id"]]["brief"]["tldr"] = "数据包未提供摘要，只能记录标题。"
    write_json(
        data_dir / "state" / "semantic-cache.json",
        {"schema_version": "1.2", "items": cache},
    )
    index_path = write_json(
        data_dir / "indexes" / "2026-07-17" / "evening-r1.json",
        {
            "date": "2026-07-17",
            "edition": "evening",
            "timezone": "Asia/Shanghai",
            "source_policies": {
                "bbc_world": {"report_target": 1, "report_max": 15}
            },
            "sources": [
                {
                    "source_id": "bbc_world",
                    "source_name": "BBC",
                    "source_url": "https://www.bbc.com/news",
                    "status": "success",
                }
            ],
            "items": [item],
        },
    )

    context = read_json(build_context(index_path, load_config(), data_dir, "evening"))
    invalidated = load_semantic_cache(data_dir)[item["item_id"]]

    assert context["semantic_cache_metrics"]["invalidated_editorial_rule"] == 1
    assert invalidated["state"] == "invalidated"
    assert invalidated["invalidation_reason"] == "current_editorial_rule"
    assert invalidated["invalidation_rule_version"] == "tldr-quality-v2"


@pytest.mark.parametrize(
    "tldr",
    [
        "公司发布季度业绩并上调全年指引；内容未抓取，仅凭标题供稿。",
        "研究提出新的模型评估方法；暂无正文详情。",
        "论文讨论低视力图表可访问性；暂无摘要，细节待披露。",
        "目前仅有标题信息，暂无摘要与正文细节。",
        "The company raised its annual guidance; article body was not fetched.",
    ],
)
def test_tldr_quality_rejects_access_status_leakage(tldr: str):
    language = "en" if tldr.startswith("The ") else "zh-CN"

    assert tldr_quality_issue(tldr, "Different source title", language)


def test_approved_cache_strips_only_trailing_access_status_without_model_call(
    tmp_path: Path,
):
    data_dir = tmp_path / "data"
    item = _item()
    report_id = "daily-access-tail"
    brief = _brief()
    brief["tldr"] = (
        "公司发布季度业绩并上调全年指引，收入与利润均超过公开预期；"
        "内容未抓取，仅凭标题供稿。"
    )
    update_semantic_cache_from_report(
        {
            "report_id": report_id,
            "generated_at": "2026-07-17T06:00:00+08:00",
            "sections": [{"briefs": [brief]}],
        },
        {"items": [item]},
        data_dir,
    )
    _approve(report_id, data_dir)

    reused = reusable_semantic_brief(
        item,
        load_semantic_cache(data_dir),
        "zh-CN",
    )

    assert reused is not None
    assert reused["tldr"] == "公司发布季度业绩并上调全年指引，收入与利润均超过公开预期"
    assert reusable_semantic_brief(
        item,
        load_semantic_cache(data_dir),
        "zh-CN",
    ) == reused


def test_cached_tldr_sanitizer_does_not_remove_substantive_availability_fact(
    tmp_path: Path,
):
    data_dir = tmp_path / "data"
    item = _item()
    report_id = "daily-substantive-availability"
    brief = _brief()
    brief["tldr"] = "公司宣布服务现已向所有付费用户开放，并公布了新的区域可用范围。"
    update_semantic_cache_from_report(
        {
            "report_id": report_id,
            "generated_at": "2026-07-17T06:00:00+08:00",
            "sections": [{"briefs": [brief]}],
        },
        {"items": [item]},
        data_dir,
    )
    _approve(report_id, data_dir)

    reused = reusable_semantic_brief(item, load_semantic_cache(data_dir), "zh-CN")

    assert reused is not None
    assert reused["tldr"] == brief["tldr"]


def test_approved_cache_accepts_zero_importance_and_rejects_translated_headline_tldr(
    tmp_path: Path,
):
    data_dir = tmp_path / "data"
    item = _item()
    report_id = "daily-zero-importance"
    brief = _brief()
    brief["importance"] = 0
    update_semantic_cache_from_report(
        {
            "report_id": report_id,
            "generated_at": "2026-07-17T06:00:00+08:00",
            "sections": [{"briefs": [brief]}],
        },
        {"items": [item]},
        data_dir,
    )
    _approve(report_id, data_dir)

    assert reusable_semantic_brief(item, load_semantic_cache(data_dir), "zh-CN")

    cache = load_semantic_cache(data_dir)
    cache[item["item_id"]]["brief"]["tldr"] = brief["title_zh"]
    assert reusable_semantic_brief(item, cache, "zh-CN") is None


def test_compiler_cache_reuse_cannot_cross_the_current_brief_plan(tmp_path: Path):
    data_dir = tmp_path / "data"
    top_item = _item()
    outside_item = _item()
    outside_item.update(
        {
            "item_id": "bbc_world-outside-top15",
            "title": "An older cached headline outside the selected Top fifteen",
            "url": "https://www.bbc.com/news/articles/outside-top15",
            "canonical_url": "https://bbc.com/news/articles/outside-top15",
        }
    )
    outside_item["metadata"] = {"source_rank": 18, "role": "evidence"}
    outside_brief = _brief()
    outside_brief.update(
        {
            "item_id": outside_item["item_id"],
            "title": outside_item["title"],
            "title_zh": "一条位于本次前十五名之外的旧缓存新闻",
        }
    )
    report_id = "daily-2026-07-17-morning-r1"
    index = {
        "date": "2026-07-17",
        "edition": "evening",
        "timezone": "Asia/Shanghai",
        "source_policies": {"bbc_world": {"report_target": 15, "report_max": 15}},
        "sources": [
            {
                "source_id": "bbc_world",
                "source_name": "BBC",
                "source_url": "https://www.bbc.com/news",
                "status": "success",
            }
        ],
        "items": [top_item, outside_item],
    }
    update_semantic_cache_from_report(
        {
            "report_id": report_id,
            "generated_at": "2026-07-17T06:00:00+08:00",
            "sections": [{"briefs": [_brief(), outside_brief]}],
        },
        index,
        data_dir,
    )
    _approve(report_id, data_dir)

    draft = {"sections": [], "analyses": []}
    compile_report_data(
        draft,
        index,
        load_semantic_cache(data_dir),
        brief_plan_item_ids={"bbc_world": [top_item["item_id"]]},
    )

    assert [
        brief["item_id"]
        for section in draft["sections"]
        for brief in section["briefs"]
    ] == [top_item["item_id"]]


def test_low_reliability_evaluation_rejects_semantic_cache(tmp_path: Path):
    data_dir = tmp_path / "data"
    report_id = "daily-low-quality"
    update_semantic_cache_from_report(
        {
            "report_id": report_id,
            "generated_at": "2026-07-17T06:00:00+08:00",
            "sections": [{"briefs": [_brief()]}],
        },
        {"items": [_item()]},
        data_dir,
    )

    finalize_semantic_cache_evaluation(
        {
            "evaluated_report_id": report_id,
            "continuity_decision": "selective",
            "dimensions": [
                {"id": "summary_accuracy", "score": 4},
                {"id": "factual_reliability", "score": 2},
                {"id": "compliance_boundaries", "score": 4},
            ],
        },
        data_dir,
    )

    assert load_semantic_cache(data_dir)[_item()["item_id"]]["state"] == "rejected"


def test_selective_evaluation_excluding_summaries_rejects_semantic_cache(
    tmp_path: Path,
):
    data_dir = tmp_path / "data"
    report_id = "daily-excluded-summaries"
    update_semantic_cache_from_report(
        {
            "report_id": report_id,
            "generated_at": "2026-07-17T06:00:00+08:00",
            "sections": [{"briefs": [_brief()]}],
        },
        {"items": [_item()]},
        data_dir,
    )

    finalize_semantic_cache_evaluation(
        {
            "evaluated_report_id": report_id,
            "continuity_decision": "selective",
            "exclude_from_continuity": ["event_summaries"],
            "dimensions": [
                {"id": "summary_accuracy", "score": 5},
                {"id": "factual_reliability", "score": 5},
                {"id": "compliance_boundaries", "score": 5},
            ],
        },
        data_dir,
    )

    assert load_semantic_cache(data_dir)[_item()["item_id"]]["state"] == "rejected"


def test_rewritten_semantics_return_to_pending_until_re_evaluated(tmp_path: Path):
    data_dir = tmp_path / "data"
    report_id = "daily-original"
    report = {
        "report_id": report_id,
        "generated_at": "2026-07-17T06:00:00+08:00",
        "sections": [{"briefs": [_brief()]}],
    }
    index = {"items": [_item()]}
    update_semantic_cache_from_report(report, index, data_dir)
    _approve(report_id, data_dir)

    rewritten = _brief()
    rewritten["tldr"] = "这是经过模型改写、尚待新评估确认的中文摘要。"
    update_semantic_cache_from_report(
        {
            "report_id": "daily-rewritten",
            "generated_at": "2026-07-17T18:00:00+08:00",
            "sections": [{"briefs": [rewritten]}],
        },
        index,
        data_dir,
    )

    entry = load_semantic_cache(data_dir)[_item()["item_id"]]
    assert entry["state"] == "pending"
    assert entry["report_id"] == "daily-rewritten"
