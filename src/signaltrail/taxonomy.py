from __future__ import annotations

from enum import StrEnum

from .localization import is_chinese_output


class ContentModule(StrEnum):
    """区分新闻与技术两个报告模块，供栏目分类和校验使用。"""
    INFORMATION = "information"
    TECHNOLOGY = "technology"


class InformationCategory(StrEnum):
    """约定新闻模块的栏目 ID，供来源分类和报告编译共用。"""
    INTERNATIONAL = "international"
    DOMESTIC = "domestic"
    MILITARY = "military"
    MARKET = "market"
    # 旧分类仍需读取 schema 1.1/1.2 报告和来源索引，但新输出只使用规范值。
    ECONOMY = "economy"
    TECHNOLOGY = "technology"


class TechnologyCategory(StrEnum):
    """约定技术模块的栏目 ID，供来源分类和报告编译共用。"""
    NEWS = "news"
    PAPERS = "papers"
    OPEN_SOURCE = "open_source"


class AnalysisDomain(StrEnum):
    """约定研判的三个领域，供分派写作、证据校验和连续性记录共用。"""
    GEOPOLITICS = "geopolitics"
    MARKETS = "markets"
    AI_TECHNOLOGY = "ai_technology"


CATEGORIES_BY_MODULE: dict[str, set[str]] = {
    ContentModule.INFORMATION: {item.value for item in InformationCategory},
    ContentModule.TECHNOLOGY: {item.value for item in TechnologyCategory},
}

REQUIRED_SECTION_IDS_V11 = {
    "information.international",
    "information.domestic",
    "information.military",
    "information.economy",
    "technology.news",
    "technology.papers",
    "technology.open_source",
}
REQUIRED_SECTION_IDS_V12 = REQUIRED_SECTION_IDS_V11 | {"information.technology"}
REQUIRED_SECTION_IDS_V13 = {
    "information.international",
    "information.domestic",
    "information.military",
    "information.market",
    "technology.news",
    "technology.papers",
    "technology.open_source",
}

SECTION_ORDER_V13 = (
    "information.international",
    "information.domestic",
    "information.military",
    "information.market",
    "technology.news",
    "technology.papers",
    "technology.open_source",
)

SECTION_GROUPS_V13 = {
    "information": SECTION_ORDER_V13[:4],
    "technology": SECTION_ORDER_V13[4:],
}

SECTION_TITLES_V13 = {
    "information.international": "国际",
    "information.domestic": "国内新闻",
    "information.military": "军事",
    "information.market": "市场",
    "technology.news": "技术新闻",
    "technology.papers": "值得阅读的论文",
    "technology.open_source": "今日值得关注的开源项目",
}

SECTION_TITLES_EN_V13 = {
    "information.international": "International",
    "information.domestic": "Domestic News",
    "information.military": "Military",
    "information.market": "Markets",
    "technology.news": "Technology News",
    "technology.papers": "Papers Worth Reading",
    "technology.open_source": "Open-Source Projects to Watch",
}


def section_titles(language: object) -> dict[str, str]:
    """按输出语言返回规范栏目 ID 到标题的映射。"""
    return SECTION_TITLES_V13 if is_chinese_output(language) else SECTION_TITLES_EN_V13

# 早期模型草稿使用过这些直观名称：只在草稿边界兼容接收，持久化时一律编译为
# 上方 schema 1.5 的规范标识。
SECTION_ID_ALIASES_V15 = {
    "information.economy": "information.market",
    "information.markets": "information.market",
    "technology.tech_news": "technology.news",
    "technology.technology_news": "technology.news",
    "technology.oss": "technology.open_source",
    "technology.opensource": "technology.open_source",
}


def canonical_section_id(section_id: str) -> str:
    """把规范或旧版栏目名称映射到当前 schema ID。
    输入：``section_id``：待规范化的报告栏目 ID 或兼容别名。
    输出：可跨修订关联的稳定字符串标识，供索引、状态或发布记录使用。
    """
    normalized = section_id.strip()
    return SECTION_ID_ALIASES_V15.get(normalized, normalized)


def required_section_ids(schema_version: str | None) -> set[str]:
    """返回指定报告 schema 强制要求的栏目 ID。
    输入：``schema_version``：报告 schema 版本；决定必须存在的栏目集合。
    """
    if schema_version in {"1.3", "1.4", "1.5", "2.0"}:
        return REQUIRED_SECTION_IDS_V13
    return REQUIRED_SECTION_IDS_V12 if schema_version == "1.2" else REQUIRED_SECTION_IDS_V11


def validate_content_taxonomy(module: str, category: str) -> None:
    """校验模块与栏目 ID 是否属于当前报告分类契约。
    输入：
    - ``module``：报告顶层领域 ID，例如 information 或 technology。
    - ``category``：报告栏目 ID；必须与 module 和当前 taxonomy 契约一致。
    """
    allowed = CATEGORIES_BY_MODULE.get(module)
    if allowed is None:
        raise ValueError(f"Unknown content module: {module}")
    if category not in allowed:
        raise ValueError(f"Category {category!r} is not valid for module {module!r}")
