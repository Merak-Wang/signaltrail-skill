from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .config import SourceConfig


def has_local_content(item: dict[str, Any], data_dir: Path) -> bool:
    """处理：检查证据文件位于数据根内，并复核存在的产物哈希。
    输入：索引中的正文路径、可选结构路径与溯源指纹，以及当前数据根。
    输出：可读取且未检测到损坏时返回真；旧版无哈希文件保持兼容。
    """
    if item.get("content_status") not in {"full_text", "partial"}:
        return False
    metadata = item.get("metadata") or {}
    manifest = metadata.get("content_artifacts") or {}
    artifacts = [(item.get("content_path"), manifest.get("markdown_sha256"))]
    if manifest.get("blocks_sha256"):
        artifacts.append((metadata.get("content_blocks_path"), manifest["blocks_sha256"]))
    try:
        for value, expected_hash in artifacts:
            if not value:
                return False
            path = Path(str(value))
            path = (path if path.is_absolute() else data_dir / path).resolve()
            path.relative_to(data_dir.resolve())
            if not path.is_file():
                return False
            if expected_hash and hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
                return False
    except (OSError, ValueError):
        return False
    return True


def content_gaps(item: dict[str, Any], data_dir: Path) -> list[str]:
    """处理：从访问状态、正文质量和本地文件识别可观察的证据缺口。
    输入：规范索引条目及其绑定数据根；未知质量不会转换为通过。
    输出：稳定缺口标签，供补全决策和停止说明使用，不推测未标注的主张。
    """
    metadata = item.get("metadata") or {}
    quality = metadata.get("content_quality") or {}
    challenge = metadata.get("content_challenge") or {}
    if challenge.get("rate_limited") or metadata.get("content_http_status") == 429:
        return ["rate_limited"]
    status = item.get("content_status", "not_fetched")
    if status == "verification_required":
        return ["verification_required"]
    if str(metadata.get("content_error", "")).startswith("unsupported content type"):
        return ["unsupported_content_type"]
    if status == "failed":
        return ["access_failed"]
    gaps = []
    if not has_local_content(item, data_dir):
        gaps.append("missing_content_artifact" if item.get("content_path") else "article_body")
    if status == "partial":
        gaps.append("incomplete_body")
    for field, gap in (
        ("response_truncated", "response_truncated"),
        ("incomplete_marker", "incomplete_marker"),
        ("numeric_tables_without_headers", "table_headers"),
    ):
        if quality.get(field):
            gaps.append(gap)
    if quality.get("region") in {"broad", "provider_candidate"}:
        gaps.append("unconfirmed_body_region")
    return list(dict.fromkeys(gaps))


def enrichment_plan(
    items: list[dict[str, Any]], sources: list[SourceConfig], data_dir: Path, limit: int,
) -> dict[str, Any]:
    """处理：为当前候选建立有界、按来源轮询的正文缺口建议队列。
    输入：上下文已允许的候选、来源角色、数据根与本轮正文硬上限。
    输出：待协调器选择的动作及跳过原因；不会浏览、修改排名或猜测事件身份。
    """
    source_map = {source.id: source for source in sources}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    blocked = Counter()
    stopped = Counter()
    total = 0
    seen: set[str] = set()
    for item in items:
        item_id = str(item.get("item_id") or "")
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        gaps = content_gaps(item, data_dir)
        completion = (item.get("metadata") or {}).get("content_completion") or {}
        gaps = list(dict.fromkeys([*gaps, *completion.get("unresolved", [])]))
        if not gaps:
            continue
        access_gaps = [gap for gap in gaps if gap in {
            "rate_limited", "verification_required", "unsupported_content_type", "access_failed",
        }]
        if access_gaps:
            blocked.update(access_gaps)
            continue
        if completion.get("stop_reason") in {
            "bounded_attempts_exhausted", "no_permitted_escalation",
        }:
            stopped.update([completion["stop_reason"]])
            continue
        source_id = str(item.get("source_id") or "")
        source = source_map.get(source_id)
        grouped[source_id].append({
            "item_id": item_id, "event_id": None, "source_id": source_id,
            "missing_claim_or_field": gaps,
            "requested_source_role": source.role if source else None,
            "expected_resolution": "read_article_body_and_recheck_structure",
            "cost_bound": {"http_attempts": 1, "browser_attempts": 1, "model_calls": 0},
        })
        total += 1
    actions = []
    for position in range(max((len(rows) for rows in grouped.values()), default=0)):
        for rows in grouped.values():
            if position < len(rows) and len(actions) < max(0, limit):
                actions.append(rows[position])
    return {
        "schema_version": "1.0", "scope": "article_body_only",
        "selection_basis": "source_round_robin_preserving_candidate_order",
        "requires_editorial_selection": True, "max_items": max(0, limit), "actions": actions,
        "deferred_count": total - len(actions), "blocked_counts": dict(blocked),
        "stopped_counts": dict(stopped),
        "claim_sufficiency": "not_assessed",
    }


def source_coverage(index: dict[str, Any], sources: list[SourceConfig]) -> dict[str, Any]:
    """处理：按配置的地区、主题和来源角色对照当前采集覆盖。
    输入：根级规范条目、来源访问结果和已启用来源配置。
    输出：包含未采集与失败状态的覆盖单元；来源数不表示独立证实数或全球覆盖率。
    """
    records = {row["source_id"]: row for row in index.get("sources", []) if row.get("source_id")}
    items: dict[str, set[str]] = defaultdict(set)
    for item in index.get("items", []):
        if (item.get("source_id") and item.get("item_id")
                and not (item.get("metadata") or {}).get("retained_from_previous_snapshot")
                and not (item.get("metadata") or {}).get("feed_stale")):
            items[str(item["source_id"])].add(str(item["item_id"]))
    cells: dict[tuple[str, str, str], dict[str, Any]] = {}
    for source in sources:
        if not source.enabled:
            continue
        policy = (index.get("source_policies") or {}).get(source.id) or {}
        topic = f"{policy.get('module', source.module)}.{policy.get('category', source.category)}"
        key = (policy.get("region", source.region) or "unknown", topic,
               policy.get("role", source.role) or "unknown")
        cell = cells.setdefault(key, {
            "region": key[0], "topic": topic, "source_role": key[2],
            "source_ids": [], "languages": [], "observed_source_ids": [],
            "item_count": 0, "source_statuses": {},
            "dimension_basis": {},
        })
        cell["source_ids"].append(source.id)
        language = policy.get("language", source.language)
        if language and language not in cell["languages"]:
            cell["languages"].append(language)
        cell["dimension_basis"][source.id] = (
            "index_policy" if all(key in policy for key in (
                "module", "category", "region", "role", "language",
            )) else "current_config_fallback"
        )
        record = records.get(source.id)
        cell["source_statuses"][source.id] = (
            record.get("status", "unknown") if record else "not_collected"
        )
        if items[source.id]:
            cell["observed_source_ids"].append(source.id)
            cell["item_count"] += len(items[source.id])
    for cell in cells.values():
        statuses = set(cell["source_statuses"].values())
        cell["status"] = (
            "observed" if cell["item_count"] and statuses <= {"success", "no_items"} else
            "partial" if cell["item_count"] else "not_observed"
        )
    return {
        "schema_version": "1.0", "scope": "configured_sources",
        "independent_corroboration": "not_assessed", "cells": list(cells.values()),
    }
