from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, TypeVar

ITEM_ORDER_VALUES = {"source", "published_at"}

T = TypeVar("T")


def _field(item: object, name: str) -> Any:
    """处理：从规范文章对象或监控快照字典读取同名字段。
    输入：
    - ``item``：来自采集模型或 JSON 快照的单条文章记录。
    - ``name``：排序逻辑要读取的稳定字段名。
    输出：字段原值；字段不存在时返回 None，供统一排序逻辑使用同一缺失值语义。
    """
    if isinstance(item, Mapping):
        return item.get(name)
    return getattr(item, name, None)


def _metadata(item: object) -> Mapping[str, Any]:
    """读取文章的非核心排序元数据且拒绝非映射值。
    输入：``item``：来自规范文章对象或监控快照字典，可能带有外部来源生成的 metadata。
    输出：可安全读取 ``source_rank`` 与历史保留标记的映射；非法值降级为空映射。
    """
    value = _field(item, "metadata")
    return value if isinstance(value, Mapping) else {}


def _published_timestamp(item: object) -> float | None:
    """把来源声明的 ISO 发布时间归一为可比较的 UTC 时间戳。
    输入：``item``：其 ``published_at`` 来自 Feed、页面 time 元素或专用适配器。
    输出：有效发布时间的 UTC 时间戳；缺失或非法时间返回 None 并排在有时间条目之后。
    """
    value = _field(item, "published_at")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def _source_order_key(item: object) -> tuple[bool, bool, int]:
    """从文章元数据读取来源原始名次。
    输出：历史、缺失名次、有效名次的升序键；并列保留输入顺序。
    """
    metadata = _metadata(item)
    raw_rank = metadata.get("source_rank")
    try:
        rank = int(raw_rank) if raw_rank is not None else 0
    except (TypeError, ValueError):
        rank = 0
    return bool(metadata.get("retained_from_previous_snapshot")), rank <= 0, max(0, rank)


def _publication_order_key(item: object) -> tuple[bool, float]:
    """处理：把发布时间换成从新到旧的排序键。
    输入：已采集的条目或监控快照字典。
    输出：可计算的实际发布时间优先，缺失时间的条目保留原来相对顺序。
    """
    timestamp = _published_timestamp(item)
    return timestamp is None, -(timestamp or 0.0)


def order_source_items(items: list[T], item_order: str | None) -> list[T]:
    """处理：在不改写原始 Top 名次的前提下选择来源顺序或发布时间顺序。
    输入：
    - ``items``：同一来源已去重并带原始名次的候选序列。
    - ``item_order``：来自已解析来源配置的排序模式。
    输出：新的有序列表；``source`` 读取 ``metadata.source_rank`` 并把历史保留项置后，
    ``published_at`` 按有效发布时间倒序，时间缺失和并列时保持输入稳定顺序。
    """
    resolved = item_order or "source"
    if resolved not in ITEM_ORDER_VALUES:
        raise ValueError(f"Unsupported item_order: {resolved!r}")

    key = _source_order_key if resolved == "source" else _publication_order_key
    return sorted(items, key=key)



class SourceStatus(StrEnum):
    """记录一次来源采集的结果，区分正常无条目、访问失败、限流与待验证。"""
    SUCCESS = "success"
    PARTIAL = "partial"
    VERIFICATION_REQUIRED = "verification_required"
    RATE_LIMITED = "rate_limited"
    FAILED = "failed"
    NO_ITEMS = "no_items"


class ContentStatus(StrEnum):
    """描述文章可用于写作的证据，从元数据、部分正文到全文，并保留访问失败和待验证状态。"""
    NOT_FETCHED = "not_fetched"
    FULL_TEXT = "full_text"
    PARTIAL = "partial"
    METADATA_ONLY = "metadata_only"
    VERIFICATION_REQUIRED = "verification_required"
    FAILED = "failed"


@dataclass(slots=True)
class ArticleItem:
    """贯穿索引、写作和配图的文章记录，由 item_id 关联各阶段。
    published_at 来自出版方，discovered_at 记录采集发现时间。metadata 保留排名、图片候选和采集方式。
    """
    item_id: str
    source_id: str
    source_name: str
    title: str
    url: str
    canonical_url: str
    discovered_at: str
    module: str = "information"
    category: str = "international"
    content_status: str = ContentStatus.NOT_FETCHED
    description: str = ""
    published_at: str | None = None
    original_provider: str | None = None
    image_url: str | None = None
    content_path: str | None = None
    content_characters: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """把文章及其来源元数据写入规范索引行。"""
        return asdict(self)


def effective_page_results(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """处理：筛选页面最终状态，保留已恢复 HTTP 尝试作为原始诊断。
    输入：同一来源按采集顺序记录的页面尝试。
    输出：用于状态汇总的页面记录；浏览器成功后排除同 URL 的 HTTP 尝试。
    """
    recovered = {
        page.get("url"): page.get("status") for page in pages
        if isinstance(page, dict) and page.get("acquisition_method") == "browser"
        and page.get("status") in {"success", "no_items"} and not page.get("error")
    }
    return [page for page in pages if isinstance(page, dict) and not (
        page.get("acquisition_method") == "http"
        and (recovered.get(page.get("url")) == "success" or (
            recovered.get(page.get("url")) == "no_items"
            and page.get("status") not in {"partial", "verification_required", "rate_limited"}
        ))
    )]


def effective_source_status(source: dict[str, Any], pages: list[dict[str, Any]]) -> str:
    """处理：将旧索引中实际访问失败的空来源恢复为失败。
    输入：来源汇总和筛选后的有效页面结果。
    输出：保留正常空来源，剔除成功页面遗留的诊断信息对状态的影响。
    """
    status = str(source.get("status", ""))
    error = source.get("error")
    if status == SourceStatus.NO_ITEMS and error:
        success_diagnostics = "; ".join(
            str(page["error"]) for page in pages
            if page.get("status") == SourceStatus.SUCCESS and page.get("error")
        )
        if error != success_diagnostics:
            return SourceStatus.FAILED
    return status


@dataclass(slots=True)
class SourceResult:
    """一次来源采集的结果，按页面保留访问状态和错误，按来源汇总规范文章。
    collected_at 记录采集时间。页面失败和真实空结果使用不同状态。
    """
    source_id: str
    source_name: str
    source_url: str
    status: str
    collected_at: str
    module: str = "information"
    category: str = "international"
    page_title: str = ""
    final_url: str = ""
    http_status: int | None = None
    error: str | None = None
    challenge: dict[str, Any] = field(default_factory=dict)
    page_results: list[dict[str, Any]] = field(default_factory=list)
    items: list[ArticleItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """将来源和逐页结果写入索引，并按文章数生成 items_count。"""
        data = asdict(self)
        data["items_count"] = len(self.items)
        return data
