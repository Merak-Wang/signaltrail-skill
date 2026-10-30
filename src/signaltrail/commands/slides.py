"""CLI entry points for budgeted news slides."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from httpx import HTTPError

from ..news_slides import check_slides, prepare_slides, render_slides, slides_status, submit_slides
from ..utils import read_json_object
from .common import CommandContext, print_json


def add_slides_parser(sub: argparse._SubParsersAction) -> None:
    """处理：注册图文流的准备、批次提交、进度和 HTML 生成命令。
    输入：主命令树；筛选与预算选项仅作用于独立图文产物。
    输出：slides 子命令，不改变既有日报命令的参数与默认输出。
    """
    parser = sub.add_parser(
        "slides", help="Build animated HTML news slides from an index or report"
    )
    stages = parser.add_subparsers(dest="action", required=True)
    prepare = stages.add_parser(
        "prepare", help="Select indexed or report news and split bounded batches"
    )
    prepare.add_argument("--report", type=Path)
    prepare.add_argument("--index", type=Path, required=True)
    prepare.add_argument("--language", choices=("zh-CN", "en"))
    prepare.add_argument("--reuse-plan", type=Path)
    prepare.add_argument("--item-id", action="append")
    prepare.add_argument("--exclude-event-id", action="append",
                         help="Exclude an event before selecting the top stories; repeatable")
    prepare.add_argument("--min-importance", type=int, default=0,
                         help="Optional importance cutoff; index mode requires supplied scores")
    prepare.add_argument("--max-news", type=int, default=30,
                         help="Maximum stories by report importance or index rank (default: 30)")
    prepare.add_argument("--batch-size", type=int, default=5)
    prepare.add_argument("--max-input-tokens", type=int,
                         help="Hard input limit; default targets 64000 and expands for one article")
    prepare.add_argument("--max-output-tokens", type=int, default=4000)
    submit = stages.add_parser("submit", help="Accept and reuse one authored batch")
    submit.add_argument("--packet", type=Path)
    submit.add_argument("--input", type=Path)
    submit.add_argument("--plan", type=Path, help="Check all batches of this plan")
    submit.add_argument("--draft-dir", type=Path, help="Directory of batch-N-draft.json files")
    submit.add_argument("--check-only", action="store_true", help="Validate without saving results")
    video = stages.add_parser("video", help="Export locally narrated MP4 from a saved deck")
    video.add_argument("--voice")
    video.add_argument("--reference-id")
    video.add_argument("--deck", type=Path, required=True)
    video.add_argument("--output", type=Path, required=True)
    video.add_argument("--model-dir", type=Path)
    video.add_argument("--tts-executable", type=Path)
    video.add_argument("--ffmpeg")
    video.add_argument("--threads", type=int, default=2)
    video.add_argument("--device", choices=("auto", "cuda", "vulkan", "metal", "cpu"))
    setup = stages.add_parser("video-setup", help="Prepare native TTS and video tools")
    setup.add_argument("--voice")
    setup.add_argument("--reference-id")
    setup.add_argument("--device", choices=("auto", "cuda", "vulkan", "metal", "cpu"))
    setup.add_argument("--proxy", help="Proxy URL for this initial download only")
    voice_setup = stages.add_parser("voice-setup", help="Import a portable local voice profile")
    voice_setup.add_argument("--profile", type=Path, required=True)
    voice_setup.add_argument("--default", action="store_true")
    for name in ("status", "render"):
        command = stages.add_parser(name)
        command.add_argument("--plan", type=Path, required=True)
        if name == "render":
            command.add_argument("--offline", action="store_true",
                                 help="Reuse saved images without fetching article pages")


def handle_slides(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：把显式图文操作派发到新闻分批与模板模块。
    输入：命令行路径、筛选条件和已绑定数据根。
    输出：图文或视频产物路径；video-setup 首次下载本地配音与编码工具。
    """
    try:
        match args.action:
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
            case "video":
                from ..slide_video import render_video
                result = render_video(args.deck, args.output, args.model_dir, context.data_dir,
                                      ffmpeg=args.ffmpeg, threads=args.threads,
                                      tts_executable=args.tts_executable, device=args.device,
                                      voice=args.voice, reference_id=args.reference_id)
                from ..local_output import refresh_report_video_entry
                player = refresh_report_video_entry(args.deck, Path(result["video_path"]),
                                                    context.data_dir,
                                                    config=context.config.output)
                if player:
                    result["report_video_path"] = str(player)
            case "prepare":
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
                )
            case "submit":
                if not args.plan and not args.check_only:
                    if not args.packet or not args.input:
                        raise ValueError("--packet and --input are required")
                    result = submit_slides(args.packet, read_json_object(args.input, "Slide draft"),
                                           context.data_dir)
                else:
                    result = _submit_many(args, context.data_dir)
                    print_json(result)
                    return 1 if result["invalid"] else 0
            case "status":
                result = slides_status(args.plan, context.data_dir)
            case "render":
                result = render_slides(args.plan, context.data_dir,
                                       refresh_images=not args.offline,
                                       media_config=context.config.media)
        print_json({"artifact_path": str(result)} if isinstance(result, Path) else result)
        return 0
    except (ValueError, KeyError, OSError, RuntimeError, HTTPError) as exc:
        print_json({"status": "rejected", "error": str(exc)})
        return 1


def _submit_many(args: argparse.Namespace, data_dir: Path) -> dict:
    """处理：先检查所有草稿，再逐项保存通过检查的批次。
    输入：单批或计划路径、草稿目录及数据根。
    输出：已接受、待处理和无效批次，以及各项路径与错误。
    """
    from ..narrative_store import load_artifact

    if args.plan:
        if not args.draft_dir or args.packet or args.input:
            raise ValueError("--plan requires --draft-dir and excludes --packet/--input")
        plan = load_artifact(args.plan, data_dir, kind="slides-plan")
        entries = []
        for number in range(1, len(plan["payload"]["batches"]) + 1):
            packets = sorted(path for path in args.plan.parent.glob(
                f"slides-packet-{number}-r*.json") if re.fullmatch(
                    rf"slides-packet-{number}-r\d+\.json", path.name))
            if not packets:
                raise ValueError(f"Missing packet for batch {number}")
            draft = args.draft_dir / f"batch-{number}-draft.json"
            legacy = args.draft_dir / f"slides-draft-{number}.json"
            entries.append((number, packets[0], draft if draft.is_file() or not legacy.is_file()
                            else legacy))
    else:
        if not args.packet or not args.input or args.draft_dir:
            raise ValueError("--packet and --input are required")
        packet = load_artifact(args.packet, data_dir)
        entries = [(packet["payload"]["batch_id"], args.packet, args.input)]
    rows = []
    for number, packet, draft_path in entries:
        row = {"batch_id": number, "packet_path": str(packet), "draft_path": str(draft_path),
               "expected_path": str(packet.parent / f"slides-result-{number}-r1.json")}
        try:
            existing = sorted(packet.parent.glob(f"slides-result-{number}-r*.json"))
            if existing and (args.plan or not draft_path.is_file()):
                accepted_record = load_artifact(existing[0], data_dir,
                                                kind=f"slides-result-{number}")
                from ..narrative_store import parent_path
                if parent_path(accepted_record, "packet", data_dir).resolve() != packet.resolve():
                    raise ValueError("Accepted batch belongs to another packet")
                row["accepted_path"] = str(existing[0])
                row["expected_path"] = str(existing[0])
                row["errors"] = []
            else:
                draft = read_json_object(draft_path, "Slide draft")
                row["errors"] = check_slides(packet, draft, data_dir)
        except (ValueError, KeyError, OSError, RuntimeError) as exc:
            row["errors"] = [str(exc)]
        rows.append(row)
    accepted = [row["accepted_path"] for row in rows if row.get("accepted_path")]
    if not args.check_only:
        for row in rows:
            if not row["errors"] and not row.get("accepted_path"):
                try:
                    path = submit_slides(Path(row["packet_path"]),
                        read_json_object(Path(row["draft_path"]), "Slide draft"), data_dir)
                    row["accepted_path"] = str(path)
                    accepted.append(str(path))
                except (ValueError, KeyError, OSError, RuntimeError) as exc:
                    row["errors"].append(str(exc))
    pending = [row["batch_id"] for row in rows if not row.get("accepted_path")]
    invalid = [row["batch_id"] for row in rows if row["errors"]]
    status = "partial" if invalid else "ready_to_submit" if pending else "ready"
    return {"status": status, "check_only": args.check_only, "accepted": accepted,
            "pending": pending, "invalid": invalid,
            "expected_paths": [row["expected_path"] for row in rows], "batches": rows}
