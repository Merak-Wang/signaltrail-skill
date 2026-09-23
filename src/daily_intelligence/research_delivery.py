"""Late binding and immutable composite readings; the daily run never waits here."""

from __future__ import annotations

import json
from pathlib import Path

from .local_output import _embedded_image_sources, render_report_html
from .narrative import load_completed_report, script_context
from .narrative_contracts import Admission, validate_schema
from .narrative_store import digest, file_ref, load_artifact, parent_path, save_artifact
from .reports import render_report_markdown
from .research_contracts import RELATIONS_SCHEMA
from .story_stream import render_story_markdown
from .utils import write_text_atomic


def bind_research_to_report(
    story_path: Path,
    run_path: Path,
    relations: list[dict],
    data_dir: Path,
    *,
    experimental: bool = False,
) -> Path:
    """处理：将完成的研究图文晚绑定到同一期真实日报修订。
    输入：研究 story、最终运行和扩展/限定/异议关系；草稿仅限显式实验预览。
    输出：不可变组合依赖和原样 Markdown，不写回原日报、索引或运行状态。
    """
    story = load_artifact(story_path, data_dir, kind="story")
    if story["payload"].get("scope") != "research":
        raise ValueError("Late binding requires a research story")
    if story["payload"]["status"] != Admission.VERIFIED and not experimental:
        raise ValueError("Research needs a supporting review; draft preview needs --experimental")
    first = story["payload"]["languages"][0]
    _, _, packet = script_context(parent_path(story, first, data_dir), data_dir)
    snapshot = load_artifact(
        parent_path(packet, "snapshot", data_dir), data_dir, kind="research-snapshot"
    )["payload"]
    run, report, _, refs = load_completed_report(run_path, data_dir, experimental=experimental)
    if (snapshot["date"], snapshot["edition"]) != (report["date"], report["edition"]):
        raise ValueError("Research and final report must belong to the same edition")
    validate_schema({"relations": relations}, RELATIONS_SCHEMA)
    research_ids = {a["analysis_id"] for a in packet["payload"]["analyses"]}
    report_analyses = {a["analysis_id"]: a for a in report["analyses"]}
    pairs = [(r["research_analysis_id"], r["report_analysis_id"]) for r in relations]
    if len(pairs) != len(set(pairs)):
        raise ValueError("Duplicate research/report relation")
    for relation in relations:
        if relation["research_analysis_id"] not in research_ids:
            raise ValueError("Unknown research analysis in relation")
        if relation["report_analysis_id"] not in report_analyses:
            raise ValueError("Unknown report analysis in relation")
    payload = {
        "report_id": report["report_id"],
        "parent_status": run["status"],
        "as_of": snapshot["as_of"],
        "status": story["payload"]["status"],
        "current_admission": Admission.BLOCKED,
        "relations": [
            {**r, "report_domain": report_analyses[r["report_analysis_id"]]["domain"]}
            for r in relations
        ],
    }
    markdown = (
        render_report_markdown(report) + "\n\n---\n\n" + render_story_markdown(story["payload"])
    )
    return save_artifact(
        data_dir,
        story["session"],
        "research-binding",
        payload,
        {"story": story_path, **refs},
        markdown,
    )


def render_composite_view(binding_path: Path, data_dir: Path, *, mode: str = "preview") -> dict:
    """处理：在原三视角和综合之后追加图文，生成独立组合阅读版本。
    输入：已绑定研究与实际报告；渲染器只复用已登记文字，不生成新语义。
    输出：本地离线 HTML 和投影记录，晚到或重试不会覆盖旧阅读文件。
    """
    binding = load_artifact(binding_path, data_dir, kind="research-binding")
    if mode != "preview":
        raise ValueError("Current admission blocked: freshness adapter and live acceptance pending")
    report_path = parent_path(binding, "report", data_dir)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    story_path = parent_path(binding, "story", data_dir)
    story = load_artifact(story_path, data_dir, kind="story")["payload"]
    html = render_report_html(
        report,
        include_pdf_link=False,
        archive_href=None,
        embedded_image_sources=_embedded_image_sources(report, data_dir),
        illustrated_story=story,
        research_relations=binding["payload"]["relations"],
    )
    output = binding_path.parent / "projections" / digest(html) / "composite.html"
    if not output.exists():
        write_text_atomic(output, html)
    if output.read_text(encoding="utf-8") != html:
        raise ValueError("Existing composite projection changed")
    projection = save_artifact(
        data_dir,
        binding["session"],
        "composite-projection",
        {"status": "preview", "html_ref": file_ref(output, data_dir)},
        {"binding": binding_path, "html": output},
    )
    return {
        "html_path": str(output),
        "projection_path": str(projection),
        "binding_path": str(binding_path),
        "content_status": story["status"],
        "current_admission": Admission.BLOCKED,
    }
