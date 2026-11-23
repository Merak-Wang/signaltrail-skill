"""Command names, options, defaults, and compatibility aliases."""

import argparse
from pathlib import Path


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
    review = stages.add_parser("review", help="Review today's candidates before writing narration")
    review.add_argument("--parts-dir", type=Path,
                        help="Save complete compact review as ordered small input parts")
    review.add_argument("--report", type=Path)
    review.add_argument("--index", type=Path, required=True)
    review.add_argument("--max-news", type=int, default=50)
    review.add_argument("--model-input", action="store_true",
                        help="Emit full-pool columnar review input without repeated metadata")
    prepare.add_argument("--review", type=Path,
                         help="Model candidate selection and merge decisions")
    prepare.add_argument("--report", type=Path)
    prepare.add_argument("--index", type=Path, required=True)
    prepare.add_argument("--language", choices=("zh-CN", "en"))
    prepare.add_argument("--reuse-plan", type=Path)
    prepare.add_argument("--item-id", action="append")
    prepare.add_argument("--exclude-event-id", action="append",
                         help="Exclude an event before selecting the top stories; repeatable")
    prepare.add_argument("--min-importance", type=int, default=0,
                         help="Optional importance cutoff; index mode requires supplied scores")
    prepare.add_argument("--max-news", type=int, default=50,
                         help="Maximum stories by report importance or index rank (default: 50)")
    prepare.add_argument("--batch-size", type=int, default=5)
    prepare.add_argument("--max-input-tokens", type=int,
                         help="Hard input limit; default targets 64000 and expands for one article")
    prepare.add_argument("--max-output-tokens", type=int, default=4000)
    author_input = stages.add_parser("input", help="Read one complete, compact writing input")
    author_input.add_argument("--packet", type=Path, required=True)
    image_prefetch = stages.add_parser("prefetch-images",
                                       help="Fetch slide images during authoring")
    image_prefetch.add_argument("--plan", type=Path, required=True)
    image_prefetch.add_argument("--refresh", action="store_true")
    submit = stages.add_parser("submit", help="Accept and reuse one authored batch")
    submit.add_argument("--packet", type=Path)
    submit.add_argument("--input", type=Path)
    submit.add_argument("--plan", type=Path, help="Check all batches of this plan")
    submit.add_argument("--draft-dir", type=Path, help="Directory of batch-N-draft.json files")
    submit.add_argument("--skip-batch", action="append", default=[],
                        help="With --plan, skip active batch IDs or packet paths")
    submit.add_argument("--check-only", action="store_true", help="Validate without saving results")
    video = stages.add_parser("video", help="Export locally narrated MP4 from a saved deck")
    video.add_argument("--title", help="Topic-specific title for this video")
    video.add_argument("--deck", type=Path, required=True)
    speech = stages.add_parser("prefetch-speech", help="Warm audio from accepted slide batches")
    speech.add_argument("--plan", type=Path, required=True)
    speech.add_argument("--follow-seconds", type=int, default=0,
                        help="Watch for additional accepted batches for up to this many seconds")
    for command in (video, speech):
        command.add_argument("--voice")
        command.add_argument("--reference-id")
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--model-dir", type=Path)
        command.add_argument("--tts-executable", type=Path)
        command.add_argument("--ffmpeg")
        command.add_argument("--threads", type=int, default=2)
        command.add_argument("--device", choices=("auto", "cuda", "vulkan", "metal", "cpu"))
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


def _add_browser_options(command: argparse.ArgumentParser, *, allow_headed: bool = True) -> None:
    """处理：为采集或人工验证注册浏览器选项。
    输入：对应命令的解析器；自动采集可选择显示窗口。
    输出：供浏览器启动使用的配置目录、通道及可选窗口开关。
    """
    if allow_headed:
        command.add_argument("--headed", action="store_true")
    command.add_argument("--profile-dir", type=Path)
    command.add_argument("--browser-channel")


def build_parser() -> argparse.ArgumentParser:
    """处理：构建命令行参数解析器。
    输入：
    - 无显式业务参数：不读取业务数据；按本模块注册的子命令、参数和默认入口构建解析器。
    输出：完整命令树；入口用它校验参数并选择命令处理函数。
    """
    parser = argparse.ArgumentParser(prog="signaltrail")
    parser.add_argument("--config", type=Path, help="Path to sources.yaml")
    parser.add_argument("--data-dir", type=Path, help="Runtime data directory")
    parser.add_argument("--timezone", help="IANA timezone overriding sources.yaml")
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Print short edition receipts; full results remain in saved artifacts",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def edition_command(name: str, *, help: str) -> argparse.ArgumentParser:
        """处理：在版次子命令中统一登记必填运行清单。
        输入：子命令名称和终端帮助。
        输出：已绑定运行路径参数的子解析器。
        """
        command = sub.add_parser(name, help=help)
        command.add_argument("--run", type=Path, required=True)
        return command

    add_slides_parser(sub)

    data_root = sub.add_parser(
        "data-root",
        help="Show or deliberately adopt the one canonical SignalTrail data root",
    )
    data_root.add_argument("action", choices=["status", "adopt"])

    cleanup = sub.add_parser("cleanup", help="Recycle collection files older than seven days")
    cleanup.add_argument("--days", type=int, default=7)
    cleanup.add_argument("--apply", action="store_true",
                         help="Move expired files to OS recycle bin")

    collect = sub.add_parser("collect", help="Collect source indexes")
    collect.add_argument("--edition", choices=["daily", "morning", "evening"], default="daily")
    _add_browser_options(collect)
    collect.add_argument("--source", action="append", default=[])

    refresh = sub.add_parser(
        "refresh-monitor",
        help="Refresh the zero-model-token local news stream and story clusters",
    )
    refresh.add_argument("--source", action="append", default=[])
    refresh.add_argument("--bundle", action="append", default=[])
    refresh.add_argument(
        "--core-only",
        action="store_true",
        help="Refresh only the 32 newspaper sources, excluding discovery bundles",
    )
    refresh.add_argument(
        "--force",
        action="store_true",
        help="Ignore feed freshness intervals and perform conditional requests now",
    )
    refresh.add_argument(
        "--no-html-fallback",
        action="store_true",
        help="Use RSS/Atom only for this refresh",
    )

    sub.add_parser(
        "monitor-status",
        help="Show the latest local monitor summary without refreshing",
    )

    serve = sub.add_parser(
        "serve",
        aliases=["serve-monitor"],
        help="Serve the personal news platform with reports, events and source status",
    )
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--open", dest="open_browser", action="store_true")
    serve.add_argument(
        "--allow-remote",
        action="store_true",
        help="Allow binding beyond localhost on a trusted network",
    )
    serve.add_argument(
        "--refresh-minutes",
        type=int,
        default=0,
        help="Refresh news every N minutes; default: 0 (read-only, no automatic collection)",
    )

    imported = sub.add_parser("import-legacy", help="Import the existing browser-link JSON")
    imported.add_argument("input", type=Path)
    imported.add_argument("--edition", default="imported")

    context = sub.add_parser("build-context", help="Build compact continuity context")
    context.add_argument("--index", type=Path, required=True)
    context.add_argument("--edition", choices=["daily", "morning", "evening"], default="daily")
    context.add_argument("--language", choices=["zh-CN", "en"])

    content = sub.add_parser("extract-content", help="Fetch selected article bodies")
    content.add_argument("--index", type=Path, required=True)
    content.add_argument("--item-id", action="append", required=True)
    content.add_argument(
        "--max-items",
        type=int,
        help="Maximum selected bodies to fetch; defaults to the configured hard cap (12)",
    )
    _add_browser_options(content)

    validate = sub.add_parser("validate-report", help="Validate a structured report")
    validate.add_argument("report", type=Path)
    validate.add_argument("--index", type=Path)
    validate.add_argument(
        "--run",
        type=Path,
        help="Use run-owned deadline coverage targets for a degraded authoring result",
    )

    publish = sub.add_parser("publish-notion", help="Publish or append report to Notion")
    publish.add_argument("report", type=Path)
    publish.add_argument(
        "--republish",
        "--force",
        dest="force",
        action="store_true",
        help="Bypass duplicate-publication protection; report validation still applies",
    )
    publish.add_argument("--notion-config", type=Path)

    backfill_images = sub.add_parser(
        "backfill-notion-images",
        help="Add missing report images to existing Notion story blocks",
    )
    backfill_images.add_argument("report", type=Path)
    backfill_images.add_argument("--notion-config", type=Path)

    verify = sub.add_parser("verify-source", help="Open a source for manual verification")
    verify.add_argument("source_id")
    _add_browser_options(verify, allow_headed=False)
    verify.add_argument("--timeout-seconds", type=int, default=300)

    verify_pending = sub.add_parser(
        "verify-pending",
        help="Open one Edge queue for failed/challenged links and capture clicked pages",
    )
    verify_pending.add_argument("--index", type=Path, required=True)
    _add_browser_options(verify_pending, allow_headed=False)
    verify_pending.add_argument("--timeout-seconds", type=int, default=300)

    resume = sub.add_parser("resume", help="Retry challenged or failed sources")
    resume.add_argument("--index", type=Path, required=True)
    _add_browser_options(resume)

    source_page = sub.add_parser(
        "source-page",
        help="List, approve, or remove Agent-discovered index pages",
    )
    source_page.add_argument("action", choices=["list", "add", "remove"])
    source_page.add_argument("--source")
    source_page.add_argument("--url")
    source_page.add_argument("--reason", default="Agent judged this page relevant")

    run = sub.add_parser("run-edition", help="Prepare an edition through authoring context")
    run.add_argument("--edition", choices=["daily", "morning", "evening"], default="daily")
    run.add_argument("--language", choices=["zh-CN", "en"])
    _add_browser_options(run)
    run.add_argument("--restart", action="store_true")
    verification_mode = run.add_mutually_exclusive_group()
    verification_mode.add_argument(
        "--open-verification",
        dest="open_verification",
        action="store_true",
        default=False,
        help=(
            "Explicitly open the connected Edge verification queue after collection; "
            "this waits until the queue completes or times out"
        ),
    )
    verification_mode.add_argument(
        "--unattended",
        dest="open_verification",
        action="store_false",
        help=("Compatibility flag that keeps verification windows disabled (already the default)"),
    )
    run.add_argument(
        "--verification-timeout-seconds",
        type=int,
        default=180,
        help="How long an explicitly requested verification queue remains active",
    )

    enrich = edition_command(
        "enrich-edition",
        help="Fetch selected bodies and refresh an edition context",
    )
    enrich.add_argument("--item-id", action="append", default=[])
    enrich.add_argument("--slides-candidates", action="store_true",
                        help="Enrich today's slide candidates before report authoring")
    enrich.add_argument("--all-slide-candidates", action="store_true",
                        help="Continue in bounded batches until all current candidates are handled")
    enrich.add_argument(
        "--max-items",
        type=int,
        help="Maximum bodies per batch; slide candidates default to 100, otherwise configured cap",
    )
    _add_browser_options(enrich)

    begin = edition_command(
        "begin-authoring",
        help="Start one timed authoring session and assign deterministic batch result paths",
    )
    begin.add_argument("--refresh-context", action="store_true",
                       help="Rebuild authoring packets from the frozen index")

    submit = edition_command(
        "submit-authoring-batch",
        help="Validate and accept one assigned model-authored brief batch",
    )
    submit.add_argument("--batch-id")
    submit.add_argument("--result", type=Path)
    submit.add_argument("--all", action="store_true", help="Check all assigned drafts")
    submit.add_argument("--skip-batch", action="append", default=[],
                        help="With --all, skip active batch IDs or packet paths")
    submit.add_argument(
        "--check-only", action="store_true", help="Validate without writing receipts"
    )

    brief_input = sub.add_parser(
        "brief-input", help="Read one compact, complete brief writing input",
    )
    brief_input.add_argument("--packet", type=Path, required=True)
    brief_input.add_argument("--include-evidence", action="store_true",
                             help="Embed complete locally available text and tables")

    metrics = edition_command(
        "record-authoring-metrics",
        help="Validate and retain bounded harness-worker duration/API/token metrics",
    )
    metrics.add_argument("--metrics", type=Path, required=True)

    edition_command(
        "authoring-status",
        help="Show completed batches, timings, and the analysis deadline",
    )

    edition_command(
        "prefetch-media",
        help="Warm report image cache while background brief batches are running",
    )

    prepare_analysis = edition_command(
        "prepare-analysis",
        help="Merge accepted brief batches and write a compact analysis packet",
    )
    prepare_analysis.add_argument(
        "--parallel",
        action="store_true",
        help="Prepare staged selection, parallel domains, and synthesis",
    )
    analysis_stage = edition_command("analysis-stage", help="Advance staged analysis writing")
    analysis_stage.add_argument(
        "--stage", choices=["domains", "synthesis", "assemble"], required=True
    )
    prepare_analysis.add_argument(
        "--allow-degraded",
        action="store_true",
        help="After the analysis deadline, continue with completed batches and cache hits",
    )

    assemble = edition_command(
        "assemble-authoring",
        help="Merge the compact analysis payload into the Python-built schema 2.0 draft",
    )
    assemble.add_argument("--analysis", type=Path, required=True)

    finalize = edition_command(
        "finalize-edition",
        help=(
            "Validate and persist local JSON/Markdown/HTML/PDF, then optionally publish to Notion"
        ),
    )
    finalize.add_argument("--report", type=Path, required=True)
    finalize.add_argument("--slides-review", type=Path,
                          help="Reviewed daily slide candidate decisions")
    finalize.add_argument("--slides-reuse-plan", type=Path,
                          help="Reuse matching accepted narration from an existing slide plan")
    finalize.add_argument(
        "--slides-exclude-event-id",
        action="append",
        help="Exclude specified slide events before filling the story limit",
    )
    finalize.add_argument(
        "--slides-max-news",
        type=int,
        help="Maximum report stories to include in the visual stream (default: 50)",
    )
    finalize.add_argument(
        "--publish",
        action="store_true",
        help="Also publish the locally saved report to Notion",
    )
    finalize.add_argument(
        "--republish",
        "--force-publish",
        dest="force_publish",
        action="store_true",
        help="Republish an already recorded edition; never bypasses report validation",
    )
    finalize.add_argument("--notion-config", type=Path)
    finalize.add_argument(
        "--defer-tail",
        action="store_true",
        help="Return after local HTML; finish PDF and requested delivery/scoring later",
    )

    tail = edition_command(
        "complete-edition-tail",
        help="Finish deferred PDF/Notion work and any explicitly requested quality scoring",
    )
    tail.add_argument("--publish", action="store_true")
    tail.add_argument("--notion-config", type=Path)

    for delivery_command in (finalize, tail):
        delivery_command.add_argument(
            "--evaluate",
            action="store_true",
            help="Explicitly request independent quality scoring (off by default)",
        )
        delivery_command.add_argument(
            "--evaluation-backend",
            choices=("hermes", "external"),
            help="Evaluation backend when --evaluate is requested (defaults to external)",
        )

    edition_status = edition_command(
        "edition-status", help="Show whether the saved report and requested delivery are complete"
    )
    edition_status.add_argument(
        "--require-complete",
        action="store_true",
        help="Exit nonzero while any declared delivery step is pending",
    )

    save = sub.add_parser(
        "save-report", help="Persist JSON/Markdown and configured local reading formats"
    )
    save.add_argument("report", type=Path)
    save.add_argument("--index", type=Path, required=True)
    save.add_argument("--refresh-images", action="store_true",
                      help="Explicitly reselect images instead of preserving published attachments")

    evaluation = sub.add_parser(
        "finalize-evaluation",
        help="Persist a post-publication independent evaluation and optionally append it to Notion",
    )
    evaluation.add_argument("--report", type=Path, required=True)
    evaluation.add_argument("--evaluation", type=Path, required=True)
    evaluation.add_argument("--publish", action="store_true")
    evaluation.add_argument("--notion-config", type=Path)

    return parser
