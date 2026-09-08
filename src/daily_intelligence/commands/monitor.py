"""CLI handlers for monitor. Business rules stay in the domain modules."""

from __future__ import annotations

import argparse

from ..dashboard import serve_monitor
from ..monitor import refresh_monitor
from ..utils import read_json_object
from .common import CommandContext, print_json


def handle_refresh_monitor(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：刷新监控快照并输出采集摘要。
    输入：
    - ``args``：解析器校验过的 refresh-monitor 参数；指定本次操作的选项与文件。
    - ``context``：入口解析的 config、data_dir；提供运行配置和路径约束。
    输出：向标准输出报告操作结果，并返回供终端或宿主判断成败的退出码。
    """
    config = context.config
    data_dir = context.data_dir
    output = refresh_monitor(
        config,
        data_dir,
        only_source_ids=set(args.source) or None,
        bundles=set(args.bundle) or None,
        include_discovery=not args.core_only,
        force=args.force,
        html_fallback=not args.no_html_fallback,
    )
    snapshot = read_json_object(output, "Monitor snapshot")
    print_json(
        {
            "snapshot_path": str(output),
            "generated_at": snapshot.get("generated_at"),
            "token_usage": snapshot.get("token_usage", 0),
            **snapshot.get("summary", {}),
        }
    )
    return 0


def handle_monitor_status(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：读取已有监控快照的状态。
    输入：
    - ``args``：解析器校验过的 monitor-status 参数；指定本次操作的选项与文件。
    - ``context``：入口解析的 data_dir；提供运行配置和路径约束。
    输出：向标准输出报告操作结果，并返回供终端或宿主判断成败的退出码。
    """
    data_dir = context.data_dir
    snapshot_path = data_dir / "monitor" / "snapshot.json"
    if not snapshot_path.exists():
        print_json(
            {
                "status": "not_initialized",
                "next_action": "daily-intel refresh-monitor",
            }
        )
        return 1
    snapshot = read_json_object(snapshot_path, "Monitor snapshot")
    print_json(
        {
            "status": "ready",
            "snapshot_path": str(snapshot_path),
            "generated_at": snapshot.get("generated_at"),
            "token_usage": snapshot.get("token_usage", 0),
            **snapshot.get("summary", {}),
        }
    )
    return 0


def handle_serve(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：启动本地监控页面和可选刷新循环。
    输入：
    - ``args``：解析器校验过的 serve 参数；指定本次操作的选项与文件。
    - ``context``：入口解析的 config、data_dir；提供运行配置和路径约束。
    输出：向标准输出报告操作结果，并返回供终端或宿主判断成败的退出码。
    """
    config = context.config
    data_dir = context.data_dir
    serve_monitor(
        config,
        data_dir,
        host=args.host,
        port=args.port,
        open_browser=args.open_browser,
        allow_remote=args.allow_remote,
        refresh_minutes=args.refresh_minutes,
    )
    return 0
