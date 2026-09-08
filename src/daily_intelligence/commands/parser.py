"""Command names, options, defaults, and compatibility aliases."""

import argparse
from pathlib import Path


def _common_parser() -> argparse.ArgumentParser:
    """处理：创建所有 CLI 子命令共享的参数解析器。
    输入：
    - 无显式业务参数：不读取业务数据；仅使用本模块声明的通用命令行选项和帮助文本。
    输出：带配置路径、数据根和时区选项的解析器；供子命令注册使用。
    """
    parser = argparse.ArgumentParser(prog="signaltrail")
    parser.add_argument("--config", type=Path, help="Path to sources.yaml")
    parser.add_argument("--data-dir", type=Path, help="Runtime data directory")
    parser.add_argument("--timezone", help="IANA timezone overriding sources.yaml")
    return parser


def build_parser() -> argparse.ArgumentParser:
    """处理：构建命令行参数解析器。
    输入：
    - 无显式业务参数：不读取业务数据；按本模块注册的子命令、参数和默认入口构建解析器。
    输出：完整命令树；入口用它校验参数并选择命令处理函数。
    """
    parser = _common_parser()
    sub = parser.add_subparsers(dest="command", required=True)

    data_root = sub.add_parser(
        "data-root",
        help="Show or deliberately adopt the one canonical SignalTrail data root",
    )
    data_root.add_argument("action", choices=["status", "adopt"])

    collect = sub.add_parser("collect", help="Collect source indexes")
    collect.add_argument("--edition", choices=["morning", "evening"], required=True)
    collect.add_argument("--headed", action="store_true")
    collect.add_argument("--profile-dir", type=Path)
    collect.add_argument("--browser-channel")
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
        help="Serve the read-only local intelligence desk",
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
        help="Refresh in the background at this interval; zero keeps the server read-only",
    )

    imported = sub.add_parser("import-legacy", help="Import the existing browser-link JSON")
    imported.add_argument("input", type=Path)
    imported.add_argument("--edition", default="imported")

    context = sub.add_parser("build-context", help="Build compact continuity context")
    context.add_argument("--index", type=Path, required=True)
    context.add_argument("--edition", choices=["morning", "evening"], required=True)
    context.add_argument("--language", choices=["zh-CN", "en"])

    content = sub.add_parser("extract-content", help="Fetch selected article bodies")
    content.add_argument("--index", type=Path, required=True)
    content.add_argument("--item-id", action="append", required=True)
    content.add_argument(
        "--max-items",
        type=int,
        help="Maximum selected bodies to fetch; defaults to the configured hard cap (12)",
    )
    content.add_argument("--headed", action="store_true")
    content.add_argument("--profile-dir", type=Path)
    content.add_argument("--browser-channel")

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
    verify.add_argument("--profile-dir", type=Path)
    verify.add_argument("--browser-channel")
    verify.add_argument("--timeout-seconds", type=int, default=300)

    verify_pending = sub.add_parser(
        "verify-pending",
        help="Open one Edge queue for failed/challenged links and capture clicked pages",
    )
    verify_pending.add_argument("--index", type=Path, required=True)
    verify_pending.add_argument("--profile-dir", type=Path)
    verify_pending.add_argument("--browser-channel")
    verify_pending.add_argument("--timeout-seconds", type=int, default=300)

    resume = sub.add_parser("resume", help="Retry challenged or failed sources")
    resume.add_argument("--index", type=Path, required=True)
    resume.add_argument("--headed", action="store_true")
    resume.add_argument("--profile-dir", type=Path)
    resume.add_argument("--browser-channel")

    source_page = sub.add_parser(
        "source-page",
        help="List, approve, or remove Agent-discovered index pages",
    )
    source_page.add_argument("action", choices=["list", "add", "remove"])
    source_page.add_argument("--source")
    source_page.add_argument("--url")
    source_page.add_argument("--reason", default="Agent judged this page relevant")

    run = sub.add_parser("run-edition", help="Prepare an edition through authoring context")
    run.add_argument("--edition", choices=["morning", "evening"], required=True)
    run.add_argument("--language", choices=["zh-CN", "en"])
    run.add_argument("--headed", action="store_true")
    run.add_argument("--profile-dir", type=Path)
    run.add_argument("--browser-channel")
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

    enrich = sub.add_parser(
        "enrich-edition",
        help="Fetch selected bodies and refresh an edition context",
    )
    enrich.add_argument("--run", type=Path, required=True)
    enrich.add_argument("--item-id", action="append", default=[])
    enrich.add_argument(
        "--max-items",
        type=int,
        help="Maximum selected bodies to fetch; defaults to the configured hard cap (12)",
    )
    enrich.add_argument("--headed", action="store_true")
    enrich.add_argument("--profile-dir", type=Path)
    enrich.add_argument("--browser-channel")

    begin = sub.add_parser(
        "begin-authoring",
        help="Start one timed authoring session and assign deterministic batch result paths",
    )
    begin.add_argument("--run", type=Path, required=True)

    submit = sub.add_parser(
        "submit-authoring-batch",
        help="Validate and accept one assigned model-authored brief batch",
    )
    submit.add_argument("--run", type=Path, required=True)
    submit.add_argument("--batch-id", required=True)
    submit.add_argument("--result", type=Path, required=True)

    metrics = sub.add_parser(
        "record-authoring-metrics",
        help="Validate and retain bounded harness-worker duration/API/token metrics",
    )
    metrics.add_argument("--run", type=Path, required=True)
    metrics.add_argument("--metrics", type=Path, required=True)

    authoring_status = sub.add_parser(
        "authoring-status",
        help="Show completed batches, timings, and the analysis deadline",
    )
    authoring_status.add_argument("--run", type=Path, required=True)

    prefetch_media = sub.add_parser(
        "prefetch-media",
        help="Warm report image cache while background brief batches are running",
    )
    prefetch_media.add_argument("--run", type=Path, required=True)

    prepare_analysis = sub.add_parser(
        "prepare-analysis",
        help="Merge accepted brief batches and write a compact analysis packet",
    )
    prepare_analysis.add_argument("--run", type=Path, required=True)
    prepare_analysis.add_argument(
        "--allow-degraded",
        action="store_true",
        help="After the analysis deadline, continue with completed batches and cache hits",
    )

    assemble = sub.add_parser(
        "assemble-authoring",
        help="Merge the compact analysis payload into the Python-built schema 2.0 draft",
    )
    assemble.add_argument("--run", type=Path, required=True)
    assemble.add_argument("--analysis", type=Path, required=True)

    finalize = sub.add_parser(
        "finalize-edition",
        help=(
            "Validate and persist local JSON/Markdown/HTML/PDF, then optionally publish to Notion"
        ),
    )
    finalize.add_argument("--run", type=Path, required=True)
    finalize.add_argument("--report", type=Path, required=True)
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
        help="Return after local HTML; generate PDF, publish Notion, and schedule evaluation later",
    )

    tail = sub.add_parser(
        "complete-edition-tail",
        help="Finish deferred PDF/Notion work and schedule independent evaluation",
    )
    tail.add_argument("--run", type=Path, required=True)
    tail.add_argument("--publish", action="store_true")
    tail.add_argument("--notion-config", type=Path)

    save = sub.add_parser(
        "save-report", help="Persist JSON/Markdown and configured local reading formats"
    )
    save.add_argument("report", type=Path)
    save.add_argument("--index", type=Path, required=True)

    evaluation = sub.add_parser(
        "finalize-evaluation",
        help="Persist a post-publication independent evaluation and optionally append it to Notion",
    )
    evaluation.add_argument("--report", type=Path, required=True)
    evaluation.add_argument("--evaluation", type=Path, required=True)
    evaluation.add_argument("--publish", action="store_true")
    evaluation.add_argument("--notion-config", type=Path)

    return parser
