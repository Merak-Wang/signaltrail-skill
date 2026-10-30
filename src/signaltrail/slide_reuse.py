"""Reuse accepted narration when the complete single-story writing input is unchanged."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator

from .narrative_store import digest, load_artifact, parent_path


def reusable_slides(reuse_plan: Path, model_inputs_by_id: dict[str, dict],
                    data_dir: Path) -> list[dict]:
    """处理：逐条比较旧稿的完整写作输入，复制语义完全相同的已接受讲稿。
    输入：明确旧计划、当前单条文字输入和数据根；图片与旧页面不参与匹配。
    输出：按当前候选顺序排列的讲稿副本，不创建缓存或旧修订父链。
    """
    plan = load_artifact(reuse_plan, data_dir, kind="slides-plan")
    payload = plan["payload"]
    template = payload.get("model_input_template")
    accepted: dict[str, tuple[dict, dict]] = {}
    for result_path in sorted(reuse_plan.parent.glob("slides-result-*-r*.json")):
        result = load_artifact(result_path, data_dir)
        packet = load_artifact(parent_path(result, "packet", data_dir), data_dir)
        if parent_path(packet, "plan", data_dir).resolve() != reuse_plan.resolve():
            continue
        model_input = packet["payload"]["model_input"]
        if template is None:
            template = {**model_input, "news": []}
        news = {row["event_id"]: row for row in model_input["news"]}
        for slide in result["payload"]["draft"]["slides"]:
            event_id = slide["event_id"]
            accepted[event_id] = (slide, {**model_input, "news": [news[event_id]]})
    if template is not None:
        news = {row["event_id"]: {k: v for k, v in row.items() if k != "images"}
                for row in payload["news"]}
        for slide in payload.get("reused_slides", []):
            event_id = slide["event_id"]
            accepted[event_id] = (slide, {**template, "news": [news[event_id]]})
    reused = []
    for event_id, current in model_inputs_by_id.items():
        if event_id not in accepted:
            continue
        slide, previous = accepted[event_id]
        if digest(current) != digest(previous):
            continue
        if not isinstance(slide.get("video_tldr"), str) or not slide["video_tldr"].strip():
            continue
        Draft202012Validator(current["output_schema"]).validate({"slides": [slide]})
        if current["language"] == "zh-CN" and not (
            200 <= len("".join(slide["narration"].split())) <= 350
        ):
            continue
        available = {a["domain"] for a in current["news"][0]["analyses"]}
        if set(slide["perspectives"]) <= available:
            reused.append(deepcopy(slide))
    return reused


def previous_narrations(reuse_plan: Path, candidates: list[dict], data_dir: Path,
                        style: str, language: str) -> dict[str, str]:
    """处理：提取证据未变且缺少口播稿的已接受讲解。
    输入：旧计划和当前候选；仅比较写作证据并忽略图片。
    输出：可供新批次原样保留的事件讲解，不修改历史成果。
    """
    plan = load_artifact(reuse_plan, data_dir, kind="slides-plan")
    template = plan["payload"].get("model_input_template", {})
    if template.get("style") != style or template.get("language") != language:
        return {}
    old_news = {row["event_id"]: {k: v for k, v in row.items() if k != "images"}
                for row in plan["payload"]["news"]}
    current = {row["event_id"]: {k: v for k, v in row.items() if k != "images"}
               for row in candidates}
    slides = list(plan["payload"].get("reused_slides", []))
    for path in sorted(reuse_plan.parent.glob("slides-result-*-r*.json")):
        result = load_artifact(path, data_dir)
        packet = load_artifact(parent_path(result, "packet", data_dir), data_dir)
        if parent_path(packet, "plan", data_dir).resolve() == reuse_plan.resolve():
            slides.extend(result["payload"]["draft"]["slides"])
    return {slide["event_id"]: slide["narration"] for slide in slides
            if not slide.get("video_tldr") and slide["event_id"] in current
            and current[slide["event_id"]] == old_news.get(slide["event_id"])}


def reusable_images(reuse_plan: Path, candidates: list[dict], data_dir: Path) -> dict[str, list]:
    """处理：沿用已渲染图文的图片，文字证据变更时不沿用。
    输入：旧计划和当前候选；图片不参与证据比较。
    输出：可复用的事件图片副本，离线重渲染保持原图顺序。
    """
    plan = load_artifact(reuse_plan, data_dir, kind="slides-plan")
    old = {row["event_id"]: {k: v for k, v in row.items() if k != "images"}
           for row in plan["payload"]["news"]}
    matching = {row["event_id"] for row in candidates
                if {k: v for k, v in row.items() if k not in {"images", "existing_narration"}}
                == {k: v for k, v in old.get(row["event_id"], {}).items()
                    if k != "existing_narration"}}
    paths = sorted(reuse_plan.parent.glob("slides-deck-r*.json"),
                   key=lambda path: int(path.stem.rsplit("-r", 1)[1]), reverse=True)
    for path in paths:
        deck = load_artifact(path, data_dir, kind="slides-deck")
        if parent_path(deck, "plan", data_dir).resolve() == reuse_plan.resolve():
            return {slide["event_id"]: deepcopy(slide["images"])
                    for slide in deck["payload"]["slides"] if slide["event_id"] in matching}
    return {}
