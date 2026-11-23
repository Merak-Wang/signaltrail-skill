from __future__ import annotations

import re
from pathlib import Path

from .collector import is_eligible
from .config import AppConfig
from .models import ArticleItem, SourceStatus
from .storage import exclusive_lock, next_revision, write_immutable_json
from .utils import canonicalize_url, clean_title, item_id, now_iso, read_json, today_str

SOURCE_NAME_ALIASES = {
    "CNBC World": "cnbc_world",
    "Reuters": "reuters",
    "ABC News": "abc_news",
    "Guardian Nigeria": "guardian_ng",
    "The Guardian Nigeria World": "guardian_ng",
    "BBC World": "bbc_world",
    "Forbes": "forbes",
    "TWZ": "twz",
    "Yahoo News": "yahoo_news",
}


def import_legacy(path: Path, config: AppConfig, data_dir: Path, edition: str = "imported") -> Path:
    """处理：读取旧版日报和状态文件，转换后写入当前数据目录结构。
    输入：本地文件路径、已校验的采集和输出配置、本次运行的数据根。
    - ``edition``：日报版本标识，通常为 morning 或 evening；参与窗口和产物命名。
    输出：指向“读取旧版日报和状态文件，
      转换后写入当前数据目录结构”所生成、定位或确认产物的本地路径。
    """
    raw = read_json(path)
    if not isinstance(raw, list):
        raise ValueError("Legacy input must be a list of source result objects")
    discovered_at = now_iso(config.timezone)
    source_results: list[dict] = []
    all_items: list[dict] = []
    for source_row in raw:
        source_name = str(source_row.get("source", "")).strip()
        source_id = SOURCE_NAME_ALIASES.get(source_name)
        if not source_id:
            source_id = re.sub(r"[^a-z0-9]+", "_", source_name.lower()).strip("_") or "unknown"
        try:
            source = config.source_by_id(source_id)
        except KeyError:
            source = None
        http_status = source_row.get("http_status")
        raw_status = source_row.get("status", "failed")
        if http_status == 429:
            status = SourceStatus.RATE_LIMITED
        elif http_status in {401, 403}:
            status = SourceStatus.VERIFICATION_REQUIRED
        else:
            try:
                status = SourceStatus(raw_status)
            except ValueError:
                status = SourceStatus.FAILED
        items: list[dict] = []
        seen: set[str] = set()
        for row in source_row.get("items", []):
            title = clean_title(row.get("title", ""))
            url = row.get("url", "")
            if source and not is_eligible(source, title, url):
                continue
            if not title or not url:
                continue
            canonical = canonicalize_url(url)
            if canonical in seen:
                continue
            seen.add(canonical)
            article = ArticleItem(
                item_id=item_id(source_id, canonical),
                source_id=source_id,
                source_name=source_name,
                title=title,
                url=url,
                canonical_url=canonical,
                discovered_at=discovered_at,
                module=source.module if source else "information",
                category=source.category if source else "international",
                metadata={"role": source.role if source else "discovery"},
            ).to_dict()
            items.append(article)
            all_items.append(article)
        if status == SourceStatus.SUCCESS and not items:
            status = SourceStatus.NO_ITEMS
        source_results.append(
            {
                "source_id": source_id,
                "source_name": source_name,
                "source_url": source_row.get("source_url", ""),
                "status": str(status),
                "collected_at": discovered_at,
                "module": source.module if source else "information",
                "category": source.category if source else "international",
                "page_title": source_row.get("page_title", ""),
                "final_url": source_row.get("final_url", ""),
                "http_status": http_status,
                "error": source_row.get("error"),
                "challenge": {"required": status == SourceStatus.VERIFICATION_REQUIRED},
                "items_count": len(items),
                "items": items,
            }
        )
    date = today_str(config.timezone)
    payload = {
        "schema_version": "1.0",
        "date": date,
        "edition": edition,
        "generated_at": discovered_at,
        "timezone": config.timezone,
        "imported_from": str(path.resolve()),
        "sources": source_results,
        "items": all_items,
    }
    directory = data_dir / "indexes" / date
    with exclusive_lock(directory / f".{edition}.import.lock", {"edition": edition}):
        revision = next_revision(directory, edition)
        payload.update(index_id=f"index-{date}-{edition}-r{revision}", revision=revision)
        return write_immutable_json(directory / f"{edition}-r{revision}.json", payload)
