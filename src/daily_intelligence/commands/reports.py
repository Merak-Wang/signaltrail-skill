"""CLI handlers for reports. Business rules stay in the domain modules."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..notion import append_evaluation, backfill_report_images, publish_report
from ..reporting import validate_report
from ..reports import save_evaluation, save_report
from ..runtime import require_data_root_path
from ..utils import read_json_object
from ..workflow import (
    brief_plan_item_ids_for_run,
)
from .common import CommandContext, print_json


def handle_validate_report(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：检查报告草稿与本轮证据及覆盖计划。
    输入：
    - ``args``：解析器校验过的 validate-report 参数；指定本次操作的选项与文件。
    - ``context``：入口解析的 data_dir、parser；提供运行配置和路径约束。
    输出：向标准输出报告操作结果，并返回供终端或宿主判断成败的退出码。
    """
    data_dir = context.data_dir
    parser = context.parser
    coverage_targets = None
    brief_plan_item_ids = None
    index_value = args.index
    if args.run:
        validation_run_path = require_data_root_path(
            args.run,
            data_dir,
            "Validation run",
        )
        validation_run = read_json_object(validation_run_path, "Validation run")
        index_value = index_value or Path(
            str(validation_run.get("artifacts", {}).get("index_path") or "")
        )
        values = validation_run.get("artifacts", {}).get("authoring", {}).get("coverage_targets")
        if isinstance(values, dict):
            coverage_targets = {str(key): value for key, value in values.items()}
        brief_plan_item_ids = brief_plan_item_ids_for_run(
            validation_run,
            data_dir,
        )
    if index_value is None:
        parser.error("validate-report requires --index or --run")
    index_path = require_data_root_path(
        index_value,
        data_dir,
        "Validation index",
    )
    errors, warnings = validate_report(
        args.report,
        index_path,
        data_dir / "state" / "events.json",
        coverage_targets=coverage_targets,
        brief_plan_item_ids=brief_plan_item_ids,
    )
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    print_json({"errors": len(errors), "warnings": len(warnings)}, indent=None)
    return 1 if errors else 0


def handle_save_report(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：保存经验证的报告及本地投影。
    输入：
    - ``args``：解析器校验过的 save-report 参数；指定本次操作的选项与文件。
    - ``context``：入口解析的 config、data_dir；提供运行配置和路径约束。
    输出：向标准输出报告操作结果，并返回供终端或宿主判断成败的退出码。
    """
    config = context.config
    data_dir = context.data_dir
    index_path = require_data_root_path(args.index, data_dir, "Report index")
    artifacts = save_report(
        args.report,
        index_path,
        data_dir,
        output_config=config.output,
        media_config=config.media,
    )
    print_json(artifacts)
    return 0


def handle_finalize_evaluation(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：保存独立评分并按选项更新远程副本。
    输入：
    - ``args``：解析器校验过的 finalize-evaluation 参数；指定本次操作的选项与文件。
    - ``context``：入口解析的 config、data_dir；提供运行配置和路径约束。
    输出：向标准输出报告操作结果，并返回供终端或宿主判断成败的退出码。
    """
    config = context.config
    data_dir = context.data_dir
    report_path = require_data_root_path(args.report, data_dir, "Evaluated report")
    artifacts = save_evaluation(
        args.evaluation,
        report_path,
        data_dir,
        output_config=config.output,
    )
    publication = None
    if args.publish:
        page_id, status = append_evaluation(
            report_path,
            Path(artifacts["evaluation_path"]),
            data_dir,
            config_path=args.notion_config,
        )
        publication = {"page_id": page_id, "status": status}
    print_json({**artifacts, "publication": publication})
    return 0


def handle_publish_notion(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：发布指定报告到已配置的 Notion。
    输入：
    - ``args``：解析器校验过的 publish-notion 参数；指定本次操作的选项与文件。
    - ``context``：入口解析的 data_dir；提供运行配置和路径约束。
    输出：向标准输出报告操作结果，并返回供终端或宿主判断成败的退出码。
    """
    data_dir = context.data_dir
    report_path = require_data_root_path(args.report, data_dir, "Published report")
    page_id, status = publish_report(
        report_path,
        data_dir=data_dir,
        force=args.force,
        config_path=args.notion_config,
    )
    print_json({"page_id": page_id, "status": status}, indent=None)
    return 0


def handle_backfill_notion_images(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：补充已发布 Notion 报告的缺失图片。
    输入：
    - ``args``：解析器校验过的 backfill-notion-images 参数；指定本次操作的选项与文件。
    - ``context``：入口解析的 data_dir；提供运行配置和路径约束。
    输出：向标准输出报告操作结果，并返回供终端或宿主判断成败的退出码。
    """
    data_dir = context.data_dir
    report_path = require_data_root_path(args.report, data_dir, "Published report")
    page_id, status = backfill_report_images(
        report_path,
        data_dir=data_dir,
        config_path=args.notion_config,
    )
    print_json({"page_id": page_id, "status": status}, indent=None)
    return 0
