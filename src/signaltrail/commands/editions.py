"""CLI handlers for editions. Business rules stay in the domain modules."""

from __future__ import annotations

import argparse
from collections.abc import Collection
from contextlib import nullcontext
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
from .common import CommandContext, batch_submission_result, print_command_result, print_json


def handle_run_edition(args: argparse.Namespace, context: CommandContext) -> int:
    """准备日报并按显式选项执行人工验证。"""
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
    """为日报补充正文并刷新上下文。"""
    config = context.config
    data_dir = context.data_dir
    complete = args.all_slide_candidates
    if complete and args.max_items is not None and args.max_items <= 0:
        raise ValueError("--all-slide-candidates requires a positive batch size")
    while True:
        output = enrich_edition(
            run_path=args.run, config=config, data_dir=data_dir,
            selected_ids=args.item_id, max_items=args.max_items,
            headed=args.headed, profile_dir=args.profile_dir, browser_channel=args.browser_channel,
            slides_candidates=args.slides_candidates or complete,
        )
        run = read_json_object(output, "Command result")
        candidates = run["artifacts"]["enrichment"].get("slides_candidates")
        if not complete or (candidates and (
            not candidates["remaining_count"] or not candidates["supplemented_count"]
        )):
            break
    print_command_result(run, context, output)
    return 0


def handle_begin_authoring(args: argparse.Namespace, context: CommandContext) -> int:
    """创建本轮写作会话与批次路径。"""
    data_dir = context.data_dir
    output = begin_authoring(args.run, data_dir, config=context.config,
                             refresh_context=args.refresh_context)
    print_command_result(read_json_object(output, "Command result"), context, output)
    return 0


def handle_submit_authoring_batch(args: argparse.Namespace, context: CommandContext) -> int:
    """校验并接收指定批次的写作结果。"""
    if args.all:
        if args.batch_id or args.result:
            raise ValueError("--all cannot be combined with --batch-id or --result")
        entry = None
    else:
        if args.skip_batch:
            raise ValueError("--skip-batch requires --all")
        if not args.batch_id or not args.result:
            raise ValueError("--batch-id and --result are required without --all")
        if not args.check_only:
            output = accept_authoring_batch(args.run, args.batch_id, args.result, context.data_dir)
            print_command_result(read_json_object(output, "Command result"), context, output)
            return 0
        entry = (args.batch_id, args.result)
    result = submit_brief_batches(args.run, context.data_dir, entry=entry,
                                  check_only=args.check_only, skip_batch=args.skip_batch)
    print_json(result)
    return 1 if result["invalid"] else 0


def submit_brief_batches(run_path: Path, data_dir: Path, *,
                         entry: tuple[str, Path] | None = None, check_only: bool = False,
                         skip_batch: Collection[str] = (), dispatch: bool = False) -> dict:
    """处理：读取一次简报会话，逐批预检或在同一运行锁内提交就绪稿。
    输入：正式运行、数据根、批次选择和在途列表。
    输出：逐批状态与错误，调度时附上已经读取的作者包路径。
    """
    from ..authoring import (
        BriefDraftError,
        _load_authoring_session,
        _validate_session_binding,
        check_authoring_batch,
        submit_authoring_batch,
    )
    from ..runtime import require_data_root_path
    from ..workflow import RunStatus, _load_run_manifest, _locked_authoring_run

    manifest = (nullcontext(_load_run_manifest(run_path, data_dir)) if check_only
                else _locked_authoring_run(run_path, data_dir, timezone="Asia/Shanghai"))
    skipped = set(skip_batch)
    rows, accepted, submitted = [], [], []
    with manifest as (_, run):
        if run.get("status") != RunStatus.AWAITING_AUTHORING:
            raise RuntimeError(f"Run must be awaiting authoring, got {run.get('status')!r}")
        _, session = _load_authoring_session(run, data_dir)
        _validate_session_binding(run, session, data_dir)
        batches = {str(batch["batch_id"]): batch for batch in session["batches"]}
        entries = [entry] if entry else [
            (batch_id, Path(batch["draft_result_path"])) for batch_id, batch in batches.items()
        ]
        for batch_id, draft_path in entries:
            batch = batches.get(batch_id)
            row = {"batch_id": batch_id, "draft_path": str(draft_path), "expected_path": None,
                   "errors": []}
            rows.append(row)
            if batch is None:
                row["errors"] = [f"Unknown authoring batch: {batch_id}"]
                continue
            row["expected_path"] = str(batch["result_path"])
            if dispatch:
                row["packet_path"] = batch["packet_path"]
            try:
                existing = require_data_root_path(Path(batch["result_path"]), data_dir,
                                                  "Authoring batch result")
                row["expected_path"] = str(existing)
                if existing.is_file() and (entry is None or not draft_path.is_file()):
                    if str(read_json_object(existing, "Authoring batch result").get(
                        "batch_id"
                    )) != batch_id:
                        raise ValueError("Accepted batch ID mismatch")
                    row["accepted_path"] = str(existing)
                    accepted.append(str(existing))
                elif batch_id in skipped or batch["packet_path"] in skipped:
                    row["in_flight"] = True
                elif check_only:
                    row.update(check_authoring_batch(
                        run, batch_id, draft_path, data_dir, _validated_session=session,
                    ))
                else:
                    path = submit_authoring_batch(
                        run, batch_id, draft_path, data_dir, _validated_session=session,
                        record_rejection=False,
                    )
                    row["accepted_path"] = str(path)
                    submitted.append(str(path))
            except BriefDraftError as exc:
                row["errors"] = exc.errors
            except (ValueError, KeyError, OSError, RuntimeError) as exc:
                row["errors"] = [str(exc)]
    return batch_submission_result(rows, accepted + submitted, check_only)


def handle_brief_input(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：一次输出独立简报作者所需的单行输入。
    输入：指定的受限包路径和当前数据根。
    输出：完整 Schema、候选证据和预检命令，不修改运行或接收结果。
    """
    from ..authoring import brief_authoring_input
    from .common import print_json

    print_json(brief_authoring_input(
        args.packet, context.data_dir, include_evidence=args.include_evidence), indent=None)
    return 0


def handle_record_authoring_metrics(args: argparse.Namespace, context: CommandContext) -> int:
    """保存宿主返回的写作计量数据。"""
    data_dir = context.data_dir
    output = accept_authoring_metrics(
        args.run,
        args.metrics,
        data_dir,
    )
    print_command_result(read_json_object(output, "Command result"), context, output)
    return 0


def handle_authoring_status(args: argparse.Namespace, context: CommandContext) -> int:
    """读取批次完成情况与写作期限。"""
    data_dir = context.data_dir
    print_command_result(get_authoring_status(args.run, data_dir), context, args.run)
    return 0


def handle_prefetch_media(args: argparse.Namespace, context: CommandContext) -> int:
    """预取本轮报告使用的图片缓存。"""
    config = context.config
    data_dir = context.data_dir
    print_command_result(prefetch_authoring_media(args.run, data_dir, config.media),
                         context, args.run)
    return 0


def handle_prepare_analysis(args: argparse.Namespace, context: CommandContext) -> int:
    """合并已接收摘要并准备研判数据包。"""
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
    """合并研判与摘要形成报告草稿。"""
    data_dir = context.data_dir
    output = assemble_authoring(args.run, args.analysis, data_dir)
    print_command_result(read_json_object(output, "Command result"), context, output)
    return 0


def handle_finalize_edition(args: argparse.Namespace, context: CommandContext) -> int:
    """校验日报草稿并保存本地报告。"""
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
        slides_review=args.slides_review,
        slides_reuse_plan=args.slides_reuse_plan,
        evaluation_backend=args.evaluation_backend,
        app_config=config,
    )
    payload = read_json_object(output, "Run manifest")
    payload["delivery"] = get_edition_status(args.run, data_dir)
    print_command_result(payload, context, output)
    return 0


def handle_complete_edition_tail(args: argparse.Namespace, context: CommandContext) -> int:
    """完成可重试的报告投影和评估调度。"""
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
