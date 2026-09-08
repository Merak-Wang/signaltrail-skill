"""Explicit command dispatch. Every parser command has one handler."""

from argparse import Namespace
from collections.abc import Callable

from . import editions, monitor, reports, sources, verification
from .common import CommandContext

HANDLERS: dict[str, Callable[[Namespace, CommandContext], int]] = {
    "source-page": sources.handle_source_page,
    "collect": sources.handle_collect,
    "import-legacy": sources.handle_import_legacy,
    "build-context": sources.handle_build_context,
    "extract-content": sources.handle_extract_content,
    "resume": sources.handle_resume,
    "refresh-monitor": monitor.handle_refresh_monitor,
    "monitor-status": monitor.handle_monitor_status,
    "serve": monitor.handle_serve,
    "run-edition": editions.handle_run_edition,
    "enrich-edition": editions.handle_enrich_edition,
    "begin-authoring": editions.handle_begin_authoring,
    "submit-authoring-batch": editions.handle_submit_authoring_batch,
    "record-authoring-metrics": editions.handle_record_authoring_metrics,
    "authoring-status": editions.handle_authoring_status,
    "prefetch-media": editions.handle_prefetch_media,
    "prepare-analysis": editions.handle_prepare_analysis,
    "assemble-authoring": editions.handle_assemble_authoring,
    "finalize-edition": editions.handle_finalize_edition,
    "complete-edition-tail": editions.handle_complete_edition_tail,
    "validate-report": reports.handle_validate_report,
    "save-report": reports.handle_save_report,
    "finalize-evaluation": reports.handle_finalize_evaluation,
    "publish-notion": reports.handle_publish_notion,
    "backfill-notion-images": reports.handle_backfill_notion_images,
    "verify-source": verification.handle_verify_source,
    "verify-pending": verification.handle_verify_pending,
    "serve-monitor": monitor.handle_serve,
}
