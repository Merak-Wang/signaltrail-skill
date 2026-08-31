from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from daily_intelligence.llm_usage import UsageLedger, ingest_hook_from_env

CommandHandler = Callable[[argparse.Namespace, Mapping[str, str]], dict[str, Any] | None]


class SafeArgumentParser(argparse.ArgumentParser):
    """处理：拒绝参数错误时回显可能误传入的回执或凭据。
    输入：
    - 无显式业务参数：构造参数沿用 argparse；本类只收紧非法参数的错误输出。
    输出：合法参数返回 Namespace；非法参数抛出固定 ValueError，由入口输出安全 JSON。
    """

    def error(self, _message: str) -> None:
        """处理：把 argparse 自带的含原值错误文本替换为固定异常。
        输入：
        - ``_message``：argparse 生成且可能包含用户原始参数的文本；不会读取或回显。
        输出：无正常返回；始终抛出不含参数值的 ValueError。
        """

        raise ValueError("invalid command arguments")


def build_parser() -> argparse.ArgumentParser:
    """处理：创建只公开本地安全计量操作的命令行解析规则。
    输入：
    - 无显式业务参数：命令行值由入口函数交给返回的解析器。
    输出：包含 start、hook、import、summary、finalize 子命令的解析器。
    """

    parser = SafeArgumentParser(
        prog="signaltrail-usage",
        description="Record and summarize local LLM usage without making model calls.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    start = subcommands.add_parser("start", help="Start an immutable usage task")
    _add_ledger_argument(start)
    start.add_argument("--agent", required=True)
    start.add_argument("--task-id")
    start.add_argument("--source-tag")
    start.add_argument("--parent-task-id")
    start.add_argument("--started-at")
    start.set_defaults(handler=_start_command)

    hook = subcommands.add_parser(
        "hook",
        help="Ingest one hook receipt from stdin and SIGNALTRAIL_USAGE_*",
    )
    hook.set_defaults(handler=_hook_command)

    import_command = subcommands.add_parser(
        "import",
        help="Import one local provider usage file",
    )
    _add_ledger_argument(import_command)
    _add_task_argument(import_command)
    import_command.add_argument("path", type=Path)
    import_command.add_argument("--adapter")
    import_command.add_argument("--phase")
    import_command.add_argument("--batch-id")
    import_command.add_argument("--agent-role")
    import_command.add_argument("--run-attempt", type=int)
    import_command.add_argument("--repair-attempt", type=int)
    import_command.add_argument("--evaluation-attempt", type=int)
    import_command.add_argument("--parent-session-id")
    import_command.set_defaults(handler=_import_command)

    summary = subcommands.add_parser("summary", help="Summarize one usage task")
    _add_ledger_argument(summary)
    _add_task_argument(summary)
    summary.set_defaults(handler=_summary_command)

    finalize = subcommands.add_parser("finalize", help="Finalize one usage task")
    _add_ledger_argument(finalize)
    _add_task_argument(finalize)
    finalize.add_argument("--status", default="completed")
    finalize.add_argument("--completed-at")
    finalize.set_defaults(handler=_finalize_command)
    return parser


def _add_ledger_argument(parser: argparse.ArgumentParser) -> None:
    """处理：为本地账本子命令添加可由环境变量补足的根路径参数。
    输入：
    - ``parser``：正在构建的子命令解析器；环境值留到执行阶段读取。
    输出：解析器新增 ``--ledger``，不读取或创建任何本地文件。
    """

    parser.add_argument(
        "--ledger",
        type=Path,
        help="SignalTrail data root or usage root; defaults to SIGNALTRAIL_USAGE_LEDGER",
    )


def _add_task_argument(parser: argparse.ArgumentParser) -> None:
    """处理：为已有任务的子命令添加可由环境变量补足的任务 ID。
    输入：
    - ``parser``：正在构建的 import、summary 或 finalize 解析器。
    输出：解析器新增 ``--task-id``，不会接受 prompt 或原始回执参数。
    """

    parser.add_argument(
        "--task-id",
        help="Usage task ID; defaults to SIGNALTRAIL_USAGE_TASK",
    )


def _required_runtime_value(
    explicit: object,
    environ: Mapping[str, str],
    env_name: str,
    label: str,
) -> str:
    """处理：按命令行优先、环境变量次之解析必需的账本定位值。
    输入：
    - ``explicit``：调用方显式传入的定位值；为空时才查询环境。
    - ``environ``：宿主进程提供的只读环境变量映射。
    - ``env_name``：允许回退读取的环境变量名。
    - ``label``：缺失值错误中使用的安全字段标签。
    输出：非空字符串；两处均缺失时抛出不包含宿主回执的 ValueError。
    """

    value = str(explicit).strip() if explicit is not None else ""
    if not value:
        value = str(environ.get(env_name) or "").strip()
    if not value:
        raise ValueError(f"{label} is required")
    return value


def _optional_runtime_value(
    explicit: object,
    environ: Mapping[str, str],
    env_name: str,
) -> str | None:
    """处理：按命令行优先级读取可选的短运行标签。
    输入：
    - ``explicit``：命令行显式提供的 adapter 或 phase 值。
    - ``environ``：宿主进程提供的只读环境变量映射。
    - ``env_name``：允许回退读取的环境变量名。
    输出：去除首尾空白的字符串；未提供时返回 None。
    """

    value = str(explicit).strip() if explicit is not None else ""
    if not value:
        value = str(environ.get(env_name) or "").strip()
    return value or None


def _ledger(
    args: argparse.Namespace,
    environ: Mapping[str, str],
) -> UsageLedger:
    """处理：为非 hook 子命令创建指向本地 usage 根的账本对象。
    输入：
    - ``args``：含可选 ledger 路径的已解析命令行命名空间。
    - ``environ``：可提供账本根路径的宿主环境变量映射。
    输出：不触发网络或模型调用的 UsageLedger；缺少根路径时明确失败。
    """

    root = _required_runtime_value(
        getattr(args, "ledger", None),
        environ,
        "SIGNALTRAIL_USAGE_LEDGER",
        "usage ledger",
    )
    return UsageLedger(root)


def _task_id(args: argparse.Namespace, environ: Mapping[str, str]) -> str:
    """处理：解析 import、summary 和 finalize 使用的现有任务 ID。
    输入：
    - ``args``：含可选 task ID 的已解析命令行命名空间。
    - ``environ``：可提供任务 ID 的宿主环境变量映射。
    输出：待 UsageLedger 进一步执行安全 ID 校验的非空字符串。
    """

    return _required_runtime_value(
        getattr(args, "task_id", None),
        environ,
        "SIGNALTRAIL_USAGE_TASK",
        "usage task ID",
    )


def _start_command(
    args: argparse.Namespace,
    environ: Mapping[str, str],
) -> dict[str, Any]:
    """处理：创建任务起始事件并只返回本地句柄字段。
    输入：
    - ``args``：账本根、Agent、安全任务标签和可选带时区开始时间。
    - ``environ``：可补足账本根路径的宿主环境变量映射。
    输出：只含 task ID、UTC 日期和任务目录路径的安全 JSON 映射。
    """

    handle = _ledger(args, environ).start_task(
        args.agent,
        task_id=args.task_id,
        source_tag=args.source_tag,
        parent_task_id=args.parent_task_id,
        started_at=args.started_at,
    )
    return {
        "task_id": handle.task_id,
        "date": handle.date,
        "path": str(handle.path),
    }


def _hook_command(
    _args: argparse.Namespace,
    environ: Mapping[str, str],
) -> None:
    """处理：把 stdin 中一个宿主 hook JSON 交给环境驱动的安全适配器。
    输入：
    - ``_args``：已解析 hook 命令空间；该子命令不接收正文参数。
    - ``environ``：定位账本、任务、适配器和关联标签的宿主环境变量映射。
    输出：成功时返回 None 且 stdout 保持为空；安全 observation 由核心库落盘。
    """

    ingest_hook_from_env(environ=environ, stdin=sys.stdin)
    return None


def _import_command(
    args: argparse.Namespace,
    environ: Mapping[str, str],
) -> dict[str, Any]:
    """处理：通过指定适配器只读导入一个本地 usage 文件。
    输入：
    - ``args``：文件路径、adapter/phase 以及账本根和任务 ID；不含内联 payload。
    - ``environ``：可补足账本、任务、adapter 和 phase 的宿主环境变量映射。
    输出：只含 task ID、事件数量和不可变事件路径，不回显宿主回执内容。
    """

    ledger = _ledger(args, environ)
    task_id = _task_id(args, environ)
    handle = ledger.resolve_task(task_id)
    adapter = _optional_runtime_value(
        args.adapter,
        environ,
        "SIGNALTRAIL_USAGE_ADAPTER",
    ) or "hermes"
    phase = _optional_runtime_value(
        args.phase,
        environ,
        "SIGNALTRAIL_USAGE_PHASE",
    )
    paths = ledger.import_usage_file(
        handle,
        adapter,
        args.path,
        phase=phase,
        batch_id=_optional_runtime_value(
            args.batch_id, environ, "SIGNALTRAIL_USAGE_BATCH"
        ),
        agent_role=_optional_runtime_value(
            args.agent_role, environ, "SIGNALTRAIL_USAGE_AGENT_ROLE"
        ),
        run_attempt=(
            args.run_attempt
            if args.run_attempt is not None
            else _optional_runtime_value(
                None, environ, "SIGNALTRAIL_USAGE_RUN_ATTEMPT"
            )
        ),
        repair_attempt=(
            args.repair_attempt
            if args.repair_attempt is not None
            else _optional_runtime_value(
                None, environ, "SIGNALTRAIL_USAGE_REPAIR_ATTEMPT"
            )
        ),
        evaluation_attempt=(
            args.evaluation_attempt
            if args.evaluation_attempt is not None
            else _optional_runtime_value(
                None, environ, "SIGNALTRAIL_USAGE_EVALUATION_ATTEMPT"
            )
        ),
        parent_session_id=_optional_runtime_value(
            args.parent_session_id,
            environ,
            "SIGNALTRAIL_USAGE_PARENT_SESSION",
        ),
    )
    return {
        "task_id": handle.task_id,
        "event_count": len(paths),
        "paths": [str(path) for path in paths],
    }


def _summary_command(
    args: argparse.Namespace,
    environ: Mapping[str, str],
) -> dict[str, Any]:
    """处理：重建并输出一个任务的 unknown-preserving 安全汇总。
    输入：
    - ``args``：含账本根和任务 ID 的已解析命令空间。
    - ``environ``：可补足账本根和任务 ID 的宿主环境变量映射。
    输出：核心库生成的 token、成本、耗时、覆盖率和 observation 安全字典。
    """

    return _ledger(args, environ).summarize_task(_task_id(args, environ))


def _finalize_command(
    args: argparse.Namespace,
    environ: Mapping[str, str],
) -> dict[str, Any]:
    """处理：封存任务汇总并只返回最终事件位置。
    输入：
    - ``args``：账本根、任务 ID、安全状态和可选带时区完成时间。
    - ``environ``：可补足账本根和任务 ID 的宿主环境变量映射。
    输出：只含 task ID 与不可变 finalized 事件路径的安全 JSON 映射。
    """

    ledger = _ledger(args, environ)
    handle = ledger.resolve_task(_task_id(args, environ))
    path = ledger.finalize_task(
        handle,
        status=args.status,
        completed_at=args.completed_at,
    )
    return {"task_id": handle.task_id, "path": str(path)}


def _write_json(payload: Mapping[str, Any]) -> None:
    """处理：以稳定 UTF-8 JSON 输出核心库已脱敏的结果。
    输入：
    - ``payload``：start/import/summary/finalize 返回的安全字段映射。
    输出：stdout 中一个 JSON 对象和换行；不输出宿主原始回执。
    """

    print(json.dumps(dict(payload), ensure_ascii=False, sort_keys=True))


def _write_safe_error(error: BaseException) -> None:
    """处理：在失败时仅报告异常类型而不复制可能含外部内容的消息。
    输入：
    - ``error``：参数解析后由账本、适配器或文件系统抛出的异常。
    输出：stderr 中一个固定结构 JSON；原始 receipt 和异常文本均不会回显。
    """

    print(
        json.dumps(
            {
                "error": "usage_command_failed",
                "error_type": type(error).__name__,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        file=sys.stderr,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """处理：分派本地 usage 子命令并强制 stdout 的安全输出契约。
    输入：
    - ``argv``：可选命令行参数；None 表示读取当前进程参数，hook 另读 stdin 与环境。
    输出：成功返回 0；可预期失败返回 2，hook 成功绝不向 stdout 写入内容。
    """

    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
        handler: CommandHandler = args.handler
        payload = handler(args, os.environ)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        _write_safe_error(exc)
        return 2
    if payload is not None:
        _write_json(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
