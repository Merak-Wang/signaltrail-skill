"""已生成日报的只读网页投影与版本选择。"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from urllib.parse import quote

from .events import get_event, report_event_cards
from .image_policy import is_editorial_template, normalize_image_candidates

_REPORTS: dict[str, tuple[list, list]] = {}


def _saved_editions(data_dir: Path) -> list[tuple[Path, dict]]:
    """处理：按既有报告目录约定读取版本化日报，排除草稿与试验目录。
    输入：资料根目录；扫描与本地归档页面一致的日期目录和版本文件。
    输出：按日期、生成时间和修订号倒序排列的权威日报。
    """
    paths = [
        path
        for path in (data_dir / "reports").glob("*/*-r*.json")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.parent.name)
        and re.fullmatch(r"[\w-]+-r\d+\.json", path.name)
    ]
    signature = [(str(path), path.stat().st_mtime_ns, path.stat().st_size) for path in paths]
    cached = _REPORTS.get(str(data_dir))
    if cached and cached[0] == signature:
        return cached[1]
    saved = []
    for path in paths:
        report = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(report, dict) or not all(
            key in report
            for key in (
                "report_id",
                "date",
                "edition",
                "revision",
                "schema_version",
                "sections",
                "analyses",
            )
        ):
            continue
        if (
            report["date"] != path.parent.name
            or path.stem != f"{report['edition']}-r{report['revision']}"
        ):
            continue
        saved.append((path, report))
    saved.sort(
        key=lambda row: (row[1]["date"], row[1].get("generated_at") or "", row[1]["revision"]),
        reverse=True,
    )
    _REPORTS[str(data_dir)] = (signature, saved)
    return saved


def _edition_metadata(report: dict) -> dict:
    """处理：提取日期、版次和实际输出语言供阅读器选择。
    输入：已保存的规范日报。
    输出：版本选择器使用的元信息，不改写日报内容。
    """
    return {
        key: report.get(key)
        for key in (
            "report_id",
            "date",
            "edition",
            "revision",
            "language",
            "generated_at",
            "title",
        )
    }


def list_editions(data_dir: Path) -> dict:
    """处理：列出真正生成过的日报版本及语言。
    输入：用户当前资料目录。
    输出：可选版次和数量；无日报时返回空列表。
    """
    editions = [_edition_metadata(report) for _, report in _saved_editions(data_dir)]
    return {
        "editions": editions,
        "total": len(editions),
        "available_languages": sorted({row["language"] for row in editions if row["language"]}),
    }


def edition_artifact_path(data_dir: Path, relative: str) -> Path | None:
    """处理：只解析已生成日报的交付文件及批准媒体目录中的文件。
    输入：网页请求的资料根相对路径。
    输出：允许流式读取的现有文件；其他运行数据不通过阅读器公开。
    """
    path = (data_dir / relative).resolve()
    if not path.is_file():
        return None
    if path.is_relative_to(data_dir / "media"):
        return path
    suffixes = (".json", ".html", ".pdf", ".md", "-slides.html", "-video.html", "-video.mp4")
    return next(
        (
            path
            for saved, _ in _saved_editions(data_dir)
            if path.parent == saved.parent
            and path.name in {saved.stem + suffix for suffix in suffixes}
        ),
        None,
    )


def _report_image(data_dir: Path, image: dict | None) -> str | None:
    """处理：按报告图片原始来源过滤推广图，并优先使用已下载的新闻图片。
    输入：报告保存的图片出处、尺寸和本地媒体路径。
    输出：阅读器可加载的本地媒体地址或原始远程候选，图标与推广图返回空。
    """
    if not image:
        return None
    urls = [image.get("source_url"), image.get("resolved_url"), image.get("url")]
    if any(is_editorial_template({**image, "url": url}) for url in urls if url):
        return None
    if image.get("width") and image.get("height") and max(image["width"], image["height"]) <= 128:
        return None
    if image.get("local_path"):
        local = (data_dir / image["local_path"]).resolve()
        if local.is_relative_to(data_dir / "media") and local.is_file():
            return "/files/" + quote(local.relative_to(data_dir).as_posix())
    return next(iter(normalize_image_candidates(urls)), None)


def _reading_projection(data_dir: Path, report: dict, cards: list[dict]) -> dict:
    """处理：为日报阅读添加绑定同篇来源的图片地址，保留原报告文件。
    输入：权威日报和已关联档案的事件卡片。
    输出：深拷贝的只读展示投影，仅采用本期保存的配图，缺图显式为空。
    """
    projection = deepcopy(report)
    briefs = {
        brief["item_id"]: brief
        for section in projection["sections"]
        for brief in section.get("briefs", [])
    }
    by_event = {card["report_event_id"]: card for card in cards}
    for brief in briefs.values():
        brief["image_url"] = _report_image(data_dir, brief.get("image"))
    for section in projection["sections"]:
        for item in section.get("items", []):
            ids = item.get("source_item_ids") or [
                ref["item_id"] for ref in item.get("source_refs", [])
            ]
            candidate = _report_image(data_dir, item.get("image")) or next(
                (
                    briefs[key]["image_url"]
                    for key in ids
                    if key in briefs and briefs[key].get("image_url")
                ),
                None,
            )
            card = by_event.get(item["event_id"], {})
            # 档案采集图尚未经过本期日报选图，不用于填补正式日报的空图。
            item["image_url"] = candidate
            card["image_url"] = candidate
    return projection


def read_edition(
    data_dir: Path,
    *,
    date: str = "",
    edition: str = "",
    revision: str = "",
    language: str = "zh-CN",
) -> dict:
    """处理：选取最新或用户指定的已生成日报并提供现有交付文件。
    输入：日期、版次、修订和实际语言筛选。
    输出：原始日报与已有产物链接；缺语言明确不可用，不回退采集新闻流。
    """
    language = language or "zh-CN"
    saved = [
        (path, report)
        for path, report in _saved_editions(data_dir)
        if (not date or report["date"] == date)
        and (not edition or report["edition"] == edition)
        and (not revision or str(report["revision"]) == revision)
    ]
    if saved and not date:
        latest_date = saved[0][1]["date"]
        saved = [(path, report) for path, report in saved if report["date"] == latest_date]
    languages = sorted({report.get("language") for _, report in saved if report.get("language")})
    matches = [
        (path, report)
        for path, report in saved
        if not language or report.get("language") == language
    ]
    if not matches:
        selected = (
            _edition_metadata(saved[0][1])
            if saved
            else {
                "date": date,
                "edition": edition,
                "revision": revision,
            }
        )
        return {
            "status": "unavailable" if saved else "empty",
            "reason": "language_not_generated" if saved else "edition_not_generated",
            "requested_language": language,
            "selection": {**selected, "language": language},
            "available_editions": [_edition_metadata(report) for _, report in saved],
            "edition": None,
            "report": None,
            "events": [],
            "artifacts": {},
            "available_languages": languages,
        }
    path, report = matches[0]
    artifacts = {}
    for kind, suffix in (
        ("json", ".json"),
        ("html", ".html"),
        ("pdf", ".pdf"),
        ("markdown", ".md"),
        ("slides", "-slides.html"),
        ("video", "-video.html"),
        ("mp4", "-video.mp4"),
    ):
        artifact = path.with_name(path.stem + suffix)
        artifacts[kind] = (
            "/files/" + quote(artifact.relative_to(data_dir).as_posix())
            if artifact.is_file()
            else None
        )
    cards = report_event_cards(data_dir, report)
    return {
        "status": "ready",
        "edition": _edition_metadata(report),
        "report": _reading_projection(data_dir, report, cards),
        "events": cards,
        "artifacts": artifacts,
        "available_languages": languages,
    }


def read_edition_event(
    data_dir: Path, report_id: str, event_id: str, language: str = ""
) -> dict | None:
    """处理：以日报原文呈现事件详情，并按实际关联提供长期研究入口。
    输入：已保存日报身份与其中的事件身份。
    输出：中文或英文原版事件、证据来源及关联分析；历史未归档事件可只读。
    """
    report = next(
        (report for _, report in _saved_editions(data_dir) if report["report_id"] == report_id),
        None,
    )
    if report is None:
        return None
    item = next(
        (
            item
            for section in report["sections"]
            for item in section.get("items", [])
            if item["event_id"] == event_id
        ),
        None,
    )
    if item is None:
        return None
    if language and language != report.get("language"):
        target = read_edition(
            data_dir, date=report["date"], edition=report["edition"], language=language
        )
        if target["status"] != "ready":
            return target
        original_refs = {ref.get("url") for ref in item.get("source_refs", []) if ref.get("url")}
        translated = next(
            (
                candidate
                for section in target["report"]["sections"]
                for candidate in section.get("items", [])
                if original_refs.intersection(
                    ref.get("url") for ref in candidate.get("source_refs", [])
                )
            ),
            None,
        )
        if translated:
            return read_edition_event(
                data_dir, target["report"]["report_id"], translated["event_id"], language=language
            )
        return {
            "status": "unavailable",
            "reason": "event_not_in_language_edition",
            "requested_language": language,
            "report": None,
            "event": None,
            "selection": {
                "date": report["date"],
                "edition": report["edition"],
                "language": language,
            },
            "available_languages": [report.get("language")],
        }
    card = next(
        card for card in report_event_cards(data_dir, report) if card["report_event_id"] == event_id
    )
    projected = _reading_projection(data_dir, report, [card])
    item = next(
        item
        for section in projected["sections"]
        for item in section.get("items", [])
        if item["event_id"] == event_id
    )
    detail = get_event(data_dir, card["platform_event_id"]) if card["platform_event_id"] else None
    if detail is None:
        primary = item.get("primary_source", {})
        articles = [
            {
                **ref,
                "source_id": primary.get("id"),
                "source_name": primary.get("name"),
                "description": "",
                "published_at": ref.get("published_at"),
                "item_ids": [ref["item_id"]],
            }
            for ref in item.get("source_refs", [])
        ]
        detail = {"articles": articles, "timeline": [], "analyses": [], "research": []}
    language = report.get("language") or "zh-CN"
    report_analyses = [
        {**analysis, "language": language, "report_id": report_id}
        for analysis in report.get("analyses", [])
        if event_id in analysis.get("evidence_event_ids", [])
    ]
    analyses = {
        (analysis["domain"], analysis.get("language") or language): analysis
        for analysis in detail["analyses"]
    }
    for analysis in report_analyses:
        analyses[(analysis["domain"], language)] = analysis
    return {
        "status": "ready",
        **detail,
        "event": card,
        "analyses": list(analyses.values()),
        "report_event": item,
        "report_language": language,
        "report_id": report_id,
    }
