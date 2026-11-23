"""验收真实或冻结回放交付的整期日报、图文、视频与宿主计量。"""

# Ruff must allow binding imports to this checkout before loading SignalTrail.
# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict, deque
from collections.abc import Callable
from datetime import datetime
from functools import cache
from hashlib import file_digest, sha256
from pathlib import Path
from statistics import mean

from bs4 import BeautifulSoup
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from signaltrail.article_time import normalize_time, original_publication_time, published_on_date
from signaltrail.config import load_config
from signaltrail.localization import (
    source_matches_output_language,
    text_matches_output_language,
    translated_title,
)
from signaltrail.narrative_store import ArtifactReader
from signaltrail.reporting import reference_time_label, report_content_hash
from signaltrail.runtime import require_data_root_path, validate_run_data_root
from signaltrail.semantics import tldr_quality_issue
from signaltrail.storage import write_immutable_json
from signaltrail.utils import read_json_object
from signaltrail.workflow import RunStatus, get_edition_status


def digest(path: Path) -> str:
    """计算本地交付证据的 SHA-256，按流读取大型视频。"""
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def json_with_digest(path: Path, label: str) -> tuple[dict, str]:
    """从同一份字节解码本地对象并计算内容摘要。"""
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value, sha256(raw).hexdigest()


def nonnegative(value: object, *, integer: bool = False) -> int | float | None:
    """保留已观察到的有效计数或秒数，缺测值保持为空。"""
    if isinstance(value, bool) or not isinstance(value, int if integer else (int, float)):
        return None
    return value if value >= 0 and (isinstance(value, int) or math.isfinite(value)) else None


def covered_window(receipt: dict, run: dict) -> bool | None:
    """用原始带时区时标核对宿主记录是否覆盖运行清单的生命周期。"""
    raw = [receipt.get("start_utc"), receipt.get("end_utc"),
           run.get("created_at"), run.get("updated_at")]
    if not all(isinstance(value, str) for value in raw):
        return None
    try:
        start, end, created, updated = (datetime.fromisoformat(value) for value in raw)
        if any(value.utcoffset() is None for value in (start, end, created, updated)):
            return False
        return start <= created <= updated <= end
    except (TypeError, ValueError):
        return False


def host_measurement(args: argparse.Namespace, run: dict, run_hash: str,
                     report_matches_run: bool, report_hash: str) -> dict:
    """按宿主输入加输出计量，完整成绩取独立生成指令的全生命周期。"""
    receipt = read_json_object(args.host_receipt) if args.host_receipt else {}
    wall = nonnegative(receipt.get("wall_seconds"))
    usage = receipt.get("total", {})
    inp = nonnegative(usage.get("input_tokens"), integer=True)
    out = nonnegative(usage.get("output_tokens"), integer=True)
    tokens = inp + out if inp is not None and out is not None else None
    window = covered_window(receipt, run)
    expected_subtree = args.expected_host_subtree_id
    subtree_matches = (
        receipt.get("subtree_thread_id") == expected_subtree if expected_subtree else None
    )
    receipt_run_hash = receipt.get("run_sha256")
    receipt_report_hash = receipt.get("report_sha256")
    binding = (
        report_matches_run
        and (subtree_matches is True or receipt_run_hash == run_hash)
        and subtree_matches is not False
        and (receipt_run_hash is None or receipt_run_hash == run_hash)
        and (receipt_report_hash is None or receipt_report_hash == report_hash)
    )
    boundary = receipt.get("selection")
    # 独立生成子任务须显式指明；工程聊天内截取的时间窗只供诊断。
    complete_invocation = (boundary in {"completed_root_turn", "completed_invocation"}
                           or (boundary == "completed_subtree_turn" and subtree_matches is True))
    full = bool(args.full_host_measurement and binding and window is True and complete_invocation
                and receipt.get("scope") == "completed_turn"
                and not receipt.get("include_agent_paths"))
    metrics = {}
    for name, value, ceiling in (
        ("wall_seconds", wall, args.max_wall_seconds),
        ("total_tokens", tokens, args.max_tokens),
    ):
        metrics[name] = {
            "observed": value, "ceiling": ceiling,
            "absolute_distance_to_target": abs(round(value - ceiling, 3))
            if value is not None else None,
            "remaining": round(ceiling - value, 3) if value is not None else None,
            "remaining_percent": round(100 * (ceiling - value) / ceiling, 3)
            if value is not None else None,
            "status": ("unknown" if value is None else "partial" if not full else
                       "within_ceiling" if value <= ceiling else "over_ceiling"),
        }
    return {
        "scope": "full" if full else "partial" if receipt else "missing",
        "invocation": boundary, "input_tokens": inp, "output_tokens": out,
        "cached_input_tokens": nonnegative(usage.get("cached_input_tokens"), integer=True),
        "model_effort_response_counts": receipt.get("model_effort_response_counts", []),
        "matches_run_and_report": binding if receipt else None,
        "matches_expected_subtree": subtree_matches,
        "window_covers_run": window,
        "receipt_sha256": digest(args.host_receipt) if receipt else None,
        "known_token_subtotal": nonnegative(usage.get("total_tokens_known"), integer=True),
        "responses": nonnegative(usage.get("responses"), integer=True),
        "observed_models": sorted({model for row in receipt.get("agents", [])
                                   for model in row.get("models", {})}),
        "observed_reasoning_efforts": sorted({
            effort for row in receipt.get("agents", [])
            for effort in row.get("reasoning_efforts", [])
        }),
        "observed_roles": dict(Counter(row.get("category") or "unknown"
                                       for row in receipt.get("agents", []))),
        **metrics,
    }


def image_decoder(data_dir: Path) -> Callable[[str], tuple[bool, int | None, int | None]]:
    """在一次整期验收内复用同一缓存图片的解码观察。"""
    @cache
    def decode(local: str) -> tuple[bool, int | None, int | None]:
        width, height = None, None
        try:
            path = require_data_root_path(data_dir / Path(local), data_dir, "Evaluation image")
            with Image.open(path) as asset:
                width, height = asset.size
                asset.load()
        except (OSError, ValueError, Image.DecompressionBombError):
            return False, width, height
        return True, width, height

    return decode


def image_observation(image: dict, decode: Callable) -> dict:
    """结合图片文件检查与该引用各自提供的归因和图注。"""
    local = image.get("local_path")
    readable, width, height = decode(local) if local else (None, None, None)
    return {
        "local_decode_ok": readable, "width": width, "height": height,
        "provider_url_present": bool(image.get("url")),
        "article_attribution_present": bool(image.get("source_url") or image.get("credit")),
        "caption_present": bool(str(image.get("caption") or "").strip()),
    }


def report_cards(path: Path) -> dict:
    """按原文链接与标题索引实际 HTML 简报，保留同链接的各来源视图。"""
    cards: dict[tuple, deque] = defaultdict(deque)
    if path.is_file():
        html = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
        for card in html.select("article.brief"):
            title = card.select_one("h4 .story-link")
            if title:
                original = card.select_one(".original-title") or title
                cards[(title.get("href"), original.get_text(" ", strip=True))].append(card)
    return cards


def brief_observation(brief: dict, item: dict | None, card: object, language: str,
                      decode: Callable) -> dict:
    """将每条简报的发布时间、目标语言、篇幅和访问证据投影为检查结果。"""
    ref = brief.get("source_ref", {})
    actual = ref.get("published_at")
    original = original_publication_time(item) if item else None
    publication_precision = "unknown" if not original else "date" if len(original) == 10 else "time"
    publication_preserved = None
    if original:
        publication_preserved = normalize_time(str(actual or ""), "Asia/Shanghai") == original
    elif item is not None and actual:
        publication_preserved = False
    tldr = str(brief.get("tldr") or "").strip()
    title = str(brief.get("title") or "")
    translation = translated_title(brief, language)
    indexed_title = str((item or {}).get("title") or "")
    source_language = ((item or {}).get("metadata") or {}).get("language")
    translation_required = not source_matches_output_language(
        source_language, indexed_title or title, language,
    )
    expected_time = reference_time_label(ref, language)
    visible_time = card.select_one(".story-time") if card else None
    visible_translation = card.select_one(".translated-title") if card else None
    visible_tldr = card.select_one(".tldr") if card else None
    headline = card.select_one("h4 .story-link") if card else None
    visible_time_text = visible_time.get_text(" ", strip=True) if visible_time else None
    expected_time_text = "：".join(expected_time) if expected_time else None
    return {
        "item_id": brief.get("item_id"), "source_id": item.get("source_id") if item else None,
        "access": ref.get("access"),
        "original_title_present": bool(title.strip()),
        "original_title_preserved": title == indexed_title if indexed_title else None,
        "translation_required": translation_required,
        "translation_present": bool(translation),
        "html_target_language_primary_headline": bool(headline)
        and bool(translation or not translation_required)
        and headline.get_text(" ", strip=True) == (translation or title),
        "html_target_title_preserved": (
            bool(visible_translation)
            and visible_translation.get_text(" ", strip=True) == translation
            if translation else bool(card) and not translation_required
        ),
        "target_title_language_heuristic": (
            text_matches_output_language(translation, language, minimum_units=2)
            if translation_required else bool(title.strip())
        ),
        "tldr_present": bool(tldr),
        "tldr_target_language_heuristic": text_matches_output_language(
            tldr, language, minimum_units=4,
        ),
        "tldr_contract_issue": tldr_quality_issue(tldr, title, language, translation),
        "tldr_characters": len(tldr),
        "tldr_words": len(re.findall(r"\b\w+\b", tldr)) if language == "en" else None,
        "tldr_sentences": len(re.findall(r"[^。！？.!?]+[。！？.!?]*", tldr)),
        "original_publication_precision": publication_precision,
        "original_publication_at": original, "reported_publication_at": actual,
        "original_publication_preserved": publication_preserved,
        "html_brief_present": bool(card),
        "html_tldr_preserved": bool(visible_tldr) and tldr == (
            visible_tldr.get_text(" ", strip=True).removeprefix("TL;DR").strip()
        ),
        "html_time_preserved": (
            visible_time_text == expected_time_text or (
                publication_precision == "date"
                and visible_time_text in {f"发布时间：{actual}", f"Published：{actual}"}
            )
        ) if expected_time else None,
        "html_time_uses_precision_label": visible_time_text == expected_time_text
        if expected_time else None,
        "image": image_observation(brief["image"], decode) if brief.get("image") else None,
    }


def coverage_observation(config_path: Path | None, index: dict, planned: dict | None,
                         rows: list, run_window: dict | None) -> dict:
    """以启用来源和冻结计划分别统计有产出来源、零产出来源与漏写条目。"""
    policies = index.get("source_policies", {})
    frozen_enabled = set(policies) if policies and all(
        row.get("selection_scope") == "latest_15_today" for row in policies.values()
    ) else None
    explicit = ({source.id for source in load_config(config_path).report_sources if source.enabled}
                if config_path else None)
    enabled = frozen_enabled if frozen_enabled is not None else explicit
    statuses = {row["source_id"]: row.get("status") for row in index.get("sources", [])}
    dates_by_source = defaultdict(Counter)
    window = index.get("collection_window") or run_window or {}
    cutoff = window.get("end") or index.get("generated_at")
    for item in index.get("items", []):
        dates = dates_by_source[item.get("source_id")]
        if published_on_date(item, index["date"], cutoff):
            dates["eligible_by_date"] += 1
        elif original_publication_time(item):
            dates["outside_edition"] += 1
        else:
            dates["original_date_unknown"] += 1
    published_by_source = defaultdict(set)
    for row in rows:
        if row["source_id"] is not None:
            published_by_source[row["source_id"]].add(row["item_id"])
    sources = {}
    for source in sorted(set(statuses) | set(enabled or ()) | set(planned or ())):
        wanted = (planned or {}).get(source, [])
        observed = published_by_source[source]
        status = statuses.get(source)
        reason = None
        if not observed:
            if source not in statuses:
                reason = "source_not_in_index"
            elif wanted:
                reason = "planned_briefs_missing"
            elif status not in {"success", "partial", "no_items"}:
                reason = status or "access_unknown"
            else:
                reason = "no_eligible_planned_items" if planned is not None else "plan_unavailable"
        sources[source] = {
            "enabled": source in enabled if enabled is not None else None,
            "access": status, "briefs": len(observed), "zero_output_reason": reason,
            "indexed_items": dates_by_source[source].total(),
            "indexed_by_publication_date": dict(dates_by_source[source]),
            "planned": len(wanted) if planned is not None else None,
            "missing_planned_item_ids": [item for item in wanted if item not in observed]
            if planned is not None else None,
        }
    zero = sorted(source for source in enabled if not published_by_source[source]) if (
        enabled is not None
    ) else None
    return {
        "enabled_source_basis": "frozen_index" if frozen_enabled is not None else
        "explicit_config" if explicit is not None else "unknown",
        "explicit_config_agrees_with_frozen_index": explicit == frozen_enabled
        if explicit is not None and frozen_enabled is not None else None,
        "configured_enabled": len(enabled) if enabled is not None else None,
        "enabled_with_output": len(enabled) - len(zero) if enabled is not None else None,
        "coverage_percent": round(100 * (len(enabled) - len(zero)) / len(enabled), 2)
        if enabled else None,
        "enabled_zero_output": zero,
        "missing_eligible_planned_briefs": (
            sum(len(row["missing_planned_item_ids"]) for row in sources.values())
            if planned is not None else None
        ),
        "sources": sources,
    }


def slide_observation(
    path: Path | None, run: dict, report_path: Path, reader: ArtifactReader, decode: Callable,
) -> dict:
    """校验完整图文父链，独立统计有图、图注及可解码图片的页数。"""
    if path is None:
        return {"binding": "missing", "pages": []}
    deck = reader.load(path, kind="slides-deck")
    plan_path = reader.parent_path(deck, "plan")
    plan = reader.load(plan_path, kind="slides-plan")
    parent = reader.parent_path(plan, "report") if "report" in plan["parents"] else None
    expected_plan = run.get("artifacts", {}).get("slides", {}).get("plan_path")
    binding = ("standalone" if parent is None else
               "different_report" if parent != report_path else
               "run_plan" if expected_plan and plan_path == Path(expected_plan).resolve()
               else "alternate_plan_same_report")
    pages = [{"event_id": row["event_id"],
              "source_count": len(row.get("sources", [])),
              "summary_present": bool(row.get("summary")),
              "video_narration_present": bool(row.get("video_tldr")),
              "images": [image_observation(asset, decode) for asset in row.get("images", [])]}
             for row in deck["payload"]["slides"]]
    return {
        "binding": binding, "report_parent": str(parent) if parent else None,
        "deck_sha256": reader.validated_ref(path)["sha256"],
        "page_count": len(pages), "pages_with_images": sum(bool(row["images"]) for row in pages),
        "pages_with_decodable_images": sum(
            any(asset["local_decode_ok"] for asset in row["images"]) for row in pages
        ),
        "pages": pages,
    }


def editorial_observation(path: Path | None, report_hash: str, brief_count: int,
                          slides: dict, video: dict) -> dict:
    """只采纳绑定本次交付字节且说明检查范围的人工判断。"""
    review = read_json_object(path) if path else {}
    bindings = {
        "report": review.get("report_sha256") == report_hash,
        "deck": bool(slides.get("deck_sha256")) and
        review.get("deck_sha256") == slides["deck_sha256"],
        "video": bool(video.get("video_sha256")) and
        review.get("video_sha256") == video["video_sha256"],
    }
    result = {}
    for name, binding, units in (
        ("brief_accuracy_concision", "report", brief_count),
        ("image_clarity_relevance", "deck", slides.get("page_count")),
        ("narration_accuracy", "video", slides.get("page_count")),
    ):
        row = review.get(name) or {}
        count = nonnegative(row.get("checked_count"), integer=True)
        status = row.get("status")
        if (bindings[binding] and count and (units is None or count <= units)
                and status in {"passed", "failed", "partial"}):
            result[name] = {
                "status": status, "checked_count": count, "expected_count": units,
                "scope": "full" if count == units else "sampled",
                "notes": row.get("notes"),
            }
            scores = row.get("scores_out_of_10")
            if isinstance(scores, dict):
                result[name]["scores_out_of_10"] = {
                    dimension: score for dimension, value in scores.items()
                    if (score := nonnegative(value)) is not None and score <= 10
                }
        else:
            result[name] = {"status": "unknown", "checked_count": None}
    intelligence = (review.get("intelligence") or {}) if bindings["report"] else {}
    return {
        **result,
        "artifact_bindings": bindings,
        "intelligence": {
            **{name: nonnegative(intelligence.get(name), integer=True) for name in (
                "editorial_decisions", "procedural_model_decisions", "manual_interventions",
            )},
            "minimum_model_comparison": intelligence.get("minimum_model_comparison"),
        },
    }


def resource_observation(path: Path | None, run: dict, run_hash: str) -> dict:
    """读取与运行绑定的设备采样，缺测、部分窗口和完整采样保留区别。"""
    row = read_json_object(path) if path else {}
    bound = row.get("run_sha256") == run_hash
    count = nonnegative(row.get("sample_count"), integer=True) if bound else None
    full = row.get("scope") == "edition" and covered_window(row, run) is True
    return {
        "scope": ("edition" if full else "partial") if count else "unavailable",
        "sample_count": count,
        "duration_seconds": nonnegative(row.get("duration_seconds")) if count else None,
        **{name: row.get(name) if count else None for name in (
            "cpu_percent_normalized", "gpu_busy_percent", "memory_pressure_percent",
        )},
    }


def joint_score(host: dict, sources: dict, editorial: dict, device: dict,
                delivery_complete: bool, *, assisted_recovery: bool = False) -> dict:
    """在同一百分制内计算运行与质量贡献，缺少的分项保留其可能区间。"""
    rows = {}

    def put(name: str, weight: int, fraction: float | None) -> None:
        points = weight * fraction if fraction is not None else None
        rows[name] = {"maximum": weight, "points": points}

    def grade_review(name: str, groups: tuple[tuple[str, ...], ...]) -> float | None:
        grades = editorial[name].get("scores_out_of_10", {})
        if all(key in grades for group in groups for key in group):
            return mean(mean(grades[key] for key in group) for group in groups) / 10
        return None

    full = host["scope"] == "full"
    for key in ("wall_seconds", "total_tokens"):
        metric = host[key]
        distance = metric["absolute_distance_to_target"]
        fraction = max(0, 1 - distance / metric["ceiling"]) if distance is not None else None
        put(key, 15, fraction if full else None)

    # 记录低档配置实际完成的比例；全程独立交付才能取得另外五分。
    counts = host.get("model_effort_response_counts", [])
    low = sum(r["responses"] for r in counts if r["model"] == "gpt-6.1-terra"
              and r["effort"] in {"low", "minimal", "none"})
    total = host.get("responses")
    measured = (full and total and sum(r["responses"] for r in counts) == total
                and all(r.get("model") not in {None, "unknown"} and r.get("effort") not in
                        {None, "unknown"} for r in counts))
    autonomous_delivery = low == total and delivery_complete and not assisted_recovery
    put("low_model_independence", 10, (low / total + int(autonomous_delivery)) / 2
        if measured else None)

    cpu = (device.get("cpu_percent_normalized") or {}).get("mean")
    gpu = (device.get("gpu_busy_percent") or {}).get("mean")
    put("device_utilization", 10, (cpu + gpu) / 200
        if device["scope"] == "edition" and cpu is not None and gpu is not None else None)
    enabled = sources["configured_enabled"]
    put("sources_with_news", 15, sources["enabled_with_output"] / enabled if enabled else None)
    put("briefs", 15, grade_review("brief_accuracy_concision", (
        ("title", "visible_publication_time", "tldr"),)))
    put("illustrations", 10, grade_review("image_clarity_relevance", (
        ("image_richness",), ("image_relevance",), ("desktop_readability", "mobile_readability"))))
    put("slide_writing", 10, grade_review("image_clarity_relevance", (
        ("writing_concision", "writing_liveliness", "writing_directness"),)))
    earned = sum(row["points"] for row in rows.values() if row["points"] is not None)
    unknown = sum(row["maximum"] for row in rows.values() if row["points"] is None)
    for row in rows.values():
        if row["points"] is not None:
            row["points"] = round(row["points"], 3)
    return {
        "rubric": "edition-100-v1", "maximum": 100,
        "points": round(earned, 2) if not unknown else None,
        "possible_points": [round(earned, 2), round(earned + unknown, 2)],
        "unmeasured_points": unknown, "components": rows,
    }


def frozen_brief_plan(
    artifacts: dict, index_path: Path, data_dir: Path, report_matches_run: bool,
) -> tuple[dict[str, list[str]] | None, str]:
    """读取会话摘要绑定的同一份情境字节，从中取得冻结计划。"""
    if not report_matches_run:
        return None, "report_mismatch"
    context_value = artifacts.get("context_path")
    session_value = artifacts.get("authoring", {}).get("session_path")
    if not context_value or not session_value:
        return None, "missing_context_or_session"
    context_path = require_data_root_path(Path(context_value), data_dir, "Frozen context")
    session_path = require_data_root_path(Path(session_value), data_dir, "Authoring session")
    if not context_path.is_file() or not session_path.is_file():
        return None, "missing_context_or_session"
    session = read_json_object(session_path)
    if not session.get("context_sha256"):
        return None, "missing_context_digest"
    content = context_path.read_bytes()
    if (session.get("context_path") != str(context_path)
            or session["context_sha256"] != sha256(content).hexdigest()):
        return None, "context_binding_mismatch"
    context = json.loads(content.decode("utf-8"))
    if (not isinstance(context, dict) or context.get("index_path") != str(index_path)
            or context.get("selection_only")
            or not isinstance(context.get("brief_plan"), list)):
        return None, "index_or_plan_mismatch"
    plan: dict[str, list[str]] = {}
    for row in context["brief_plan"]:
        if not isinstance(row, dict):
            return None, "invalid_plan"
        source, items = row.get("source_id"), row.get("default_item_ids")
        if (not isinstance(source, str) or not source or source in plan
                or not isinstance(items, list)
                or not all(isinstance(item, str) and item for item in items)):
            return None, "invalid_plan"
        plan[source] = items
    return plan, "verified"


def evaluate(args: argparse.Namespace) -> dict:
    """从绑定运行和显式提供的证据生成整期指标，不拼接不同报告修订的通过结果。"""
    run_path = args.run.resolve()
    run, run_hash = json_with_digest(run_path, "Run manifest")
    data_dir = Path(run["data_root"]).resolve()
    validate_run_data_root(run, run_path, data_dir)
    if run.get("status") not in {RunStatus.COMPLETED, RunStatus.COMPLETED_PARTIAL}:
        raise ValueError("Edition run must have a completed report")
    artifacts = run["artifacts"]
    report_path = require_data_root_path(
        args.report or Path(artifacts["json_path"]), data_dir, "Report revision",
    )
    report, report_hash = json_with_digest(report_path, "Report revision")
    if any(run[key] != report[key] for key in ("date", "edition")):
        raise ValueError("Report belongs to a different edition")
    report_matches_run = (
        report_path == Path(artifacts["json_path"]).resolve()
        and artifacts.get("report_id") == report.get("report_id")
        and artifacts.get("content_hash") == report_content_hash(report)
    )
    index_path = require_data_root_path(Path(artifacts["index_path"]), data_dir, "Frozen index")
    index, index_hash = json_with_digest(index_path, "Frozen index")
    index_by_id = {item["item_id"]: item for item in index.get("items", [])}
    planned, plan_binding = frozen_brief_plan(
        artifacts, index_path, data_dir, report_matches_run,
    )
    cards = report_cards(report_path.with_suffix(".html"))
    decode = image_decoder(data_dir)
    reader = ArtifactReader(data_dir)
    rows = []
    for section in report.get("sections", []):
        for brief in section.get("briefs", []):
            ref = brief.get("source_ref", {})
            matches = cards[(ref.get("url"), brief.get("title"))]
            rows.append(brief_observation(
                brief, index_by_id.get(brief.get("item_id")),
                matches.popleft() if matches else None, report["language"], decode,
            ))
    sources = coverage_observation(args.config, index, planned, rows, run.get("collection_window"))
    slides = slide_observation(args.deck, run, report_path, reader, decode)
    video = {}
    if args.video:
        video["video_sha256"] = digest(args.video)
        receipt_path = (args.video.with_suffix("") / "page-cache"
                        / f"video-receipt{args.video.suffix}.json")
        receipt = read_json_object(receipt_path) if receipt_path.is_file() else {}
        video["matches_export_receipt"] = (
            receipt["output_sha256"] == video["video_sha256"]
        ) if receipt.get("output_sha256") else None
        video["matches_supplied_deck"] = (
            video["matches_export_receipt"] is True
            and receipt["deck_sha256"] == slides["deck_sha256"]
        ) if receipt.get("deck_sha256") and slides.get("deck_sha256") else None
    editorial = editorial_observation(args.editorial, report_hash, len(rows), slides, video)
    host = host_measurement(args, run, run_hash, report_matches_run, report_hash)
    delivery = get_edition_status(run_path, data_dir, reader=reader)
    hardware = resource_observation(args.resources, run, run_hash)
    assisted_recovery = getattr(args, "assisted_recovery", False)
    rendered = delivery["delivery_complete"] and slides["binding"] in {
        "run_plan", "alternate_plan_same_report"}
    if args.video:
        rendered = rendered and video.get("matches_supplied_deck") is True
    return {
        "schema_version": "1.1",
        "edition": {
            "date": run["date"], "edition": run["edition"], "attempt": run.get("attempt"),
            "run_sha256": run_hash, "report_id": report["report_id"],
            "report_sha256": report_hash, "report_matches_run": report_matches_run,
            "frozen_plan_matches_report": plan_binding == "verified",
            "frozen_plan_binding": plan_binding, "index_sha256": index_hash,
        },
        "delivery": {
            "run_report_and_slides_complete": delivery["delivery_complete"],
            "run_pending_steps": delivery["pending_steps"],
            "assisted_recovery": assisted_recovery,
            "supplied_deck_binding": slides["binding"],
            "supplied_video_present": bool(video),
            "supplied_report_deck_match": slides["binding"] in {
                "run_plan", "alternate_plan_same_report",
            },
            "supplied_report_and_deck_match_run": report_matches_run
            and slides["binding"] == "run_plan",
        },
        "host_performance": host,
        "source_coverage": sources,
        "briefs": {
            "count": len(rows), "language": report["language"], "checks": rows,
            "issues": {
                "missing_html_item_ids": [row["item_id"] for row in rows
                                          if not row["html_brief_present"]],
                "original_publication_mismatch_item_ids": [row["item_id"] for row in rows
                    if row["original_publication_preserved"] is False],
                "tldr_language_or_contract_item_ids": [row["item_id"] for row in rows
                    if not row["tldr_target_language_heuristic"] or row["tldr_contract_issue"]],
                "title_language_or_fidelity_item_ids": [row["item_id"] for row in rows
                    if not row["target_title_language_heuristic"]
                    or not row["html_target_title_preserved"]
                    or row["original_title_preserved"] is False],
            },
        },
        "slides": slides, "video": video,
        "editorial": editorial,
        "device_utilization": hardware,
        "joint_score": joint_score(
            host, sources, editorial, hardware, rendered, assisted_recovery=assisted_recovery,
        ),
    }


def main() -> None:
    """解析输入证据和目标，独占写入本次 JSON 回执。"""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "report", "deck", "video", "host-receipt", "editorial", "resources",
                 "config", "output"):
        parser.add_argument(f"--{name}", type=Path, required=name in {"run", "output"})
    parser.add_argument("--full-host-measurement", action="store_true")
    parser.add_argument("--assisted-recovery", action="store_true",
                        help="Record operator intervention and withhold autonomy bonus")
    parser.add_argument("--expected-host-subtree-id",
                        help="Dedicated coordinator thread ID expected in the host receipt")
    parser.add_argument("--max-wall-seconds", type=int, default=1800)
    parser.add_argument("--max-tokens", type=int, default=20_000_000)
    args = parser.parse_args()
    if min(args.max_wall_seconds, args.max_tokens) <= 0:
        parser.error("Performance ceilings must be positive")
    if args.full_host_measurement and not args.host_receipt:
        parser.error("--full-host-measurement requires --host-receipt")
    report = evaluate(args)
    write_immutable_json(args.output, report)
    print(json.dumps({"result": str(args.output.resolve()), "delivery": report["delivery"],
                      "joint_score": report["joint_score"]}, ensure_ascii=True))


if __name__ == "__main__":
    main()
