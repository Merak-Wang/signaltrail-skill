"""用冻结作者稿和来源索引评估日报编译、校验与本地交付。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from time import perf_counter

from pypdf import PdfReader
from tiktoken import get_encoding

from signaltrail.authoring import brief_authoring_input
from signaltrail.config import MediaConfig, OutputConfig
from signaltrail.reporting import validate_report_data
from signaltrail.reports import save_report
from signaltrail.utils import read_json, write_json

_DATE = "2026-07-12"
_SOURCES = (
    ("information.international", "基础设施互联"),
    ("information.international", "产业协作"),
    ("information.domestic", "公共数据开放"),
    ("information.domestic", "城市能源改造"),
    ("information.market", "设备采购"),
    ("information.market", "供给交付"),
    ("technology.news", "推理延迟"),
    ("technology.news", "部署成本"),
)
_ITEMS_PER_SOURCE = 15


def _evaluate_author_input(work_dir: Path, index: dict) -> tuple[dict, dict, Path]:
    """处理：通过生产入口评估嵌入正文后的作者输入投影。
    输入：独立工作目录以及与报告共用的冻结来源索引。
    输出：证据完整性检查、输入体量及冻结模型投影的路径。
    """
    candidates, expected = [], {}
    for rank, row in enumerate(index["items"][:_ITEMS_PER_SOURCE], start=1):
        item_id = row["item_id"]
        body = row["description"] + "\n\n公开材料列明安装范围、时间条件与后续核验安排。"
        path = work_dir / "evidence" / f"{item_id}.md"
        path.parent.mkdir(exist_ok=True)
        path.write_text(body, encoding="utf-8")
        candidate = {**row, "content_status": "full_text", "content_path": str(path),
                     "feed_content_path": str(path.with_suffix(".json")),
                     "content_observations": {"unresolved": ["需核验实际交付进度"]}}
        if rank % 2 == 0:
            candidate["description"] = f"第{rank}批新增的来源摘要提供独立背景。"
        candidates.append(candidate)
        expected[item_id] = {"kind": "article", "text": body, "partial": False}

    packet = write_json(work_dir / "brief-packet.json", {
        "output_language": "zh-CN", "candidates": candidates, "author_item_ids": list(expected),
        "output_schema": {"type": "object"},
    })
    original_packet = packet.read_bytes()
    started = perf_counter()
    projected = brief_authoring_input(packet, work_dir, include_evidence=True)
    elapsed = perf_counter() - started
    projections = {row["item_id"]: row for row in projected["candidates"]}
    checks = {
        "author_input_keeps_full_evidence": projected["evidence_by_item_id"] == expected,
        "author_input_keeps_identity_status_warnings_and_unique_description": all(
            {key: value for key, value in projections[row["item_id"]].items()
             if key != "description"}
            == {key: value for key, value in row.items()
                if key not in {"description", "content_path", "feed_content_path"}}
            and projections[row["item_id"]].get("description")
            == (row["description"] if rank % 2 == 0 else None)
            for rank, row in enumerate(candidates, start=1)
        ),
        "author_input_keeps_frozen_packet_and_schema": (
            packet.read_bytes() == original_packet
            and projected["output_schema"] == {"type": "object"}
        ),
    }
    output = write_json(work_dir / "brief-input.json", projected)
    tokens = get_encoding("o200k_base").encode(output.read_text(encoding="utf-8"))
    metrics = {"author_input_projection_seconds": elapsed, "author_input_o200k_tokens": len(tokens)}
    return checks, metrics, output


def _frozen_report_inputs() -> tuple[dict, dict, dict[str, list[str]]]:
    """处理：构造多来源稿件、权威索引和冻结覆盖计划。
    输入：仓库的公开合成报告及固定的来源和条目数量。
    输出：可交给生产保存入口的日报草稿、索引和每来源条目顺序。
    """
    root = Path(__file__).resolve().parents[2]
    sample = read_json(root / "examples" / "sample_report.json")
    index = {
        "date": _DATE, "edition": "daily", "timezone": "Asia/Shanghai",
        "generated_at": f"{_DATE}T09:00:00+08:00", "sources": [], "items": [],
        "source_policies": {},
    }
    sections = {}
    plan = {}
    featured_ids = []
    for source_number, (section_id, subject) in enumerate(_SOURCES, start=1):
        module, category = section_id.split(".")
        source_id = f"fixture-{source_number}"
        source_url = f"https://{source_id}.example/"
        source_name = f"合成来源{source_number}"
        source = {
            "source_id": source_id, "source_name": source_name, "source_url": source_url,
            "module": module, "category": category, "status": "success",
        }
        index["sources"].append(source)
        index["source_policies"][source_id] = {
            "report_target": _ITEMS_PER_SOURCE, "report_max": _ITEMS_PER_SOURCE,
        }
        plan[source_id] = []
        section = sections.setdefault(section_id, {"id": section_id, "briefs": [], "items": []})
        for rank in range(1, _ITEMS_PER_SOURCE + 1):
            item_id = f"{source_id}-{rank:02}"
            url = f"{source_url}articles/{rank}"
            title = f"{subject}第{rank}批公开记录"
            summary = f"{subject}第{rank}批记录公布了试点范围，实施进度将由后续材料核验。"
            index["items"].append({
                "item_id": item_id, "source_id": source_id, "source_name": source_name,
                "module": module, "category": category, "title": title, "description": summary,
                "url": url, "canonical_url": url, "content_status": "not_fetched",
                "published_at": f"{_DATE}T08:{60-rank:02}:00+08:00", "source_rank": rank,
            })
            plan[source_id].append(item_id)
            brief = {
                "item_id": item_id, "title_zh": title, "tldr": summary,
                "importance": 90 - rank, "status": "NEW",
            }
            section["briefs"].append(brief)
            if rank == 1:
                featured_ids.append(item_id)
                section["items"].append({
                    "source_item_ids": [item_id], "title": title, "tldr": summary,
                    "why_it_matters": "试点范围为后续比较部署进度提供了依据。",
                    "importance": 90 - source_number, "confidence": 0.7, "status": "NEW",
                    "evidence_notes": [], "tags": [],
                })
        # 草稿送达顺序与选题顺序不同，正式编译从冻结计划恢复组内顺序。
        section["briefs"][-_ITEMS_PER_SOURCE:] = reversed(section["briefs"][-_ITEMS_PER_SOURCE:])

    # 早期索引策略仍包含一条跨日稿，冻结计划在正文日期复核后将其排除。
    excluded_source = "fixture-outside-edition"
    index["sources"].append({
        **index["sources"][0], "source_id": excluded_source, "source_name": "跨日来源",
        "source_url": "https://outside.example/",
    })
    index["items"].append({
        **index["items"][0], "item_id": "outside-edition", "source_id": excluded_source,
        "source_name": "跨日来源", "url": "https://outside.example/previous",
        "canonical_url": "https://outside.example/previous",
        "published_at": "2026-07-11T23:50:00+08:00",
    })
    index["source_policies"][excluded_source] = {"report_target": 1, "report_max": 1}

    analyses = []
    for domain in ("geopolitics", "ai_technology", "markets"):
        analysis = deepcopy(sample["analyses"][0])
        analysis.pop("analysis_id")
        analysis.pop("evidence_event_ids")
        analysis.update(
            domain=domain,
            narrative=(
                "合成来源披露了各批试点的范围，形成可逐项追踪的公开记录。\n\n"
                "比较试点范围有助于辨认政策落地、工程投入和市场需求的先后关系。\n\n"
                "各部门进度差异可能来自预算安排和既有设施条件，需要结合实际交付记录观察。\n\n"
                "下一阶段核验采购、部署和维护数据，依此调整对试点进度和可扩展性的判断。"
            ),
            facts=["本版各来源均提供了包含试点范围的合成公开记录。"],
            time_horizon="未来数周",
            causal_chain=["试点范围影响采购安排。", "采购进度影响部署时间。"],
            assumptions=["后续可获得同口径交付记录。"],
            evidence_gaps=["缺少实际交付和维护数据。"],
            confidence_rationale="当前记录覆盖计划，交付结果仍需实测。",
            change_from_prior="本期建立试点范围基线。",
            decision_relevance="以公开交付进度安排后续核验。",
            evidence_item_ids=featured_ids,
        )
        analyses.append(analysis)

    draft = {
        "schema_version": "2.0", "language": "zh-CN", "date": _DATE, "edition": "daily",
        "title": "合成情报日报模块评估", "executive_summary": ["本期汇总试点公开记录。"],
        "sections": list(sections.values()), "analyses": analyses,
        "cross_perspective_synthesis": {
            "overall_judgment": "试点落地进度取决于采购、部署和持续维护。",
            "consensus": ["公开记录可用于建立观察基线。"],
            "tensions": [{
                "issue": "执行时间", "perspectives": ["产业政策", "工程部署"],
                "source_of_difference": "资源与施工条件存在差异。",
            }],
            "transmission_chain": ["试点范围影响采购。", "采购完成后进入部署。"],
            "shared_watch_signals": ["采购交付", "部署进度", "维护投入"],
            "revision_triggers": ["按新的交付记录更新判断。"],
            "evidence_item_ids": featured_ids,
        },
    }
    return draft, index, plan


def evaluate(work_dir: Path) -> dict:
    """处理：运行报告保存入口并检查完整发布和修订。
    输入：本次评估独占的工作目录，用于写入冻结输入与交付文件。
    输出：报告覆盖、证据、修订结果和各阶段时延，以及可复查产物路径。
    """
    draft, index, plan = _frozen_report_inputs()
    author_checks, author_metrics, author_input = _evaluate_author_input(work_dir, index)
    draft_path = write_json(work_dir / "draft.json", draft)
    index_path = write_json(work_dir / "index.json", index)
    options = {
        "output_config": OutputConfig(formats=["html", "pdf"], pdf_engine="reportlab"),
        "media_config": MediaConfig(enabled=False),
        "brief_plan_item_ids": plan,
    }
    expected_briefs = {
        brief["item_id"]: brief for section in draft["sections"] for brief in section["briefs"]
    }
    indexed_urls = {item["item_id"]: item["url"] for item in index["items"]}
    expected_text_and_links = {
        item_id: (brief["title_zh"], brief["tldr"], indexed_urls[item_id])
        for item_id, brief in expected_briefs.items()
    }

    incomplete = deepcopy(draft)
    incomplete["sections"][0]["briefs"].pop()
    incomplete_path = write_json(work_dir / "incomplete.json", incomplete)
    # 用另一数据根观察缺稿阻断，保持首版测量的存储与缓存为空。
    rejected_root = work_dir / "rejected"
    rejected = False
    try:
        save_report(incomplete_path, index_path, rejected_root, **options)
    except ValueError as error:
        rejected = "coverage source" in str(error)

    data_dir = work_dir / "data"
    started = perf_counter()
    first = save_report(draft_path, index_path, data_dir, **options)
    save_seconds = perf_counter() - started
    outputs = {
        kind: Path(first[f"{kind}_path"])
        for kind in ("json", "markdown", "html", "pdf") if first.get(f"{kind}_path")
    }
    saved = read_json(outputs["json"])
    errors, warnings = validate_report_data(saved, index, brief_plan_item_ids=plan)
    briefs = [brief for section in saved["sections"] for brief in section["briefs"]]
    featured = [event for section in saved["sections"] for event in section["items"]]
    featured_by_item = {
        ref["item_id"]: event["event_id"] for event in featured for ref in event["source_refs"]
    }
    featured_urls_match = all(
        ref["url"] == indexed_urls.get(ref["item_id"])
        for event in featured for ref in event["source_refs"]
    )
    expected_featured_items = {ids[0] for ids in plan.values()}
    evidence_event_ids = set(featured_by_item.values())
    briefs_by_source: dict[str, list[str]] = {}
    for brief in briefs:
        briefs_by_source.setdefault(brief["primary_source"]["id"], []).append(brief["item_id"])
    actual_text_and_links = {
        brief["item_id"]: (
            brief.get("title_zh") or brief["title"], brief["tldr"], brief["source_ref"]["url"],
        )
        for brief in briefs
    }
    markdown = outputs["markdown"].read_text(encoding="utf-8")
    html = outputs["html"].read_text(encoding="utf-8") if "html" in outputs else ""
    pdf_pages = len(PdfReader(outputs["pdf"]).pages) if "pdf" in outputs else 0
    original_bytes = {kind: path.read_bytes() for kind, path in outputs.items()}

    revised_draft = deepcopy(saved)
    revised_draft["executive_summary"][0] = "本期修订补充试点范围的核验进度。"
    revised_path = write_json(work_dir / "revised.json", revised_draft)
    started = perf_counter()
    second = save_report(revised_path, index_path, data_dir, **options)
    revision_seconds = perf_counter() - started
    latest = read_json(data_dir / "reports" / "latest-daily.json")
    revised_outputs = {
        kind: Path(second[f"{kind}_path"])
        for kind in ("json", "markdown", "html", "pdf") if second.get(f"{kind}_path")
    }

    return {
        "workload": {
            "input": "frozen synthetic author drafts and source index",
            "sources": len(plan), "briefs": len(expected_briefs),
            "featured_events": len(expected_featured_items),
            "analyses": len(draft["analyses"]),
            "author_input_articles": _ITEMS_PER_SOURCE,
            "requested_output_formats": ["json", "markdown", "html", "pdf"],
        },
        "checks": {
            **author_checks,
            "report_contract": not errors and not warnings,
            "complete_frozen_coverage_and_order": briefs_by_source == plan,
            "titles_summaries_and_source_links_preserved": (
                actual_text_and_links == expected_text_and_links
            ),
            "featured_references_and_analysis_evidence": (
                len(featured) == len(expected_featured_items)
                and set(featured_by_item) == expected_featured_items
                and featured_urls_match
                and len(saved["analyses"]) == len(draft["analyses"])
                and all(
                    set(analysis["evidence_event_ids"]) == evidence_event_ids
                    for analysis in saved["analyses"]
                )
                and set(saved["cross_perspective_synthesis"]["evidence_event_ids"])
                == evidence_event_ids
            ),
            "html_markdown_complete_and_pdf_readable": pdf_pages > 0 and all(
                brief["tldr"] in markdown and brief["tldr"] in html
                and indexed_urls[item_id] in markdown and indexed_urls[item_id] in html
                for item_id, brief in expected_briefs.items()
            ),
            "missing_brief_blocks_publication": (
                rejected and not (rejected_root / "reports").exists()
            ),
            "revision_preserves_original_and_updates_latest": (
                saved["revision"] == 1 and latest["revision"] == 2
                and latest["report_id"] == second["report_id"]
                and latest["executive_summary"] == revised_draft["executive_summary"]
                and all(path.is_file() for path in revised_outputs.values())
                and set(revised_outputs) == {"json", "markdown", "html", "pdf"}
                and all(path.read_bytes() == original_bytes[kind] for kind, path in outputs.items())
            ),
        },
        "metrics": {
            **author_metrics,
            "save_seconds": round(save_seconds, 6),
            "briefs_per_second": round(len(briefs) / save_seconds, 3),
            "revision_seconds": round(revision_seconds, 6),
            "pdf_pages": pdf_pages,
            "output_bytes": sum(map(len, original_bytes.values())),
            **{f"save_{key}": value for key, value in first["save_metrics"].items()},
        },
        "artifacts": {
            "author_input": str(author_input),
            **{kind: str(path) for kind, path in outputs.items()},
            **{f"revision_{kind}": str(path) for kind, path in revised_outputs.items()},
        },
        "limitations": [
            "Frozen author drafts measure report compilation and local delivery. "
            "Model generation, coordination, media fetching and remote publication "
            "are outside this workload.",
        ],
    }
