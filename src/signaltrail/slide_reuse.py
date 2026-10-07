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
        Draft202012Validator(current["output_schema"]).validate({"slides": [slide]})
        if current["language"] == "zh-CN" and not (
            200 <= len("".join(slide["narration"].split())) <= 350
        ):
            continue
        available = {a["domain"] for a in current["news"][0]["analyses"]}
        if set(slide["perspectives"]) <= available:
            reused.append(deepcopy(slide))
    return reused
