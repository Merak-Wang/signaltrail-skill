"""CLI entry points for budgeted news slides."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..news_slides import prepare_slides, render_slides, slides_status, submit_slides
from ..utils import read_json_object
from .common import CommandContext, print_json


def add_slides_parser(sub: argparse._SubParsersAction) -> None:
    """处理：注册图文流的准备、批次提交、进度和 HTML 生成命令。
    输入：主命令树；筛选与预算选项仅作用于独立图文产物。
    输出：slides 子命令，不改变既有日报命令的参数与默认输出。
    """
    parser = sub.add_parser("slides", help="Build animated HTML news slides from a saved report")
    stages = parser.add_subparsers(dest="action", required=True)
    prepare = stages.add_parser(
        "prepare", help="Select representative news and split bounded batches"
    )
    prepare.add_argument("--report", type=Path, required=True)
    prepare.add_argument("--index", type=Path, required=True)
    prepare.add_argument("--item-id", action="append")
    prepare.add_argument("--min-importance", type=int, default=70)
    prepare.add_argument("--batch-size", type=int, default=4)
    prepare.add_argument("--max-input-tokens", type=int, default=12000)
    prepare.add_argument("--max-output-tokens", type=int, default=4000)
    submit = stages.add_parser("submit", help="Accept and reuse one authored batch")
    submit.add_argument("--packet", type=Path, required=True)
    submit.add_argument("--input", type=Path, required=True)
    for name in ("status", "render"):
        command = stages.add_parser(name)
        command.add_argument("--plan", type=Path, required=True)


def handle_slides(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：把显式图文操作派发到新闻分批与模板模块。
    输入：命令行路径、筛选条件和已绑定数据根。
    输出：JSON 路径或可恢复错误；不调用模型、TTS 或视频服务。
    """
    try:
        match args.action:
            case "prepare":
                result = prepare_slides(
                    args.report, args.index, context.data_dir,
                    min_importance=args.min_importance, item_ids=args.item_id,
                    batch_size=args.batch_size, max_input_tokens=args.max_input_tokens,
                    max_output_tokens=args.max_output_tokens,
                )
            case "submit":
                result = submit_slides(args.packet, read_json_object(args.input, "Slide draft"),
                                       context.data_dir)
            case "status":
                result = slides_status(args.plan, context.data_dir)
            case "render":
                result = render_slides(args.plan, context.data_dir)
        print_json({"artifact_path": str(result)} if isinstance(result, Path) else result)
        return 0
    except (ValueError, KeyError, OSError, RuntimeError) as exc:
        print_json({"status": "rejected", "error": str(exc)})
        return 1
