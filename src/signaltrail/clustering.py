from __future__ import annotations

import hashlib
import math
import re
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

_MATCH_WINDOW = timedelta(hours=96)
_LATIN_TOKEN = re.compile(r"[a-z0-9][a-z0-9_-]*")
_CJK_RUN = re.compile(r"[\u3400-\u9fff]+")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "in",
    "is",
    "it",
    "its",
    "new",
    "of",
    "on",
    "or",
    "says",
    "the",
    "to",
    "with",
}
_SEVERITY_TERMS = {
    "attack",
    "ban",
    "bankruptcy",
    "ceasefire",
    "crash",
    "crisis",
    "emergency",
    "explosion",
    "invasion",
    "launch",
    "lawsuit",
    "outage",
    "recall",
    "sanction",
    "war",
    "下调",
    "制裁",
    "危机",
    "召回",
    "战争",
    "爆炸",
    "禁令",
    "袭击",
}


class _UnionFind:
    """维护文章所属的连通分量，供监控聚类合并同一事件。"""

    def __init__(self, size: int) -> None:
        """为每篇候选文章建立一个独立集合。"""
        self.parent = list(range(size))
        self.rank = [0] * size

    def find(self, value: int) -> int:
        """查找文章所属的根节点，沿途缩短下次查找的路径。"""
        while self.parent[value] != value:
            self.parent[value] = self.parent[self.parent[value]]
            value = self.parent[value]
        return value

    def union(self, left: int, right: int) -> None:
        """合并两篇候选文章所在的集合。"""
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        if self.rank[left_root] < self.rank[right_root]:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        if self.rank[left_root] == self.rank[right_root]:
            self.rank[left_root] += 1


def _normalized_title(value: str) -> str:
    """统一标题大小写、空白和标点，保留可比较字符。"""
    return " ".join(re.sub(r"[^\w\u3400-\u9fff]+", " ", (value or "").casefold()).split())


def lexical_tokens(value: str) -> list[str]:
    """把中英文标题拆成去停用词的词项和中文二元组。"""
    normalized = _normalized_title(value)
    tokens = [
        token
        for token in _LATIN_TOKEN.findall(normalized)
        if len(token) > 1 and token not in _STOPWORDS
    ]
    for run in _CJK_RUN.findall(normalized):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
    return tokens


def _hash_feature(feature: str, dimensions: int) -> tuple[int, float]:
    """对标题特征取稳定哈希，用余数确定向量位置，用最高位确定加一或减一。"""
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    number = int.from_bytes(digest, "big")
    return number % dimensions, -1.0 if number & (1 << 63) else 1.0


def lexical_vector(value: str, dimensions: int = 512) -> dict[int, float]:
    """将标题中的词项、相邻词和连续三个字符映射成指定维数的归一化稀疏向量。"""
    tokens = lexical_tokens(value)
    features = [f"u:{token}" for token in tokens]
    features.extend(f"b:{left}|{right}" for left, right in zip(tokens, tokens[1:], strict=False))
    compact = re.sub(r"\s+", "", _normalized_title(value))
    features.extend(f"c:{compact[index : index + 3]}" for index in range(max(0, len(compact) - 2)))
    vector: defaultdict[int, float] = defaultdict(float)
    for feature in features:
        position, sign = _hash_feature(feature, dimensions)
        vector[position] += sign
    norm = math.sqrt(sum(weight * weight for weight in vector.values()))
    if not norm:
        return {}
    return {position: weight / norm for position, weight in vector.items()}


def cosine_similarity(left: dict[int, float], right: dict[int, float]) -> float:
    """对两个已归一化的稀疏标题向量求点积，得到聚类使用的余弦相似度。"""
    if len(left) > len(right):
        left, right = right, left
    return sum(weight * right.get(position, 0.0) for position, weight in left.items())


def _parse_time(item: dict[str, Any]) -> datetime | None:
    """把可选 ISO 时间文本解析为带时区时间，空值或非法值返回 None。"""
    value = item.get("published_at") or item.get("discovered_at")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)


def _role_score(item: dict[str, Any]) -> int:
    """把来源角色转换为聚类重要性分值。"""
    metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
    role = str(metadata.get("role") or "discovery")
    return {"primary": 10, "evidence": 8, "corroboration": 7, "discovery": 4}.get(role, 4)


def _tier(item: dict[str, Any]) -> int:
    """把来源层级规范到 1 至 3，异常值回退到第二层。"""
    metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
    try:
        return min(3, max(1, int(metadata.get("tier", 2))))
    except (TypeError, ValueError):
        return 2


def _representative(items: list[dict[str, Any]]) -> dict[str, Any]:
    """按层级、角色、标题信息量和 ID 稳定选择代表条目。
    输入：有序索引条目。
    """
    return min(
        items,
        key=lambda item: (
            _tier(item),
            -_role_score(item),
            -len(str(item.get("title") or "")),
            str(item.get("item_id") or ""),
        ),
    )


def _cluster_importance(
    representative: dict, source_count: int, latest: datetime | None, generated: datetime,
    terms: set[str], reported: bool,
) -> int:
    """处理：合计代表来源、佐证数量、时效、严重事件词及新颖度的分值。
    输入：聚类过程中已汇总的来源、时间、标题词项及历史命中情况。
    输出：监控首页排序采用的百分制重要性。
    """
    age_hours = max(0.0, (generated - latest).total_seconds() / 3600) if latest else 168.0
    recency = round(20 * max(0.0, 1.0 - min(age_hours, 168.0) / 168.0))
    source_score = {1: 25, 2: 18, 3: 12}[_tier(representative)] + _role_score(representative)
    corroboration = min(20, max(0, source_count - 1) * 7)
    severity = min(15, 5 * len(terms & _SEVERITY_TERMS))
    return min(100, source_score + corroboration + recency + severity + (3 if reported else 10))


def cluster_articles(
    items: list[dict[str, Any]],
    generated_at: str,
    *,
    threshold: float = 0.68,
    previous_clusters: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """处理：按同源链接或近期相似标题聚类，保留旧事件身份。
    输入：有序快照条目、采集时间、相似度阈值和上一快照的事件。
    输出：按重要性和时间排序的新闻簇，同时在条目元数据中写入归属。
    """
    if not items:
        return []
    generated = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    generated = generated.replace(tzinfo=generated.tzinfo or UTC)
    titles = [_normalized_title(str(item.get("title") or "")) for item in items]
    compact = [title.replace(" ", "") for title in titles]
    terms = [set(lexical_tokens(title)) for title in titles]
    times = [_parse_time(item) for item in items]
    modules = [str(item.get("module")) for item in items]
    urls = [item.get("canonical_url") for item in items]
    vector = lru_cache(maxsize=None)(lexical_vector)
    first_by_url: dict[str, int] = {}
    postings: defaultdict[str, deque[int]] = defaultdict(lambda: deque(maxlen=80))
    union = _UnionFind(len(items))
    for right, right_terms in enumerate(terms):
        candidates = set()
        for token in right_terms:
            candidates.update(postings[token])
            postings[token].append(right)
        url = str(urls[right] or "")
        if url and (first := first_by_url.setdefault(url, right)) != right:
            candidates.add(first)
        # 连通分量与边的处理顺序无关，逐条合并即可丢弃本条的候选。
        for left in candidates:
            if modules[left] != modules[right]:
                continue
            if times[left] and times[right] and abs(times[left] - times[right]) > _MATCH_WINDOW:
                continue
            if urls[left] and urls[left] == urls[right]:
                union.union(left, right)
                continue
            if (min(len(terms[left]), len(right_terms)) < 4 and titles[left] != titles[right]
                    or len(terms[left] & right_terms) < 2):
                continue
            shorter, longer = sorted((compact[left], compact[right]), key=len)
            if (len(shorter) >= 24 and len(shorter) / len(longer) >= 0.65 and shorter in longer
                    or cosine_similarity(vector(titles[left]), vector(titles[right])) >= threshold):
                union.union(left, right)

    groups: defaultdict[int, list[int]] = defaultdict(list)
    for index in range(len(items)):
        groups[union.find(index)].append(index)

    previous_clusters = previous_clusters or []
    prior_story_by_item = {
        str(item_id): str(cluster.get("story_id"))
        for cluster in previous_clusters
        if isinstance(cluster, dict) and cluster.get("story_id")
        for item_id in cluster.get("item_ids", [])
    }
    clusters: list[dict[str, Any]] = []
    for members in groups.values():
        grouped_items = [items[index] for index in members]
        representative = _representative(grouped_items)
        item_ids = [str(item.get("item_id")) for item in grouped_items]
        previous_ids = [prior_story_by_item[key] for key in item_ids if key in prior_story_by_item]
        if previous_ids:
            story_id = min(previous_ids)
        else:
            # 新故事由确定性的代表标题生成身份，不依赖本次列表顺序。
            identity = _normalized_title(str(representative.get("title") or ""))
            digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
            story_id = f"story-{digest}"
        all_sources = {str(item.get("source_id") or "") for item in grouped_items}
        source_ids = sorted(all_sources - {""})
        latest = max((times[i] for i in members if times[i] is not None), default=None)
        if len(source_ids) >= 3:
            phase = "confirmed"
        elif 0 < len(previous_ids) < len(members):
            phase = "updated"
        elif len(source_ids) >= 2:
            phase = "developing"
        else:
            phase = "new"
        cluster = {
            "story_id": story_id,
            "title": representative.get("title"),
            "representative_item_id": representative.get("item_id"),
            "item_ids": item_ids,
            "source_ids": source_ids,
            "source_count": len(source_ids),
            "module": representative.get("module"),
            "category": representative.get("category"),
            "phase": phase,
            "importance": _cluster_importance(
                representative, len(all_sources), latest, generated,
                set().union(*(terms[i] for i in members)), bool(previous_ids),
            ),
            "first_seen_at": min(
                (str(item.get("discovered_at")) for item in grouped_items),
                default=generated_at,
            ),
            "last_seen_at": max(
                (str(item.get("discovered_at")) for item in grouped_items),
                default=generated_at,
            ),
            "published_at": latest.isoformat(timespec="seconds") if latest else None,
            "image_url": next(
                (str(item.get("image_url")) for item in grouped_items if item.get("image_url")),
                None,
            ),
        }
        for item in grouped_items:
            metadata = item.setdefault("metadata", {})
            if isinstance(metadata, dict):
                metadata["story_id"] = story_id
                metadata["story_phase"] = phase
                metadata["cluster_importance"] = cluster["importance"]
        clusters.append(cluster)
    clusters.sort(
        key=lambda cluster: (
            int(cluster["importance"]),
            str(cluster.get("published_at") or cluster.get("last_seen_at") or ""),
        ),
        reverse=True,
    )
    return clusters
