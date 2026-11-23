"""用冻结作者稿和来源索引评估日报编译、校验与本地交付。"""

from __future__ import annotations

import json
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from bs4 import BeautifulSoup
from pypdf import PdfReader
from tiktoken import get_encoding

from signaltrail import authoring
from signaltrail.authoring import brief_authoring_input
from signaltrail.commands.common import CommandContext
from signaltrail.commands.editions import handle_enrich_edition, handle_submit_authoring_batch
from signaltrail.commands.parser import build_parser
from signaltrail.config import (
    AppConfig,
    BrowserConfig,
    MediaConfig,
    MonitorConfig,
    OutputConfig,
    SourceConfig,
)
from signaltrail.reporting import validate_report_data
from signaltrail.reports import save_report
from signaltrail.utils import read_json, write_json
from signaltrail.workflow import (
    adopt_index_for_run,
    begin_authoring,
    enrich_edition,
    prepare_edition,
)

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


def _evaluate_bulk_submission(
    context: CommandContext, run_path: Path, session: dict, report_draft: dict,
) -> tuple[dict, dict]:
    """对有草稿、缺字段和在途的批次运行真实接收命令，核对单次校验与产物。"""
    ready, invalid, in_flight = session["batches"]
    briefs = {
        row["item_id"]: row for section in report_draft["sections"] for row in section["briefs"]
    }
    expected = [briefs[item_id] for item_id in ready["author_item_ids"]]
    write_json(Path(ready["draft_result_path"]), {"briefs": expected})
    invalid_briefs = [dict(briefs[item_id]) for item_id in invalid["author_item_ids"]]
    invalid_briefs[0].pop("importance")
    write_json(Path(invalid["draft_result_path"]), {"briefs": invalid_briefs})
    in_flight_draft = Path(in_flight["draft_result_path"])
    partial = b'{"briefs": ['
    in_flight_draft.write_bytes(partial)
    args = context.parser.parse_args([
        "submit-authoring-batch", "--run", str(run_path), "--all",
        "--skip-batch", in_flight["batch_id"],
    ])
    output = StringIO()
    with (
        patch.object(authoring, "validate_authoring_batch",
                     wraps=authoring.validate_authoring_batch) as validator,
        redirect_stdout(output),
    ):
        started = perf_counter()
        exit_code = handle_submit_authoring_batch(args, context)
        elapsed = perf_counter() - started
    receipt = json.loads(output.getvalue())
    accepted_path = Path(ready["result_path"])
    invalid_packet = Path(invalid["packet_path"])
    rejection_dir = invalid_packet.with_name(f"{invalid_packet.stem}-rejections")
    return ({
        "bulk_accepts_valid_draft_and_keeps_invalid_diagnostics": (
            exit_code == 1 and receipt["accepted"] == [str(accepted_path)]
            and receipt["invalid"] == [invalid["batch_id"]]
            and read_json(accepted_path)["briefs"] == expected
            and "importance" in " ".join(receipt["batches"][1]["errors"])
            and not rejection_dir.exists() and not Path(invalid["result_path"]).exists()
        ),
        "bulk_skips_in_flight_partial_draft": (
            receipt["batches"][2].get("in_flight") and not receipt["batches"][2]["errors"]
            and in_flight_draft.read_bytes() == partial
            and not Path(in_flight["result_path"]).exists()
        ),
        "bulk_validates_each_available_draft_once": validator.call_count == 2,
    }, {
        "bulk_submit_seconds": elapsed,
        "bulk_draft_validations": validator.call_count,
    })


def _evaluate_context_freeze(
    data_dir: Path, index: dict, plan: dict, draft: dict,
) -> tuple[dict, dict]:
    """用冻结采集与提取结果评估选材、补证和写作会话之间的产物转换。"""
    index = deepcopy(index)
    article = index["items"][0]
    radio_url = "https://www.cbc.ca/radio/example/segment-9.1234567"
    article.update(url=radio_url, canonical_url=radio_url)
    tracked_url = f"{radio_url}?cmp=rss"
    index["items"].append({
        **article, "item_id": "cbc-radio-feed-alias",
        "url": tracked_url, "canonical_url": tracked_url,
    })
    config = AppConfig(
        index["timezone"], BrowserConfig(), [
            SourceConfig(
                row["source_id"], row["source_name"], row["source_url"],
                module=row["module"], category=row["category"],
            )
            for row in index["sources"]
        ],
        monitor=MonitorConfig(enabled=False),
    )
    initial_index = write_json(data_dir / "indexes" / "initial.json", index)
    with (
        patch("signaltrail.workflow.today_str", return_value=index["date"]),
        patch("signaltrail.workflow.collect_sources", return_value=initial_index),
    ):
        started = perf_counter()
        run_path = prepare_edition(config, data_dir, "daily")
        prepare_seconds = perf_counter() - started
    initial_context = Path(read_json(run_path)["artifacts"]["context_path"])
    verified_index = write_json(data_dir / "indexes" / "verified.json", index)
    started = perf_counter()
    adopted = adopt_index_for_run(config, data_dir, verified_index)
    adopt_seconds = perf_counter() - started
    adopted_run = read_json(run_path)
    selection_context = Path(adopted_run["artifacts"]["context_path"])
    selection_bytes = selection_context.read_bytes()
    initial = read_json(initial_context)
    selection = read_json(selection_context)
    provisional_packets = list(initial_context.parent.glob("*-brief-batch-*.json"))

    item = index["items"][0]
    expected_text = "补证后的完整正文。公开记录列明范围、时间条件和接收方。"
    content_path = data_dir / "content" / "article.md"
    content_path.parent.mkdir()
    content_path.write_text(expected_text, encoding="utf-8")
    enriched_index = deepcopy(index)
    enriched_index["items"][0].update(content_status="full_text", content_path=str(content_path))
    frozen_index = write_json(data_dir / "indexes" / "enriched.json", enriched_index)
    with patch("signaltrail.workflow.extract_content", return_value=frozen_index) as extract:
        started = perf_counter()
        enrich_edition(run_path, config, data_dir, [item["item_id"]], max_items=1)
        enrich_seconds = perf_counter() - started
    cli = CommandContext(config, data_dir, build_parser(), compact=True)
    args = cli.parser.parse_args(["enrich-edition", "--run", str(run_path),
                                  "--all-slide-candidates", "--max-items", "12"])
    output = StringIO()
    with (redirect_stdout(output),
          patch("signaltrail.workflow.extract_content", return_value=frozen_index) as batches):
        handle_enrich_edition(args, cli)
    selected_batches = [call.kwargs["selected_ids"] for call in batches.call_args_list]
    processed_ids = [item_id for batch in selected_batches for item_id in batch]
    last_batch = json.loads(output.getvalue())["artifacts"]["enrichment"]["slides_candidates"]
    started = perf_counter()
    begin_authoring(run_path, data_dir)
    dispatch_seconds = perf_counter() - started
    artifacts = read_json(run_path)["artifacts"]
    context = read_json(Path(artifacts["context_path"]))
    session = read_json(Path(artifacts["authoring"]["session_path"]))
    evidence = {}
    packet_paths = [Path(batch["packet_path"]) for batch in session["batches"]]
    for path in packet_paths:
        projected = brief_authoring_input(path, data_dir, include_evidence=True)
        evidence.update(projected["evidence_by_item_id"])
    planned_ids = {row["source_id"]: row["default_item_ids"] for row in selection["brief_plan"]}
    submit_checks, submit_metrics = _evaluate_bulk_submission(
        CommandContext(config, data_dir, build_parser()), run_path, session, draft,
    )
    return ({
        **submit_checks,
        "single_command_finishes_all_candidate_batches": (
            len(selected_batches) > 1 and all(len(batch) <= 12 for batch in selected_batches)
            and len(processed_ids) == len(set(processed_ids)) and last_batch["remaining_count"] == 0
        ),
        "selection_keeps_plans_without_provisional_packets": (
            adopted == run_path and adopted_run["status"] == "awaiting_selection"
            and not provisional_packets
            and initial.get("selection_only") and selection.get("selection_only")
            and all(initial[key] == selection[key] for key in (
                "candidate_items", "brief_plan", "enrichment_plan", "collection_coverage",
            ))
            and planned_ids == plan
        ),
        "authoring_freezes_revised_full_evidence": (
            extract.call_args.kwargs["selected_ids"] == [item["item_id"]]
            and artifacts["index_path"] == str(frozen_index)
            and selection_context.read_bytes() == selection_bytes
            and selection["brief_plan"] == context["brief_plan"]
            and set(evidence) == {item_id for item_ids in plan.values() for item_id in item_ids}
            and evidence[item["item_id"]] == {
                "kind": "article", "text": expected_text, "partial": False,
            }
            and all(evidence[row["item_id"]] == {
                "kind": "description", "text": row["description"], "partial": True,
            } for row in index["items"][1:] if row["item_id"] in evidence)
        ),
    }, {
        **submit_metrics,
        "selection_prepare_seconds": prepare_seconds,
        "selection_adopt_seconds": adopt_seconds,
        "selection_packet_count": len(provisional_packets),
        "selection_packet_bytes": sum(path.stat().st_size for path in provisional_packets),
        "frozen_enrichment_seconds": enrich_seconds,
        "frozen_dispatch_seconds": dispatch_seconds,
        "frozen_packet_count": len(session["batches"]),
        "frozen_packet_bytes": sum(path.stat().st_size for path in packet_paths),
    })


def evaluate(work_dir: Path) -> dict:
    """处理：运行报告保存入口并检查完整发布和修订。
    输入：本次评估独占的工作目录，用于写入冻结输入与交付文件。
    输出：报告覆盖、证据、修订结果和各阶段时延，以及可复查产物路径。
    """
    draft, index, plan = _frozen_report_inputs()
    author_checks, author_metrics, author_input = _evaluate_author_input(work_dir, index)
    freeze_checks, freeze_metrics = _evaluate_context_freeze(
        work_dir.resolve() / "context-freeze", index, plan, draft,
    )
    # 榜单收录时间与出版方原发时间并存时，成稿应显示后者并保留原有精度。
    platform_item = index["items"][0]
    platform_item["published_at"] = "2026-07-05T08:59:00+08:00"
    platform_item["metadata"] = {
        "publication_time_kind": "platform", "content_source": {"published_at": _DATE},
    }
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
    document = BeautifulSoup(html, "html.parser")
    cards = document.select("article.brief")
    target_headlines = [brief.get("title_zh") or brief["title"] for brief in briefs]
    reader = PdfReader(outputs["pdf"]) if "pdf" in outputs else None
    pdf_pages = len(reader.pages) if reader else 0
    analysis_anchors = {"analysis-synthesis", *(f"analysis-{row['domain']}"
                                                for row in saved["analyses"])}
    home_links = {link["href"][1:] for link in document.select(".analysis-contents a")}
    pdf_targets = [annot.get_object()["/Dest"] for annot in reader.pages[0].get("/Annots", [])
                   if "/Dest" in annot.get_object()] if pdf_pages else []
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
            **freeze_checks,
            "publisher_date_shown_in_brief_and_featured_event": all(
                ref.get("published_at") == _DATE
                for ref in [*(brief["source_ref"] for brief in briefs),
                            *(ref for event in featured for ref in event["source_refs"])]
                if ref["item_id"] == platform_item["item_id"]
            ) and f"发布日期：{_DATE}<" in html,
            "summary_links_to_analysis_in_html_and_pdf": (
                home_links == analysis_anchors and all(document.find(id=key) for key in home_links)
                and len(pdf_targets) == len(analysis_anchors)
                and all(reader.get_page_number(dest[0].get_object()) > 0 for dest in pdf_targets)
            ),
            "report_contract": not errors and not warnings,
            "complete_frozen_coverage_and_order": briefs_by_source == plan,
            "titles_summaries_and_source_links_preserved": (
                actual_text_and_links == expected_text_and_links
            ),
            "target_language_headings_reference_originals": (
                [card.select_one("h4 .story-link").get_text(strip=True) for card in cards]
                == target_headlines
                and all(not brief.get("title_zh") or
                        card.select_one(".original-title").get_text(strip=True) == brief["title"]
                        for card, brief in zip(cards, briefs, strict=True))
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
            **freeze_metrics,
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
            "The context-freeze workload uses frozen collection and extraction responses. "
            "Model generation, coordination, media fetching and remote publication "
            "are outside this workload.",
        ],
    }
