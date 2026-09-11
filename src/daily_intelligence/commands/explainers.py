"""Explicit CLI boundaries for report-derived experimental explainers."""

from __future__ import annotations

import argparse

from ..narrative import prepare_explainer, submit_ledger, submit_script
from ..narrative_verification import (
    explainer_status,
    prepare_bilingual,
    prepare_review,
    submit_bilingual,
    submit_review,
)
from ..story_stream import build_story_stream, render_story, submit_visual_review
from ..utils import read_json_object
from .common import CommandContext, print_json


def handle_explainer(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：将显式阶段命令映射到讲解域函数。
    输入：解析器确认的父修订、草稿和宿主上下文；数据根来自既有配置。
    输出：路径或可用性 JSON；拒绝时返回非零退出码并保留既有日报。
    """
    data_dir = context.data_dir
    try:
        match args.action:
            case "prepare":
                result = prepare_explainer(args.run, data_dir, experimental=args.experimental)
            case "ledger":
                result = submit_ledger(
                    args.packet, read_json_object(args.input, "Claim draft"), data_dir
                )
            case "script":
                result = submit_script(
                    args.ledger,
                    read_json_object(args.input, "Script draft"),
                    data_dir,
                    author_context=args.author_context,
                )
            case "review-packet":
                result = prepare_review(args.script, data_dir)
            case "review":
                result = submit_review(
                    args.packet,
                    read_json_object(args.input, "Review"),
                    data_dir,
                    reviewer_context=args.reviewer_context,
                )
            case "bilingual-packet":
                result = prepare_bilingual(args.zh_review, args.en_review, data_dir)
            case "bilingual":
                result = submit_bilingual(
                    args.packet,
                    read_json_object(args.input, "Review"),
                    data_dir,
                    reviewer_context=args.reviewer_context,
                )
            case "story":
                result = build_story_stream(args.script, data_dir, bilingual_path=args.bilingual)
            case "render":
                print_json(render_story(args.story, data_dir, mode=args.mode))
                return 0
            case "visual-review":
                result = submit_visual_review(
                    args.projection, read_json_object(args.input, "Visual review"), data_dir
                )
            case "status":
                print_json(explainer_status(args.script, data_dir))
                return 0
            case _:
                raise ValueError("Unknown explainer action")
        print_json({"artifact_path": str(result)})
        return 0
    except (ValueError, KeyError, OSError, RuntimeError) as exc:
        print_json({"status": "rejected", "error": str(exc)})
        return 1
