from __future__ import annotations

import re
from typing import Any

OUTPUT_LANGUAGES = ("zh-CN", "en")

_CJK_PATTERN = re.compile(r"[\u3400-\u9fff]")
_ENGLISH_WORD_PATTERN = re.compile(r"\b[A-Za-z][A-Za-z'-]*\b")
_TRADITIONAL_BRIEF_SOURCES = {"cna_mainland", "rthk_finance_alt"}


STATUS_LABELS = {
    "NEW": "新增",
    "UPD": "更新",
    "CONF": "确认",
    "REV": "修正",
    "WATCH": "观察",
    "CLOSED": "关闭",
}
STATUS_LABELS_EN = {
    "NEW": "New",
    "UPD": "Updated",
    "CONF": "Confirmed",
    "REV": "Revised",
    "WATCH": "Watch",
    "CLOSED": "Closed",
}

ANALYSIS_SECTION_LABELS = {
    "geopolitics": "从地缘政治专家的角度",
    "ai_technology": "从 AI 研究/开发工程师的角度",
    "markets": "从股票分析师的角度",
}
ANALYSIS_SECTION_LABELS_EN = {
    "geopolitics": "Geopolitical Perspective",
    "ai_technology": "AI Research and Engineering Perspective",
    "markets": "Equity-Market Perspective",
}

EVALUATION_LABELS = {
    "coverage": "信息覆盖度",
    "importance_ordering": "重要性排序",
    "factual_reliability": "事实可靠性",
    "summary_accuracy": "摘要准确性",
    "analysis_traceability": "分析可追溯性",
    "historical_continuity": "历史连续性",
    "readability": "可读性",
    "timeliness": "时效性",
    "compliance_boundaries": "合规与边界",
}
EVALUATION_LABELS_EN = {
    "coverage": "Coverage",
    "importance_ordering": "Importance Ordering",
    "factual_reliability": "Factual Reliability",
    "summary_accuracy": "Summary Accuracy",
    "analysis_traceability": "Analysis Traceability",
    "historical_continuity": "Historical Continuity",
    "readability": "Readability",
    "timeliness": "Timeliness",
    "compliance_boundaries": "Compliance and Boundaries",
}

GROUP_LABELS = {"information": "资讯", "technology": "技术"}
GROUP_LABELS_EN = {"information": "News", "technology": "Technology"}


def validate_output_language(value: str) -> str:
    """校验输出语言并在不满足约束时报告错误。"""
    language = str(value or "").strip()
    if language not in OUTPUT_LANGUAGES:
        raise ValueError(
            "output.language must be one of: " + ", ".join(OUTPUT_LANGUAGES)
        )
    return language


def is_chinese_output(language: object) -> bool:
    """判断规范化后的输出语言是否为简体中文。"""
    return str(language or "zh-CN") == "zh-CN"


def localized(language: object, chinese: str, english: str) -> str:
    """根据目标语言在中英文文本之间选择。
    输入：输出语言。
    - ``chinese``：界面或报告字段的中文候选文本。
    - ``english``：界面或报告字段的英文候选文本。
    """
    return chinese if is_chinese_output(language) else english


def translated_title_field(language: object) -> str:
    """返回目标语言对应的译文标题字段名。"""
    return "title_zh" if is_chinese_output(language) else "title_en"


def translated_title(item: dict[str, Any], language: object) -> str:
    """读取目标语言的译文标题，缺失时回退到规范标题。"""
    return str(item.get(translated_title_field(language)) or "").strip()


def text_matches_output_language(
    value: object,
    language: object,
    *,
    minimum_units: int = 1,
) -> bool:
    """按最小信息单元判断文本是否符合目标输出语言。
    输入：待解析的值、输出语言。
    - ``minimum_units``：判定文本属于目标语言所需的最少有效字符单元数。
    """
    text = str(value or "").strip()
    if not text:
        return False
    if is_chinese_output(language):
        return len(_CJK_PATTERN.findall(text)) >= minimum_units
    return len(_ENGLISH_WORD_PATTERN.findall(text)) >= minimum_units


def source_matches_output_language(
    source_language: object,
    title: object,
    output_language: object,
) -> bool:
    """结合来源语言和标题内容判断是否需要翻译。
    输入：报告目标语言。
    - ``source_language``：来源内容声明的语言；与标题文本共同决定是否需要翻译。
    - ``title``：来源提供的标题文本；会清理空白，并用于过滤、身份或展示。
    """
    source = str(source_language or "").strip().lower()
    if source:
        if is_chinese_output(output_language):
            return source.startswith("zh") and not (
                "hant" in source.split("-") or source in {"zh-tw", "zh-hk", "zh-mo"}
            )
        return source.startswith("en")
    if not is_chinese_output(output_language) and _CJK_PATTERN.search(str(title or "")):
        return False
    return text_matches_output_language(title, output_language)


def brief_title_requires_translation(item: dict[str, Any], output_language: object) -> bool:
    """处理：根据材料的书写体系判断当前简报是否需要译题。
    输入：作者包或索引中的候选条目，以及日报目标语言。
    输出：需要用目标语言撰写主标题时返回真。
    """
    if is_chinese_output(output_language) and item.get("source_id") in _TRADITIONAL_BRIEF_SOURCES:
        # 旧索引将两个繁体来源标作 zh-CN，仍需将标题写成简体。
        return True
    metadata = item.get("metadata")
    source_language = item.get("source_language") or (
        metadata.get("language") if isinstance(metadata, dict) else None
    )
    return not source_matches_output_language(source_language, item.get("title"), output_language)
