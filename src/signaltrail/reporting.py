from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator
from copy import deepcopy
from datetime import date, datetime
from functools import lru_cache
from itertools import chain
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from jsonschema import Draft202012Validator, FormatChecker

from .article_time import original_publication_time
from .config import canonical_source_page_url, project_root
from .localization import (
    OUTPUT_LANGUAGES,
    brief_title_requires_translation,
    is_chinese_output,
    localized,
    text_matches_output_language,
    translated_title,
    translated_title_field,
)
from .models import effective_page_results, effective_source_status
from .semantics import (
    brief_requires_watch,
    reusable_semantic_brief,
    semantic_fingerprint,
    tldr_quality_issue,
)
from .state import stable_analysis_id
from .taxonomy import (
    SECTION_GROUPS_V13,
    SECTION_ID_ALIASES_V15,
    SECTION_ORDER_V13,
    canonical_section_id,
    required_section_ids,
    section_titles,
    validate_content_taxonomy,
)
from .utils import canonicalize_url, now_iso, read_json

MAX_FEATURED_EVENTS = 12
CURRENT_REPORT_SCHEMA = "2.0"
BRIEF_REPORT_SCHEMAS = {"1.5", "2.0"}
_SOURCE_GROUP_SCHEMAS = BRIEF_REPORT_SCHEMAS | {"1.4"}
_DAILY_SCHEMAS = _SOURCE_GROUP_SCHEMAS | {"1.3"}
_FRESHNESS_SCHEMAS = _DAILY_SCHEMAS | {"1.2"}
_STRICT_SCHEMAS = _FRESHNESS_SCHEMAS | {"1.1"}
IMPORTANCE_CAPS = {
    "impact": 30,
    "freshness": 15,
    "relevance": 15,
    "source_quality": 15,
    "corroboration": 10,
    "novelty": 10,
    "continuity": 5,
}
ANALYSIS_DOMAIN_REQUIREMENTS = {
    "geopolitics": {
        "perspectives": ["geopolitics", "china_standpoint", "western_standpoint"],
        "assessment_types": ["trend", "risk"],
    },
    "ai_technology": {
        "perspectives": ["ai_research_engineering"],
        "assessment_types": ["trend", "learning_research"],
    },
    "markets": {
        "perspectives": ["equity_analysis"],
        "assessment_types": ["trend", "risk"],
    },
}

CONTENT_STATUS_TO_ACCESS = {
    "not_fetched": "metadata_only",
    "failed": "metadata_only",
    "metadata_only": "metadata_only",
    "partial": "partial",
    "full_text": "full_text",
    "verification_required": "verification_required",
}

_CJK_PATTERN = re.compile(r"[\u3400-\u9fff]")
_NUMERIC_SCENARIO_PATTERN = re.compile(
    r"(?:\d+(?:\.\d+)?\s*%|[$¥￥]\s*\d|\d+(?:\.\d+)?\s*(?:美元|元|亿|万亿)|"
    r"\d+(?:\.\d+)?\s*[-—–至]\s*\d+(?:\.\d+)?)"
)
_LANGUAGE_MARKER_PATTERN = re.compile(r"^\s*\[(?:英|英文|EN|中|中文|ZH)\]\s*", re.I)
_TRANSLATION_PREFIX_PATTERN = re.compile(
    r"^\s*(?:\[[^\]\r\n]{1,40}\]|【[^】\r\n]{1,40}】)\s*[:：-]?\s*"
)
_CHINESE_BRIEF_TITLE_SUFFIX = {
    "cna_mainland": re.compile(
        r"(?:\s*\|\s*(?:兩岸|两岸|政治))?\s*\|\s*(?:中央社\s+CNA|CNA|中央社)\s*$", re.I,
    ),
    "rthk_finance_alt": re.compile(r"\s*[-–—|]\s*(?:RTHK|香港[电電][台臺])\s*$", re.I),
}
_UNREAD_BODY_MARKERS = (
    "未读取正文",
    "正文尚未读取",
    "仅依据标题",
    "仅依据元数据",
    "body was not read",
    "body not fetched",
    "based only on the title",
    "based only on metadata",
)


def ordered_sections(
    report: dict[str, Any], module: str, *, preserve_extra: bool = False,
) -> list[dict[str, Any]]:
    """处理：按报告契约读取栏目，供发布视图共用。
    输入：报告、栏目组及本地视图是否保留历史自定义栏目。
    输出：规范栏目按契约顺序排列，旧版栏目沿用各投影的历史顺序。
    """
    values = report.get("sections", []) if preserve_extra else report["sections"]
    sections = [section for section in values if section.get("module") == module]
    if preserve_extra:
        by_id = {str(section.get("id")): section for section in sections}
    else:
        if report.get("schema_version") not in {"1.3", "1.4", "1.5", "2.0"}:
            return sections
        by_id = {section["id"]: section for section in sections}
    ordered = [by_id[key] for key in SECTION_GROUPS_V13[module] if key in by_id]
    if preserve_extra:
        ordered.extend(section for section in sections if section not in ordered)
    return ordered


def group_items_by_source(
    section: dict[str, Any], language: object = "zh-CN", *, local: bool = False,
) -> list[tuple[dict[str, Any], list[dict]]]:
    """处理：按来源组织已编译栏目，保留简报和来源首次出现顺序。
    输入：报告栏目、显示语言及本地视图对旧记录的回退规则。
    输出：按来源分组的简报，供 Markdown 和本地发布视图使用。
    """
    values = section.get("briefs") if "briefs" in section else section.get("items", [])
    groups: dict[str, tuple[dict[str, Any], list[dict]]] = {}
    for item in values or []:
        source = item.get("primary_source")
        if (local and not isinstance(source, dict)) or (not local and not source):
            refs = item.get("source_refs") or [item.get("source_ref", {})]
            source = {
                "id": "unknown",
                "name": localized(language, "未知来源", "Unknown source"),
                "url": (refs[0] or {}).get("url", "#") if local else refs[0]["url"],
            }
        key = (source.get("id") or source.get("name") or "unknown") if local else source["id"]
        groups.setdefault(str(key), (source, []))[1].append(item)
    return list(groups.values())


def optional_analysis_prose(
    analysis: dict[str, Any], language: object,
) -> Iterator[tuple[str, str]]:
    """处理：读取有正文的可选研判说明，沿用发布视图的共同标题。
    输入：已编译研判与目标语言。
    输出：按合同顺序排列的说明标题和原文。
    """
    for key, chinese, english in (
        ("time_horizon", "时间跨度", "Time horizon"),
        ("confidence_rationale", "置信度依据", "Confidence rationale"),
        ("change_from_prior", "相对上一版", "Change from prior"),
        ("decision_relevance", "决策相关性", "Decision relevance"),
    ):
        if value := analysis.get(key):
            yield localized(language, chinese, english), value


def report_followups(
    report: dict[str, Any], language: object,
) -> Iterator[tuple[str, list[str]]]:
    """处理：按固定顺序读取日报新增变动和次日观察。
    输入：已编译日报和显示语言。
    输出：有条目的相关栏目标题及正文。
    """
    for key, chinese, english in (
        ("changes", "日间新增、确认与修正", "New, Confirmed, and Revised Since Morning"),
        ("tomorrow_watch_items", "次日观察项", "Next-Day Watch List"),
    ):
        if items := report.get(key):
            yield localized(language, chinese, english), items


def split_narrative_paragraphs(value: object) -> list[str]:
    """处理：返回作者正文段落，不把自动换行误判为结构。
    输入：待解析的值。
    输出：“返回作者正文段落，不把自动换行误判为结构”得到的字符串列表；
      顺序保持确定并可供下一步骤逐项处理。
    """

    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    return [
        re.sub(r"[ \t]*\n[ \t]*", " ", paragraph).strip()
        for paragraph in re.split(r"\n[ \t]*\n+", text)
        if paragraph.strip()
    ]


_REPORT_REVISION_PATTERN = re.compile(r"^(.+)-r\d+$")
EVALUATION_DIMENSION_ORDER = (
    "coverage",
    "importance_ordering",
    "factual_reliability",
    "summary_accuracy",
    "analysis_traceability",
    "historical_continuity",
    "readability",
    "timeliness",
    "compliance_boundaries",
)
EVALUATION_DIMENSIONS = set(EVALUATION_DIMENSION_ORDER)
REQUIRED_PERSPECTIVES = {
    "geopolitics",
    "ai_research_engineering",
    "equity_analysis",
    "china_standpoint",
    "western_standpoint",
}


def _report_series_id(report_id: object) -> str | None:
    """处理：根据日期和版本生成跨修订稳定的报告系列 ID。
    输入：
    - ``report_id``：报告或报告系列的稳定 ID；用于推导跨修订关联键。
    输出：封装“根据日期和版本生成跨修订稳定的报告系列 ID”业务结果的 ``str | None`` 对象；
      调用方据此继续相邻阶段或识别无结果状态。
    """
    match = _REPORT_REVISION_PATTERN.fullmatch(str(report_id or ""))
    return match.group(1) if match else None


def evaluation_continuity_floor(
    evaluation: dict[str, Any],
) -> tuple[str, set[str], str | None]:
    """处理：对评估器的复用决定应用确定性的污染防护门槛。
    输入：独立质量评估。
    输出：“对评估器的复用决定应用确定性的污染防护门槛”得到的固定结构结果；
      返回位置依次对应 decision、excluded、None。
    """
    decision = str(evaluation.get("continuity_decision", "selective"))
    raw_excluded = evaluation.get("exclude_from_continuity", [])
    excluded = set(raw_excluded) if isinstance(raw_excluded, list) else set()
    dimensions = evaluation.get("dimensions", [])
    scores_by_id = {
        str(item.get("id")): int(item["score"])
        for item in dimensions
        if isinstance(item, dict) and isinstance(item.get("score"), int)
    }
    critical_ids = {
        "factual_reliability",
        "summary_accuracy",
        "analysis_traceability",
        "compliance_boundaries",
    }
    low_critical = sorted(
        dimension_id
        for dimension_id in critical_ids
        if scores_by_id.get(dimension_id, 5) <= 2
    )
    total_score = evaluation.get("total_score")
    reject_required = (
        isinstance(total_score, int) and total_score <= 22
    ) or len(low_critical) >= 3
    if reject_required:
        if decision == "reject" and "all" in excluded:
            return decision, excluded, None
        return (
            "reject",
            {"all"},
            "continuity must reject all content when total_score <= 22 or at least "
            "three critical dimensions score <= 2",
        )

    required_exclusions: set[str] = set()
    if scores_by_id.get("summary_accuracy", 5) <= 2:
        required_exclusions.add("event_summaries")
    if scores_by_id.get("factual_reliability", 5) <= 2:
        required_exclusions.add("source_access")
    if decision == "accept" and (
        (isinstance(total_score, int) and total_score < 32) or low_critical
    ):
        if not required_exclusions:
            required_exclusions.update({"event_summaries", "analyses"})
        return (
            "selective",
            excluded | required_exclusions,
            "continuity cannot accept a report with total_score < 32 or a critical "
            f"dimension score <= 2: {low_critical}",
        )
    if decision == "selective":
        effective_excluded = excluded | required_exclusions
        if not effective_excluded:
            effective_excluded.add("event_summaries")
        if effective_excluded != excluded:
            return (
                decision,
                effective_excluded,
                "selective continuity requires explicit exclusions for low-quality fields",
            )
    return decision, excluded, None


def content_status_to_access(status: str | None) -> str | None:
    """处理：把正文采集状态映射为报告来源访问级别。
    输入：
    - ``status``：当前操作或来源状态；值必须属于对应的显式状态模型。
    输出：封装“把正文采集状态映射为报告来源访问级别”业务结果的 ``str | None`` 对象；
      调用方据此继续相邻阶段或识别无结果状态。
    """
    if status is None:
        return None
    return CONTENT_STATUS_TO_ACCESS.get(str(status))


def reference_time_fields(
    indexed: dict[str, Any],
    source: dict[str, Any] | None = None,
    fallback_collected_at: object | None = None,
) -> dict[str, str]:
    """处理：返回唯一权威展示时间，且不改变新鲜度语义。
    输入：带入口与筛选规则的来源配置。
    - ``indexed``：权威来源索引中与当前 item_id 对应的条目记录。
    - ``fallback_collected_at``：索引级采集时间；仅在条目没有发布时间和发现时间时作为展示回退。
    输出：“返回唯一权威展示时间，且不改变新鲜度语义”形成的结构化字典；
      典型键包括 collected_at、published_at。
    """
    # 选材和展示均采用出版方原发时间；发现平台的时间只说明上榜或收录。
    published_at = original_publication_time(indexed)
    if published_at:
        return {"published_at": published_at}
    source = source or {}
    collected_at = str(
        indexed.get("discovered_at")
        or source.get("collected_at")
        or fallback_collected_at
        or ""
    ).strip()
    return {"collected_at": collected_at} if collected_at else {}


def reference_time_label(
    ref: dict[str, Any],
    output_language: object = "zh-CN",
) -> tuple[str, str] | None:
    """处理：选择读者可见的时间标签，并优先使用实际发布时间。
    输入：报告目标语言。
    - ``ref``：报告条目的 reference_time 对象；包含时间值、类型和是否为回退。
    输出：“选择读者可见的时间标签，并优先使用实际发布时间”得到的固定结构结果；
      返回位置依次对应 localized(output_language, '发布时间、published_at。
    """
    published_at = str(ref.get("published_at") or "").strip()
    if published_at:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", published_at):
            return localized(output_language, "发布日期", "Publication date"), published_at
        return localized(output_language, "发布时间", "Published"), published_at
    collected_at = str(ref.get("collected_at") or "").strip()
    if collected_at:
        return localized(output_language, "采集时间", "Collected"), collected_at
    return None


def _require_output_language(
    value: object,
    location: str,
    errors: list[str],
    language: object = "zh-CN",
) -> None:
    """处理：从报告对象读取输出语言，并在不属于受支持语言集合时记录校验错误。
    输入：待解析的值、输出语言。
    - ``location``：当前校验字段的 JSON 路径；用于生成可定位的错误消息。
    - ``errors``：已收集的校验错误列表；调用方可一次性修复。
    输出：不返回新数据；完成“从报告对象读取输出语言，并在不属于受支持语言集合时记录校验错误”，
      副作用限于该处理声明的受控对象或产物。
    """
    if isinstance(value, str) and value.strip() and not text_matches_output_language(
        value, language
    ):
        name = localized(language, "Chinese", "English")
        errors.append(f"{location}: published user-facing text must contain {name}")


def _normalize_brief_title(
    brief: dict[str, Any],
    indexed: dict[str, Any],
    output_language: object,
) -> None:
    """处理：保留索引原题，并只保留一个目标语言译题。
    输入：报告目标语言。
    - ``brief``：模型生成或缓存复用的单条简报；包含标题、摘要、重要性、证据和条目 ID。
    - ``indexed``：权威来源索引中与当前 item_id 对应的条目记录。
    输出：不返回新数据；完成“保留索引原题，并只保留一个目标语言译题”，
      副作用限于该处理声明的受控对象或产物。
    """
    original_title = str(indexed.get("title") or "").strip()
    if not original_title:
        return
    translation_field = translated_title_field(output_language)
    other_field = "title_en" if translation_field == "title_zh" else "title_zh"
    drafted_title = _LANGUAGE_MARKER_PATTERN.sub(
        "", str(brief.get("title") or "").strip()
    )
    drafted_translation = _TRANSLATION_PREFIX_PATTERN.sub(
        "", str(brief.get(translation_field) or "").strip()
    )
    brief["title"] = original_title
    brief.pop(other_field, None)
    if not brief_title_requires_translation(indexed, output_language):
        brief.pop(translation_field, None)
        return
    if not text_matches_output_language(
        drafted_translation, output_language
    ) and text_matches_output_language(drafted_title, output_language):
        drafted_translation = drafted_title
    if translation_field == "title_zh" and (
        source_suffix := _CHINESE_BRIEF_TITLE_SUFFIX.get(indexed.get("source_id"))
    ):
        drafted_translation = source_suffix.sub("", drafted_translation).strip()
    if text_matches_output_language(drafted_translation, output_language):
        brief[translation_field] = drafted_translation
    else:
        brief.pop(translation_field, None)


@lru_cache(maxsize=4)
def _report_schema_validator(contents: bytes) -> Draft202012Validator:
    """处理：解析并复用同一份日报 Schema 的校验器。
    输入：当前生效的 Schema 文件字节，修改后的资源具有新缓存键。
    输出：使用标准 Draft 2020-12 规则和格式校验的实例。
    """
    return Draft202012Validator(json.loads(contents), format_checker=FormatChecker())


def _schema_errors(report: object) -> list[str]:
    """处理：使用 JSON Schema 收集并格式化结构错误。
    输入：含栏目和来源引用的报告。
    输出：可操作的校验错误消息列表；空列表表示通过当前规则。
    """
    schema_path = project_root() / "schemas" / "report.schema.json"
    validator = _report_schema_validator(schema_path.read_bytes())
    errors: list[str] = []
    for error in sorted(validator.iter_errors(report), key=lambda item: list(item.absolute_path)):
        location = "$"
        for part in error.absolute_path:
            location += f"[{part}]" if isinstance(part, int) else f".{part}"
        errors.append(f"{location}: {error.message}")
    return errors


def _publication_date(value: object, timezone: str) -> date | None:
    """处理：从条目或来源引用中读取规范发布日期。
    输入：待解析的值、用于解释本地日期的 IANA 时区。
    输出：封装“从条目或来源引用中读取规范发布日期”业务结果的 ``date | None`` 对象；
      调用方据此继续相邻阶段或识别无结果状态。
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return date.fromisoformat(text)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(ZoneInfo(timezone))
        return parsed.date()
    except (ValueError, KeyError):
        return None


def _freshness_cap(age_days: int) -> int:
    """处理：按信息年龄和采集状态计算时效分上限。
    输入：
    - ``age_days``：条目参考时间距报告时间的完整天数；用于限制可分配的重要性。
    输出：上述规则计算出的计数、分数、排名或限制值，供确定性决策使用。
    """
    if age_days <= 0:
        return 15
    if age_days == 1:
        return 13
    if age_days <= 3:
        return 8
    if age_days <= 7:
        return 4
    return 1


def hydrate_report_evidence(report: dict, index: dict | None) -> None:
    """处理：用权威索引回填报告简报的来源身份、引用时间和正文证据，拒绝未知条目。
    输入：含栏目和来源引用的报告、规范来源索引。
    输出：不返回新数据；完成“用权威索引回填报告简报的来源身份、引用时间和正文证据，
      拒绝未知条目”，副作用限于该处理声明的受控对象或产物。
    """
    if not isinstance(index, dict):
        return
    sources = {
        row.get("source_id"): row
        for row in index.get("sources", [])
        if isinstance(row, dict) and row.get("source_id")
    }
    items = {
        row.get("item_id"): row
        for row in index.get("items", [])
        if isinstance(row, dict) and row.get("item_id")
    }
    for section in report.get("sections", []):
        for brief in section.get("briefs", []):
            indexed = items.get(brief.get("item_id"), {})
            if not indexed:
                continue
            _normalize_brief_title(
                brief, indexed, report.get("language") or "zh-CN"
            )
            source = sources.get(indexed.get("source_id"), {})
            ref = brief.setdefault("source_ref", {})
            for key, value in (
                ("item_id", indexed.get("item_id")),
                ("title", indexed.get("title")),
                ("url", indexed.get("url")),
                ("access", content_status_to_access(indexed.get("content_status"))),
                ("role", indexed.get("metadata", {}).get("role", "discovery")),
            ):
                if value is not None:
                    ref.setdefault(key, value)
            ref.pop("published_at", None)
            ref.pop("collected_at", None)
            ref.update(
                reference_time_fields(
                    indexed,
                    source,
                    index.get("generated_at") or report.get("generated_at"),
                )
            )
            brief.setdefault(
                "primary_source",
                {
                    "id": indexed.get("source_id", "unknown"),
                    "name": indexed.get("source_name", "未知来源"),
                    "url": source.get("source_url") or indexed.get("url"),
                },
            )
        for event in section.get("items", []):
            for ref in event.get("source_refs", []):
                indexed = items.get(ref.get("item_id"), {})
                source = sources.get(indexed.get("source_id"), {})
                for key in ("source_id", "source_name"):
                    if indexed.get(key):
                        ref[key] = indexed[key]
                ref.pop("published_at", None)
                ref.pop("collected_at", None)
                ref.update(
                    reference_time_fields(
                        indexed,
                        source,
                        index.get("generated_at") or report.get("generated_at"),
                    )
                )
                if source.get("source_url"):
                    ref["source_url"] = source["source_url"]
            if not event.get("primary_source") and event.get("source_refs"):
                ref = event["source_refs"][0]
                event["primary_source"] = {
                    "id": ref.get("source_id", "unknown"),
                    "name": ref.get("source_name") or ref.get("title", "未知来源"),
                    "url": ref.get("source_url") or ref.get("url"),
                }


def _allocate_importance(total: int, freshness_cap: int) -> tuple[int, dict[str, int]]:
    """处理：把总重要性按约束拆分为影响、时效、可信度等分项。
    输入：
    - ``total``：待分配的重要性总分；算法确定性地分配到各简报。
    - ``freshness_cap``：按内容年龄计算的单条重要性上限。
    输出：“把总重要性按约束拆分为影响、时效、可信度等分项”得到的固定结构结果；
      返回位置依次对应 total、result。
    """
    caps = {**IMPORTANCE_CAPS, "freshness": freshness_cap}
    total = max(0, min(int(total), sum(caps.values())))
    cap_total = sum(caps.values())
    raw = {key: total * cap / cap_total for key, cap in caps.items()}
    result = {key: min(caps[key], int(value)) for key, value in raw.items()}
    remainder = total - sum(result.values())
    order = sorted(
        caps,
        key=lambda key: (raw[key] - int(raw[key]), caps[key]),
        reverse=True,
    )
    while remainder:
        progressed = False
        for key in order:
            if result[key] >= caps[key]:
                continue
            result[key] += 1
            remainder -= 1
            progressed = True
            if not remainder:
                break
        if not progressed:
            break
    return total, result


def _source_rank_label(source_id: str, rank: int, output_language: object) -> str:
    """处理：把来源内排序转换为读者可理解的排名标签。
    输入：稳定来源 ID、报告目标语言。
    - ``rank``：简报或来源在当前栏目中的一基排序号。
    输出：“把来源内排序转换为读者可理解的排名标签”得到的规范字符串，供调用方存储、比较或展示。
    """
    if not is_chinese_output(output_language):
        if source_id == "weibo_hot":
            return f"Trending #{rank}"
        if source_id in {"hacker_news", "lobsters", "github_trending"}:
            return f"List #{rank}"
        return f"Source #{rank}"
    if source_id == "weibo_hot":
        return f"热搜Top{rank}"
    if source_id in {"hacker_news", "lobsters", "github_trending"}:
        return f"榜单Top{rank}"
    return f"来源Top{rank}"


def _pending_from_index(
    index: dict,
    output_language: object = "zh-CN",
) -> list[dict[str, str]]:
    """处理：从索引提取仍需验证或失败的来源记录。
    输入：规范来源索引、报告目标语言。
    输出：“从索引提取仍需验证或失败的来源记录”得到的有序结构化记录；
      典型字段包括 error、note、source_id、source_name、status、url，可直接交给下一阶段。
    """
    pending: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for source in index.get("sources", []):
        if not isinstance(source, dict):
            continue
        source_id = str(source.get("source_id", ""))
        source_name = str(source.get("source_name", source_id))
        page_rows = []
        effective_pages = effective_page_results(source.get("page_results", []))
        for page in effective_pages:
            status = str(page.get("status", ""))
            if status == "no_items" and (
                page.get("error")
                or (
                    isinstance(page.get("http_status"), int)
                    and int(page["http_status"]) >= 400
                )
            ):
                page = {**page, "status": "failed"}
                status = "failed"
            if status in {"verification_required", "rate_limited", "failed"}:
                page_rows.append(page)
        source_status = effective_source_status(source, effective_pages)
        if not page_rows and source_status in {
            "verification_required",
            "rate_limited",
            "failed",
        }:
            page_rows = [
                {
                    "status": source_status,
                    "url": source.get("source_url"),
                    "error": source.get("error"),
                }
            ]
        for page in page_rows:
            url = canonical_source_page_url(
                source_id,
                str(page.get("url") or source.get("source_url") or ""),
            )
            if not url.startswith(("http://", "https://")) or (source_id, url) in seen:
                continue
            seen.add((source_id, url))
            status = str(page.get("status"))
            if status == "rate_limited":
                note = localized(
                    output_language,
                    "来源暂时限制访问；本版保留链接，停止自动重试并等待后续时段",
                    "The source is rate-limiting access; the link is retained for a later run.",
                )
            elif status == "verification_required":
                note = localized(
                    output_language,
                    "需要人工验证；可从验证链接队列打开",
                    "Manual verification is required; open it from the verification queue.",
                )
            else:
                note = localized(
                    output_language,
                    "采集失败；保留链接供人工打开",
                    "Collection failed; the link is retained for manual review.",
                )
            pending.append(
                {
                    "source_id": source_id,
                    "source_name": source_name,
                    "status": status,
                    "note": note,
                    "url": url,
                }
            )
    return pending


def _normalize_draft_sections(value: object) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """处理：规范化列表或映射形式的草稿栏目及已知模型别名。
    输入：待解析的值。
    输出：“规范化列表或映射形式的草稿栏目及已知模型别名”得到的固定结构结果；
      返回位置依次对应 normalized、warnings。
    """
    warnings: list[str] = []
    if value is None:
        entries: list[tuple[str | None, object]] = []
    elif isinstance(value, list):
        entries = [(None, section) for section in value]
    elif isinstance(value, dict):
        entries = [(str(section_id), section) for section_id, section in value.items()]
        warnings.append("sections object mapping was normalized to the canonical section array")
    else:
        raise ValueError(
            "Report draft sections must be an array or an object keyed by section ID"
        )

    normalized: dict[str, dict[str, Any]] = {}
    invalid: list[str] = []
    for position, (mapping_id, raw_section) in enumerate(entries):
        if not isinstance(raw_section, dict):
            raise ValueError(f"Report draft sections[{position}] must be an object")
        draft_id = str(
            raw_section.get("id")
            or mapping_id
            or f"{raw_section.get('module', '')}.{raw_section.get('category', '')}"
        ).strip(".")
        section_id = canonical_section_id(draft_id)
        if section_id not in SECTION_ORDER_V13:
            invalid.append(draft_id or f"sections[{position}]")
            continue
        if section_id != draft_id:
            warnings.append(f"section ID {draft_id!r} was normalized to {section_id!r}")

        target = normalized.setdefault(section_id, {"id": section_id, "briefs": [], "items": []})
        for collection in ("briefs", "items"):
            rows = raw_section.get(collection, [])
            if rows is None:
                rows = []
            if not isinstance(rows, list):
                raise ValueError(
                    f"Report draft section {draft_id!r}.{collection} must be an array"
                )
            target[collection].extend(rows)
        for key, item in raw_section.items():
            if key not in {"id", "module", "category", "title", "briefs", "items"}:
                target[key] = item

    if invalid:
        allowed = ", ".join(SECTION_ORDER_V13)
        aliases = ", ".join(sorted(SECTION_ID_ALIASES_V15))
        raise ValueError(
            "Unsupported report draft section IDs: "
            f"{sorted(invalid)}. Use one of: {allowed}. Accepted legacy aliases: {aliases}"
        )
    return normalized, warnings


def _normalize_draft_analyses(value: object) -> tuple[list[dict[str, Any]], list[str]]:
    """处理：规范化列表或映射形式的分析草稿，不虚构语义内容。
    输入：待解析的值。
    输出：“规范化列表或映射形式的分析草稿，不虚构语义内容”得到的固定结构结果；
      返回位置依次对应 [dict(analysis) for analysis in 、warnings。
    """
    warnings: list[str] = []
    if value is None:
        return [], warnings
    if isinstance(value, list):
        rows = value
    elif isinstance(value, dict):
        rows = []
        for domain, raw_analysis in value.items():
            if not isinstance(raw_analysis, dict):
                raise ValueError(f"Report draft analysis {domain!r} must be an object")
            analysis = dict(raw_analysis)
            analysis.setdefault("domain", str(domain))
            rows.append(analysis)
        warnings.append("analyses object mapping was normalized to the canonical analysis array")
    else:
        raise ValueError("Report draft analyses must be an array or an object keyed by domain")
    if not all(isinstance(analysis, dict) for analysis in rows):
        raise ValueError("Every report draft analysis entry must be an object")
    return [dict(analysis) for analysis in rows], warnings


def _indexed_report_section(item: dict) -> str | None:
    """处理：将来源索引的栏目别名归入报告使用的栏目。
    输入：权威索引条目的模块和类别。
    输出：规范栏目 ID，索引无分类时为空。
    """
    module, category = item.get("module"), item.get("category")
    return canonical_section_id(f"{module}.{category}") if module and category else None


def compile_report_data(
    report: dict,
    index: dict,
    semantic_cache: dict[str, dict[str, Any]] | None = None,
    brief_plan_item_ids: dict[str, list[str]] | None = None,
) -> list[str]:
    """处理：把模型撰写的语义编译进当前确定性报告外壳。
    输入：
    - ``report``：模型生成的报告语义草稿；Python 将补齐身份、来源、排序、计数和约束字段。
    - ``index``：本次运行的权威来源索引；提供条目身份、来源信息、时间和访问证据。
    - ``semantic_cache``：按 item_id 保存且带内容指纹、语言和审核状态的语义缓存。
    - ``brief_plan_item_ids``：当前 context 按来源固定的有序 default_item_ids；传入后
      同时限定缓存复用、草稿保留和最终普通 brief 顺序。
    输出：编译过程中产生的非阻断警告；report 会被就地改造成身份和来源均与索引绑定的确定性报告。
    """
    warnings: list[str] = []
    # 模型只提供语义草稿；schema 版本、来源身份、排序和计数由 Python 确定性补齐。
    report.setdefault("schema_version", CURRENT_REPORT_SCHEMA)
    if report.get("schema_version") not in BRIEF_REPORT_SCHEMAS:
        return warnings
    report.setdefault("date", index.get("date"))
    report.setdefault("edition", index.get("edition"))
    output_language = str(
        report.get("language") or index.get("output_language") or "zh-CN"
    )
    report["language"] = output_language
    edition_label = localized(
        output_language,
        {"daily": "日报", "evening": "晚报", "morning": "晨报"}[report["edition"]],
        {"daily": "Daily Edition", "evening": "Evening Edition",
         "morning": "Morning Edition"}[report["edition"]],
    )
    if not report.get("title"):
        report["title"] = localized(
            output_language,
            f"迹简·{edition_label} — {report.get('date', '')}",
            f"SignalTrail {edition_label} — {report.get('date', '')}",
        )
        warnings.append("missing draft title was filled with the deterministic report title")
    summary = report.get("executive_summary")
    if isinstance(summary, str):
        report["executive_summary"] = [summary]
        warnings.append("executive_summary string was normalized to an array")
    elif not isinstance(summary, list):
        report["executive_summary"] = [
            localized(
                output_language,
                "本版重点见以下资讯、技术与研判。",
                "This edition's key developments and analysis follow.",
            )
        ]
        warnings.append("missing executive_summary was filled with a neutral fallback")
    report["analyses"], analysis_warnings = _normalize_draft_analyses(
        report.get("analyses")
    )
    warnings.extend(analysis_warnings)
    provided_sections, section_warnings = _normalize_draft_sections(report.get("sections"))
    warnings.extend(section_warnings)
    report["generated_at"] = now_iso(str(index.get("timezone", "Asia/Shanghai")))
    report["evaluation_status"] = "pending"
    if report.get("schema_version") == "2.0":
        report["analysis_protocol_version"] = "2.0"
    report.pop("quality_evaluation", None)
    report.setdefault("changes", [])
    report.setdefault("tomorrow_watch_items", [])
    report["pending_verifications"] = _pending_from_index(index, output_language)

    sources, source_positions = {}, {}
    for position, row in enumerate(index.get("sources", [])):
        if isinstance(row, dict) and row.get("source_id"):
            source_id = str(row["source_id"])
            sources[source_id] = row
            source_positions[source_id] = position
    indexed_items: dict[str, dict] = {}
    source_item_counts: Counter[str] = Counter()
    source_item_positions: dict[str, int] = {}
    indexed_section_candidate_counts: Counter[str] = Counter()
    for row in index.get("items", []):
        if not isinstance(row, dict) or not row.get("item_id"):
            continue
        item_id = str(row["item_id"])
        indexed_items[item_id] = row
        source_id = str(row.get("source_id") or "")
        source_item_counts[source_id] += 1
        source_item_positions[item_id] = source_item_counts[source_id]
        source_positions.setdefault(source_id, len(source_positions))
        if section_id := _indexed_report_section(row):
            indexed_section_candidate_counts[section_id] += 1
    normalized_plan = (
        {
            str(source_id): [str(item_id) for item_id in item_ids]
            for source_id, item_ids in brief_plan_item_ids.items()
        }
        if brief_plan_item_ids is not None
        else None
    )
    planned_positions = {
        item_id: position
        for item_ids in (normalized_plan or {}).values()
        for position, item_id in enumerate(item_ids, start=1)
    }
    ordered_plan = sorted(
        (normalized_plan or {}).items(),
        key=lambda row: (source_positions.get(row[0], 1_000_000), row[0]),
    )
    allowed_brief_ids = planned_positions.keys() if normalized_plan is not None else None
    if semantic_cache and normalized_plan is not None:
        existing_ids = {
            str(brief.get("item_id"))
            for section in provided_sections.values()
            for brief in section.get("briefs", [])
            if isinstance(brief, dict) and brief.get("item_id")
        }
        for source_id, planned_ids in ordered_plan:
            for item_id in planned_ids:
                if item_id in existing_ids:
                    continue
                indexed = indexed_items.get(item_id)
                if not indexed or str(indexed.get("source_id") or "") != source_id:
                    continue
                cached = reusable_semantic_brief(
                    indexed,
                    semantic_cache,
                    output_language,
                    reference_date=report.get("date"),
                )
                if not cached:
                    continue
                # 只有 brief_plan 明确授权的条目才能进入当前版本，避免旧缓存越过 Top 窗口。
                section_id = _indexed_report_section(indexed)
                if section_id not in SECTION_ORDER_V13:
                    continue
                target_section = provided_sections.setdefault(
                    section_id, {"id": section_id, "briefs": [], "items": []}
                )
                target_section.setdefault("briefs", []).append(cached)
                existing_ids.add(item_id)
                warnings.append(
                    f"reused approved semantic cache for brief {item_id!r}"
                )
    fallback_ranks: dict[str, int] = {}
    item_ranks: dict[str, int] = {}
    for item in index.get("items", []):
        if not isinstance(item, dict) or not item.get("item_id"):
            continue
        source_id = str(item.get("source_id", ""))
        fallback_ranks[source_id] = fallback_ranks.get(source_id, 0) + 1
        metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
        item_ranks[str(item["item_id"])] = int(
            item.get("source_rank")
            or metadata.get("source_rank")
            or metadata.get("hot_rank")
            or metadata.get("list_position")
            or fallback_ranks[source_id]
        )

    def authoritative_ref(item_id: str) -> dict[str, Any] | None:
        """处理：按引用 ID 返回与索引绑定的权威来源对象。
        输入：
        - ``item_id``：规范条目的稳定 ID；用于连接索引、正文、简报和图片。
        输出：“按引用 ID 返回与索引绑定的权威来源对象”形成的结构化字典；
          典型键包括 access、item_id、role、title、url。
        """
        indexed = indexed_items.get(item_id)
        if not indexed:
            return None
        metadata = indexed.get("metadata", {})
        source = sources.get(str(indexed.get("source_id") or ""), {})
        return {
            "item_id": item_id,
            "title": indexed.get("title", ""),
            "url": indexed.get("url", ""),
            "access": content_status_to_access(indexed.get("content_status"))
            or "metadata_only",
            "role": metadata.get("role", "discovery"),
            **reference_time_fields(
                indexed,
                source,
                index.get("generated_at") or report.get("generated_at"),
            ),
        }

    def primary_source(indexed: dict) -> dict:
        """处理：从索引条目和配置的发布者构造统一的来源标识。
        输入：当前简报或精选事件的第一条权威来源。
        输出：引用主来源的 ID、名称和链接。
        """
        source_id = str(indexed.get("source_id", ""))
        source = sources.get(source_id, {})
        return {
            "id": source_id,
            "name": indexed.get("source_name") or source.get("source_name") or source_id,
            "url": source.get("source_url") or indexed.get("url"),
        }

    for original_section_id, section in list(provided_sections.items()):
        retained_briefs: list[dict[str, Any]] = []
        for brief in section.get("briefs", []):
            if not isinstance(brief, dict):
                retained_briefs.append(brief)
                continue
            item_id = str(brief.get("item_id") or "")
            indexed = indexed_items.get(item_id)
            if not indexed:
                warnings.append(
                    f"omitted brief with unknown or missing item_id {item_id!r}; use an exact "
                    "item_id from context.brief_plan"
                )
                continue
            if allowed_brief_ids is not None and item_id not in allowed_brief_ids:
                warnings.append(
                    f"omitted brief {item_id!r} because it is outside the current "
                    "context.brief_plan default_item_ids"
                )
                continue
            target_section_id = _indexed_report_section(indexed) or original_section_id
            if target_section_id not in SECTION_ORDER_V13:
                warnings.append(
                    f"omitted brief {item_id!r} because its indexed section "
                    f"{target_section_id!r} is unsupported"
                )
                continue
            if target_section_id != original_section_id:
                target = provided_sections.setdefault(
                    target_section_id,
                    {"id": target_section_id, "briefs": [], "items": []},
                )
                target.setdefault("briefs", []).append(brief)
                warnings.append(
                    f"moved brief {item_id!r} from {original_section_id!r} to indexed section "
                    f"{target_section_id!r}"
                )
            else:
                retained_briefs.append(brief)
        section["briefs"] = retained_briefs

        retained_events: list[dict[str, Any]] = []
        for event in section.get("items", []):
            if not isinstance(event, dict):
                retained_events.append(event)
                continue
            refs = event.get("source_refs", [])
            source_item_ids = event.get("source_item_ids", [])
            primary_item_id = next(
                (
                    str(ref.get("item_id"))
                    for ref in refs
                    if isinstance(ref, dict) and ref.get("item_id")
                ),
                str(source_item_ids[0]) if source_item_ids else "",
            )
            indexed = indexed_items.get(primary_item_id)
            if not indexed:
                retained_events.append(event)
                continue
            target_section_id = _indexed_report_section(indexed) or original_section_id
            if target_section_id in SECTION_ORDER_V13 and target_section_id != original_section_id:
                target = provided_sections.setdefault(
                    target_section_id,
                    {"id": target_section_id, "briefs": [], "items": []},
                )
                target.setdefault("items", []).append(event)
                warnings.append(
                    f"moved featured event for {primary_item_id!r} from "
                    f"{original_section_id!r} to indexed section {target_section_id!r}"
                )
            else:
                retained_events.append(event)
        section["items"] = retained_events

    planned_coverage: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
    for source_id, planned_ids in ordered_plan:
        planned_by_section: dict[str, list[dict]] = defaultdict(list)
        for item_id in planned_ids:
            indexed = indexed_items.get(item_id)
            if not indexed or str(indexed.get("source_id") or "") != source_id:
                continue
            if section_id := _indexed_report_section(indexed):
                planned_by_section[section_id].append(indexed)
        source = sources.get(source_id)
        for section_id, items in planned_by_section.items():
            name = (source or items[0]).get("source_name") or source_id
            planned_coverage[section_id].append((source_id, str(name), len(items)))

    compiled_sections: list[dict[str, Any]] = []
    event_by_item: dict[str, str] = {}
    used_brief_ids: set[str] = set()
    used_brief_urls: set[tuple[str, str]] = set()
    titles = section_titles(output_language)
    for section_id in SECTION_ORDER_V13:
        module, category = section_id.split(".", 1)
        section = provided_sections.get(section_id, {})
        section.update(
            {
                "id": section_id,
                "module": module,
                "category": category,
                "title": titles[section_id],
            }
        )
        section.setdefault("briefs", [])
        section.setdefault("items", [])
        deduplicated_briefs: list[dict[str, Any]] = []
        for brief in section["briefs"]:
            if not isinstance(brief, dict):
                deduplicated_briefs.append(brief)
                continue
            item_id = str(brief.get("item_id", ""))
            if item_id and item_id in used_brief_ids:
                warnings.append(f"omitted duplicate brief item_id {item_id!r}")
                continue
            indexed = indexed_items.get(item_id, {})
            raw_url = indexed.get("canonical_url") or indexed.get("url")
            url = canonicalize_url(raw_url) if raw_url else ""
            source_url = (str(indexed.get("source_id", "")), url)
            if url and source_url in used_brief_urls:
                warnings.append(f"omitted duplicate brief canonical URL for {item_id!r}")
                continue
            deduplicated_briefs.append(brief)
            if item_id:
                used_brief_ids.add(item_id)
            if url:
                used_brief_urls.add(source_url)
        section["briefs"] = deduplicated_briefs
        for brief in section["briefs"]:
            item_id = str(brief.get("item_id", ""))
            ref = authoritative_ref(item_id)
            if not ref:
                continue
            indexed = indexed_items[item_id]
            _normalize_brief_title(brief, indexed, output_language)
            brief["source_ref"] = ref
            brief["semantic_fingerprint"] = semantic_fingerprint(indexed)
            primary = primary_source(indexed)
            brief["primary_source"] = primary
            rank = item_ranks.get(item_id, 1)
            brief["source_rank"] = rank
            brief["selection_rank"] = planned_positions.get(
                item_id,
                source_item_positions.get(item_id, rank),
            )
            brief["source_rank_label"] = _source_rank_label(
                primary["id"], rank, output_language
            )
            published = _publication_date(
                indexed.get("published_at"),
                str(index.get("timezone", "Asia/Shanghai")),
            )
            if brief_requires_watch(indexed):
                brief["status"] = "WATCH"
            if brief.get("status") == "NEW":
                age = (
                    (date.fromisoformat(str(report["date"])) - published).days
                    if published
                    else None
                )
                if age not in {0, 1}:
                    brief["status"] = "WATCH"
        for event in section["items"]:
            refs = event.get("source_refs", [])
            source_item_ids = event.get("source_item_ids", [])
            requested_ids = [str(item_id) for item_id in source_item_ids] or [
                str(ref.get("item_id"))
                for ref in refs
                if isinstance(ref, dict) and ref.get("item_id")
            ]
            compiled_refs = [
                ref for item_id in requested_ids if (ref := authoritative_ref(item_id)) is not None
            ]
            if compiled_refs:
                event["source_refs"] = compiled_refs
                event["primary_source"] = primary_source(indexed_items[compiled_refs[0]["item_id"]])
            if compiled_refs and (source_item_ids or not event.get("event_id")):
                digest = hashlib.sha256(compiled_refs[0]["item_id"].encode()).hexdigest()[:8]
                event["event_id"] = f"EVT-{str(report['date']).replace('-', '')}-{digest.upper()}"
            event_id = str(event.get("event_id", ""))
            for ref in compiled_refs:
                event_by_item[ref["item_id"]] = event_id
            publication_dates = [
                value
                for ref in compiled_refs
                if (
                    value := _publication_date(
                        ref.get("published_at"),
                        str(index.get("timezone", "Asia/Shanghai")),
                    )
                )
            ]
            raw_newest_age = (
                (date.fromisoformat(str(report["date"])) - max(publication_dates)).days
                if publication_dates
                else 8
            )
            newest_age = max(0, raw_newest_age)
            importance, breakdown = _allocate_importance(
                int(event.get("importance", 50)), _freshness_cap(newest_age)
            )
            event["importance"] = importance
            event["importance_breakdown"] = breakdown
            event.setdefault(
                "importance_reason",
                localized(
                    output_language,
                    "内部相对排序由生成 Agent 给出，分项由 Python 按约束归一化。",
                    "The authoring model supplied the relative rank; Python normalized the "
                    "component scores under the report constraints.",
                ),
            )
            event.setdefault("evidence_notes", [])
            event.setdefault("tags", [])
            access_levels = [ref["access"] for ref in compiled_refs]
            confidence = max(0.0, min(float(event.get("confidence", 0.6)), 1.0))
            if access_levels and all(
                access in {"metadata_only", "verification_required"} for access in access_levels
            ):
                confidence = min(confidence, 0.65)
                disclosure = " ".join(str(note) for note in event["evidence_notes"])
                if not any(marker in disclosure for marker in _UNREAD_BODY_MARKERS):
                    event["evidence_notes"].append(
                        localized(
                            output_language,
                            "未读取正文，仅依据索引标题或公开摘要；未补写不可见内容。",
                            "The article body was not read; this item uses only the indexed "
                            "headline or public abstract and adds no unseen details.",
                        )
                    )
            event["confidence"] = confidence
            if event.get("status") == "NEW" and raw_newest_age not in {0, 1}:
                event["status"] = "WATCH"
        section["items"].sort(key=lambda item: item.get("importance", 0), reverse=True)
        section["briefs"].sort(
            key=lambda item: (
                source_positions.get(
                    str(item.get("primary_source", {}).get("id") or ""),
                    1_000_000,
                ),
                int(item.get("selection_rank", 1_000_000)),
                str(item.get("item_id") or ""),
            )
        )
        selected_source_counts = Counter(
            str(brief.get("primary_source", {}).get("id") or "")
            for brief in section["briefs"]
            if isinstance(brief, dict)
        )
        incomplete_sources = [
            (name, selected_source_counts[source_id], planned)
            for source_id, name, planned in planned_coverage[section_id]
            if selected_source_counts[source_id] < planned
        ]
        if incomplete_sources:
            details = (
                "、".join(
                    f"{name}（已验证摘要 {selected}/{planned}）"
                    for name, selected, planned in incomplete_sources
                )
                if is_chinese_output(output_language)
                else "; ".join(
                    f"{name} (validated summaries {selected}/{planned})"
                    for name, selected, planned in incomplete_sources
                )
            )
            section["coverage_note"] = localized(
                output_language,
                "以下来源已采集到候选内容，但写作或校验未完成，因此未发布未经验证的摘要："
                f"{details}。",
                "The following sources had collected candidates, but authoring or validation "
                f"did not finish, so unverified summaries were withheld: {details}.",
            )
        elif not section["items"] and not section["briefs"]:
            section["coverage_note"] = (
                localized(
                    output_language,
                    "本时段已采集到候选内容，但写作或校验未完成，因此未发布未经验证的摘要。",
                    "Candidates were collected in this window, but authoring or validation "
                    "did not finish, so no unverified summaries were published.",
                )
                if indexed_section_candidate_counts[section_id]
                else localized(
                    output_language,
                    "本时段未收集到可展示内容。",
                    "No publishable items were collected in this window.",
                )
            )
        else:
            section.pop("coverage_note", None)
        compiled_sections.append(section)
    report["sections"] = compiled_sections

    event_ids = {
        str(event.get("event_id"))
        for section in report["sections"]
        for event in section["items"]
        if event.get("event_id")
    }

    def bind_evidence(draft: dict) -> list[str]:
        """处理：把研判引用的索引条目转为已编译的精选事件。
        输入：研判或综合草稿中的条目 ID，或旧稿直接引用的事件 ID。
        输出：保序写入去重后的事件 ID，返回未关联的来源条目。
        """
        requested = draft.get("evidence_item_ids") or draft.get("evidence_event_ids", [])
        bound: dict[str, None] = {}
        ignored: set[str] = set()
        for item_id in map(str, requested):
            event_id = event_by_item.get(item_id)
            if event_id:
                bound[event_id] = None
            elif item_id in event_ids:
                bound[item_id] = None
            else:
                ignored.add(item_id)
        draft["evidence_event_ids"] = list(bound)
        return sorted(ignored)

    for position, analysis in enumerate(report.get("analyses", []), start=1):
        domain = str(analysis.get("domain", ""))
        if domain in ANALYSIS_DOMAIN_REQUIREMENTS:
            analysis["analysis_id"] = stable_analysis_id(domain)
        else:
            analysis.setdefault("analysis_id", f"ANALYSIS-UNSUPPORTED-{position}")
        requirements = ANALYSIS_DOMAIN_REQUIREMENTS.get(domain, {})
        for field in ("perspectives", "assessment_types"):
            values = [*requirements.get(field, []), *analysis.get(field, [])]
            analysis[field] = list(dict.fromkeys(values))
        if ignored_evidence := bind_evidence(analysis):
            warnings.append(
                f"analysis {domain or position!r} ignored evidence item IDs that are not "
                f"part of any featured event: {ignored_evidence}"
            )
    if report.get("schema_version") == "2.0":
        synthesis = report.get("cross_perspective_synthesis")
        if isinstance(synthesis, dict):
            ignored_evidence = bind_evidence(synthesis)
            synthesis.pop("evidence_item_ids", None)
            if ignored_evidence:
                warnings.append(
                    "cross-perspective synthesis ignored evidence item IDs that are not "
                    f"part of any featured event: {ignored_evidence}"
                )
    analysis_order = {"geopolitics": 0, "ai_technology": 1, "markets": 2}
    report.setdefault("analyses", []).sort(
        key=lambda analysis: analysis_order.get(str(analysis.get("domain")), 99)
    )

    briefs_by_item = {
        str(brief.get("item_id")): brief
        for section in report["sections"]
        for brief in section["briefs"]
        if brief.get("item_id")
    }
    for section in report["sections"]:
        for event in section["items"]:
            event_id = str(event.get("event_id", ""))
            for ref in event.get("source_refs", []):
                brief = briefs_by_item.get(str(ref.get("item_id")))
                if brief and event_id in event_ids:
                    brief["featured_event_id"] = event_id
                    break
    return warnings


def normalize_report_data(report: dict, index: dict | None) -> None:
    """处理：为当前契约补齐确定性计数和来源指标。
    输入：含栏目和来源引用的报告、规范来源索引。
    输出：不返回新数据；完成“为当前契约补齐确定性计数和来源指标”，
      副作用限于该处理声明的受控对象或产物。
    """
    hydrate_report_evidence(report, index)
    if report.get("schema_version") not in BRIEF_REPORT_SCHEMAS:
        return
    events = [item for section in report.get("sections", []) for item in section.get("items", [])]
    briefs = [item for section in report.get("sections", []) for item in section.get("briefs", [])]
    brief_counts = Counter(
        str(item.get("primary_source", {}).get("id"))
        for item in briefs
        if item.get("primary_source", {}).get("id")
    )
    report["event_count"] = len({item.get("event_id") for item in events})
    report["brief_count"] = len({item.get("item_id") for item in briefs})
    if isinstance(index, dict):
        sources = index.get("sources", [])
        successful = sum(
            row.get("status") in {"success", "partial"}
            for row in sources
            if isinstance(row, dict)
        )
        pending = sum(
            row.get("status")
            in {"failed", "verification_required", "rate_limited", "partial"}
            for row in sources
            if isinstance(row, dict)
        )
        report["source_count"] = len(brief_counts)
        report["source_metrics"] = {
            "configured": len(sources),
            "successful": successful,
            "represented": len(brief_counts),
            "pending": pending,
        }
        indexed_counts = Counter(
            str(item.get("source_id"))
            for item in index.get("items", [])
            if isinstance(item, dict) and item.get("source_id")
        )
        policies = index.get("source_policies", {})
        report["coverage_metrics"] = [
            {
                "source_id": source_id,
                "available": indexed_counts[source_id],
                "selected": brief_counts[source_id],
                "target": min(
                    indexed_counts[source_id],
                    int(policy.get("report_target", indexed_counts[source_id])),
                ),
                "maximum": int(policy.get("report_max", indexed_counts[source_id])),
            }
            for source_id, policy in policies.items()
            if indexed_counts[source_id]
        ]
    report.setdefault("evaluation_status", "pending")


def report_content_hash(report: dict) -> str:
    """处理：移除可变投影字段后计算报告语义内容哈希。
    输入：含栏目和来源引用的报告。
    输出：“移除可变投影字段后计算报告语义内容哈希”得到的规范字符串，供调用方存储、比较或展示。
    """
    payload = {key: value for key, value in report.items() if key != "quality_evaluation"}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _require_list_text(
    values: Iterable[object], location: str, check_text: Callable[[object, str], None]
) -> None:
    """处理：按顺序检查用户可见列表中的每段文字。
    输入：字段中的文字列表、JSON 路径和当前报告的文本规则。
    输出：路径带数组下标的语言诊断由本版检查器收集。
    """
    for position, value in enumerate(values):
        check_text(value, f"{location}[{position}]")


def _validate_report_analyses(
    report: dict,
    event_source_ids: dict[str, set[str]],
    mentioned_source_ids: Callable[[list[object]], set[str]],
    require_output_language: Callable[[object, str], None],
    errors: list[str],
    warnings: list[str],
) -> None:
    """处理：校验研判文本、领域覆盖及其与精选事件的证据关联。
    输入：通过结构校验的报告、事件到来源的关系和本版文本检查规则。
    输出：将按报告顺序发现的研判错误和警告加入交付诊断。
    """
    schema_version = report.get("schema_version")
    strict_contract = schema_version in _STRICT_SCHEMAS
    daily_contract = schema_version in _DAILY_SCHEMAS
    source_group_contract = schema_version in _SOURCE_GROUP_SCHEMAS
    analysis_v2_contract = schema_version == "2.0"
    event_ids = event_source_ids.keys()
    if daily_contract and not report["analyses"]:
        errors.append(
            f"analyses: schema_version {schema_version} requires evidence-backed judgement"
        )

    analysis_ids: set[str] = set()
    analysis_domains: Counter[str] = Counter()
    assessment_types: set[str] = set()
    perspectives: set[str] = set()
    analyzed_event_ids: set[str] = set()
    for analysis_index, analysis in enumerate(report["analyses"]):
        analysis_prefix = f"analyses[{analysis_index}]"
        require_output_language(analysis.get("claim"), f"{analysis_prefix}.claim")
        require_output_language(
            analysis.get("reasoning"), f"{analysis_prefix}.reasoning"
        )
        if source_group_contract:
            for field in ("narrative", "dialectical_analysis", "historical_context"):
                require_output_language(
                    analysis.get(field), f"{analysis_prefix}.{field}"
                )
                if not analysis.get(field):
                    errors.append(
                        f"{analysis_prefix}.{field}: required by schema_version {schema_version}"
                    )
            narrative_paragraphs = split_narrative_paragraphs(
                analysis.get("narrative")
            )
            if analysis_v2_contract and not 4 <= len(narrative_paragraphs) <= 7:
                errors.append(
                    f"{analysis_prefix}.narrative: analysis protocol 2.0 requires "
                    f"4-7 natural paragraphs, got {len(narrative_paragraphs)}"
                )
            perspectives.update(analysis.get("perspectives", []))
            if not analysis.get("perspectives"):
                errors.append(
                    f"{analysis_prefix}.perspectives: required by schema_version {schema_version}"
                )
            positions = analysis.get("stakeholder_positions", [])
            if not positions:
                errors.append(
                    f"{analysis_prefix}.stakeholder_positions: required by schema_version "
                    f"{schema_version}"
                )
            for position_index, position in enumerate(positions):
                for field in ("stakeholder", "position", "interests"):
                    require_output_language(
                        position.get(field),
                        f"{analysis_prefix}.stakeholder_positions[{position_index}].{field}",
                    )
        for field in (
            "facts",
            "counter_evidence",
            "scenarios",
            "implications",
            "actions",
            "watch_signals",
            "invalidation_signals",
        ):
            _require_list_text(analysis.get(field, []), f"{analysis_prefix}.{field}",
                               require_output_language)
        if strict_contract:
            for field in ("facts", "reasoning", "scenarios", "actions", "invalidation_signals"):
                if not analysis.get(field):
                    errors.append(
                        f"{analysis_prefix}.{field}: required by schema_version {schema_version}"
                    )
        if analysis_v2_contract:
            for field in (
                "time_horizon",
                "confidence_rationale",
                "change_from_prior",
                "decision_relevance",
            ):
                value = analysis.get(field)
                if not value:
                    errors.append(
                        f"{analysis_prefix}.{field}: required by analysis protocol 2.0"
                    )
                else:
                    require_output_language(value, f"{analysis_prefix}.{field}")
            for field in ("causal_chain", "assumptions", "evidence_gaps"):
                values = analysis.get(field, [])
                minimum = 2 if field == "causal_chain" else 1
                if not isinstance(values, list) or len(values) < minimum:
                    errors.append(
                        f"{analysis_prefix}.{field}: analysis protocol 2.0 requires "
                        f"at least {minimum} item(s)"
                    )
                    continue
                _require_list_text(values, f"{analysis_prefix}.{field}", require_output_language)
        evidence_ids = analysis["evidence_event_ids"]
        if daily_contract:
            assessment_types.update(analysis.get("assessment_types", []))
            if not analysis.get("assessment_types"):
                errors.append(
                    f"{analysis_prefix}.assessment_types: required by schema_version "
                    f"{schema_version}"
                )
            if not evidence_ids:
                errors.append(
                    f"{analysis_prefix}.evidence_event_ids: judgement must cite report events"
                )
        domain = str(analysis.get("domain"))
        analysis_domains[domain] += 1
        if analysis_v2_contract and domain in ANALYSIS_DOMAIN_REQUIREMENTS:
            expected_analysis_id = stable_analysis_id(domain)
            if analysis.get("analysis_id") != expected_analysis_id:
                errors.append(
                    f"{analysis_prefix}.analysis_id: must equal stable domain identity "
                    f"{expected_analysis_id!r}"
                )
        if analysis["analysis_id"] in analysis_ids:
            errors.append(
                f"analyses[{analysis_index}]: duplicate analysis_id {analysis['analysis_id']}"
            )
        analysis_ids.add(analysis["analysis_id"])
        missing_events = [event_id for event_id in evidence_ids if event_id not in event_ids]
        if missing_events:
            errors.append(
                f"analyses[{analysis_index}] references unknown event IDs: {missing_events}"
            )
        bound_analysis_sources = {
            source_id
            for event_id in evidence_ids
            for source_id in event_source_ids.get(str(event_id), set())
        }
        fact_mentions = mentioned_source_ids(list(analysis.get("facts", [])))
        unbound_fact_sources = sorted(fact_mentions - bound_analysis_sources)
        if unbound_fact_sources:
            errors.append(
                f"{analysis_prefix}.facts names sources not represented by evidence_event_ids: "
                f"{unbound_fact_sources}"
            )
        if any(_NUMERIC_SCENARIO_PATTERN.search(str(value))
               for value in analysis.get("scenarios", [])):
            scenario_basis = str(analysis.get("scenario_basis") or "").strip()
            if not scenario_basis:
                errors.append(
                    f"{analysis_prefix}.scenario_basis: numeric probabilities, prices, or ranges "
                    "must state their source or explicitly identify them as scenario assumptions"
                )
            else:
                require_output_language(
                    scenario_basis, f"{analysis_prefix}.scenario_basis"
                )
        analyzed_event_ids.update(evidence_ids)
        if not analysis["watch_signals"]:
            warnings.append(f"analyses[{analysis_index}] has no watch_signals")
    if daily_contract:
        missing_assessments = sorted(
            {"trend", "risk", "learning_research"} - assessment_types
        )
        if missing_assessments:
            errors.append(
                "analyses missing required assessment coverage: " f"{missing_assessments}"
            )
    if source_group_contract:
        missing_perspectives = sorted(REQUIRED_PERSPECTIVES - perspectives)
        if missing_perspectives:
            errors.append(f"analyses missing required perspectives: {missing_perspectives}")
        if event_ids and len(analyzed_event_ids) / len(event_ids) < 0.6:
            errors.append(
                "analyses must cite at least 60% of selected events; "
                f"covered {len(analyzed_event_ids)}/{len(event_ids)}"
            )
    if schema_version in BRIEF_REPORT_SCHEMAS:
        missing_domains = sorted(ANALYSIS_DOMAIN_REQUIREMENTS.keys() - analysis_domains.keys())
        if missing_domains:
            errors.append(
                "analyses must contain separate geopolitics, ai_technology, and markets "
                f"sections; missing {missing_domains}"
            )
        duplicate_domains = sorted(
            domain for domain, count in analysis_domains.items() if count > 1
        )
        if duplicate_domains:
            errors.append(
                "analyses must contain exactly one section per domain; duplicates "
                f"{duplicate_domains}"
            )
    if analysis_v2_contract:
        _validate_report_synthesis(report, event_source_ids, require_output_language, errors)


def _validate_report_synthesis(
    report: dict,
    event_source_ids: dict[str, set[str]],
    require_output_language: Callable[[object, str], None],
    errors: list[str],
) -> None:
    """处理：检查跨视角综合的判断、分歧与精选事件引用。
    输入：2.0 版报告、已登记的精选事件与本版文本检查规则。
    输出：将协议、综合正文和事件绑定错误追加到报告诊断。
    """
    if report.get("analysis_protocol_version") != "2.0":
        errors.append("analysis_protocol_version: schema 2.0 requires '2.0'")
    synthesis = report.get("cross_perspective_synthesis")
    if not isinstance(synthesis, dict):
        errors.append("cross_perspective_synthesis: schema 2.0 requires an explicit synthesis")
        return
    location = "cross_perspective_synthesis"
    overall = synthesis.get("overall_judgment")
    if not overall:
        errors.append(f"{location}.overall_judgment: required")
    else:
        require_output_language(overall, f"{location}.overall_judgment")
    for field, minimum in (
        ("consensus", 1),
        ("transmission_chain", 2),
        ("shared_watch_signals", 3),
        ("revision_triggers", 1),
    ):
        values = synthesis.get(field, [])
        if not isinstance(values, list) or len(values) < minimum:
            errors.append(
                f"cross_perspective_synthesis.{field}: require at least "
                f"{minimum} item(s)"
            )
            continue
        _require_list_text(values, f"{location}.{field}", require_output_language)
    tensions = synthesis.get("tensions", [])
    if not isinstance(tensions, list) or not tensions:
        errors.append(
            "cross_perspective_synthesis.tensions: require at least one "
            "explicit disagreement"
        )
    else:
        for tension_index, tension in enumerate(tensions):
            prefix = f"{location}.tensions[{tension_index}]"
            if not isinstance(tension, dict):
                errors.append(f"{prefix}: must be an object")
                continue
            for field in ("issue", "source_of_difference"):
                if not tension.get(field):
                    errors.append(f"{prefix}.{field}: required")
                else:
                    require_output_language(
                        tension[field], f"{prefix}.{field}"
                    )
            tension_perspectives = tension.get("perspectives", [])
            if (
                not isinstance(tension_perspectives, list)
                or len(tension_perspectives) < 2
            ):
                errors.append(
                    f"{prefix}.perspectives: require at least two viewpoints"
                )
            else:
                _require_list_text(tension_perspectives, f"{prefix}.perspectives",
                                   require_output_language)
    synthesis_evidence = synthesis.get("evidence_event_ids", [])
    if not synthesis_evidence:
        errors.append(
            "cross_perspective_synthesis.evidence_event_ids: synthesis must "
            "cite featured events"
        )
    unknown_synthesis_events = [
        event_id
        for event_id in synthesis_evidence
        if event_id not in event_source_ids
    ]
    if unknown_synthesis_events:
        errors.append(
            "cross_perspective_synthesis references unknown event IDs: "
            f"{unknown_synthesis_events}"
        )


def validate_report_data(
    report: object,
    index: object | None = None,
    existing_events: list[dict] | None = None,
    coverage_targets: dict[str, int] | None = None,
    *,
    brief_plan_item_ids: dict[str, list[str]] | None = None,
) -> tuple[list[str], list[str]]:
    """处理：校验报告数据并在不满足约束时报告错误。
    输入：含栏目和来源引用的报告、规范来源索引。
    - ``existing_events``：已在其他栏目登记的事件；用于阻止跨栏目重复 item_id。
    - ``coverage_targets``：按来源 ID 指定的最小报告覆盖数；由运行情境拥有。
    - ``brief_plan_item_ids``：冻结计划中的每源条目与顺序，决定覆盖目标；独立评估可使用已编译名次。
    输出：阻断错误和非阻断警告两个列表；调用方只有在错误列表为空时才能持久化或发布报告。
    """
    if isinstance(report, dict):
        normalize_report_data(report, index if isinstance(index, dict) else None)
    errors = _schema_errors(report)
    if errors or not isinstance(report, dict):
        return errors or ["Report must be a JSON object"], []

    warnings: list[str] = []
    schema_version = report.get("schema_version")
    strict_contract = schema_version in _STRICT_SCHEMAS
    freshness_contract = schema_version in _FRESHNESS_SCHEMAS
    daily_contract = schema_version in _DAILY_SCHEMAS
    source_group_contract = schema_version in _SOURCE_GROUP_SCHEMAS
    brief_contract = schema_version in BRIEF_REPORT_SCHEMAS
    analysis_v2_contract = schema_version == "2.0"
    output_language = str(report.get("language") or "zh-CN")
    source_positions: dict[str, int] = {}
    item_positions: dict[str, int] = {}
    known_items: dict[str, dict] = {}
    if isinstance(index, dict):
        source_positions = {
            str(source["source_id"]): position
            for position, source in enumerate(index.get("sources", []))
            if isinstance(source, dict) and source.get("source_id")
        }
        positioned_counts: Counter[str] = Counter()
        index_items = index.get("items", [])
        for item in index_items:
            if not isinstance(item, dict) or not (item_id := item.get("item_id")):
                continue
            source_id = str(item.get("source_id") or "")
            positioned_counts[source_id] += 1
            item_positions[str(item_id)] = positioned_counts[source_id]
            source_positions.setdefault(source_id, len(source_positions))
            if isinstance(index_items, list):
                known_items[item_id] = item
    if brief_plan_item_ids is not None:
        item_positions.update(
            (item_id, position)
            for item_ids in brief_plan_item_ids.values()
            for position, item_id in enumerate(item_ids, start=1)
        )

    def require_output_language(value: object, location: str) -> None:
        """处理：读取当前校验节点的输出语言，并把缺失或非法值加入报告错误列表。
        输入：待解析的值。
        - ``location``：当前校验字段的 JSON 路径；用于生成可定位的错误消息。
        输出：不返回新数据；完成“读取当前校验节点的输出语言，并把缺失或非法值加入报告错误列表”，
          副作用限于该处理声明的受控对象或产物。
        """
        if strict_contract:
            _require_output_language(value, location, errors, output_language)

    def require_reference_time(ref: dict[str, Any], location: str) -> None:
        """处理：要求来源引用至少包含发布时间或采集时间。
        输入：
        - ``ref``：报告条目的 reference_time 对象；包含时间值、类型和是否为回退。
        - ``location``：当前校验字段的 JSON 路径；用于生成可定位的错误消息。
        输出：不返回新数据；完成“要求来源引用至少包含发布时间或采集时间”，
          副作用限于该处理声明的受控对象或产物。
        """
        if not brief_contract:
            return
        published_at = str(ref.get("published_at") or "").strip()
        collected_at = str(ref.get("collected_at") or "").strip()
        if not published_at and not collected_at:
            errors.append(
                f"{location}: requires published_at or collected_at for report display"
            )
        elif published_at and collected_at:
            errors.append(
                f"{location}: keep published_at only when available; collected_at is fallback-only"
            )

    if strict_contract and output_language not in OUTPUT_LANGUAGES:
        errors.append(
            f"language: schema_version {schema_version} requires one of "
            f"{list(OUTPUT_LANGUAGES)}"
        )
    require_output_language(report.get("title"), "title")
    _require_list_text(report.get("executive_summary", []), "executive_summary",
                       require_output_language)
    source_aliases: dict[str, set[str]] = {}
    if isinstance(index, dict):
        for source in chain(index.get("sources", []), known_items.values()):
            if not isinstance(source, dict) or not source.get("source_id"):
                continue
            source_id = str(source["source_id"])
            name = str(source.get("source_name") or "").strip()
            if len(name) >= 3:
                source_aliases.setdefault(source_id, set()).add(name.casefold())

    def mentioned_source_ids(values: list[object]) -> set[str]:
        """处理：收集分析文本和结构化字段中实际提及的来源 ID。
        输入：
        - ``values``：待规范化、匹配或渲染的一组输入值。
        输出：封装“收集分析文本和结构化字段中实际提及的来源 ID”业务结果的 ``set[str]`` 对象；
          调用方据此继续相邻阶段或识别无结果状态。
        """
        text = " ".join(str(value) for value in values).casefold()
        return {
            source_id
            for source_id, aliases in source_aliases.items()
            if any(alias in text for alias in aliases)
        }
    previous_events = {
        event.get("event_id"): event
        for event in (existing_events or [])
        if isinstance(event, dict) and event.get("event_id")
    }
    previous_item_ids = {
        item_id
        for event in previous_events.values()
        for item_id in event.get("source_item_ids", [])
        if isinstance(item_id, str)
    }
    report_series_id = _report_series_id(report.get("report_id"))
    report_date = date.fromisoformat(report["date"])
    timezone = (
        str(index.get("timezone", "Asia/Shanghai"))
        if isinstance(index, dict)
        else "Asia/Shanghai"
    )

    event_source_ids: dict[str, set[str]] = {}
    featured_brief_event_ids: set[str] = set()
    brief_item_ids: set[str] = set()
    brief_source_urls: set[tuple[str, str]] = set()
    source_counts: Counter[str] = Counter()
    source_importance_values: dict[str, list[int]] = {}
    section_ids: set[str] = set()
    expected_section_titles = section_titles(output_language)
    for section_index, section in enumerate(report["sections"]):
        prefix = f"sections[{section_index}]"
        try:
            validate_content_taxonomy(section["module"], section["category"])
        except ValueError as exc:
            errors.append(f"{prefix}: {exc}")
        expected_id = f"{section['module']}.{section['category']}"
        if section["id"] != expected_id:
            errors.append(f"{prefix}: id must be {expected_id!r}")
        if section["id"] in section_ids:
            errors.append(f"{prefix}: duplicate section id {section['id']!r}")
        section_ids.add(section["id"])
        require_output_language(section.get("title"), f"{prefix}.title")
        expected_title = expected_section_titles.get(section["id"])
        if daily_contract and section.get("title") != expected_title:
            errors.append(
                f"{prefix}.title: schema {schema_version} requires "
                f"{expected_title!r} for {section['id']!r}"
            )
        briefs = section.get("briefs", []) if brief_contract else []
        if brief_contract and "briefs" not in section:
            errors.append(
                f"{prefix}.briefs: required by brief-based schema {schema_version}"
            )
        note = section.get("coverage_note")
        if strict_contract and not section["items"] and not briefs and not note:
            errors.append(f"{prefix}: empty section requires coverage_note")
        if note:
            require_output_language(note, f"{prefix}.coverage_note")

        importance_values = [item["importance"] for item in section["items"]]
        if importance_values != sorted(importance_values, reverse=True):
            errors.append(f"{prefix}: items must be sorted by importance descending")

        if item_positions:
            brief_order_values = [
                (
                    source_positions.get(
                        str(brief.get("primary_source", {}).get("id") or ""),
                        1_000_000,
                    ),
                    brief["selection_rank"]
                    if brief_plan_item_ids is None and type(brief.get("selection_rank")) is int
                    else item_positions.get(
                        str(brief.get("item_id") or ""),
                        1_000_000,
                    ),
                )
                for brief in briefs
                if isinstance(brief, dict)
            ]
            if brief_order_values != sorted(brief_order_values):
                errors.append(
                    f"{prefix}: briefs must preserve the planned source and item order"
                )

        for brief_index, brief in enumerate(briefs):
            brief_prefix = f"{prefix}.briefs[{brief_index}]"
            item_id = brief["item_id"]
            if item_id in brief_item_ids:
                errors.append(f"{brief_prefix}: duplicate item_id {item_id}")
            brief_item_ids.add(item_id)
            require_output_language(brief.get("tldr"), f"{brief_prefix}.tldr")
            if issue := tldr_quality_issue(
                brief.get("tldr"),
                str(brief.get("title", "")),
                output_language,
                [brief.get("title_zh"), brief.get("title_en")],
            ):
                errors.append(f"{brief_prefix}.tldr: {issue}; item_id={item_id}")
            primary = brief.get("primary_source", {})
            source_id = str(primary.get("id", ""))
            source_counts[source_id] += 1
            if source_id:
                source_importance_values.setdefault(source_id, []).append(brief["importance"])
            if urlsplit(str(primary.get("url", ""))).scheme not in {"http", "https"}:
                errors.append(f"{brief_prefix}.primary_source.url: invalid URL")
            ref = brief.get("source_ref", {})
            require_reference_time(ref, f"{brief_prefix}.source_ref")
            if ref.get("item_id") != item_id:
                errors.append(f"{brief_prefix}.source_ref.item_id must equal brief item_id")
            if known_items and item_id not in known_items:
                errors.append(f"{brief_prefix}: item_id not present in index: {item_id}")
                continue
            indexed = known_items.get(item_id, {})
            indexed_url = str(indexed.get("url", ""))
            canonical_url = canonicalize_url(str(
                indexed.get("canonical_url") or indexed_url or ref.get("url", "")))
            source_url = (str(indexed.get("source_id") or source_id), canonical_url)
            if canonical_url:
                if source_url in brief_source_urls:
                    errors.append(f"{brief_prefix}: duplicate canonical URL within source")
                brief_source_urls.add(source_url)
            if indexed_url and canonicalize_url(str(ref.get("url", ""))) != canonicalize_url(
                indexed_url
            ):
                errors.append(f"{brief_prefix}.source_ref.url does not match indexed item URL")
            if indexed.get("title") and ref.get("title") != indexed.get("title"):
                errors.append(f"{brief_prefix}.source_ref.title does not match indexed item title")
            indexed_title = str(indexed.get("title") or "")
            if indexed_title and brief.get("title") != indexed_title:
                errors.append(f"{brief_prefix}.title must preserve the indexed original headline")
            translation_field = translated_title_field(output_language)
            translated = translated_title(brief, output_language)
            other_translation_field = (
                "title_en" if translation_field == "title_zh" else "title_zh"
            )
            if indexed_title and brief_title_requires_translation(indexed, output_language):
                if not text_matches_output_language(
                    translated, output_language, minimum_units=2
                ):
                    errors.append(
                        f"{brief_prefix}.{translation_field}: headline outside the output "
                        f"language requires a {localized(output_language, 'Chinese', 'English')} "
                        f"translation on the following line; item_id={item_id}"
                    )
                elif _LANGUAGE_MARKER_PATTERN.match(translated):
                    errors.append(
                        f"{brief_prefix}.{translation_field}: remove the language marker"
                    )
            elif indexed_title and translated:
                errors.append(
                    f"{brief_prefix}.{translation_field}: omit the redundant translation "
                    "when the original headline already matches the output language"
                )
            if brief.get(other_translation_field):
                errors.append(
                    f"{brief_prefix}.{other_translation_field}: remove the translation for "
                    "the inactive output language"
                )
            if indexed.get("source_id") and source_id != str(indexed.get("source_id", "")):
                errors.append(f"{brief_prefix}.primary_source.id does not match indexed source")
            actual_access = content_status_to_access(indexed.get("content_status"))
            if actual_access and ref.get("access") != actual_access:
                errors.append(
                    f"{brief_prefix}.source_ref.access {ref.get('access')!r} does not match "
                    f"index content_status {indexed.get('content_status')!r}"
                )
            if actual_access in {"full_text", "partial"} and any(
                marker in str(brief.get("tldr", "")) for marker in _UNREAD_BODY_MARKERS
            ):
                errors.append(
                    f"{brief_prefix}.tldr: index contains {actual_access} content; do not claim "
                    f"that the body was unread; item_id={item_id}"
                )
            published_date = _publication_date(
                original_publication_time(indexed, timezone)
                if indexed else ref.get("published_at"), timezone,
            )
            if brief["status"] == "NEW":
                if published_date is None:
                    errors.append(
                        f"{brief_prefix}.status: NEW requires a parseable indexed publication date"
                    )
                elif (report_date - published_date).days not in {0, 1}:
                    errors.append(
                        f"{brief_prefix}.status: NEW requires publication today or yesterday"
                    )
            if brief.get("featured_event_id"):
                featured_brief_event_ids.add(str(brief["featured_event_id"]))

        for item_index, item in enumerate(section["items"]):
            item_prefix = f"{prefix}.items[{item_index}]"
            event_id = item["event_id"]
            if event_id in event_source_ids:
                errors.append(f"{item_prefix}: duplicate event_id {event_id}")
            for field in ("title", "tldr", "why_it_matters", "importance_reason"):
                require_output_language(item.get(field), f"{item_prefix}.{field}")
            if _LANGUAGE_MARKER_PATTERN.match(str(item.get("title", ""))):
                errors.append(f"{item_prefix}.title: remove the [英]/[EN] marker")
            if issue := tldr_quality_issue(
                item.get("tldr"),
                str(item.get("title", "")),
                output_language,
                [item.get("title_zh"), item.get("title_en")],
            ):
                errors.append(f"{item_prefix}.tldr: {issue}")
            if source_group_contract:
                primary = item.get("primary_source")
                if not isinstance(primary, dict):
                    errors.append(
                        f"{item_prefix}.primary_source: required by schema_version {schema_version}"
                    )
                else:
                    source_id = str(primary.get("id", ""))
                    if not brief_contract:
                        source_counts[source_id] += 1
                    if urlsplit(str(primary.get("url", ""))).scheme not in {"http", "https"}:
                        errors.append(f"{item_prefix}.primary_source.url: invalid URL")
            _require_list_text(item.get("evidence_notes", []), f"{item_prefix}.evidence_notes",
                               require_output_language)

            score = item["importance_breakdown"]
            calculated = sum(score.values())
            if calculated != item["importance"]:
                errors.append(
                    f"{item_prefix}: importance {item['importance']} "
                    f"does not equal breakdown total {calculated}"
                )

            publication_dates: list[date] = []
            referenced_item_ids: set[str] = set()
            referenced_sources: Counter[str] = Counter()
            access_levels: list[str] = []
            for ref_index, ref in enumerate(item["source_refs"]):
                ref_prefix = f"{item_prefix}.source_refs[{ref_index}]"
                require_reference_time(ref, ref_prefix)
                if urlsplit(ref["url"]).scheme not in {"http", "https"}:
                    errors.append(f"{ref_prefix}: invalid URL")
                item_id = ref["item_id"]
                referenced_item_ids.add(item_id)
                access_levels.append(ref["access"])
                if known_items and item_id not in known_items:
                    errors.append(f"{ref_prefix}: item_id not present in index: {item_id}")
                if (indexed := known_items.get(item_id)) is not None:
                    if source_id := indexed.get("source_id"):
                        referenced_sources[str(source_id)] += 1
                    content_status = indexed.get("content_status")
                    actual_access = content_status_to_access(content_status)
                    if actual_access and ref["access"] != actual_access:
                        errors.append(
                            f"{ref_prefix}: access {ref['access']!r} does not match "
                            f"index content_status {content_status!r}, which maps to "
                            f"report access {actual_access!r}"
                        )
                    if indexed.get("url") and canonicalize_url(ref["url"]) != canonicalize_url(
                        str(indexed["url"])
                    ):
                        errors.append(f"{ref_prefix}: URL does not match indexed item URL")
                    if indexed.get("title") and ref.get("title") != indexed.get("title"):
                        errors.append(f"{ref_prefix}: title does not match indexed item title")
                    primary = item.get("primary_source", {})
                    if (
                        ref_index == 0
                        and indexed.get("source_id")
                        and primary.get("id") != indexed.get("source_id")
                    ):
                        errors.append(
                            f"{item_prefix}.primary_source.id does not match the first "
                            "indexed source reference"
                        )
                    published_at = (
                        original_publication_time(indexed, timezone)
                        if analysis_v2_contract else indexed.get("published_at")
                    )
                else:
                    published_at = ref.get("published_at")
                if published_date := _publication_date(published_at, timezone):
                    publication_dates.append(published_date)

            repeated_sources = sorted(
                source_id for source_id, count in referenced_sources.items() if count > 1
            )
            event_source_ids[event_id] = set(referenced_sources)
            note_mentions = mentioned_source_ids(list(item.get("evidence_notes", [])))
            unbound_note_sources = sorted(note_mentions - event_source_ids[event_id])
            if unbound_note_sources:
                errors.append(
                    f"{item_prefix}.evidence_notes names sources not bound in source_refs: "
                    f"{unbound_note_sources}. Add separate featured events and cite them from "
                    "analysis instead of claiming unbound corroboration."
                )
            if brief_contract and len(item["source_refs"]) > 1:
                errors.append(
                    f"{item_prefix}.source_refs: schema {schema_version} featured events "
                    "require exactly one "
                    "source item. Keep corroborating articles as separate featured events and "
                    "cite both event IDs in analysis"
                )
            elif repeated_sources:
                errors.append(
                    f"{item_prefix}.source_refs: a featured event may use at most one item per "
                    f"publisher; repeated sources {repeated_sources}. Keep one primary article and "
                    "use distinct publishers only when they corroborate the same event"
                )

            metadata_only = bool(access_levels) and all(
                access in {"metadata_only", "verification_required"} for access in access_levels
            )
            if freshness_contract and metadata_only and item["confidence"] > 0.65:
                errors.append(
                    f"{item_prefix}: confidence above 0.65 requires at least one partial or "
                    "full-text source"
                )

            if daily_contract and metadata_only:
                disclosure = " ".join(str(note) for note in item.get("evidence_notes", []))
                if not any(marker in disclosure for marker in _UNREAD_BODY_MARKERS):
                    errors.append(
                        f"{item_prefix}.evidence_notes: metadata-only evidence must disclose "
                        "that the body was not read or that only a public abstract/title was used"
                    )

            is_new = item["status"] == "NEW"
            if freshness_contract and publication_dates:
                raw_newest_age = (report_date - max(publication_dates)).days
                newest_age = max(0, raw_newest_age)
                cap = _freshness_cap(newest_age)
                if score["freshness"] > cap:
                    errors.append(
                        f"{item_prefix}.importance_breakdown.freshness: {score['freshness']} "
                        f"exceeds age-based cap {cap}; newest source is {newest_age} day(s) old"
                    )
                if is_new and raw_newest_age not in {0, 1}:
                    errors.append(
                        f"{item_prefix}.status: NEW requires source evidence published today "
                        "or yesterday; use WATCH/UPD or provide newer evidence"
                    )
            elif freshness_contract and is_new:
                message = f"{item_prefix}.status: NEW has no parseable source publication date"
                (errors if brief_contract else warnings).append(message)

            if freshness_contract and is_new:
                previous_event = previous_events.get(event_id, {})
                previous_report_ids = previous_event.get("report_ids", [])
                if not isinstance(previous_report_ids, list):
                    previous_report_ids = []
                latest_report = previous_event.get("last_report_id")
                same_edition_revision = report_series_id and any(
                    _report_series_id(report_id) == report_series_id
                    for report_id in [*previous_report_ids, latest_report]
                )
                if previous_event and not same_edition_revision:
                    errors.append(
                        f"{item_prefix}.status: event_id {event_id!r} already exists; "
                        "reuse it with UPD/CONF/REV/WATCH/CLOSED"
                    )
                reused_items = referenced_item_ids & previous_item_ids
                if same_edition_revision:
                    reused_items.difference_update(
                        item_id for item_id in previous_event.get("source_item_ids", [])
                        if isinstance(item_id, str)
                    )
                if reused_items:
                    errors.append(
                        f"{item_prefix}.status: NEW reuses previously reported source items "
                        f"{sorted(reused_items)}; split continuing evidence from genuinely "
                        "new events"
                    )

    required_sections = required_section_ids(schema_version)
    missing_sections = sorted(required_sections - section_ids)
    if strict_contract and missing_sections:
        errors.append(f"sections missing required ids: {missing_sections}")
    if daily_contract:
        unexpected_sections = sorted(section_ids - required_sections)
        if unexpected_sections:
            errors.append(
                f"sections contain unsupported ids for schema {schema_version}: "
                f"{unexpected_sections}"
            )
    if brief_contract:
        for source_id, values in sorted(source_importance_values.items()):
            if len(values) >= 3 and len(set(values)) == 1:
                warnings.append(
                    f"source {source_id!r} has {len(values)} briefs with identical importance; "
                    "the current index order remains authoritative"
                )
        if isinstance(index, dict):
            if brief_plan_item_ids is not None:
                # 正文日期复核后以计划内条目计数，未入计划的来源覆盖目标为零。
                targets = {
                    source_id: len(item_ids) for source_id, item_ids in brief_plan_item_ids.items()
                }
            else:
                targets = {
                    row["source_id"]: min(row["target"], row["maximum"])
                    for row in report["coverage_metrics"]
                }
            for source_id, target in sorted(targets.items()):
                if coverage_targets is not None and source_id in coverage_targets:
                    override = coverage_targets[source_id]
                    if (
                        not isinstance(override, int)
                        or isinstance(override, bool)
                        or override < 0
                    ):
                        errors.append(
                            f"coverage target override for {source_id!r} must be "
                            "a non-negative integer"
                        )
                        continue
                    target = min(target, override)
                selected = source_counts[source_id]
                if selected < target:
                    errors.append(
                        f"coverage source {source_id!r}: selected {selected} of required {target}; "
                        "complete this source's entries from context.brief_plan before finalization"
                    )

    event_ids = event_source_ids.keys()
    if brief_contract:
        if len(event_ids) > MAX_FEATURED_EVENTS:
            errors.append(
                f"schema {schema_version} allows at most {MAX_FEATURED_EVENTS} "
                "featured events; "
                "keep the remaining stories as briefs"
            )
        missing_featured = sorted(event_ids - featured_brief_event_ids)
        unknown_featured = sorted(featured_brief_event_ids - event_ids)
        if missing_featured:
            errors.append(f"briefs missing featured_event_id links for events: {missing_featured}")
        if unknown_featured:
            errors.append(f"briefs reference unknown featured events: {unknown_featured}")

    if report["event_count"] != len(event_ids):
        errors.append(
            f"event_count is {report['event_count']}, "
            f"but {len(event_ids)} unique event IDs were found"
        )

    _validate_report_analyses(
        report, event_source_ids, mentioned_source_ids, require_output_language, errors, warnings
    )
    for field in ("changes", "tomorrow_watch_items"):
        _require_list_text(report.get(field, []), field, require_output_language)
    if daily_contract and report["edition"] == "evening":
        if not report.get("changes"):
            errors.append(
                f"changes: evening schema {schema_version} report must state additions, "
                "confirmations, "
                "corrections, or explicitly state that no material change occurred"
            )
        if not report.get("tomorrow_watch_items"):
            errors.append(
                f"tomorrow_watch_items: evening schema {schema_version} report requires "
                "next-day watch items"
            )
    for pending_index, pending in enumerate(report.get("pending_verifications", [])):
        require_output_language(
            pending.get("note"), f"pending_verifications[{pending_index}].note"
        )
        if source_group_contract and urlsplit(str(pending.get("url", ""))).scheme not in {
            "http",
            "https",
        }:
            errors.append(f"pending_verifications[{pending_index}].url: required valid link")

    if schema_version == "1.4":
        evaluation = report.get("quality_evaluation")
        if not isinstance(evaluation, dict):
            errors.append("quality_evaluation: schema_version 1.4 requires independent evaluation")
        else:
            dimensions = evaluation.get("dimensions", [])
            dimension_ids = [item.get("id") for item in dimensions if isinstance(item, dict)]
            if set(dimension_ids) != EVALUATION_DIMENSIONS or len(dimension_ids) != 9:
                errors.append("quality_evaluation.dimensions: require all nine unique dimensions")
            scores = [
                item.get("score")
                for item in dimensions
                if isinstance(item, dict) and isinstance(item.get("score"), int)
            ]
            if len(scores) == 9 and evaluation.get("total_score") != sum(scores):
                errors.append("quality_evaluation.total_score: must equal dimension score sum")
            for dimension_index, dimension in enumerate(dimensions):
                require_output_language(
                    dimension.get("finding"),
                    f"quality_evaluation.dimensions[{dimension_index}].finding",
                )
            for field in ("main_defects", "insufficient_evidence", "improvements"):
                _require_list_text(evaluation.get(field, []), f"quality_evaluation.{field}",
                                   require_output_language)
            if evaluation.get("evaluated_report_id") != report.get("report_id"):
                errors.append("quality_evaluation.evaluated_report_id must match report_id")
            if (
                evaluation.get("continuity_decision") == "reject"
                and "all" not in evaluation.get("exclude_from_continuity", [])
            ):
                errors.append(
                    "quality_evaluation.exclude_from_continuity: reject requires 'all'"
                )
    if brief_contract and report.get("evaluation_status") != "pending":
        errors.append(
            "evaluation_status: newly published brief-based report must be pending"
        )
    if brief_contract and "quality_evaluation" in report:
        errors.append(
            "quality_evaluation: brief-based schemas store evaluation as a separate "
            "post-publication artifact"
        )
    return errors, warnings


def validate_report(
    report_path: Path,
    index_path: Path | None = None,
    events_path: Path | None = None,
    coverage_targets: dict[str, int] | None = None,
    brief_plan_item_ids: dict[str, list[str]] | None = None,
) -> tuple[list[str], list[str]]:
    """处理：校验报告并在不满足约束时报告错误。
    输入：版本化报告路径、版本化来源索引路径。
    - ``events_path``：可选历史事件 JSON 路径；提供时参与报告语义校验。
    - ``coverage_targets``：按来源 ID 指定的最小报告覆盖数；由运行情境拥有。
    - ``brief_plan_item_ids``：当前 context 固定的每来源有序条目；用于按同一边界编译验证副本。
    输出：“校验报告并在不满足约束时报告错误”得到的固定结构结果；
      返回位置依次对应 errors、[*compile_warnings, *validation_。
    """
    report = read_json(report_path)
    index = read_json(index_path) if index_path else None
    compile_warnings: list[str] = []
    if isinstance(report, dict) and isinstance(index, dict):
        report = deepcopy(report)
        # 草稿契约禁止模型预先分配不可变身份；只读校验使用内存占位身份来执行完整
        # schema/语义检查，真实 revision 仍只能由 save_report() 在持久化时分配。
        report.setdefault("date", index.get("date"))
        report.setdefault("edition", index.get("edition"))
        if "revision" not in report:
            report["revision"] = 1
        if "report_id" not in report:
            report["report_id"] = (
                f"daily-{report.get('date')}-{report.get('edition')}-"
                f"r{report.get('revision')}"
            )
        try:
            compile_warnings = compile_report_data(
                report,
                index,
                brief_plan_item_ids=brief_plan_item_ids,
            )
        except ValueError as exc:
            return [f"Report draft compilation failed: {exc}"], []
    existing_events: list[dict] = []
    if events_path and events_path.exists():
        payload = read_json(events_path)
        if isinstance(payload, dict) and isinstance(payload.get("items"), list):
            existing_events = [item for item in payload["items"] if isinstance(item, dict)]
    errors, validation_warnings = validate_report_data(
        report,
        index,
        existing_events,
        coverage_targets=coverage_targets,
        brief_plan_item_ids=brief_plan_item_ids,
    )
    return errors, [*compile_warnings, *validation_warnings]


def validate_evaluation_data(evaluation: object, report: object) -> list[str]:
    """处理：校验评估数据并在不满足约束时报告错误。
    输入：独立质量评估、含栏目和来源引用的报告。
    输出：可操作的校验错误消息列表；空列表表示通过当前规则。
    """
    if not isinstance(evaluation, dict) or not isinstance(report, dict):
        return ["Evaluation and report must both be JSON objects"]
    # 校验器一次收集完整错误集，调用方可修复整批问题而非逐个失败重跑。
    errors: list[str] = []
    if evaluation.get("evaluator_role") != "independent":
        errors.append("evaluator_role must be 'independent'")
    if evaluation.get("evaluated_report_id") != report.get("report_id"):
        errors.append("evaluated_report_id must match the immutable report")
    expected_hash = report_content_hash(report)
    if evaluation.get("evaluated_content_hash") != expected_hash:
        errors.append("evaluated_content_hash does not match the immutable report content")
    dimensions = evaluation.get("dimensions", [])
    dimension_ids = [item.get("id") for item in dimensions if isinstance(item, dict)]
    if set(dimension_ids) != EVALUATION_DIMENSIONS or len(dimension_ids) != 9:
        errors.append("dimensions must contain all nine unique evaluation dimensions")
    scores = [
        item.get("score")
        for item in dimensions
        if isinstance(item, dict) and isinstance(item.get("score"), int)
    ]
    if len(scores) != 9 or any(score < 1 or score > 5 for score in scores):
        errors.append("each evaluation dimension score must be an integer from 1 to 5")
    elif evaluation.get("total_score") != sum(scores):
        errors.append("total_score must equal the sum of all dimension scores")
    for position, dimension in enumerate(dimensions):
        _require_output_language(
            dimension.get("finding"),
            f"dimensions[{position}].finding",
            errors,
            report.get("language") or "zh-CN",
        )
    for field in ("main_defects", "insufficient_evidence", "improvements"):
        values = evaluation.get(field)
        if not isinstance(values, list):
            errors.append(f"{field} must be an array")
            continue
        for position, value in enumerate(values):
            _require_output_language(
                value,
                f"{field}[{position}]",
                errors,
                report.get("language") or "zh-CN",
            )
    if evaluation.get("continuity_decision") not in {"accept", "selective", "reject"}:
        errors.append("continuity_decision must be accept, selective, or reject")
    excluded = evaluation.get("exclude_from_continuity", [])
    allowed = {"formatting", "event_summaries", "analyses", "source_access", "all"}
    if not isinstance(excluded, list) or not set(excluded) <= allowed:
        errors.append("exclude_from_continuity contains unsupported values")
    if evaluation.get("continuity_decision") == "reject" and "all" not in excluded:
        errors.append("reject continuity_decision requires exclude_from_continuity=['all']")
    effective_decision, effective_excluded, continuity_error = (
        evaluation_continuity_floor(evaluation)
    )
    if continuity_error and (
        effective_decision != evaluation.get("continuity_decision")
        or effective_excluded != set(excluded)
    ):
        errors.append(continuity_error)
    return errors
