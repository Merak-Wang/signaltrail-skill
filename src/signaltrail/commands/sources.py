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


def handle_source_page(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：读取或修改已批准的来源索引页。
    输入：
    - ``args``：解析器校验过的 source-page 参数；指定本次操作的选项与文件。
    - ``context``：入口解析的 config、data_dir、parser；提供运行配置和路径约束。
    输出：向标准输出报告操作结果，并返回供终端或宿主判断成败的退出码。
    """
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
    """处理：按配置采集一次来源索引。
    输入：
    - ``args``：解析器校验过的 collect 参数；指定本次操作的选项与文件。
    - ``context``：入口解析的 config、data_dir；提供运行配置和路径约束。
    输出：向标准输出报告操作结果，并返回供终端或宿主判断成败的退出码。
    """
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
    """处理：把旧链接文件导入当前索引格式。
    输入：
    - ``args``：解析器校验过的 import-legacy 参数；指定本次操作的选项与文件。
    - ``context``：入口解析的 config、data_dir；提供运行配置和路径约束。
    输出：向标准输出报告操作结果，并返回供终端或宿主判断成败的退出码。
    """
    config = context.config
    data_dir = context.data_dir
    output = import_legacy(args.input, config, data_dir, args.edition)
    print(output)
    return 0


def handle_build_context(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：从索引构建本轮写作上下文。
    输入：
    - ``args``：解析器校验过的 build-context 参数；指定本次操作的选项与文件。
    - ``context``：入口解析的 config、data_dir；提供运行配置和路径约束。
    输出：向标准输出报告操作结果，并返回供终端或宿主判断成败的退出码。
    """
    config = context.config
    data_dir = context.data_dir
    index_path = require_data_root_path(args.index, data_dir, "Context index")
    output = build_context(index_path, config, data_dir, args.edition)
    print(output)
    return 0


def handle_extract_content(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：为指定候选补充正文证据。
    输入：
    - ``args``：解析器校验过的 extract-content 参数；指定本次操作的选项与文件。
    - ``context``：入口解析的 config、data_dir；提供运行配置和路径约束。
    输出：向标准输出报告操作结果，并返回供终端或宿主判断成败的退出码。
    """
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
    """处理：重试失败来源并将新索引关联到运行。
    输入：
    - ``args``：解析器校验过的 resume 参数；指定本次操作的选项与文件。
    - ``context``：入口解析的 config、data_dir；提供运行配置和路径约束。
    输出：向标准输出报告操作结果，并返回供终端或宿主判断成败的退出码。
    """
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
