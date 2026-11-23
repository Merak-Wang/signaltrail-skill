"""CLI handlers for sources. Business rules stay in the domain modules."""

from __future__ import annotations

import argparse

from ..collector import collect_sources, merge_resume_index
from ..config import (
    add_source_page,
    load_source_pages,
    remove_source_page,
)
from ..content import extract_content
from ..context import build_context
from ..importer import import_legacy
from ..runtime import require_data_root_path
from ..utils import read_json
from ..workflow import (
    adopt_index_for_run,
)
from .common import CommandContext, print_json


def handle_cleanup(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：预览或回收超过指定天数的采集材料。
    输入：保留天数、执行开关和当前数据根。
    输出：候选和回收失败回执，失败时返回非零状态。
    """
    from ..retention import cleanup_collection

    result = cleanup_collection(context.data_dir, days=args.days, apply=args.apply)
    print_json(result, indent=None)
    return 1 if result["failures"] else 0


def handle_source_page(args: argparse.Namespace, context: CommandContext) -> int:
    """读取或修改已批准的来源索引页。"""
    config = context.config
    data_dir = context.data_dir
    parser = context.parser
    if args.action == "list":
        print_json(load_source_pages(data_dir))
        return 0
    if not args.source or not args.url:
        parser.error("source-page add/remove requires --source and --url")
    output = (
        add_source_page(config, data_dir, args.source, args.url, args.reason)
        if args.action == "add"
        else remove_source_page(data_dir, args.source, args.url)
    )
    print(output)
    return 0


def handle_collect(args: argparse.Namespace, context: CommandContext) -> int:
    """按配置采集一次来源索引。"""
    config = context.config
    data_dir = context.data_dir
    output = collect_sources(
        config=config,
        data_dir=data_dir,
        edition=args.edition,
        headed=args.headed,
        only_source_ids=set(args.source) or None,
        profile_dir=args.profile_dir,
        browser_channel=args.browser_channel,
    )
    print(output)
    return 0


def handle_import_legacy(args: argparse.Namespace, context: CommandContext) -> int:
    """把旧链接文件导入当前索引格式。"""
    config = context.config
    data_dir = context.data_dir
    output = import_legacy(args.input, config, data_dir, args.edition)
    print(output)
    return 0


def handle_build_context(args: argparse.Namespace, context: CommandContext) -> int:
    """从索引构建本轮写作上下文。"""
    config = context.config
    data_dir = context.data_dir
    index_path = require_data_root_path(args.index, data_dir, "Context index")
    output = build_context(index_path, config, data_dir, args.edition)
    print(output)
    return 0


def handle_extract_content(args: argparse.Namespace, context: CommandContext) -> int:
    """为指定候选补充正文证据。"""
    config = context.config
    data_dir = context.data_dir
    index_path = require_data_root_path(args.index, data_dir, "Content index")
    output = extract_content(
        index_path=index_path,
        config=config,
        data_dir=data_dir,
        selected_ids=args.item_id,
        max_items=args.max_items,
        headed=args.headed,
        profile_dir=args.profile_dir,
        browser_channel=args.browser_channel,
    )
    print(output)
    return 0


def handle_resume(args: argparse.Namespace, context: CommandContext) -> int:
    """重试失败来源并将新索引关联到运行。"""
    config = context.config
    data_dir = context.data_dir
    index_path = require_data_root_path(args.index, data_dir, "Resume index")
    index = read_json(index_path)
    if not isinstance(index, dict):
        raise ValueError("Index must be a JSON object")
    source_ids = {
        row["source_id"]
        for row in index.get("sources", [])
        if row.get("status") in {"verification_required", "rate_limited", "failed"}
    }
    if not source_ids:
        print("No challenged or failed sources to retry")
        return 0
    retry_output = collect_sources(
        config=config,
        data_dir=data_dir,
        edition=index.get("edition", "resume"),
        headed=args.headed,
        only_source_ids=source_ids,
        profile_dir=args.profile_dir,
        browser_channel=args.browser_channel,
        temporary=True,
    )
    output = merge_resume_index(index_path, retry_output, data_dir)
    adopt_index_for_run(config, data_dir, output)
    print(output)
    return 0
