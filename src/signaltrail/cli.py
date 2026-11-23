"""CLI entry point: configuration, data-root binding, and dispatch."""

from __future__ import annotations

from .commands import HANDLERS, PARSER
from .commands.common import CommandContext, print_json
from .commands.parser import build_parser as build_parser
from .config import (
    load_config,
    resolve_data_dir,
    resolve_signaltrail_home,
    validate_output_config,
)
from .runtime import bind_data_root, load_bound_data_root

_VERIFICATION_EXPORTS = (
    "capture_verified_page",
    "pending_verification_pages",
    "run_pending_verification",
    "update_verification_portal",
    "wait_for_clicked_verifications",
    "wait_for_visible_verification",
    "write_verification_queue",
)
__all__ = ["build_parser", *_VERIFICATION_EXPORTS]


def __getattr__(name: str):
    """处理：首次导入旧版人工验证入口时才加载浏览器依赖。
    输入：外部调用者从 CLI 模块请求的导出名。
    输出：原验证函数，未知属性遵循 Python 模块访问语义。
    """
    if name in _VERIFICATION_EXPORTS:
        from . import verification

        return getattr(verification, name)
    raise AttributeError(name)


def main(argv: list[str] | None = None) -> int:
    """解析命令行参数并执行对应入口。
    输入：``argv``：命令行传入的参数序列；None 表示读取当前进程的 sys.argv。
    输出：进程退出码；0 表示检查通过，非 0 表示存在已输出的错误。
    """
    args = PARSER.parse_args(argv)
    # argparse 直接复用未传入的 append 默认列表，命令应拥有自己的副本。
    for name, value in vars(args).items():
        if isinstance(value, list):
            setattr(args, name, value.copy())
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

    context = CommandContext(config=config, data_dir=data_dir, parser=PARSER, compact=args.compact)
    return HANDLERS[args.command](args, context)


if __name__ == "__main__":
    raise SystemExit(main())
