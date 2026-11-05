"""个人新闻平台研究任务的宿主交接命令。"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from ..events import list_research_jobs
from ..utils import read_json_object
from .common import CommandContext, print_json


def add_platform_parser(sub: argparse._SubParsersAction) -> None:
    """处理：注册研究任务查看、执行与结果提交命令。
    输入：已有主命令树。
    输出：宿主可读取冻结证据并完成平台中等待模型的任务。
    """
    platform = sub.add_parser("platform-research", help="Inspect and complete event research jobs")
    stages = platform.add_subparsers(dest="action", required=True)
    listing = stages.add_parser("list", help="List jobs and their evidence packet paths")
    listing.add_argument("--event")
    listing.add_argument("--status")
    run = stages.add_parser("run", help="Run an existing job with the configured research host")
    run.add_argument("--job", required=True)
    run.add_argument("--worker-command")
    submit = stages.add_parser("submit", help="Submit host-authored JSON against the frozen packet")
    submit.add_argument("--job", required=True)
    submit.add_argument("--input", type=Path, required=True)


def handle_platform_research(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：交接平台研究给后台宿主或当前技能宿主。
    输入：任务身份、结果文件和应用资料目录。
    输出：持久任务状态；执行失败返回非零退出码。
    """
    if args.action == "list":
        print_json(
            {"jobs": list_research_jobs(context.data_dir, status=args.status, event_id=args.event)}
        )
        return 0
    from ..platform_research import ResearchService

    service = ResearchService(
        context.config,
        context.data_dir,
        worker_command=getattr(args, "worker_command", None),
        resume=False,
    )
    try:
        if args.action == "submit":
            job = service.complete(args.job, read_json_object(args.input, "Research result"))
        else:
            job = service.run(args.job)
            deadline = time.monotonic() + service.timeout + 60
            while job["status"] in {"queued", "running"} and time.monotonic() < deadline:
                time.sleep(0.25)
                job = service.get(args.job)
        print_json({"job": job})
        return 1 if job["status"] in {"failed", "queued", "running"} else 0
    finally:
        service.close()
