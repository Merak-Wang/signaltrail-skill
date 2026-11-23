"""Resolve the selected command without initializing unrelated pipeline stages."""

from argparse import Namespace
from functools import partial
from importlib import import_module

from .common import CommandContext
from .parser import build_parser


def dispatch(module: str, command: str, args: Namespace, context: CommandContext) -> int:
    """处理：在执行时载入命令所属模块。
    输入：命令组、已解析参数和本次运行上下文。
    输出：原处理函数返回的退出码。
    """
    handlers = import_module(f".{module}", __name__)
    return getattr(handlers, "handle_" + command.replace("-", "_"))(args, context)


_ROUTES: dict[str, tuple[str, str]] = {}
PARSER = build_parser(_ROUTES)
_ROUTE_HANDLERS = {route: partial(dispatch, *route) for route in set(_ROUTES.values())}
HANDLERS = {name: _ROUTE_HANDLERS[route] for name, route in _ROUTES.items()}
