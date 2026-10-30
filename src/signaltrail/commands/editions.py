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
    get_edition_status,
    prefetch_authoring_media,
    prepare_authoring_analysis,
    prepare_edition,
)
from .common import CommandContext, print_command_result


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
    run_payload["delivery"] = get_edition_status(output, data_dir)
    print_command_result(run_payload, context, output)
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
    print_command_result(read_json_object(output, "Command result"), context, output)
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
    print_command_result(read_json_object(output, "Command result"), context, output)
    return 0


def handle_submit_authoring_batch(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：校验并接收指定批次的写作结果。
    输入：
    - ``args``：解析器校验过的 submit-authoring-batch 参数；指定本次操作的选项与文件。
    - ``context``：入口解析的 data_dir；提供运行配置和路径约束。
    输出：向标准输出报告操作结果，并返回供终端或宿主判断成败的退出码。
    """
    if not args.all and not args.check_only:
        if not args.batch_id or not args.result:
            raise ValueError("--batch-id and --result are required without --all")
        output = accept_authoring_batch(args.run, args.batch_id, args.result, context.data_dir)
        print_command_result(read_json_object(output, "Command result"), context, output)
        return 0
    from ..authoring import _validate_session_binding, check_authoring_batch
    from ..runtime import require_data_root_path, validate_run_data_root
    from .common import print_json

    data_dir = context.data_dir
    run_path = require_data_root_path(args.run, data_dir, "Run manifest")
    run = read_json_object(run_path, "Run manifest")
    validate_run_data_root(run, run_path, data_dir)
    if run.get("status") != "awaiting_authoring":
        raise RuntimeError(f"Run must be awaiting authoring, got {run.get('status')!r}")
    session_path = require_data_root_path(
        Path(run["artifacts"]["authoring"]["session_path"]), data_dir, "Authoring session")
    session = read_json_object(session_path, "Authoring session")
    _validate_session_binding(run, session, data_dir)
    if args.all:
        if args.batch_id or args.result:
            raise ValueError("--all cannot be combined with --batch-id or --result")
        entries = [(str(b["batch_id"]), Path(b["draft_result_path"]))
                   for b in session["batches"]]
    else:
        if not args.batch_id or not args.result:
            raise ValueError("--batch-id and --result are required without --all")
        entries = [(args.batch_id, args.result)]
    rows = []
    for batch_id, draft_path in entries:
        batch = next((b for b in session["batches"] if str(b["batch_id"]) == batch_id), None)
        if batch is None:
            rows.append({"batch_id": batch_id, "draft_path": str(draft_path),
                         "expected_path": None, "errors": [f"Unknown authoring batch: {batch_id}"]})
            continue
        try:
            existing = require_data_root_path(Path(batch["result_path"]), data_dir,
                                              "Authoring batch result")
            if existing.is_file() and (args.all or not draft_path.is_file()):
                accepted_record = read_json_object(existing, "Authoring batch result")
                if str(accepted_record.get("batch_id")) != batch_id:
                    raise ValueError("Accepted batch ID mismatch")
                row = {"batch_id": batch_id, "draft_path": str(draft_path),
                       "expected_path": str(existing), "accepted_path": str(existing),
                       "errors": []}
            else:
                row = check_authoring_batch(run, batch_id, draft_path, data_dir)
        except (ValueError, KeyError, OSError, RuntimeError) as exc:
            row = {"batch_id": batch_id, "draft_path": str(draft_path),
                   "expected_path": str(batch["result_path"]), "errors": [str(exc)]}
        rows.append(row)
    accepted = [row["accepted_path"] for row in rows if row.get("accepted_path")]
    if not args.check_only:
        for row in rows:
            if not row["errors"] and not row.get("accepted_path"):
                try:
                    path = accept_authoring_batch(run_path, row["batch_id"],
                                                  Path(row["draft_path"]), data_dir)
                    row["accepted_path"] = str(path)
                    accepted.append(str(path))
                except (ValueError, KeyError, OSError, RuntimeError) as exc:
                    row["errors"].append(str(exc))
    pending = [row["batch_id"] for row in rows if not row.get("accepted_path")]
    invalid = [row["batch_id"] for row in rows if row["errors"]]
    status = "partial" if invalid else "ready_to_submit" if pending else "ready"
    print_json({"status": status, "check_only": args.check_only, "accepted": accepted,
                "pending": pending, "invalid": invalid,
                "expected_paths": [row["expected_path"] for row in rows], "batches": rows})
    return 1 if invalid else 0


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
    print_command_result(read_json_object(output, "Command result"), context, output)
    return 0


def handle_authoring_status(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：读取批次完成情况与写作期限。
    输入：
    - ``args``：解析器校验过的 authoring-status 参数；指定本次操作的选项与文件。
    - ``context``：入口解析的 data_dir；提供运行配置和路径约束。
    输出：向标准输出报告操作结果，并返回供终端或宿主判断成败的退出码。
    """
    data_dir = context.data_dir
    print_command_result(get_authoring_status(args.run, data_dir), context, args.run)
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
    print_command_result(prefetch_authoring_media(args.run, data_dir, config.media),
                         context, args.run)
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
    if args.parallel:
        from ..analysis_parallel import prepare_analysis_selection

        result = prepare_analysis_selection(read_json_object(args.run, "Run manifest"), data_dir)
        print_command_result(result, context, Path(result["packet_path"]))
    else:
        print_command_result(read_json_object(output, "Command result"), context, output)
    return 0


def handle_analysis_stage(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：根据显式阶段推进选题后的并行领域研判、综合与组装。
    输入：运行清单、已写入固定路径的阶段结果及阶段名。
    输出：下一阶段数据包路径，或供 assemble-authoring 使用的研判结果路径。
    """
    from ..analysis_parallel import (
        assemble_parallel_analysis,
        prepare_analysis_domains,
        prepare_analysis_synthesis,
    )

    stage = {"domains": prepare_analysis_domains, "synthesis": prepare_analysis_synthesis,
             "assemble": assemble_parallel_analysis}[args.stage]
    result = stage(read_json_object(args.run, "Run manifest"), context.data_dir)
    print_command_result(result, context, args.run)
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
    print_command_result(read_json_object(output, "Command result"), context, output)
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
        evaluate=args.evaluate,
        slides_max_news=args.slides_max_news,
        slides_exclude_event_ids=args.slides_exclude_event_id,
        evaluation_backend=args.evaluation_backend,
        app_config=config,
    )
    payload = read_json_object(output, "Run manifest")
    payload["delivery"] = get_edition_status(args.run, data_dir)
    print_command_result(payload, context, output)
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
        evaluate=args.evaluate,
        evaluation_backend=args.evaluation_backend,
    )
    payload = read_json_object(output, "Run manifest")
    payload["delivery"] = get_edition_status(args.run, data_dir)
    print_command_result(payload, context, output)
    return 0


def handle_edition_status(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：输出整期交付门禁并按需设置失败退出码。
    输入：运行清单路径、require-complete 选项和数据根目录。
    输出：交付状态 JSON；仅强制验收且存在待办时返回非零。
    """
    result = get_edition_status(args.run, context.data_dir)
    print_command_result(result, context, args.run)
    return 0 if result["delivery_complete"] or not args.require_complete else 1
