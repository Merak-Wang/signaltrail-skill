"""Explicit research commands alongside the unchanged daily workflow."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..research import (
    evaluate_research,
    prepare_research_snapshot,
    search_research,
    select_research_evidence,
    submit_research_memo,
    update_research_questions,
)
from ..research_delivery import bind_research_to_report, render_composite_view
from ..utils import read_json_object
from .common import CommandContext, print_json


def add_research_parser(sub: argparse._SubParsersAction) -> None:
    """处理：注册与日报主线独立的研究准备、检索、底稿及晚绑定命令。
    输入：主命令树；文件路径明确指定每一步消费的修订。
    输出：可执行的 research 子命令，不隐式派发模型或网络请求。
    """
    research = sub.add_parser("research", help="Research frozen evidence alongside daily authoring")
    stages = research.add_subparsers(dest="action", required=True)
    prepare = stages.add_parser(
        "prepare", help="Freeze approved index items without a final report"
    )
    prepare.add_argument("--index", type=Path, required=True)
    prepare.add_argument("--item-id", action="append", required=True)
    prepare.add_argument("--cutoff", required=True)
    prepare.add_argument("--questions", type=Path, required=True)
    prepare.add_argument("--previous", type=Path)
    prepare.add_argument("--discovery", type=Path)
    for name in ("search", "select", "questions", "memo", "evaluate"):
        command = stages.add_parser(name)
        command.add_argument("--snapshot", type=Path, required=True)
        if name in {"questions", "memo"}:
            command.add_argument("--input", type=Path, required=True)
        if name in {"search", "select"}:
            command.add_argument("--limit", type=int, default=6)
        if name == "search":
            command.add_argument("--query", required=True)
    bind = stages.add_parser("bind", help="Bind reviewed research to the actual final edition")
    bind.add_argument("--story", type=Path, required=True)
    bind.add_argument("--run", type=Path, required=True)
    bind.add_argument("--relations", type=Path, required=True)
    bind.add_argument("--experimental", action="store_true")
    render = stages.add_parser("render", help="Write a new composite reading projection")
    render.add_argument("--binding", type=Path, required=True)
    render.add_argument("--mode", choices=["preview", "current"], default="preview")


def handle_research(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：将研究阶段参数传给域函数，输出下一步可用路径或指标。
    输入：命令参数、既有数据根和显式 JSON 草稿。
    输出：成功返回零；研究失败只报告本阶段错误，不改变日报状态。
    """
    root = context.data_dir
    try:
        match args.action:
            case "prepare":
                result = prepare_research_snapshot(
                    args.index,
                    args.item_id,
                    args.cutoff,
                    read_json_object(args.questions, "Questions")["questions"],
                    root,
                    previous_path=args.previous,
                    discovery_path=args.discovery,
                )
            case "search":
                result = search_research(args.snapshot, args.query, root, limit=args.limit)
            case "select":
                result = select_research_evidence(args.snapshot, root, limit=args.limit)
            case "questions":
                result = update_research_questions(
                    args.snapshot, read_json_object(args.input, "Findings")["questions"], root
                )
            case "memo":
                result = submit_research_memo(
                    args.snapshot, read_json_object(args.input, "Research memo"), root
                )
            case "evaluate":
                result = evaluate_research(args.snapshot, root)
            case "bind":
                result = bind_research_to_report(
                    args.story,
                    args.run,
                    read_json_object(args.relations, "Relations")["relations"],
                    root,
                    experimental=args.experimental,
                )
            case "render":
                result = render_composite_view(args.binding, root, mode=args.mode)
            case _:
                raise ValueError("Unknown research action")
        print_json({"artifact_path": str(result)} if isinstance(result, Path) else result)
        return 0
    except (ValueError, KeyError, OSError, RuntimeError) as exc:
        print_json({"status": "rejected", "error": str(exc)})
        return 1
