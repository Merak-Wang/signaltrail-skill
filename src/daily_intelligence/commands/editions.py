"""CLI handlers for editions. Business rules stay in the domain modules."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..utils import read_json_object, write_json
from ..verification import (
    run_pending_verification,
)
from ..workflow import (
    accept_authoring_batch,
    accept_authoring_metrics,
    assemble_authoring,
    begin_authoring,
    complete_edition_tail,
    enrich_edition,
    finalize_edition,
    get_authoring_status,
    prefetch_authoring_media,
    prepare_authoring_analysis,
    prepare_edition,
)
from .common import CommandContext, print_json, print_json_file


def handle_run_edition(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：准备日报并按显式选项执行人工验证。
    输入：
    - ``args``：解析器校验过的 run-edition 参数；指定本次操作的选项与文件。
    - ``context``：入口解析的 config、data_dir；提供运行配置和路径约束。
    输出：向标准输出报告操作结果，并返回供终端或宿主判断成败的退出码。
    """
    config = context.config
    data_dir = context.data_dir
    output = prepare_edition(
        config=config,
        data_dir=data_dir,
        edition=args.edition,
        headed=args.headed,
        profile_dir=args.profile_dir,
        browser_channel=args.browser_channel,
        restart=args.restart,
    )
    run_payload = read_json_object(output, "Run manifest")
    automatic_verification = None
    index_value = run_payload.get("artifacts", {}).get("index_path")
    if args.open_verification and index_value:
        automatic_verification = run_pending_verification(
            Path(index_value),
            config,
            data_dir,
            profile_dir=args.profile_dir,
            browser_channel=args.browser_channel,
            timeout_seconds=args.verification_timeout_seconds,
        )
        run_payload = read_json_object(output, "Run manifest")
    elif args.open_verification:
        automatic_verification = {
            "status": "index_unavailable",
            "next_action": (
                "The run has not completed collection yet; resume it before opening "
                "interactive verification."
            ),
        }
    if automatic_verification is not None:
        run_payload["automatic_verification"] = automatic_verification
        write_json(output, run_payload)
    print_json(run_payload)
    return 0


def handle_enrich_edition(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：为日报补充正文并刷新上下文。
    输入：
    - ``args``：解析器校验过的 enrich-edition 参数；指定本次操作的选项与文件。
    - ``context``：入口解析的 config、data_dir；提供运行配置和路径约束。
    输出：向标准输出报告操作结果，并返回供终端或宿主判断成败的退出码。
    """
    config = context.config
    data_dir = context.data_dir
    output = enrich_edition(
        run_path=args.run,
        config=config,
        data_dir=data_dir,
        selected_ids=args.item_id,
        max_items=args.max_items,
        headed=args.headed,
        profile_dir=args.profile_dir,
        browser_channel=args.browser_channel,
    )
    print_json_file(output)
    return 0


def handle_begin_authoring(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：创建本轮写作会话与批次路径。
    输入：
    - ``args``：解析器校验过的 begin-authoring 参数；指定本次操作的选项与文件。
    - ``context``：入口解析的 data_dir；提供运行配置和路径约束。
    输出：向标准输出报告操作结果，并返回供终端或宿主判断成败的退出码。
    """
    data_dir = context.data_dir
    output = begin_authoring(args.run, data_dir)
    print_json_file(output)
    return 0


def handle_submit_authoring_batch(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：校验并接收指定批次的写作结果。
    输入：
    - ``args``：解析器校验过的 submit-authoring-batch 参数；指定本次操作的选项与文件。
    - ``context``：入口解析的 data_dir；提供运行配置和路径约束。
    输出：向标准输出报告操作结果，并返回供终端或宿主判断成败的退出码。
    """
    data_dir = context.data_dir
    output = accept_authoring_batch(
        args.run,
        args.batch_id,
        args.result,
        data_dir,
    )
    print_json_file(output)
    return 0


def handle_record_authoring_metrics(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：保存宿主返回的写作计量数据。
    输入：
    - ``args``：解析器校验过的 record-authoring-metrics 参数；指定本次操作的选项与文件。
    - ``context``：入口解析的 data_dir；提供运行配置和路径约束。
    输出：向标准输出报告操作结果，并返回供终端或宿主判断成败的退出码。
    """
    data_dir = context.data_dir
    output = accept_authoring_metrics(
        args.run,
        args.metrics,
        data_dir,
    )
    print_json_file(output)
    return 0


def handle_authoring_status(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：读取批次完成情况与写作期限。
    输入：
    - ``args``：解析器校验过的 authoring-status 参数；指定本次操作的选项与文件。
    - ``context``：入口解析的 data_dir；提供运行配置和路径约束。
    输出：向标准输出报告操作结果，并返回供终端或宿主判断成败的退出码。
    """
    data_dir = context.data_dir
    print_json(get_authoring_status(args.run, data_dir))
    return 0


def handle_prefetch_media(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：预取本轮报告使用的图片缓存。
    输入：
    - ``args``：解析器校验过的 prefetch-media 参数；指定本次操作的选项与文件。
    - ``context``：入口解析的 config、data_dir；提供运行配置和路径约束。
    输出：向标准输出报告操作结果，并返回供终端或宿主判断成败的退出码。
    """
    config = context.config
    data_dir = context.data_dir
    print_json(prefetch_authoring_media(args.run, data_dir, config.media))
    return 0


def handle_prepare_analysis(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：合并已接收摘要并准备研判数据包。
    输入：
    - ``args``：解析器校验过的 prepare-analysis 参数；指定本次操作的选项与文件。
    - ``context``：入口解析的 data_dir；提供运行配置和路径约束。
    输出：向标准输出报告操作结果，并返回供终端或宿主判断成败的退出码。
    """
    data_dir = context.data_dir
    output = prepare_authoring_analysis(
        args.run,
        data_dir,
        allow_degraded=args.allow_degraded,
    )
    print_json_file(output)
    return 0


def handle_assemble_authoring(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：合并研判与摘要形成报告草稿。
    输入：
    - ``args``：解析器校验过的 assemble-authoring 参数；指定本次操作的选项与文件。
    - ``context``：入口解析的 data_dir；提供运行配置和路径约束。
    输出：向标准输出报告操作结果，并返回供终端或宿主判断成败的退出码。
    """
    data_dir = context.data_dir
    output = assemble_authoring(args.run, args.analysis, data_dir)
    print_json_file(output)
    return 0


def handle_finalize_edition(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：校验日报草稿并保存本地报告。
    输入：
    - ``args``：解析器校验过的 finalize-edition 参数；指定本次操作的选项与文件。
    - ``context``：入口解析的 config、data_dir；提供运行配置和路径约束。
    输出：向标准输出报告操作结果，并返回供终端或宿主判断成败的退出码。
    """
    config = context.config
    data_dir = context.data_dir
    output = finalize_edition(
        run_path=args.run,
        report_path=args.report,
        data_dir=data_dir,
        publish=args.publish,
        force_publish=args.force_publish,
        notion_config=args.notion_config,
        output_config=config.output,
        media_config=config.media,
        defer_tail=args.defer_tail,
    )
    print_json_file(output)
    return 0


def handle_complete_edition_tail(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：完成可重试的报告投影和评估调度。
    输入：
    - ``args``：解析器校验过的 complete-edition-tail 参数；指定本次操作的选项与文件。
    - ``context``：入口解析的 config、data_dir；提供运行配置和路径约束。
    输出：向标准输出报告操作结果，并返回供终端或宿主判断成败的退出码。
    """
    config = context.config
    data_dir = context.data_dir
    output = complete_edition_tail(
        args.run,
        data_dir,
        publish=args.publish,
        notion_config=args.notion_config,
        output_config=config.output,
    )
    print_json_file(output)
    return 0
