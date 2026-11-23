"""CLI handlers for verification. Business rules stay in the domain modules."""

from __future__ import annotations

import argparse

from ..runtime import require_data_root_path
from ..verification import (
    capture_verified_page,
    open_verification_browser,
    run_pending_verification,
    wait_for_visible_verification,
)
from .common import CommandContext, print_json


def handle_verify_source(args: argparse.Namespace, context: CommandContext) -> int:
    """打开单个来源并提取人工验证后的内容。"""
    config = context.config
    source = config.source_by_id(args.source_id)
    captured = []

    def capture_source(_key: str, page: object) -> None:
        """从已验证页面提取指定来源并暂存结构化结果。
        输入：已加载的 Playwright 页面。
        - ``_key``：并发采集任务绑定的内部键；用于把完成结果放回原来源位置。
        """
        captured.append(capture_verified_page(page, source, config))

    with open_verification_browser(config, args.profile_dir, args.browser_channel) as browser:
        page = browser.new_page()
        response = page.goto(
            source.url,
            wait_until="domcontentloaded",
            timeout=config.browser.navigation_timeout_ms,
        )
        page.bring_to_front()
        print(
            "A visible browser is open. Complete legitimate verification; "
            "success is detected automatically. You may close the tab when finished."
        )
        results = wait_for_visible_verification(
            [(source.id, page, response.status if response else None)],
            args.timeout_seconds,
            on_verified=capture_source,
        )
    if captured:
        results[source.id]["items_captured"] = len(captured[0].items)
    print_json(results[source.id], indent=None)
    return 1 if results[source.id].get("required") or not captured else 0


def handle_verify_pending(args: argparse.Namespace, context: CommandContext) -> int:
    """处理索引中待人工验证的来源队列。"""
    config = context.config
    data_dir = context.data_dir
    index_path = require_data_root_path(args.index, data_dir, "Verification index")
    result = run_pending_verification(
        index_path,
        config,
        data_dir,
        profile_dir=args.profile_dir,
        browser_channel=args.browser_channel,
        timeout_seconds=args.timeout_seconds,
    )
    if result["status"] == "no_pending_pages":
        print("No failed or verification-required sources in the index")
        return 0
    print_json(result)
    return 0
