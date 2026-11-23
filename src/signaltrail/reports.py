from __future__ import annotations

import time
from collections.abc import Iterator
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import MediaConfig, OutputConfig
from .local_output import write_local_outputs
from .localization import (
    ANALYSIS_SECTION_LABELS,
    ANALYSIS_SECTION_LABELS_EN,
    EVALUATION_LABELS,
    EVALUATION_LABELS_EN,
    GROUP_LABELS,
    GROUP_LABELS_EN,
    STATUS_LABELS,
    STATUS_LABELS_EN,
    is_chinese_output,
    localized,
    translated_title,
)
from .media import materialize_report_images
from .reporting import (
    BRIEF_REPORT_SCHEMAS,
    compile_report_data,
    group_items_by_source,
    normalize_report_data,
    optional_analysis_prose,
    ordered_sections,
    reference_time_label,
    report_content_hash,
    report_followups,
    split_narrative_paragraphs,
    validate_evaluation_data,
    validate_report_data,
)
from .semantics import (
    finalize_semantic_cache_evaluation,
    load_semantic_cache,
    update_semantic_cache_from_report,
)
from .state import update_continuity_state
from .storage import exclusive_lock, next_revision, write_immutable_json, write_text_atomic
from .utils import read_json, write_json

EDITION_LABELS = {"daily": "日报", "morning": "早报", "evening": "晚报"}
EDITION_LABELS_EN = {"daily": "Daily Brief", "morning": "Morning Brief", "evening": "Evening Brief"}
DOMAIN_LABELS = {
    "geopolitics": "地缘政治",
    "markets": "市场与经济",
    "ai_technology": "人工智能与技术",
}
DOMAIN_LABELS_EN = {
    "geopolitics": "Geopolitics",
    "markets": "Markets and Economy",
    "ai_technology": "Artificial Intelligence and Technology",
}
STATE_LABELS = {
    "new": "新观点",
    "strengthening": "增强",
    "unchanged": "不变",
    "weakening": "减弱",
    "revised": "修正",
    "invalidated": "失效",
    "closed": "关闭",
}
STATE_LABELS_EN = {
    "new": "New",
    "strengthening": "Strengthening",
    "unchanged": "Unchanged",
    "weakening": "Weakening",
    "revised": "Revised",
    "invalidated": "Invalidated",
    "closed": "Closed",
}
ACCESS_LABELS = {
    "full_text": "已读正文",
    "partial": "已读部分正文",
    "metadata_only": "仅元数据",
    "verification_required": "需要人工验证",
}
ACCESS_LABELS_EN = {
    "full_text": "Full text read",
    "partial": "Partial text read",
    "metadata_only": "Metadata only",
    "verification_required": "Manual verification required",
}

ASSESSMENT_LABELS = {
    "trend": "趋势判断",
    "risk": "风险分析",
    "learning_research": "学习与研究建议",
}
ASSESSMENT_LABELS_EN = {
    "trend": "Trend",
    "risk": "Risk",
    "learning_research": "Learning and Research",
}
PERSPECTIVE_LABELS = {
    "geopolitics": "地缘政治专家",
    "ai_research_engineering": "AI研究与开发工程师",
    "equity_analysis": "股票分析师",
    "china_standpoint": "中国立场",
    "western_standpoint": "西方立场",
}
PERSPECTIVE_LABELS_EN = {
    "geopolitics": "Geopolitical Expert",
    "ai_research_engineering": "AI Research and Engineering",
    "equity_analysis": "Equity Analyst",
    "china_standpoint": "Chinese Perspective",
    "western_standpoint": "Western Perspective",
}


def _image_markdown_url(image: dict[str, Any], media_path_prefix: str | None) -> str:
    """处理：把本地图片路径或安全公网地址转换为 Markdown URL。
    输入：本地媒体相对路径前缀。
    - ``image``：报告或索引中的图片元数据；包含 URL、本地路径、哈希、尺寸和说明。
    输出：经过选择、规范化或安全处理的 URL 字符串，供后续访问或渲染使用。
    """
    local_path = str(image.get("local_path") or "").replace("\\", "/")
    local_parts = [part for part in local_path.split("/") if part]
    if (
        media_path_prefix
        and local_parts
        and local_parts[0] == "media"
        and ".." not in local_parts
    ):
        return f"{media_path_prefix.rstrip('/')}/{local_path}"
    return str(image.get("source_url") or image.get("url") or "")


def _brief_markdown(
    item: dict[str, Any],
    rank: int,
    media_path_prefix: str | None = None,
    language: object = "zh-CN",
) -> list[str]:
    """把单条简报渲染为含来源和图片的 Markdown。
    输入：带稳定 ID 的索引条目、本地媒体相对路径前缀、输出语言。
    - ``rank``：简报或来源在当前栏目中的一基排序号。
    """
    colon = "：" if is_chinese_output(language) else ":"
    ref = item["source_ref"]
    status_labels = STATUS_LABELS if is_chinese_output(language) else STATUS_LABELS_EN
    status = status_labels.get(item["status"], item["status"])
    source_rank = f" `{item['source_rank_label']}`" if item.get("source_rank_label") else ""
    localized_title = translated_title(item, language)
    lines = [f"**{rank}. [{localized_title or item['title']}]({ref['url']})** "
             f"`[{status}]`{source_rank}"]
    if localized_title:
        lines.extend(["", f"**{localized(language, '原题', 'Original headline')}{colon}** "
                          f"{item['title']}"])
    if time_info := reference_time_label(ref, language):
        label, value = time_info
        lines.extend(["", f"**{label}{colon}** {value}"])
    lines.extend(["", f"**TL;DR{colon}** {item['tldr']}"])
    image = item.get("image")
    if isinstance(image, dict):
        image_url = _image_markdown_url(image, media_path_prefix)
        if image_url:
            lines.extend(
                [
                    "",
                    f"![{image.get('caption', '')}]({image_url})",
                    "",
                    f"*{localized(language, '图片来源', 'Image source')}{colon} "
                    f"{image.get('credit', localized(language, '原始来源', 'Original source'))}*",
                    "",
                ]
            )
    lines.append("")
    return lines


def _event_markdown(
    item: dict[str, Any],
    title: str,
    language: object = "zh-CN",
) -> list[str]:
    """把单个事件渲染为兼容旧 schema 的 Markdown。
    输入：带稳定 ID 的索引条目、输出语言。
    - ``title``：来源提供的标题文本；会清理空白，并用于过滤、身份或展示。
    """
    colon = "：" if is_chinese_output(language) else ":"
    separator = "，" if is_chinese_output(language) else ", "
    access_labels = ACCESS_LABELS if is_chinese_output(language) else ACCESS_LABELS_EN
    lines = [
        title,
        "",
        f"**{localized(language, '摘要（TL;DR）', 'Summary (TL;DR)')}{colon}** {item['tldr']}",
        "",
        f"**{localized(language, '为什么重要', 'Why it matters')}{colon}** "
        f"{item['why_it_matters']}",
        "",
        (
            f"**{localized(language, '重要性', 'Importance')}{colon}** "
            f"{item['importance']}/100 | "
            f"**{localized(language, '置信度', 'Confidence')}{colon}** "
            f"{item['confidence']:.2f}"
        ),
        "",
        f"**{localized(language, '重要性依据', 'Importance rationale')}{colon}** "
        f"{item['importance_reason']}",
        "",
        f"**{localized(language, '证据与原文', 'Evidence and sources')}{colon}**",
        "",
    ]
    for ref in item["source_refs"]:
        access = access_labels.get(ref["access"], ref["access"])
        time_text = ""
        if time_info := reference_time_label(ref, language):
            label, value = time_info
            time_text = f"{separator}{label}{colon}{value}"
        lines.append(
            f"- [{ref['title']}]({ref['url']}) — {access}{separator}"
            f"{ref['role']}{time_text}"
        )
    if item["evidence_notes"]:
        lines.extend(
            [
                "",
                f"**{localized(language, '证据说明', 'Evidence notes')}{colon}**",
                "",
            ]
        )
        lines.extend(f"- {note}" for note in item["evidence_notes"])
    image = item.get("image")
    if image:
        lines.extend(
            [
                "",
                f"![{image['caption']}]({image['url']})",
                "",
                f"*{localized(language, '图片来源', 'Image source')}{colon} "
                f"{image['credit']}*",
            ]
        )
    lines.append("")
    return lines


def evaluation_findings(
    evaluation: dict[str, Any], language: object,
) -> Iterator[tuple[str, list[str]]]:
    """处理：按固定顺序取出评估发现及其栏目名。
    输入：已接受的质量评估和报告语言。
    输出：供发布视图逐组渲染的标签与条目。
    """
    for key, chinese, english in (
        ("main_defects", "主要缺陷", "Main Defects"),
        ("insufficient_evidence", "证据不足项", "Insufficient Evidence"),
        ("improvements", "改进建议", "Recommended Improvements"),
    ):
        yield localized(language, chinese, english), (
            evaluation.get(key) or [localized(language, "无", "None")]
        )


def render_report_markdown(
    report: dict[str, Any],
    media_path_prefix: str | None = None,
) -> str:
    """把已验证报告栏目、来源引用和本地图片投影为可追踪的 Markdown。
    输入：含栏目和来源引用的报告、本地媒体相对路径前缀。
    """
    language = report.get("language") or "zh-CN"
    chinese = is_chinese_output(language)
    colon = "：" if chinese else ":"
    joiner = "、" if chinese else ", "
    edition_labels = EDITION_LABELS if chinese else EDITION_LABELS_EN
    status_labels = STATUS_LABELS if chinese else STATUS_LABELS_EN
    domain_labels = DOMAIN_LABELS if chinese else DOMAIN_LABELS_EN
    state_labels = STATE_LABELS if chinese else STATE_LABELS_EN
    group_labels = GROUP_LABELS if chinese else GROUP_LABELS_EN
    assessment_labels = ASSESSMENT_LABELS if chinese else ASSESSMENT_LABELS_EN
    perspective_labels = PERSPECTIVE_LABELS if chinese else PERSPECTIVE_LABELS_EN
    analysis_section_labels = (
        ANALYSIS_SECTION_LABELS if chinese else ANALYSIS_SECTION_LABELS_EN
    )
    evaluation_labels = EVALUATION_LABELS if chinese else EVALUATION_LABELS_EN
    collection_notes_label = localized(
        language,
        "采集与验证说明",
        "Collection and verification notes",
    )
    stakeholder_positions_label = localized(
        language,
        "不同立场与利益",
        "Stakeholder positions and interests",
    )
    quality_heading = localized(
        language,
        "质量评估与用户反馈",
        "Quality Evaluation and Reader Feedback",
    )
    edition = edition_labels.get(report["edition"], report["edition"])
    lines = [
        f"# {report['title']}",
        "",
        f"- {localized(language, '版本', 'Edition')}{colon}{edition}",
        f"- {localized(language, '修订号', 'Revision')}{colon}{report['revision']}",
        f"- {localized(language, '生成时间', 'Generated at')}{colon}"
        f"{report['generated_at']}",
        "",
        f"**{localized(language, '摘要', 'Executive Summary')}**",
        "",
    ]
    lines.extend(f"- {item}" for item in report["executive_summary"])

    schema = report.get("schema_version")
    brief_schema = schema in BRIEF_REPORT_SCHEMAS
    grouped = brief_schema or schema == "1.4"
    for module in ("information", "technology"):
        lines.extend(["", f"## {group_labels[module]}", ""])
        for section in ordered_sections(report, module):
            lines.extend([f"### {section['title']}", ""])
            if section.get("coverage_note"):
                lines.extend([section["coverage_note"], ""])
            if grouped:
                for source, items in group_items_by_source(section, language):
                    lines.extend([f"#### [{source['name']}]({source['url']})", ""])
                    for rank, item in enumerate(items, start=1):
                        if brief_schema:
                            lines.extend(_brief_markdown(item, rank, media_path_prefix, language))
                        else:
                            link = item["source_refs"][0]["url"]
                            status = status_labels.get(item["status"], item["status"])
                            heading = f"**{rank}. [{item['title']}]({link})** `[{status}]`"
                            lines.extend(_event_markdown(item, heading, language))
            else:
                for item in sorted(
                    section["items"],
                    key=lambda value: value["importance"],
                    reverse=True,
                ):
                    status = status_labels.get(item["status"], item["status"])
                    lines.extend(
                        _event_markdown(
                            item,
                            f"#### [{status}] {item['title']}",
                            language,
                        )
                    )
        if module == "information" and report["pending_verifications"]:
            lines.extend(
                [
                    f"**{collection_notes_label}{colon}**",
                    "",
                ]
            )
            for item in report["pending_verifications"]:
                lines.append(f"- {item['source_name']}: {item.get('note', item['status'])}")

    lines.extend(["", f"## {localized(language, '研判', 'Analysis')}", ""])
    if report["analyses"]:
        last_domain = None
        for analysis in report["analyses"]:
            domain = analysis.get("domain")
            if domain != last_domain:
                section_title = analysis_section_labels.get(
                    domain, domain_labels.get(domain, domain)
                )
                lines.extend(
                    [
                        f"### {section_title}",
                        "",
                    ]
                )
                last_domain = domain
            lines.extend(
                [
                    f"#### {analysis['claim']}",
                    "",
                    (
                        f"**{localized(language, '领域', 'Domain')}{colon}** "
                        f"{domain_labels.get(analysis['domain'], analysis['domain'])} | "
                        f"**{localized(language, '置信度', 'Confidence')}{colon}** "
                        f"{analysis['confidence']:.2f} | "
                        f"**{localized(language, '观点变化', 'State change')}{colon}** "
                        f"{state_labels.get(analysis['state_change'], analysis['state_change'])}"
                    ),
                    "",
                    f"**{localized(language, '证据事件', 'Evidence events')}{colon}** "
                    + ", ".join(analysis["evidence_event_ids"]),
                    "",
                    (
                        f"**{localized(language, '研判类型', 'Assessment types')}{colon}** "
                        + joiner.join(
                            assessment_labels.get(item, item)
                            for item in analysis.get("assessment_types", [])
                        )
                    ),
                    "",
                    (
                        f"**{localized(language, '观察视角', 'Perspectives')}{colon}** "
                        + joiner.join(
                            perspective_labels.get(item, item)
                            for item in analysis.get("perspectives", [])
                        )
                    ),
                    "",
                ]
            )
            for paragraph in split_narrative_paragraphs(analysis.get("narrative")):
                lines.extend([paragraph, ""])
            support_summary = localized(
                language,
                "论证与证据（展开）",
                "Evidence and reasoning (expand)",
            )
            lines.extend(
                [
                    "<details>",
                    f"<summary>{support_summary}</summary>",
                    "",
                    f"**{localized(language, '事实基础', 'Facts')}{colon}**",
                    "",
                ]
            )
            lines.extend(f"- {item}" for item in analysis.get("facts", []))
            for key, chinese_label, english_label in (
                ("historical_context", "历史脉络", "Historical context"),
                ("dialectical_analysis", "辩证分析", "Dialectical analysis"),
            ):
                if value := analysis.get(key):
                    label = localized(language, chinese_label, english_label)
                    lines.extend([f"**{label}{colon}** {value}", ""])
            if analysis.get("stakeholder_positions"):
                lines.extend(
                    [
                        f"**{stakeholder_positions_label}{colon}**",
                        "",
                    ]
                )
                lines.extend(
                    f"- **{position['stakeholder']}{colon}** {position['position']} "
                    f"{localized(language, '利益基础', 'Interest basis')}{colon}"
                    f"{position['interests']}"
                    for position in analysis["stakeholder_positions"]
                )
            lines.extend(
                [
                    "",
                    f"**{localized(language, '推理链', 'Reasoning chain')}{colon}** "
                    f"{analysis.get('reasoning', '')}",
                    "",
                ]
            )
            for key, chinese_label, english_label, optional in (
                ("counter_evidence", "反证与不确定性", "Counterevidence and uncertainty", False),
                ("scenarios", "可能情景", "Scenarios", False),
                ("implications", "影响与启示", "Implications", False),
                ("actions", "建议行动", "Recommended actions", False),
                ("watch_signals", "后续观察信号", "Watch signals", False),
                ("invalidation_signals", "观点失效信号", "Invalidation signals", False),
                ("causal_chain", "因果传导链", "Causal chain", True),
                ("assumptions", "关键假设", "Key assumptions", True),
                ("evidence_gaps", "证据缺口", "Evidence gaps", True),
            ):
                values = analysis.get(key, [])
                if optional and not values:
                    continue
                if key != "counter_evidence":
                    lines.append("")
                label = localized(language, chinese_label, english_label)
                lines.extend([f"**{label}{colon}**", ""])
                lines.extend(f"- {value}" for value in values)
            for label, value in optional_analysis_prose(analysis, language):
                lines.extend(["", f"**{label}{colon}** {value}"])
            lines.extend(["", "</details>"])
    else:
        lines.append(
            localized(
                language,
                "本版没有形成达到证据门槛的研判。",
                "No analysis met the evidence threshold in this edition.",
            )
        )

    synthesis = report.get("cross_perspective_synthesis")
    if isinstance(synthesis, dict):
        lines.extend(
            [
                "",
                f"### {localized(language, '跨视角综合', 'Cross-Perspective Synthesis')}",
                "",
                synthesis.get("overall_judgment", ""),
                "",
                f"**{localized(language, '共同结论', 'Consensus')}{colon}**",
                "",
            ]
        )
        lines.extend(f"- {item}" for item in synthesis.get("consensus", []))
        lines.extend(
            [
                "",
                f"**{localized(language, '关键分歧', 'Key tensions')}{colon}**",
                "",
            ]
        )
        for tension in synthesis.get("tensions", []):
            if not isinstance(tension, dict):
                continue
            perspectives = joiner.join(tension.get("perspectives", []))
            lines.append(
                f"- **{tension.get('issue', '')}** ({perspectives}){colon}"
                f"{tension.get('source_of_difference', '')}"
            )
        for title, key in (
            (
                localized(
                    language,
                    "地缘—技术—市场传导链",
                    "Geopolitics–Technology–Markets Transmission Chain",
                ),
                "transmission_chain",
            ),
            (
                localized(language, "共同观察信号", "Shared watch signals"),
                "shared_watch_signals",
            ),
            (
                localized(language, "必须修正判断的触发条件", "Revision triggers"),
                "revision_triggers",
            ),
        ):
            lines.extend(["", f"**{title}{colon}**", ""])
            lines.extend(f"- {item}" for item in synthesis.get(key, []))
        lines.extend(
            [
                "",
                f"**{localized(language, '综合引用事件', 'Synthesis evidence events')}{colon}** "
                + joiner.join(synthesis.get("evidence_event_ids", [])),
            ]
        )

    for label, values in report_followups(report, language):
        lines.extend(["", f"### {label}", ""])
        lines.extend(f"- {value}" for value in values)

    evaluation = report.get("quality_evaluation")
    show_feedback = evaluation or report.get("schema_version") in BRIEF_REPORT_SCHEMAS
    if show_feedback:
        lines.extend(["", f"## {quality_heading}", ""])
    if evaluation:
        lines.extend(
            [
                f"**{localized(language, '独立评估总分', 'Independent evaluation score')}"
                f"{colon}{evaluation['total_score']}/45**",
                "",
                localized(
                    language,
                    "| 维度 | 得分 | 重点结论 |",
                    "| Dimension | Score | Finding |",
                ),
                "| --- | ---: | --- |",
            ]
        )
        lines.extend(
            f"| {evaluation_labels.get(item['id'], item['id'])} | {item['score']}/5 | "
            f"{item['finding']} |"
            for item in evaluation["dimensions"]
        )
        for title, values in evaluation_findings(evaluation, language):
            lines.extend(["", f"### {title}", ""])
            lines.extend(f"- {value}" for value in values)
    elif show_feedback:
        lines.append(localized(
            language,
            "尚未评分。质量评分默认关闭，仅在用户明确要求时补充。",
            "Not scored. Quality scoring is off by default and runs only "
            "when explicitly requested.",
        ))
    if show_feedback:
        lines.extend(
            [
                "",
                f"### {localized(language, '用户反馈', 'Reader Feedback')}",
                "",
                f"- {localized(language, '相关性', 'Relevance')}{colon}__/5",
                f"- {localized(language, '准确性', 'Accuracy')}{colon}__/5",
                f"- {localized(language, '分析价值', 'Analysis value')}{colon}__/5",
                f"- {localized(language, '整体满意度', 'Overall satisfaction')}{colon}__/5",
                f"- {localized(language, '补充意见', 'Additional comments')}{colon}",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def save_report(
    input_path: Path,
    index_path: Path,
    data_dir: Path,
    output_config: OutputConfig | None = None,
    media_config: MediaConfig | None = None,
    coverage_targets: dict[str, int] | None = None,
    brief_plan_item_ids: dict[str, list[str]] | None = None,
    refresh_images: bool = False,
) -> dict[str, Any]:
    """编译模型报告草稿、绑定权威索引、执行校验并创建不可变报告修订。
    输入：本次运行的数据根。
    - ``input_path``：待编译的模型报告草稿 JSON 路径；其日期、版本和条目必须与索引一致。
    - ``index_path``：草稿所引用的不可变来源索引路径；用于恢复权威身份并验证证据。
    - ``output_config``：本地 HTML、PDF、桌面交付和打开行为配置。
    - ``media_config``：图片下载、格式、安全、缓存和报告预算配置。
    - ``coverage_targets``：按来源 ID 指定的最小报告覆盖数；由运行情境拥有。
    - ``brief_plan_item_ids``：当前 context 按来源固定的有序 default_item_ids；限制缓存与草稿边界。
    - ``refresh_images``：显式重新选择图片；默认文字修订保留其已发布父版本的有效本地附件。
    输出：已保存的报告版本、交付文件路径和各阶段处理时间。
    """
    save_started = time.perf_counter()
    raw = read_json(input_path)
    index = read_json(index_path)
    if not isinstance(raw, dict):
        raise ValueError("Report must be a JSON object")
    if not isinstance(index, dict):
        raise ValueError("Index must be a JSON object")

    report = deepcopy(raw)
    report.setdefault("date", index.get("date"))
    report.setdefault("edition", index.get("edition"))
    date = str(report["date"])
    edition = str(report["edition"])
    if date != str(index.get("date")) or edition != str(index.get("edition")):
        raise ValueError(
            "Report date and edition must match the source index: "
            f"report={date}/{edition}, "
            f"index={index.get('date')}/{index.get('edition')}"
        )
    report_dir = data_dir / "reports" / date
    revision = next_revision(report_dir, edition)
    report["revision"] = revision
    report["report_id"] = f"daily-{date}-{edition}-r{revision}"

    compile_started = time.perf_counter()
    # 先把模型草稿编译进确定性外壳，再统一规范化和校验。
    compile_warnings = compile_report_data(
        report,
        index,
        load_semantic_cache(data_dir),
        brief_plan_item_ids=brief_plan_item_ids,
    )
    normalize_report_data(report, index)
    evaluation = report.get("quality_evaluation")
    if isinstance(evaluation, dict):
        evaluation["evaluated_report_id"] = report["report_id"]

    events_path = data_dir / "state" / "events.json"
    existing_events: list[dict[str, Any]] = []
    if events_path.exists():
        existing_payload = read_json(events_path)
        if isinstance(existing_payload, dict) and isinstance(existing_payload.get("items"), list):
            existing_events = [
                item for item in existing_payload["items"] if isinstance(item, dict)
            ]

    # 在触发网络图片处理前拒绝语义和来源身份错误，避免无效草稿产生外部副作用。
    errors, pre_media_validation_warnings = validate_report_data(
        report,
        index,
        existing_events,
        coverage_targets=coverage_targets,
        brief_plan_item_ids=brief_plan_item_ids,
    )
    if errors:
        raise ValueError("Report validation failed: " + "; ".join(errors))
    compile_validation_seconds = time.perf_counter() - compile_started

    media_started = time.perf_counter()
    preserved_images = None
    previous_path = report_dir / f"{edition}-r{raw.get('revision')}.json"
    if not refresh_images and previous_path.is_file():
        previous = read_json(previous_path)
        if raw.get("report_id") == previous.get("report_id"):
            preserved_images = {str(brief["item_id"]): brief.get("image")
                                for section in previous["sections"]
                                for brief in section.get("briefs", [])}
    media_warnings = materialize_report_images(
        report,
        index,
        data_dir,
        media_config or MediaConfig(),
        preserved_images=preserved_images,
    )
    media_seconds = time.perf_counter() - media_started
    errors, final_validation_warnings = validate_report_data(
        report,
        index,
        existing_events,
        coverage_targets=coverage_targets,
        brief_plan_item_ids=brief_plan_item_ids,
    )
    warnings = list(
        dict.fromkeys(
            [
                *compile_warnings,
                *media_warnings,
                *pre_media_validation_warnings,
                *final_validation_warnings,
            ]
        )
    )
    if errors:
        raise ValueError(
            "Report validation failed after media binding: " + "; ".join(errors)
        )

    persistence_started = time.perf_counter()
    json_path = report_dir / f"{edition}-r{revision}.json"
    markdown_path = report_dir / f"{edition}-r{revision}.md"
    # JSON 是权威记录，Markdown/HTML/PDF 都是可由它重新生成的投影。
    write_immutable_json(json_path, report)
    write_text_atomic(
        markdown_path,
        render_report_markdown(report, media_path_prefix="../.."),
    )
    write_json(data_dir / "reports" / f"latest-{edition}.json", report)
    persistence_seconds = time.perf_counter() - persistence_started

    local_output_started = time.perf_counter()
    try:
        local_outputs = write_local_outputs(
            report,
            data_dir,
            output_config or OutputConfig(),
        )
    except Exception as exc:
        warning = (
            "Local HTML/PDF projection failed after JSON/Markdown persistence: "
            f"{type(exc).__name__}: {exc}"
        )
        local_outputs = {"local_output_error": warning, "warnings": [warning]}
    local_output_seconds = time.perf_counter() - local_output_started
    warnings.extend(local_outputs.pop("warnings", []))

    state_started = time.perf_counter()
    semantic_cache_path = None
    state_paths: dict[str, Any] = {}
    try:
        # 报告已经安全持久化；派生语义/连续性状态失败只降级为警告，不回滚记录。
        semantic_cache_path = update_semantic_cache_from_report(report, index, data_dir)
        state_paths = (
            update_continuity_state(report, data_dir)
            if (
                report.get("quality_evaluation")
                or report.get("schema_version") not in BRIEF_REPORT_SCHEMAS
            )
            else {}
        )
    except Exception as exc:
        warnings.append(
            "Derived semantic/continuity state update failed after report persistence: "
            f"{type(exc).__name__}: {exc}"
        )
    state_seconds = time.perf_counter() - state_started
    save_metrics = {
        "compile_and_validation_seconds": round(compile_validation_seconds, 3),
        "media_seconds": round(media_seconds, 3),
        "persistence_seconds": round(persistence_seconds, 3),
        "local_output_seconds": round(local_output_seconds, 3),
        "state_update_seconds": round(state_seconds, 3),
        "total_seconds": round(time.perf_counter() - save_started, 3),
    }

    return {
        "report_id": report["report_id"],
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
        **local_outputs,
        "warnings": warnings,
        "state_paths": state_paths,
        "content_hash": report_content_hash(report),
        "evaluation_status": report.get("evaluation_status", "completed"),
        **(
            {"semantic_cache_path": str(semantic_cache_path)}
            if semantic_cache_path is not None
            else {}
        ),
        "save_metrics": save_metrics,
    }


def _evaluation_semantic_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """移除独立评估的分配身份和落盘时间以识别语义重放。
    输入：``payload``：评估草稿或不可变评估修订；内容已由本地 JSON 解析器读取。
    输出：不含 evaluation_id/evaluated_at 的新字典；不同评分或结论仍保持可区分。
    """

    comparable = dict(payload)
    comparable.pop("evaluation_id", None)
    comparable.pop("evaluated_at", None)
    return comparable


def _evaluation_history(
    directory: Path, edition: str, candidate: dict, report_id: str, content_hash: str,
) -> tuple[tuple[Path, dict] | None, Path | None]:
    """处理：一次扫描该版评估历史，定位语义匹配和同报告的最新修订。
    输入：评估目录、版次、候选草稿和被评报告的身份。
    输出：最近匹配的草稿修订及同报告的最近评估路径。
    """
    expected = _evaluation_semantic_payload(candidate)
    matching = None
    latest = None
    matched_revision = latest_revision = -1
    for path in directory.glob(f"{edition}-r*.json"):
        existing = read_json(path)
        if not isinstance(existing, dict):
            continue
        same_evaluation = _evaluation_semantic_payload(existing) == expected
        same_report = (
            existing.get("evaluated_report_id") == report_id
            and existing.get("evaluated_content_hash") == content_hash
        )
        if same_evaluation or same_report:
            revision = int(path.stem.rsplit("-r", 1)[1])
            if same_evaluation and revision > matched_revision:
                matching, matched_revision = (path, existing), revision
            if same_report and revision > latest_revision:
                latest, latest_revision = path, revision
    return matching, latest


def _completed_evaluation_replay(
    run: dict, report_id: str, content_hash: str, evaluation_path: Path, evaluation: dict,
) -> dict | None:
    """处理：识别已完成运行对相同评估草稿的无副作用重放。
    输入：本版运行清单、报告身份及匹配的评估修订。
    输出：已交付时返回原评估与现有投影位置，否则为空。
    """
    state = run.get("evaluation")
    artifacts = run.get("artifacts", {})
    if (
        not isinstance(state, dict)
        or state.get("status") != "completed"
        or state.get("evaluation_id") != evaluation.get("evaluation_id")
        or state.get("content_hash") != content_hash
        or not isinstance(artifacts, dict)
        or artifacts.get("report_id") != report_id
    ):
        return None
    local_keys = {
        "html_path",
        "pdf_path",
        "desktop_html_path",
        "desktop_pdf_path",
        "local_index_path",
    }
    local_outputs = {key: value for key, value in artifacts.items() if key in local_keys}
    return {
        "status": "already_completed",
        "evaluation_id": evaluation["evaluation_id"],
        "evaluation_path": str(evaluation_path),
        "content_hash": content_hash,
        "state_paths": {},
        "local_outputs": local_outputs,
    }


def save_evaluation(
    input_path: Path,
    report_path: Path,
    data_dir: Path,
    output_config: OutputConfig | None = None,
) -> dict[str, Any]:
    """校验独立评估与报告身份和内容哈希一致后，创建不可变评估修订。
    输入：版本化报告路径、本次运行的数据根。
    - ``input_path``：上游阶段生成的输入文件路径；读取前会执行存在性或数据根校验。
    - ``output_config``：本地 HTML、PDF、桌面交付和打开行为配置。
    输出：评估版本与绑定的报告，以及本次更新的连续性和本地产物。
    """
    raw = read_json(input_path)
    report = read_json(report_path)
    if not isinstance(raw, dict) or not isinstance(report, dict):
        raise ValueError("Evaluation and report must both be JSON objects")
    date = str(report["date"])
    edition = str(report["edition"])
    # 与 prepare/restart/finalize 共用 edition 锁，避免旧 evaluator 与新 attempt
    # 交错推进 run、continuity、semantic cache 或本地投影。
    lock_path = data_dir / "locks" / f"{date}-{edition}.lock"
    with exclusive_lock(
        lock_path,
        {
            "date": date,
            "edition": edition,
            "locked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        },
    ):
        return _save_evaluation_locked(
            dict(raw),
            report,
            data_dir,
            output_config,
        )


def _save_evaluation_locked(
    candidate: dict[str, Any],
    report: dict[str, Any],
    data_dir: Path,
    output_config: OutputConfig | None,
) -> dict[str, Any]:
    """处理：在日期版本排他锁内提交评估修订并推进全部派生状态。
    输入：
    - ``candidate``：已读取的独立评估草稿；只在锁内分配不可变修订身份。
    - ``report``：对应的本地权威报告；提供日期、版本和内容哈希。
    - ``data_dir``：当前运行的唯一数据根；锁、修订和派生状态均位于其中。
    - ``output_config``：本地 HTML、PDF、桌面交付和打开行为配置。
    输出：新建或无副作用重放的评估结果；mutable 指针与运行状态在同一锁内推进。
    """

    date = str(report["date"])
    edition = str(report["edition"])
    evaluation_dir = data_dir / "evaluations" / date
    run_path = data_dir / "runs" / date / f"{edition}.json"
    run = read_json(run_path) if run_path.is_file() else None
    artifacts = run.get("artifacts") if isinstance(run, dict) else None
    report_id = report["report_id"]
    content_hash = report_content_hash(report)
    current_report = (
        isinstance(artifacts, dict) and artifacts.get("report_id") == report_id
        and artifacts.get("content_hash") == content_hash
    )
    matching, latest = _evaluation_history(
        evaluation_dir, edition, candidate, report_id, content_hash,
    )
    if matching is not None:
        output, evaluation = matching
        errors = validate_evaluation_data(evaluation, report)
        if errors:
            raise ValueError("Evaluation validation failed: " + "; ".join(errors))
        if isinstance(run, dict) and (replay := _completed_evaluation_replay(
            run, report_id, content_hash, output, evaluation,
        )):
            return replay
    recover_existing = matching is not None and current_report and matching[0] == latest
    if recover_existing:
        output, evaluation = matching
    else:
        # 命中非当前历史语义时仍创建新修订，避免 A→B→A 回放把状态退回 r1。
        evaluation = candidate
        revision = next_revision(evaluation_dir, edition)
        evaluation["evaluation_id"] = f"evaluation-{report['report_id']}-r{revision}"
        evaluation.setdefault(
            "evaluated_at",
            datetime.now().astimezone().isoformat(timespec="seconds"),
        )
        errors = validate_evaluation_data(evaluation, report)
        if errors:
            raise ValueError("Evaluation validation failed: " + "; ".join(errors))
        output = evaluation_dir / f"{edition}-r{revision}.json"
        write_immutable_json(output, evaluation)

    if not current_report:
        return {
            "status": "stale_report",
            "evaluation_id": evaluation["evaluation_id"],
            "evaluation_path": str(output),
            "content_hash": content_hash,
            "state_paths": {},
            "local_outputs": {},
        }

    write_json(data_dir / "evaluations" / f"latest-{edition}.json", evaluation)
    semantic_cache_path = finalize_semantic_cache_evaluation(evaluation, data_dir)
    assessed_report = dict(report)
    assessed_report["quality_evaluation"] = evaluation
    state_paths = update_continuity_state(assessed_report, data_dir)
    local_outputs = write_local_outputs(
        report,
        data_dir,
        output_config or OutputConfig(),
        evaluation=evaluation,
        open_after_finalize=False,
        regenerate_pdf=False,
    )
    run["evaluation"] = {
        "status": "completed",
        "report_id": report_id,
        "evaluation_id": evaluation["evaluation_id"],
        "evaluation_path": str(output),
        "content_hash": content_hash,
    }
    artifacts.update({key: value for key, value in local_outputs.items() if key.endswith("_path")})
    write_json(run_path, run)
    return {
        "evaluation_id": evaluation["evaluation_id"],
        "evaluation_path": str(output),
        "content_hash": content_hash,
        "state_paths": state_paths,
        "local_outputs": local_outputs,
        **({"semantic_cache_path": str(semantic_cache_path)} if semantic_cache_path else {}),
    }
