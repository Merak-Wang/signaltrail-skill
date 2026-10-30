"""CLI entry point: configuration, data-root binding, and dispatch."""

from __future__ import annotations

from .commands import HANDLERS
from .commands.common import CommandContext, print_json
from .commands.parser import build_parser as build_parser
from .config import (
    load_config,
    resolve_data_dir,
    resolve_signaltrail_home,
    validate_output_config,
)
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


def main(argv: list[str] | None = None) -> int:
    """处理：解析命令行参数并执行对应入口。
    输入：
    - ``argv``：命令行传入的参数序列；None 表示读取当前进程的 sys.argv。
    输出：进程退出码；0 表示检查通过，非 0 表示存在已输出的错误。
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(args.config, timezone=args.timezone)
    if language := getattr(args, "language", None):
        config.output.language = language
        validate_output_config(config.output)
    adopting_data_root = args.command == "data-root" and args.action == "adopt"
    data_dir = resolve_data_dir(args.data_dir, allow_conflict=adopting_data_root)
    app_home = resolve_signaltrail_home()

    if args.command == "data-root":
        if args.action == "status":
            bound = load_bound_data_root(app_home)
            print_json(
                {
                    "status": "bound" if bound else "default",
                    "data_root": str(bound or data_dir),
                    **({"resolved_from_current_configuration": str(data_dir)}
                       if bound and bound != data_dir else {}),
                }
            )
            return 0
        output = bind_data_root(
            data_dir,
            app_home,
            adopt=True,
            timezone=config.timezone,
        )
        print_json(output)
        return 0

    data_dir.mkdir(parents=True, exist_ok=True)

    context = CommandContext(config=config, data_dir=data_dir, parser=parser, compact=args.compact)
    return HANDLERS[args.command](args, context)


if __name__ == "__main__":
    raise SystemExit(main())
