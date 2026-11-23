"""Resolve the selected command without initializing unrelated pipeline stages."""

from argparse import Namespace
from functools import partial
from importlib import import_module

from .common import CommandContext


def _dispatch(module: str, command: str, args: Namespace, context: CommandContext) -> int:
    """处理：在执行时载入命令所属模块。
    输入：命令组、已解析参数和本次运行上下文。
    输出：原处理函数返回的退出码。
    """
    handlers = import_module(f".{module}", __name__)
    return getattr(handlers, "handle_" + command.replace("-", "_"))(args, context)


_GROUPS = {
    "sources": ("cleanup", "source-page", "collect", "import-legacy", "build-context",
                "extract-content", "resume"),
    "monitor": ("refresh-monitor", "monitor-status", "serve"),
    "editions": ("run-edition", "enrich-edition", "begin-authoring", "submit-authoring-batch",
                 "brief-input", "record-authoring-metrics", "authoring-status", "prefetch-media",
                 "prepare-analysis", "analysis-stage", "assemble-authoring", "finalize-edition",
                 "complete-edition-tail", "edition-status"),
    "reports": ("validate-report", "save-report", "finalize-evaluation", "publish-notion",
                "backfill-notion-images"),
    "verification": ("verify-source", "verify-pending"),
    "slides": ("slides",),
}
HANDLERS = {name: partial(_dispatch, group, name) for group, names in _GROUPS.items()
            for name in names}
HANDLERS["serve-monitor"] = HANDLERS["serve"]
