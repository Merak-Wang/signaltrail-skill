"""CLI handlers for monitor. Business rules stay in the domain modules."""

from __future__ import annotations

import argparse

from ..dashboard import serve_monitor
from ..monitor import refresh_monitor
from ..utils import read_json_object
from .common import CommandContext, print_json


def handle_refresh_monitor(args: argparse.Namespace, context: CommandContext) -> int:
    """刷新监控快照并输出采集摘要。"""
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
    """读取已有监控快照的状态。"""
    data_dir = context.data_dir
    snapshot_path = data_dir / "monitor" / "snapshot.json"
    if not snapshot_path.exists():
        print_json(
            {
                "status": "not_initialized",
                "next_action": "signaltrail refresh-monitor",
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
    """启动本地监控页面和可选刷新循环。"""
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
