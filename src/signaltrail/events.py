"""持续新闻平台的长期事件、关注与研究记录。"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlencode

from .adapters import is_article_link
from .clustering import cluster_articles, cosine_similarity, lexical_tokens, lexical_vector
from .image_policy import normalize_image_candidates
from .utils import canonicalize_url

_SNAPSHOT_FILES: dict[str, tuple[int, int]] = {}


@contextmanager
def _connect(data_dir: Path):
    """处理：打开个人平台数据库并建立轻量记录表。
    输入：新闻资料根目录。
    输出：支持事务的数据库连接，供事件和关注操作使用。
    """
    directory = data_dir / "platform"
    directory.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(directory / "events.sqlite", timeout=30)
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, payload TEXT,
                                            PRIMARY KEY(kind, id));
        CREATE TABLE IF NOT EXISTS follows (kind TEXT, target TEXT,
                                            PRIMARY KEY(kind, target));
    """)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _records(connection: sqlite3.Connection, kind: str) -> dict[str, dict]:
    """处理：读取某类记录并按身份索引。
    输入：数据库连接和记录类别。
    输出：供事件匹配与读取使用的字典。
    """
    return {
        key: json.loads(payload)
        for key, payload in connection.execute(
            "SELECT id,payload FROM records WHERE kind=?", (kind,)
        )
    }


def _put(connection: sqlite3.Connection, kind: str, key: str, value: dict) -> None:
    """处理：在当前事务内保存一项平台记录。
    输入：记录类别、身份和新的完整内容。
    输出：数据库中的该记录更新，其他记录保持原值。
    """
    connection.execute(
        "INSERT INTO records VALUES (?,?,?) ON CONFLICT(kind,id) DO UPDATE "
        "SET payload=excluded.payload WHERE records.payload<>excluded.payload",
        (
            kind,
            key,
            json.dumps(value, ensure_ascii=False),
        ),
    )


def _article_key(item: dict) -> str:
    """处理：优先用原文地址识别跨采集轮次的同一文章。
    输入：规范新闻条目。
    输出：文章去重使用的稳定键。
    """
    return str(item.get("canonical_url") or item.get("url") or item["item_id"])


def _canonical_event(connection: sqlite3.Connection, event_id: str) -> str:
    """处理：沿旧事件链接找到合并后的当前档案。
    输入：数据库连接和旧或当前事件身份。
    输出：继续读取与写入研究时使用的当前身份。
    """
    while row := connection.execute(
        "SELECT payload FROM records WHERE kind='event_alias' AND id=?",
        (event_id,),
    ).fetchone():
        event_id = json.loads(row[0])["event_id"]
    return event_id


def _merge_events(
    connection: sqlite3.Connection, event: dict, others: list[dict], events: dict, articles: dict
) -> None:
    """处理：共同报道确认事件合并时归并旧档案及其关注研究。
    输入：选定的最早事件、其他候选和已有文章。
    输出：保留单一首页卡片，旧链接和进行中研究继续指向该事件。
    """
    for other in others:
        old_id = other["event_id"]
        if old_id == event["event_id"]:
            continue
        event["article_keys"] = sorted(set(event["article_keys"]) | set(other["article_keys"]))
        event["story_ids"] = sorted(set(event["story_ids"]) | set(other["story_ids"]))
        event["research"].extend(other.get("research", []))
        for key in other["article_keys"]:
            articles[key]["event_id"] = event["event_id"]
            _put(connection, "article", key, articles[key])
        for job in other.get("research", []):
            job_id = job.get("job_id") or job.get("id")
            if job_id:
                _put(connection, "research", job_id, {**job, "event_id": event["event_id"]})
        connection.execute(
            "INSERT OR IGNORE INTO follows SELECT kind,? FROM follows "
            "WHERE kind='event' AND target=?",
            (event["event_id"], old_id),
        )
        connection.execute("DELETE FROM follows WHERE kind='event' AND target=?", (old_id,))
        connection.execute("DELETE FROM records WHERE kind='event' AND id=?", (old_id,))
        _put(connection, "event_alias", old_id, {"event_id": event["event_id"]})
        del events[old_id]


def _snapshot_clusters(snapshot: dict, items: dict[str, dict]) -> list[dict]:
    """处理：复用监控已完成的分组，只为未覆盖或含无效链接的文章补算。
    输入：快照分组和已过滤导航的文章映射。
    输出：覆盖全部有效文章的簇；兼容聚类只修改文章副本。
    """
    groups = snapshot.get("clusters", [])
    counts = Counter(key for group in groups for key in group["item_ids"])
    clusters = []
    covered = set()
    for group in groups:
        members = group["item_ids"]
        if (members and group.get("story_id") and group.get("title")
                and all(key in items and counts[key] == 1 for key in members)):
            clusters.append(group)
            covered.update(members)
    pending = [item for key, item in items.items() if key not in covered]
    if pending:
        originals = {frozenset(group["item_ids"]): group for group in groups}
        for cluster in cluster_articles(
            pending, snapshot.get("generated_at") or "1970-01-01T00:00:00+00:00",
        ):
            original = originals.get(frozenset(cluster["item_ids"]))
            if original:
                cluster["story_id"] = original["story_id"]
                cluster["importance"] = original.get("importance", cluster["importance"])
                for key in cluster["item_ids"]:
                    items[key]["metadata"]["story_id"] = cluster["story_id"]
                    items[key]["metadata"]["cluster_importance"] = cluster["importance"]
            clusters.append(cluster)
    return clusters


def sync_monitor_snapshot(data_dir: Path, snapshot: dict | None = None) -> None:
    """处理：把新监控快照并入长期事件档案，保留已离开快照的文章。
    输入：资料根目录及可选的刚生成快照；缺省读取监控文件。
    输出：数据库保存新增文章与事件，重复快照不重写事件记录。
    """
    path = data_dir / "monitor" / "snapshot.json"
    signature = None
    if snapshot is None:
        if not path.exists():
            return
        signature = (path.stat().st_mtime_ns, path.stat().st_size)
        if _SNAPSHOT_FILES.get(str(path)) == signature:
            return
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    fingerprint = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
    items = {
        str(item["item_id"]): {**item, "metadata": dict(item.get("metadata") or {})}
        for item in snapshot.get("items", [])
        if is_article_link(item.get("title", ""), item.get("url", ""))
    }
    clusters = _snapshot_clusters(snapshot, items)
    with _connect(data_dir) as connection:
        connection.execute("BEGIN IMMEDIATE")
        meta = _records(connection, "meta")
        if meta.get("snapshot", {}).get("fingerprint") == fingerprint:
            if (signature is not None and path.exists()
                    and (path.stat().st_mtime_ns, path.stat().st_size) == signature):
                _SNAPSHOT_FILES[str(path)] = signature
            return
        events = _records(connection, "event")
        articles = _records(connection, "article")
        story_events = {
            key: event["event_id"] for event in events.values() for key in event["story_ids"]
        }
        article_events = {
            key: event["event_id"] for event in events.values() for key in event["article_keys"]
        }
        title_events = defaultdict(set)
        for event in events.values():
            for token in set(lexical_tokens(event["title"])):
                title_events[token].add(event["event_id"])
        sources = {
            str(row.get("source_id") or row.get("id")): row for row in snapshot.get("sources", [])
        }
        source_names = meta.get("sources", {})
        source_names.update(
            {key: row.get("source_name") or row.get("name") or key for key, row in sources.items()}
        )
        _put(connection, "meta", "sources", source_names)
        for cluster in clusters:
            members = [items[key] for key in cluster["item_ids"] if key in items]
            if not members:
                continue
            keys = {_article_key(item) for item in members}
            candidate_ids = {article_events[key] for key in keys if key in article_events}
            if cluster["story_id"] in story_events:
                candidate_ids.add(story_events[cluster["story_id"]])
            candidates = [
                events[key] for key in {_canonical_event(connection, key) for key in candidate_ids}
            ]
            if not candidates:
                title = cluster["title"]
                tokens = set(lexical_tokens(title))
                shared = Counter(key for token in tokens for key in title_events[token])
                # 高相似标题只续接同栏目近期事件，主题相同不会直接合并。
                candidates = [
                    event
                    for event in (
                        events[key] for key, count in shared.items() if count >= 3 and key in events
                    )
                    if (
                        event["category"] == cluster.get("category")
                        and len(tokens.intersection(lexical_tokens(event["title"]))) >= 3
                        and cosine_similarity(lexical_vector(title), lexical_vector(event["title"]))
                        >= 0.86
                        and abs(
                            _time(cluster.get("published_at") or snapshot["generated_at"])
                            - _time(event["latest_at"])
                        )
                        <= 96 * 3600
                    )
                ]
            event = (
                min(candidates, key=lambda row: (row["first_seen_at"], row["event_id"]))
                if candidates
                else {
                    "event_id": cluster["story_id"],
                    "story_ids": [],
                    "article_keys": [],
                    "first_seen_at": min(
                        item.get("discovered_at") or snapshot["generated_at"] for item in members
                    ),
                    "research": [],
                }
            )
            _merge_events(connection, event, candidates, events, articles)
            for item in members:
                key = _article_key(item)
                previous = articles.get(key, {})
                article = {**previous, **item, "event_id": event["event_id"]}
                article["first_discovered_at"] = (
                    previous.get("first_discovered_at")
                    or item.get("discovered_at")
                    or snapshot["generated_at"]
                )
                # 监控只带摘要时保留研究阶段补齐的正文，避免下一轮采集擦除。
                if previous.get("content_path") and not item.get("content_path"):
                    article.update(
                        {
                            field: value
                            for field, value in previous.items()
                            if field.startswith("content") or field == "body"
                        }
                    )
                article["metadata"] = {**previous.get("metadata", {}), **item.get("metadata", {})}
                if previous.get("content_path") and not item.get("content_path"):
                    old_meta = previous.get("metadata") or {}
                    new_meta = item.get("metadata") or {}
                    changed_feed = (old_meta.get("feed_content_sha256")
                                    and new_meta.get("feed_content_sha256")
                                    and old_meta["feed_content_sha256"]
                                    != new_meta["feed_content_sha256"])
                    changed_text = any(
                        str(previous.get(field) or "").split() != str(item.get(field) or "").split()
                        for field in ("title", "description")
                    )
                    # 同 URL 的实际文字变化才重验正文，单纯刷新发现时间不触发。
                    if changed_feed or changed_text:
                        article["metadata"]["content_needs_refresh"] = True
                source = sources.get(str(item.get("source_id")), {})
                article["source_name"] = (
                    item.get("source_name")
                    or source.get("source_name")
                    or source.get("name")
                    or item.get("source_id")
                )
                article["item_ids"] = sorted(
                    set(previous.get("item_ids", [])) | {str(item["item_id"])}
                )
                articles[key] = article
                if article != previous:
                    _put(connection, "article", key, article)
            event["story_ids"] = sorted(set(event["story_ids"]) | {cluster["story_id"]})
            event["article_keys"] = sorted(set(event["article_keys"]) | keys)
            event_articles = [articles[key] for key in event["article_keys"]]
            dated_articles = [row for row in event_articles if _valid_publication(row)]
            newest = max(dated_articles or event_articles, key=lambda row: _news_time(row))
            event.update(
                {
                    "title": newest.get("title") or cluster["title"],
                    "representative_url": _article_key(newest),
                    "original_language": newest.get("metadata", {}).get("language"),
                    "summary": newest.get("description") or newest.get("summary") or "",
                    "image_url": next(
                        iter(
                            normalize_image_candidates(
                                [
                                    newest.get("image_url"),
                                    cluster.get("image_url"),
                                    event.get("image_url"),
                                ]
                            )
                        ),
                        None,
                    ),
                    "category": cluster.get("category") or "",
                    "module": cluster.get("module") or "",
                    "latest_at": datetime.fromtimestamp(_news_time(newest), UTC).isoformat(),
                    "dated": bool(dated_articles),
                    "recent_articles": [
                        {"at": _news_time(row), "source_id": row.get("source_id")}
                        for row in dated_articles
                    ],
                    "source_ids": sorted(
                        {str(row["source_id"]) for row in event_articles if row.get("source_id")}
                    ),
                    "article_count": len(event_articles),
                    "importance": cluster.get("importance", 0),
                }
            )
            event["topics"] = sorted(
                {str(topic) for row in event_articles for topic in row.get("topics", [])}
                | {event["category"]}
            )
            event["source_count"] = len(event["source_ids"])
            event["attention"] = event["source_count"] * 10 + event["article_count"]
            events[event["event_id"]] = event
            for key in event["story_ids"]:
                story_events[key] = event["event_id"]
            for key in event["article_keys"]:
                article_events[key] = event["event_id"]
            for token in set(lexical_tokens(event["title"])):
                title_events[token].add(event["event_id"])
            _put(connection, "event", event["event_id"], event)
        _put(
            connection,
            "meta",
            "snapshot",
            {"fingerprint": fingerprint, "generated_at": snapshot.get("generated_at")},
        )
    if (signature is not None and path.exists()
            and (path.stat().st_mtime_ns, path.stat().st_size) == signature):
        _SNAPSHOT_FILES[str(path)] = signature


def _time(value: str) -> float:
    """处理：把新闻时间转为排序与短期续接使用的秒数。
    输入：新闻时间字符串，未知时间为空。
    输出：时间戳；未知时间排在末尾。
    """
    if not value:
        return 0
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).timestamp()


def _article_time(item: dict) -> str:
    """处理：选取新闻发布时间，缺失时使用首次发现时间。
    输入：采集文章记录。
    输出：事件更新时间与时间线使用的时间。
    """
    return item.get("published_at") or item.get("discovered_at") or ""


def _valid_publication(item: dict) -> bool:
    """处理：判定声明的发布时间是否可以作为当前新闻排序依据。
    输入：保留原始发布时间的文章。
    输出：已发布文章为真，未来计划日期留在详情中而不置顶。
    """
    return (
        bool(item.get("published_at"))
        and _time(item["published_at"]) <= datetime.now(UTC).timestamp() + 300
    )


def _news_time(item: dict) -> float:
    """处理：采用可信发布时间，缺失时采用首次发现时间。
    输入：规范文章记录。
    输出：新闻排序时间，不让未来页面日期进入首页头条。
    """
    return (
        _time(item["published_at"])
        if _valid_publication(item)
        else min(
            _time(item.get("first_discovered_at") or item.get("discovered_at") or ""),
            datetime.now(UTC).timestamp(),
        )
    )


def get_follows(data_dir: Path) -> dict:
    """处理：读取个人关注的事件、来源和主题。
    输入：个人资料根目录。
    输出：前端可直接恢复的三类关注列表。
    """
    result = {"events": [], "sources": [], "topics": []}
    with _connect(data_dir) as connection:
        for kind, target in connection.execute("SELECT kind,target FROM follows ORDER BY target"):
            result[kind + "s"].append(target)
    return result


def set_follow(data_dir: Path, kind: str, target: str, following: bool) -> dict:
    """处理：保存或取消一项个人关注。
    输入：事件、来源或主题身份以及关注开关。
    输出：更新后的完整关注列表。
    """
    if (
        kind not in {"event", "source", "topic"}
        or not isinstance(target, str)
        or not target.strip()
    ):
        raise ValueError("关注类别和目标不能为空")
    with _connect(data_dir) as connection:
        if following:
            connection.execute("INSERT OR IGNORE INTO follows VALUES (?,?)", (kind, target))
        else:
            connection.execute("DELETE FROM follows WHERE kind=? AND target=?", (kind, target))
    return get_follows(data_dir)


def _card(event: dict, follows: dict) -> dict:
    """处理：把长期档案投影为新闻卡片并计算关注状态。
    输入：事件记录和个人关注列表。
    输出：列表和详情共用的卡片字段。
    """
    fields = (
        "event_id",
        "title",
        "summary",
        "image_url",
        "category",
        "module",
        "latest_at",
        "first_seen_at",
        "source_count",
        "article_count",
        "attention",
        "importance",
        "source_ids",
        "topics",
    )
    result = {key: event[key] for key in fields}
    original_language = event.get("original_language") or (
        "zh-CN" if re.search(r"[\u3400-\u9fff]", event["title"]) else "en"
    )
    result["original_language"] = original_language
    for lang in ("zh", "en"):
        for field in ("title", "summary"):
            result[f"{field}_{lang}"] = event[field] if original_language.startswith(lang) else None
    result["dated"] = event.get("dated", False)
    now = datetime.now(UTC).timestamp()
    recent = [row for row in event.get("recent_articles", []) if now - row["at"] <= 72 * 3600]
    recent_sources = {row["source_id"] for row in recent}
    age = max(0, now - _time(event["latest_at"])) / 3600
    result["attention"] = round((10 * len(recent_sources) + len(recent)) * math.exp(-age / 36), 2)
    result["followed"] = event["event_id"] in follows["events"]
    result["interest"] = (
        100 * result["followed"]
        + 20 * len(set(event["source_ids"]) & set(follows["sources"]))
        + 30 * len(set(event["topics"]) & set(follows["topics"]))
    )
    return result


def report_event_cards(data_dir: Path, report: dict) -> list[dict]:
    """处理：将日报重点事件与已有长期档案按原文证据关联。
    输入：已生成日报中的来源引用，不引入日报之外的素材事件。
    输出：带日报事件身份的延伸阅读卡片，未归档的事件保持仅日报阅读。
    """
    cards = []
    follows = get_follows(data_dir)
    with _connect(data_dir) as connection:
        for section in report.get("sections", []):
            for item in section.get("items", []):
                card = None
                for ref in item.get("source_refs", []):
                    if not ref.get("url"):
                        continue
                    row = connection.execute(
                        "SELECT payload FROM records WHERE kind='article' AND id=?",
                        (canonicalize_url(ref["url"]),),
                    ).fetchone()
                    if row is None:
                        continue
                    article = json.loads(row[0])
                    event_id = _canonical_event(connection, article["event_id"])
                    event = json.loads(
                        connection.execute(
                            "SELECT payload FROM records WHERE kind='event' AND id=?", (event_id,)
                        ).fetchone()[0]
                    )
                    card = _card(event, follows)
                    break
                platform_id = card["event_id"] if card else None
                primary = item.get("primary_source", {})
                card = card or {
                    "event_id": item["event_id"],
                    "image_url": None,
                    "category": section.get("category", ""),
                    "module": section.get("module", ""),
                    "source_count": len(item.get("source_refs", [])),
                    "article_count": len(item.get("source_refs", [])),
                    "source_ids": [primary["id"]] if primary.get("id") else [],
                    "topics": [section.get("category", "")],
                    "latest_at": report.get("generated_at") or report["date"],
                    "first_seen_at": report.get("generated_at") or report["date"],
                    "attention": 0,
                    "followed": False,
                }
                language = report.get("language") or "zh-CN"
                if card.get("original_language") == "en" and not card.get("title_en"):
                    card["title_en"] = card["title"]
                card.update(
                    title=item["title"],
                    summary=item.get("tldr", ""),
                    importance=item.get("importance", 0),
                    report_id=report["report_id"],
                    report_event_id=item["event_id"],
                    platform_event_id=platform_id,
                    research_available=platform_id is not None,
                    original_language=language,
                )
                suffix = "zh" if language.startswith("zh") else "en"
                card[f"title_{suffix}"] = item["title"]
                card[f"summary_{suffix}"] = item.get("tldr", "")
                card["detail_url"] = (
                    "/events/"
                    + quote(card["event_id"])
                    + "?"
                    + urlencode(
                        {
                            "report_id": report["report_id"],
                            "report_event_id": item["event_id"],
                        }
                    )
                )
                cards.append(card)
    return cards


def list_events(
    data_dir: Path,
    *,
    sort: str = "latest",
    category: str = "",
    source: str = "",
    q: str = "",
    following: bool = False,
    limit: int = 60,
    offset: int = 0,
) -> dict:
    """处理：按时间、关注度或个人关注筛选长期事件。
    输入：资料目录与首页筛选条件。
    输出：事件卡片、筛选项和快照更新时间。
    """
    sync_monitor_snapshot(data_dir)
    follows = get_follows(data_dir)
    with _connect(data_dir) as connection:
        events = [
            _card(event, follows)
            for event in _records(connection, "event").values()
            if is_article_link(event["title"], event["article_keys"][0])
        ]
        meta = _records(connection, "meta")
        sources = meta.get("sources", {})
        generated_at = meta.get("snapshot", {}).get("generated_at")
    topics = sorted({topic for event in events for topic in event["topics"] if topic})
    events = [
        event
        for event in events
        if (
            (not category or _matches_category(event, category))
            and (not source or source in event["source_ids"])
            and (not q or q.casefold() in (event["title"] + " " + event["summary"]).casefold())
            and (not following or event["interest"] > 0)
        )
    ]
    events.sort(
        key=lambda event: (
            event["dated"] if sort == "latest" else True,
            event.get(sort, 0) if sort in {"attention", "interest"} else _time(event["latest_at"]),
            _time(event["latest_at"]),
            event["event_id"],
        ),
        reverse=True,
    )
    total = len(events)
    offset = max(0, offset)
    return {
        "events": events[offset : offset + min(120, max(1, limit))],
        "total": total,
        "generated_at": generated_at,
        "sources": [{"id": key, "name": name} for key, name in sorted(sources.items())],
        "topics": topics,
    }


def _matches_category(event: dict, category: str) -> bool:
    """处理：把首页栏目映射到采集阶段已有分类。
    输入：事件的模块、细分类与用户选择的栏目。
    输出：科技聚合技术模块，市场聚合经济分类，国际保持原分类范围。
    """
    if category == "technology":
        return event.get("module") == "technology" or event["category"] == "technology"
    if category == "market":
        return event["category"] in {"market", "markets", "economy"}
    return event["category"] == category


def get_event(data_dir: Path, event_id: str) -> dict | None:
    """处理：读取事件完整文章、发展时间线和研究历史。
    输入：资料目录和长期事件身份。
    输出：事件详情，未知身份返回空值供服务返回未找到。
    """
    sync_monitor_snapshot(data_dir)
    with _connect(data_dir) as connection:
        event_id = _canonical_event(connection, event_id)
        row = connection.execute(
            "SELECT payload FROM records WHERE kind='event' AND id=?", (event_id,)
        ).fetchone()
        if row is None:
            return None
        event = json.loads(row[0])
        stored = {
            key: json.loads(
                connection.execute(
                    "SELECT payload FROM records WHERE kind='article' AND id=?",
                    (key,),
                ).fetchone()[0]
            )
            for key in event["article_keys"]
        }
    articles = sorted(
        (stored[key] for key in event["article_keys"]),
        key=lambda row: _time(_article_time(row)),
        reverse=True,
    )
    analyses = {}
    for analysis in reversed(_report_analyses(data_dir, articles)):
        analyses[(analysis["domain"], analysis.get("language") or "zh-CN")] = analysis
    for job in sorted(
        event.get("research", []),
        key=lambda row: row.get("updated_at") or row.get("created_at") or "",
    ):
        if job.get("status") == "completed":
            for analysis in job.get("result", {}).get("analyses", []):
                language = analysis.get("language") or job.get("language") or "zh-CN"
                analyses[(analysis["domain"], language)] = {
                    **analysis,
                    "language": language,
                    "job_id": job.get("job_id"),
                }
    return {
        "event": _card(event, get_follows(data_dir)),
        "articles": articles,
        "timeline": [
            {"at": _article_time(row), "title": row["title"], "item_ids": row["item_ids"]}
            for row in reversed(articles)
        ],
        "analyses": list(analyses.values()),
        "research": event.get("research", []),
    }


def _report_analyses(data_dir: Path, articles: list[dict]) -> list[dict]:
    """处理：只关联证据文章命中本事件的已有日报分析。
    输入：报告目录与当前事件的文章身份及地址。
    输出：带报告出处的三视角分析，不引入日报中的无关论点。
    """
    item_ids = {key for item in articles for key in item.get("item_ids", [item["item_id"]])}
    urls = {_article_key(item) for item in articles}
    found = []
    for path in sorted((data_dir / "reports").rglob("*.json"), reverse=True):
        report = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(report, dict) or not report.get("analyses"):
            continue
        matching_events = set()
        for section in report.get("sections", []):
            for event in section.get("items", []):
                if any(
                    ref.get("item_id") in item_ids or ref.get("url") in urls
                    for ref in event.get("source_refs", [])
                ):
                    matching_events.add(event["event_id"])
        for analysis in report["analyses"]:
            if matching_events.intersection(analysis.get("evidence_event_ids", [])):
                found.append(
                    {
                        **analysis,
                        "report_id": report.get("report_id"),
                        "generated_at": report.get("generated_at"),
                        "language": report.get("language") or "zh-CN",
                    }
                )
    return sorted(found, key=lambda analysis: analysis.get("generated_at") or "", reverse=True)


def save_event_research(data_dir: Path, event_id: str, research: dict) -> dict:
    """处理：把研究执行结果挂接到其事件，保留此前研究。
    输入：事件身份与包含研究身份的结果记录。
    输出：保存后的研究记录，供研究任务接口返回。
    """
    with _connect(data_dir) as connection:
        connection.execute("BEGIN IMMEDIATE")
        event_id = _canonical_event(connection, event_id)
        research = {**research, "event_id": event_id}
        row = connection.execute(
            "SELECT payload FROM records WHERE kind='event' AND id=?", (event_id,)
        ).fetchone()
        if row is None:
            raise ValueError("事件不存在")
        event = json.loads(row[0])
        records = event.setdefault("research", [])
        job_id = research.get("job_id") or research.get("id")
        records[:] = [
            row for row in records if not job_id or (row.get("job_id") or row.get("id")) != job_id
        ]
        records.append(research)
        _put(connection, "event", event_id, event)
        if job_id:
            _put(connection, "research", job_id, {**research, "event_id": event_id})
    return research


def get_research_job(data_dir: Path, job_id: str) -> dict | None:
    """处理：按任务身份读取后台研究状态。
    输入：个人资料目录和任务身份。
    输出：任务记录，供详情页轮询或后台恢复使用。
    """
    with _connect(data_dir) as connection:
        row = connection.execute(
            "SELECT payload FROM records WHERE kind='research' AND id=?", (job_id,)
        ).fetchone()
    return json.loads(row[0]) if row else None


def list_research_jobs(
    data_dir: Path, status: str | None = None, event_id: str | None = None
) -> list[dict]:
    """处理：列出后台研究任务并按状态选取待恢复任务。
    输入：资料目录和可选任务状态。
    输出：研究调度器或前端使用的任务列表。
    """
    with _connect(data_dir) as connection:
        jobs = list(_records(connection, "research").values())
        if event_id is not None:
            event_id = _canonical_event(connection, event_id)
    return [
        job
        for job in jobs
        if (status is None or job.get("status") == status)
        and (event_id is None or job.get("event_id") == event_id)
    ]


def update_event_articles(data_dir: Path, event_id: str, articles: list[dict]) -> None:
    """处理：将按需抓取的正文补回事件文章而不改变首页事件时间。
    输入：事件身份和正文提取后返回的规范文章。
    输出：原文章的正文路径、内容和提取元数据更新，日报及事件排序保持原值。
    """
    with _connect(data_dir) as connection:
        connection.execute("BEGIN IMMEDIATE")
        event_id = _canonical_event(connection, event_id)
        row = connection.execute(
            "SELECT payload FROM records WHERE kind='event' AND id=?", (event_id,)
        ).fetchone()
        if row is None:
            raise ValueError("事件不存在")
        event = json.loads(row[0])
        for article in articles:
            key = _article_key(article)
            if key not in event["article_keys"]:
                continue
            previous = json.loads(
                connection.execute(
                    "SELECT payload FROM records WHERE kind='article' AND id=?",
                    (key,),
                ).fetchone()[0]
            )
            updated = {
                **previous,
                **{
                    field: value
                    for field, value in article.items()
                    if field.startswith("content") or field == "body"
                },
            }
            updated["metadata"] = {**previous.get("metadata", {}), **article.get("metadata", {})}
            _put(connection, "article", key, updated)


def refresh_event_images(data_dir: Path, items: list[dict]) -> None:
    """处理：把重新筛选的文章配图原地更新到档案卡片。
    输入：已修正图片字段的监控条目。
    输出：仅更新文章配图与受影响卡片，保留关注、研究和事件时间。
    """
    with _connect(data_dir) as connection:
        connection.execute("BEGIN IMMEDIATE")
        affected = set()
        for item in items:
            key = _article_key(item)
            row = connection.execute(
                "SELECT payload FROM records WHERE kind='article' AND id=?", (key,)
            ).fetchone()
            if row is None:
                continue
            article = json.loads(row[0])
            article["image_url"] = item.get("image_url")
            article.setdefault("metadata", {})["image_candidates"] = item.get("metadata", {}).get(
                "image_candidates", []
            )
            _put(connection, "article", key, article)
            affected.add(article["event_id"])
        for event_id in affected:
            event = json.loads(
                connection.execute(
                    "SELECT payload FROM records WHERE kind='event' AND id=?", (event_id,)
                ).fetchone()[0]
            )
            articles = [
                json.loads(
                    connection.execute(
                        "SELECT payload FROM records WHERE kind='article' AND id=?",
                        (key,),
                    ).fetchone()[0]
                )
                for key in event["article_keys"]
            ]
            articles.sort(key=_news_time, reverse=True)
            event["image_url"] = next(
                iter(
                    normalize_image_candidates(
                        [article.get("image_url") for article in articles],
                    )
                ),
                None,
            )
            _put(connection, "event", event_id, event)
