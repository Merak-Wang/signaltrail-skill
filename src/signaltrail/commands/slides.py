"""CLI entry points for budgeted news slides."""

from __future__ import annotations

import argparse
import json
from collections.abc import Collection
from pathlib import Path

from httpx import HTTPError

from ..news_slides import (
    SlideDraftError,
    check_slides,
    prepare_slides,
    render_slides,
    slide_batch_paths,
    slides_status,
    submit_slides,
)
from ..utils import read_json_object
from .common import CommandContext, batch_submission_result, print_json
from .parser import add_slides_parser as add_slides_parser


def handle_slides(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：把显式图文操作派发到新闻分批与模板模块。
    输入：命令行路径、筛选条件和已绑定数据根。
    输出：图文或视频产物路径；video-setup 首次下载本地配音与编码工具。
    """
    try:
        match args.action:
            case "review":
                from ..news_slides import review_candidates, review_model_input

                result = review_candidates(
                    read_json_object(args.report, "Report") if args.report else None,
                    read_json_object(args.index, "Index"), args.max_news, context.data_dir)
                if args.parts_dir is not None:
                    from ..author_inputs import materialize_input_parts
                    from ..runtime import require_data_root_path
                    from ..utils import write_text_atomic

                    directory = require_data_root_path(args.parts_dir, context.data_dir,
                                                       "Review input directory")
                    path = directory / "review-input.json"
                    write_text_atomic(path, json.dumps(
                        review_model_input(result), ensure_ascii=False, separators=(",", ":"),
                    ))
                    print_json({"eligible_count": result["eligible_count"],
                                "max_news": result["max_news"],
                                **materialize_input_parts(path)}, indent=None)
                    return 0
                if args.model_input:
                    print_json(review_model_input(result), indent=None)
                    return 0
            case "input":
                from ..narrative_store import load_artifact

                packet = load_artifact(args.packet, context.data_dir)
                payload = packet["payload"]
                if packet["kind"] != f"slides-packet-{payload['batch_id']}":
                    raise ValueError("Expected a slide authoring packet")
                # 只向作者输出一次完整模型输入，父计划与程序计量留在已绑定产物中。
                print_json(payload["model_input"], indent=None)
                return 0
            case "voice-setup":
                from ..video_runtime import register_voice
                result = {"profile": str(register_voice(args.profile, context.data_dir,
                                                       make_default=args.default))}
            case "video-setup":
                from ..video_runtime import ensure_video_runtime
                result = {key: str(value) if isinstance(value, Path) else value for key, value in
                          ensure_video_runtime(context.data_dir, proxy=args.proxy,
                                               device=args.device, voice=args.voice,
                                               reference_id=args.reference_id).items()}
            case "prefetch-speech":
                from ..slide_video import prefetch_speech

                result = prefetch_speech(
                    args.plan, args.output, args.model_dir, context.data_dir,
                    ffmpeg=args.ffmpeg, threads=args.threads, tts_executable=args.tts_executable,
                    device=args.device, voice=args.voice, reference_id=args.reference_id,
                    follow_seconds=args.follow_seconds,
                )
            case "video":
                from ..slide_video import render_video
                result = render_video(args.deck, args.output, args.model_dir, context.data_dir,
                                      ffmpeg=args.ffmpeg, threads=args.threads,
                                      tts_executable=args.tts_executable, device=args.device,
                                      voice=args.voice, reference_id=args.reference_id,
                                      title=args.title)
                from ..local_output import refresh_report_video_entry
                player = refresh_report_video_entry(args.deck, Path(result["video_path"]),
                                                    context.data_dir,
                                                    config=context.config.output,
                                                    title=result["title"])
                if player:
                    result["report_video_path"] = str(player)
            case "prepare":
                if args.review is None:
                    from ..news_slides import review_candidates

                    result = review_candidates(
                        read_json_object(args.report, "Report") if args.report else None,
                        read_json_object(args.index, "Index"), args.max_news, context.data_dir)
                    if not result["eligible_count"]:
                        result["next_action"] = result["message"]
                        print_json(result)
                        return 0
                    result["status"] = "review_required"
                    result["next_action"] = ("Review candidates, save decisions, then "
                                             "prepare --review REVIEW.json")
                    print_json(result)
                    return 0
                decisions = read_json_object(args.review, "Candidate review")
                if "selected_event_ids" not in decisions:
                    raise ValueError("Candidate review requires selected_event_ids")
                result = prepare_slides(
                    args.report, args.index, context.data_dir,
                    language=args.language or (context.config.output.language
                                               if args.report is None else None),
                    reuse_plan=args.reuse_plan,
                    min_importance=args.min_importance, item_ids=args.item_id,
                    max_news=args.max_news, exclude_event_ids=args.exclude_event_id,
                    batch_size=args.batch_size, max_input_tokens=args.max_input_tokens,
                    max_output_tokens=args.max_output_tokens,
                    config=context.config,
                    review=decisions,
                )
            case "submit":
                if not args.plan and not args.check_only:
                    if not args.packet or not args.input:
                        raise ValueError("--packet and --input are required")
                    result = submit_slides(args.packet, read_json_object(args.input, "Slide draft"),
                                           context.data_dir)
                else:
                    result = submit_slide_batches(
                        context.data_dir, plan_path=args.plan, draft_dir=args.draft_dir,
                        packet_path=args.packet, input_path=args.input, check_only=args.check_only,
                        skip_batch=args.skip_batch,
                    )
                    print_json(result)
                    return 1 if result["invalid"] else 0
            case "status":
                result = slides_status(args.plan, context.data_dir)
            case "prefetch-images":
                from ..news_slides import prefetch_slide_images

                result = prefetch_slide_images(args.plan, context.data_dir,
                                               media_config=context.config.media,
                                               refresh=args.refresh)
            case "render":
                result = render_slides(args.plan, context.data_dir,
                                       refresh_images=not args.offline,
                                       media_config=context.config.media)
        print_json({"artifact_path": str(result)} if isinstance(result, Path) else result)
        return 0
    except (ValueError, KeyError, OSError, RuntimeError, HTTPError) as exc:
        print_json({"status": "rejected", "error": str(exc)})
        return 1


def submit_slide_batches(data_dir: Path, *, plan_path: Path | None = None,
                         draft_dir: Path | None = None, packet_path: Path | None = None,
                         input_path: Path | None = None, check_only: bool = False,
                         skip_batch: Collection[str] = ()) -> dict:
    """处理：一次读取各份草稿，逐批预检或验证并提交，共享本轮核对的父链。
    输入：单批或计划路径、草稿目录及数据根。
    输出：已接受、待处理和无效批次，以及各项路径与错误。
    """
    from ..narrative_store import ArtifactReader

    reader = ArtifactReader(data_dir)
    skipped = set(skip_batch)
    if skipped and not plan_path:
        raise ValueError("--skip-batch requires --plan")
    if plan_path:
        if not draft_dir or packet_path or input_path:
            raise ValueError("--plan requires --draft-dir and excludes --packet/--input")
        plan = reader.load(plan_path, kind="slides-plan")
        packets = slide_batch_paths(plan_path, "packet")
        entries = []
        for number in range(1, len(plan["payload"]["batches"]) + 1):
            packet = packets.get(str(number))
            if packet is None:
                raise ValueError(f"Missing packet for batch {number}")
            draft = draft_dir / f"batch-{number}-draft.json"
            legacy = draft_dir / f"slides-draft-{number}.json"
            entries.append((number, packet, draft if draft.is_file() or not legacy.is_file()
                            else legacy))
    else:
        if not packet_path or not input_path or draft_dir:
            raise ValueError("--packet and --input are required")
        packet = reader.load(packet_path)
        entries = [(packet["payload"]["batch_id"], packet_path, input_path)]
    rows, already_accepted, submitted = [], [], []
    for number, packet, draft_path in entries:
        row = {"batch_id": number, "packet_path": str(packet), "draft_path": str(draft_path),
               "expected_path": str(packet.parent / f"slides-result-{number}-r1.json")}
        rows.append(row)
        try:
            existing = min(packet.parent.glob(f"slides-result-{number}-r*.json"), default=None)
            use_saved = existing is not None and (plan_path is not None or not draft_path.is_file())
            if not use_saved and (str(number) in skipped or str(packet) in skipped):
                row.update(errors=[], in_flight=True)
                continue
            draft = None if use_saved else read_json_object(draft_path, "Slide draft")
            if plan_path:
                packet_record = reader.load(packet, kind=f"slides-packet-{number}")
                if reader.parent_path(packet_record, "plan") != plan_path.resolve():
                    raise ValueError("Batch belongs to another slide plan")
            if use_saved:
                accepted_record = reader.load(existing, kind=f"slides-result-{number}")
                if reader.parent_path(accepted_record, "packet") != packet.resolve():
                    raise ValueError("Accepted batch belongs to another packet")
                row["accepted_path"] = str(existing)
                row["expected_path"] = str(existing)
                row["errors"] = []
                already_accepted.append(str(existing))
            elif check_only:
                row["errors"] = check_slides(packet, draft, data_dir, reader=reader)
            else:
                # 传入同一份草稿；提交只验一次，锁内重新绑定该版本写作包。
                path = submit_slides(packet, draft, data_dir, reader=reader)
                row.update(accepted_path=str(path), errors=[])
                submitted.append(str(path))
        except SlideDraftError as exc:
            row["errors"] = exc.errors
        except (ValueError, KeyError, OSError, RuntimeError) as exc:
            row["errors"] = [str(exc)]
    return batch_submission_result(rows, already_accepted + submitted, check_only)
