"""CLI entry point: configuration, data-root binding, and dispatch."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

from .commands import HANDLERS
from .commands.common import CommandContext, print_json
from .commands.parser import build_parser as build_parser
from .config import load_config, resolve_data_dir, resolve_hermes_home, validate_output_config
from .runtime import bind_data_root, load_bound_data_root
from .verification import (
    capture_verified_page,
    pending_verification_pages,
    run_pending_verification,
    update_verification_portal,
    wait_for_clicked_verifications,
    wait_for_visible_verification,
    write_verification_queue,
)

__all__ = [
    "build_parser",
    "capture_verified_page",
    "pending_verification_pages",
    "run_pending_verification",
    "update_verification_portal",
    "wait_for_clicked_verifications",
    "wait_for_visible_verification",
    "write_verification_queue",
]


def load_hermes_environment() -> Path:
    """处理：从 Hermes 环境文件补充尚未设置的进程变量。
    输入：
    - 无显式业务参数：按 HERMES_HOME 定位 .env，读取其中变量并保留当前进程已有值。
    输出：已尝试加载的 .env 路径；现有进程变量保留优先级。
    """
    env_path = resolve_hermes_home() / ".env"
    load_dotenv(env_path, override=False)
    return env_path


def main(argv: list[str] | None = None) -> int:
    """处理：解析命令行参数并执行对应入口。
    输入：
    - ``argv``：命令行传入的参数序列；None 表示读取当前进程的 sys.argv。
    输出：进程退出码；0 表示检查通过，非 0 表示存在已输出的错误。
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    load_hermes_environment()
    config = load_config(args.config, timezone=args.timezone)
    if language := getattr(args, "language", None):
        config.output.language = language
        validate_output_config(config.output)
    adopting_data_root = args.command == "data-root" and args.action == "adopt"
    data_dir = resolve_data_dir(args.data_dir, allow_conflict=adopting_data_root)
    hermes_home = resolve_hermes_home()

    if args.command == "data-root":
        if args.action == "status":
            bound = load_bound_data_root(hermes_home)
            print_json(
                {
                    "status": "bound" if bound else "unbound",
                    "data_root": str(bound or data_dir),
                    "resolved_from_current_configuration": str(data_dir),
                }
            )
            return 0
        output = bind_data_root(
            data_dir,
            hermes_home,
            adopt=True,
            timezone=config.timezone,
        )
        print_json(output)
        return 0

    bind_data_root(data_dir, hermes_home, timezone=config.timezone)
    data_dir.mkdir(parents=True, exist_ok=True)

    context = CommandContext(config=config, data_dir=data_dir, parser=parser)
    return HANDLERS[args.command](args, context)


if __name__ == "__main__":
    raise SystemExit(main())
