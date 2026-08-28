from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .localization import (
    localized,
    text_matches_output_language,
    validate_output_language,
)
from .utils import canonicalize_url, clean_title, now_iso, read_json, write_json

SEMANTIC_CACHE_SCHEMA = "1.2"
REUSABLE_BRIEF_FIELDS = (
    "item_id",
    "title",
    "title_zh",
    "title_en",
    "tldr",
)

_TLDR_BOILERPLATE_PATTERNS = (
    re.compile(r"^\s*来源[：:]"),
    re.compile(r"^\s*来源.{0,80}(?:报道|消息)[。.!]?\s*$", re.I),
    re.compile(r"^\s*(?:详见|请见)(?:原文)?(?:链接|报道)"),
    re.compile(r"来源原文标题|原文标题[：:]"),
    re.compile(r"暂未获取中文摘要|待补写|需由生成\s*Agent", re.I),
    re.compile(r"(?:尚未|暂未|未)获取(?:到)?(?:正文|中文摘要)"),
    re.compile(r"仅取得(?:来源)?标题或公开元数据"),
    re.compile(r"正文尚未读取.{0,80}(?:原文链接|完整内容)"),
    re.compile(r"(?:内容|正文|摘要).{0,12}(?:未抓取|未获取|未读取|不可用)"),
    re.compile(r"(?:暂无|没有可用的?)(?:正文(?:详情|细节)?|摘要)"),
    re.compile(r"(?:目前)?仅有(?:来源)?标题(?:信息)?"),
    re.compile(r"仅凭标题(?:和|与)?(?:简介|元数据)?供稿"),
    re.compile(r"\bnot[_ -]?fetched\b", re.I),
    re.compile(
        r"(?:content|article body|summary).{0,20}(?:unavailable|not fetched|not available)",
        re.I,
    ),
    re.compile(r"only (?:the )?(?:headline|title|metadata) (?:was|is )?available", re.I),
    re.compile(
        r"(?:packet|数据包|原文)(?:中|内)?\s*(?:未|没有)(?:提供|包含)"
        r".{0,24}(?:摘要|项目说明|简介|正文)",
        re.I,
    ),
    re.compile(r"仅依据标题(?:和|与)?(?:来源信息|元数据)?.*记录"),
    re.compile(r"关于.{0,100}(?:详细报道|相关报道)"),
    re.compile(r"^\s*source\s*:", re.I),
    re.compile(r"^\s*(?:see|read)\s+(?:the\s+)?(?:original|source|link)", re.I),
    re.compile(r"^\s*(?:summary|article body)\s+(?:is\s+)?(?:unavailable|not fetched)", re.I),
    re.compile(r"^\s*based only on (?:the )?(?:title|metadata)", re.I),
    re.compile(
        r"(?:the\s+)?(?:packet|data package)\s+(?:(?:does|did)\s+not\s+"
        r"(?:provide|include)|lacks).{0,24}(?:summary|description|body)",
        re.I,
    ),
)

_TLDR_ACCESS_STATUS_PATTERN = re.compile(
    r"(?:"
    r"(?:内容|正文|摘要).{0,12}(?:未抓取|未获取|未读取|不可用)"
    r"|(?:暂无|没有可用的?)(?:正文(?:详情|细节)?|摘要)"
    r"|(?:目前)?仅有(?:来源)?标题(?:信息)?"
    r"|仅凭标题(?:和|与)?(?:简介|元数据)?供稿"
    r"|\bnot[_ -]?fetched\b"
    r"|(?:content|article body|summary).{0,20}(?:unavailable|not fetched|not available)"
    r"|only (?:the )?(?:headline|title|metadata) (?:was|is )?available"
    r")",
    re.I,
)


def _sanitize_cached_tldr(value: object) -> str:
    """处理：从历史已审核摘要尾部删除纯访问状态说明而不改写事实句。
    输入：
    - ``value``：语义缓存中的 TL;DR；可能含“内容未抓取”等旧版读者层泄漏。
    输出：保留状态标记之前原文的字符串；若整条都是状态说明则返回空字符串。
    """

    text = str(value or "").strip()
    match = _TLDR_ACCESS_STATUS_PATTERN.search(text)
    if match is None:
        return text
    prefix = text[: match.start()].rstrip()
    prefix = re.sub(r"[\s，,；;：:、-]+$", "", prefix).strip()
    return prefix


def tldr_quality_issue(
    value: object,
    title: str,
    output_language: object = "zh-CN",
    alternate_titles: object = None,
) -> str | None:
    """处理：识别空泛、运行过程泄漏、免责声明式或语言不合格的摘要。
    输入：
    - ``value``：模型生成的 TL;DR；只读取读者可见文字，不读取提示词或模型内部状态。
    - ``title``：来源提供的标题；用于识别只复述标题、没有新增信息的摘要。
    - ``output_language``：报告目标语言；决定摘要必须满足的自然语言要求。
    - ``alternate_titles``：目标语译题等标题形式；同样不得原样充当摘要。
    输出：发现的单一质量问题；``None`` 表示摘要可进入语义缓存或后续确定性校验。
    """
    if not isinstance(value, str) or not value.strip():
        return "TL;DR is empty"
    text = value.strip()
    for pattern in _TLDR_BOILERPLATE_PATTERNS:
        if pattern.search(text):
            return (
                "TL;DR is boilerplate instead of a "
                f"{localized(output_language, 'Chinese', 'English')} summary of observed content"
            )
    if not text_matches_output_language(text, output_language, minimum_units=4):
        return (
            "TL;DR must contain a substantive "
            f"{localized(output_language, 'Chinese', 'English')} sentence"
        )
    normalized_text = re.sub(r"[\s\W_]+", "", text)
    titles = [title]
    if isinstance(alternate_titles, (list, tuple, set)):
        titles.extend(str(candidate) for candidate in alternate_titles if candidate)
    elif alternate_titles:
        titles.append(str(alternate_titles))
    normalized_titles = {
        normalized
        for candidate in titles
        if (normalized := re.sub(r"[\s\W_]+", "", candidate))
    }
    if normalized_text in normalized_titles:
        return "TL;DR merely repeats the headline"
    return None


def semantic_fingerprint(item: dict[str, Any]) -> str:
    """处理：只哈希会合理改变翻译或摘要语义的证据字段。
    输入：
    - ``item``：单个规范条目对象；通常包含 item_id、来源、标题、URL、时间和元数据。
    输出：“只哈希会合理改变翻译或摘要语义的证据字段”得到的规范字符串，供调用方存储、比较或展示。
    """
    payload = {
        "title": clean_title(str(item.get("title") or "")),
        "url": canonicalize_url(str(item.get("canonical_url") or item.get("url") or "")),
        "description": clean_title(str(item.get("description") or "")),
        "published_at": str(item.get("published_at") or ""),
        "content_status": str(item.get("content_status") or "not_fetched"),
        "content_path": str(item.get("content_path") or ""),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def run_relative_brief_fields(
    item: dict[str, Any],
    reference_date: object = None,
) -> dict[str, Any]:
    """处理：从当前索引排名、新鲜度、证据状态和历史使用标记重算动态字段。
    输入：
    - ``item``：当前索引候选；提供排名、发布时间、正文状态和 previously_reported。
    - ``reference_date``：本次报告日期或时间；用于确定新鲜度而不读取墙钟。
    输出：当前运行专用的 importance 整数和 NEW/UPD/WATCH 状态。
    """

    metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
    raw_rank = (
        item.get("source_rank")
        or item.get("source_candidate_rank")
        or metadata.get("source_rank")
        or metadata.get("hot_rank")
        or metadata.get("list_position")
        or 15
    )
    try:
        rank = max(1, int(raw_rank))
    except (TypeError, ValueError):
        rank = 15
    published_date = _coerce_date(item.get("published_at"))
    target_date = _coerce_date(reference_date) or published_date or date(1970, 1, 1)
    age_days = (
        max(0, (target_date - published_date).days)
        if published_date is not None
        else None
    )
    freshness = (
        30
        if age_days == 0
        else 25
        if age_days == 1
        else max(5, 20 - 2 * (age_days or 7))
    )
    evidence = {
        "full_text": 15,
        "partial": 11,
        "metadata_only": 7,
        "not_fetched": 5,
    }.get(str(item.get("content_status") or "not_fetched"), 5)
    previously_reported = bool(item.get("previously_reported"))
    importance = min(
        100,
        10
        + max(0, 30 - min(rank - 1, 15) * 2)
        + freshness
        + evidence
        + (6 if previously_reported else 15),
    )
    status = ("UPD" if previously_reported else "NEW") if age_days in {0, 1} else "WATCH"
    return {"importance": importance, "status": status}


def semantic_cache_reuse_issue(
    item: dict[str, Any],
    entry: dict[str, Any] | None,
    output_language: str,
) -> str | None:
    """处理：为语义缓存未复用原因返回一个稳定机器标签。
    输入：
    - ``item``：当前索引候选；用于重新计算内容指纹和标题质量边界。
    - ``entry``：相同 item ID 的可选缓存条目；包含审批状态、语言和稳定语义。
    - ``output_language``：当前报告目标语言；阻止跨语言复用。
    输出：可复用时为 None；否则为 miss/pending/rejected/fingerprint/language/editorial 标签。
    """

    language = validate_output_language(output_language)
    if not entry:
        return "cache_miss"
    if entry.get("fingerprint") != semantic_fingerprint(item):
        return "fingerprint_mismatch"
    if str(entry.get("language") or "zh-CN") != language:
        return "language_mismatch"
    state = str(entry.get("state") or "pending")
    if state == "pending":
        return "pending_evaluation"
    if state == "rejected":
        return "rejected"
    if state == "invalidated":
        return "invalidated_editorial_rule"
    if state != "approved":
        return "unsupported_state"
    brief = entry.get("brief")
    if not isinstance(brief, dict):
        return "invalidated_editorial_rule"
    tldr = _sanitize_cached_tldr(brief.get("tldr"))
    if tldr_quality_issue(
        tldr,
        str(item.get("title") or ""),
        language,
        [brief.get("title_zh"), brief.get("title_en")],
    ):
        return "invalidated_editorial_rule"
    return None


def semantic_cache_path(data_dir: Path) -> Path:
    """处理：返回按语言隔离的语义简报缓存文件路径。
    输入：
    - ``data_dir``：当前运行的唯一数据根；所有状态和版本化产物都必须位于其中。
    输出：指向“返回按语言隔离的语义简报缓存文件路径”所生成、定位或确认产物的本地路径。
    """
    return data_dir / "state" / "semantic-cache.json"


def load_semantic_cache(data_dir: Path) -> dict[str, dict[str, Any]]:
    """处理：读取指定语言的语义简报缓存，文件缺失或损坏时返回空缓存。
    输入：
    - ``data_dir``：当前运行的唯一数据根；所有状态和版本化产物都必须位于其中。
    输出：“读取指定语言的语义简报缓存，文件缺失或损坏时返回空缓存”形成的结构化字典；
      键值表达该处理定义的业务记录或查找关系。
    """
    path = semantic_cache_path(data_dir)
    if not path.exists():
        return {}
    payload = read_json(path)
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), dict):
        raise ValueError(f"Invalid semantic cache: {path}")
    return {
        str(item_id): entry
        for item_id, entry in payload["items"].items()
        if isinstance(entry, dict)
    }


def reusable_semantic_brief(
    item: dict[str, Any],
    cache: dict[str, dict[str, Any]],
    output_language: str = "zh-CN",
    reference_date: object = None,
) -> dict[str, Any] | None:
    """处理：校验指纹、语言和审核状态后返回可复用简报。
    输入：
    - ``item``：单个规范条目对象；通常包含 item_id、来源、标题、URL、时间和元数据。
    - ``cache``：本地持久化缓存对象；包含状态、时间、响应元数据和可复用结果。
    - ``output_language``：目标报告语言；决定标题译文字段、校验规则和界面文本。
    - ``reference_date``：当前报告或索引日期；用于重算本轮 status 与 importance。
    输出：“校验指纹、语言和审核状态后返回可复用简报”形成的结构化字典；
      键值表达该处理定义的业务记录或查找关系。
    """
    language = validate_output_language(output_language)
    item_id = str(item.get("item_id") or "")
    entry = cache.get(item_id)
    if semantic_cache_reuse_issue(item, entry, language) is not None:
        return None
    brief = entry.get("brief")
    if not isinstance(brief, dict):
        return None
    reused = {
        key: deepcopy(brief[key])
        for key in REUSABLE_BRIEF_FIELDS
        if key in brief
    }
    reused["tldr"] = _sanitize_cached_tldr(reused.get("tldr"))
    if (
        not reused.get("tldr")
        or tldr_quality_issue(
            reused.get("tldr"),
            str(item.get("title") or ""),
            language,
            [reused.get("title_zh"), reused.get("title_en")],
        )
    ):
        return None
    reused.update(run_relative_brief_fields(item, reference_date))
    reused["semantic_fingerprint"] = entry["fingerprint"]
    reused["semantic_cache_source_report_id"] = entry.get("report_id")
    reused["semantic_cache_reused"] = True
    return reused


def _coerce_date(value: object) -> date | None:
    """处理：从报告日期或带时区时间中提取日历日期用于动态新鲜度。
    输入：
    - ``value``：索引发布时间或报告参考日期的 date、datetime、ISO 字符串候选值。
    输出：可解析日期；缺失或非法输入返回 None，调用方采用受控回退。
    """

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def update_semantic_cache_from_report(
    report: dict[str, Any], index: dict[str, Any], data_dir: Path
) -> Path:
    """处理：从已验证报告更新按条目指纹索引的语义缓存。
    输入：
    - ``report``：当前报告结构；包含栏目、简报或事件、来源引用及质量元数据。
    - ``index``：当前来源索引对象；包含规范条目、来源结果、策略和采集时间。
    - ``data_dir``：当前运行的唯一数据根；所有状态和版本化产物都必须位于其中。
    输出：指向“从已验证报告更新按条目指纹索引的语义缓存”所生成、定位或确认产物的本地路径。
    """
    path = semantic_cache_path(data_dir)
    cache = load_semantic_cache(data_dir)
    indexed_items = {
        str(item.get("item_id")): item
        for item in index.get("items", [])
        if isinstance(item, dict) and item.get("item_id")
    }
    report_id = str(report.get("report_id") or "")
    output_language = validate_output_language(
        str(report.get("language") or "zh-CN")
    )
    updated_at = str(report.get("generated_at") or now_iso("Asia/Shanghai"))
    for section in report.get("sections", []):
        if not isinstance(section, dict):
            continue
        for brief in section.get("briefs", []):
            if not isinstance(brief, dict):
                continue
            item_id = str(brief.get("item_id") or "")
            indexed = indexed_items.get(item_id)
            if not indexed:
                continue
            fingerprint = semantic_fingerprint(indexed)
            existing = cache.get(item_id)
            current_brief = {
                key: deepcopy(brief[key])
                for key in REUSABLE_BRIEF_FIELDS
                if key in brief
            }
            if (
                existing
                and existing.get("state") == "approved"
                and existing.get("fingerprint") == fingerprint
                and str(existing.get("language") or "zh-CN") == output_language
                and existing.get("brief") == current_brief
            ):
                continue
            cache[item_id] = {
                "fingerprint": fingerprint,
                "language": output_language,
                "state": "pending",
                "report_id": report_id,
                "updated_at": updated_at,
                "brief": current_brief,
            }
    return write_json(
        path,
        {"schema_version": SEMANTIC_CACHE_SCHEMA, "items": cache},
    )


def finalize_semantic_cache_evaluation(
    evaluation: dict[str, Any], data_dir: Path
) -> Path | None:
    """处理：完成并固化语义缓存评估。
    输入：
    - ``evaluation``：独立质量评估对象；包含评分、问题和改进建议。
    - ``data_dir``：当前运行的唯一数据根；所有状态和版本化产物都必须位于其中。
    输出：指向“完成并固化语义缓存评估”所生成、定位或确认产物的本地路径；条件不满足时返回 None。
    """
    path = semantic_cache_path(data_dir)
    if not path.exists():
        return None
    cache = load_semantic_cache(data_dir)
    report_id = str(evaluation.get("evaluated_report_id") or "")
    dimensions = {
        str(row.get("id")): int(row.get("score", 0))
        for row in evaluation.get("dimensions", [])
        if isinstance(row, dict) and row.get("id")
    }
    continuity = str(evaluation.get("continuity_decision") or "selective")
    excluded = {
        str(value) for value in evaluation.get("exclude_from_continuity", [])
    }
    approved = (
        continuity != "reject"
        and not excluded.intersection({"all", "event_summaries"})
        and dimensions.get("summary_accuracy", 0) >= 3
        and dimensions.get("factual_reliability", 0) >= 3
        and dimensions.get("compliance_boundaries", 0) >= 3
    )
    changed = False
    for entry in cache.values():
        if entry.get("report_id") != report_id or entry.get("state") != "pending":
            continue
        entry["state"] = "approved" if approved else "rejected"
        entry["evaluation_id"] = evaluation.get("evaluation_id")
        entry["evaluation_scores"] = {
            key: dimensions.get(key, 0)
            for key in ("summary_accuracy", "factual_reliability", "compliance_boundaries")
        }
        changed = True
    if not changed:
        return path
    return write_json(
        path,
        {"schema_version": SEMANTIC_CACHE_SCHEMA, "items": cache},
    )
