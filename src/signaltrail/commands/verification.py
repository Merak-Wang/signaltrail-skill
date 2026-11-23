"""CLI handlers for verification. Business rules stay in the domain modules."""

from __future__ import annotations

import argparse

from playwright.sync_api import sync_playwright

from ..config import (
    resolve_browser_channel,
    resolve_profile_dir,
)
from ..runtime import require_data_root_path
from ..verification import (
    capture_verified_page,
    run_pending_verification,
    wait_for_visible_verification,
)
from .common import CommandContext, print_json


def handle_verify_source(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：打开单个来源并提取人工验证后的内容。
    输入：已解析的命令选项、当前命令的运行上下文。
    输出：终端结果及供宿主判断成败的退出码。
    """
    config = context.config
    source = config.source_by_id(args.source_id)
    captured = []

    def capture_source(_key: str, page: object) -> None:
        """处理：从已验证页面提取指定来源并暂存结构化结果。
        输入：已加载的 Playwright 页面。
        - ``_key``：并发采集任务绑定的内部键；用于把完成结果放回原来源位置。
        输出：不返回新数据；完成“从已验证页面提取指定来源并暂存结构化结果”，
          副作用限于该处理声明的受控对象或产物。
        """
        captured.append(capture_verified_page(page, source, config))

    profile = resolve_profile_dir(config, args.profile_dir)
    profile.mkdir(parents=True, exist_ok=True)
    channel = resolve_browser_channel(config, args.browser_channel)
    with sync_playwright() as playwright:
        kwargs = {
            "user_data_dir": str(profile),
            "headless": False,
            "locale": "en-US",
            "timezone_id": config.timezone,
            "viewport": {"width": 1440, "height": 1000},
        }
        if channel:
            kwargs["channel"] = channel
        context = playwright.chromium.launch_persistent_context(**kwargs)
        page = context.new_page()
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
        context.close()
    if captured:
        results[source.id]["items_captured"] = len(captured[0].items)
    print_json(results[source.id], indent=None)
    return 1 if results[source.id].get("required") or not captured else 0


def handle_verify_pending(args: argparse.Namespace, context: CommandContext) -> int:
    """处理：处理索引中待人工验证的来源队列。
    输入：已解析的命令选项、当前命令的运行上下文。
    输出：终端结果及供宿主判断成败的退出码。
    """
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
