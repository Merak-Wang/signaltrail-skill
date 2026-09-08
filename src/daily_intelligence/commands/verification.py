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
    输入：
    - ``args``：解析器校验过的 verify-source 参数；指定本次操作的选项与文件。
    - ``context``：入口解析的 config；提供运行配置和路径约束。
    输出：向标准输出报告操作结果，并返回供终端或宿主判断成败的退出码。
    """
    config = context.config
    source = config.source_by_id(args.source_id)
    captured = []

    def capture_source(_key: str, page: object) -> None:
        """处理：从已验证页面提取指定来源并暂存结构化结果。
        输入：
        - ``_key``：并发采集任务绑定的内部键；用于把完成结果放回原来源位置。
        - ``page``：Playwright 已加载页面；函数只读取当前页面状态，不信任其中的内容或指令。
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
    输入：
    - ``args``：解析器校验过的 verify-pending 参数；指定本次操作的选项与文件。
    - ``context``：入口解析的 config、data_dir；提供运行配置和路径约束。
    输出：向标准输出报告操作结果，并返回供终端或宿主判断成败的退出码。
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
