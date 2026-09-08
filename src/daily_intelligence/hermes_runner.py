"""Explicit, metered Hermes entry point; the usage-only CLI remains offline."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from daily_intelligence.llm_usage import UsageLedger
from daily_intelligence.storage import write_immutable_json
from daily_intelligence.usage_cli import SafeArgumentParser


def _write_receipt(path: Path, payload: dict[str, Any]) -> None:
    """处理：独占写入安全运行回执，禁止覆盖已经存在的验收证据。
    输入：
    - ``path``：当前 host-run 下尚不存在的输出文件。
    - ``payload``：仅含运行状态、计数和本地定位字段的映射。
    输出：UTF-8 JSON 文件；碰撞明确失败。
    """
    write_immutable_json(path, payload)


def coverage_complete(summary: dict[str, Any], observer: dict[str, Any]) -> bool:
    """处理：验证宿主实际发出的请求事件与账本全部闭合且 token 可精确计量。
    输入：
    - ``summary``：核心账本重新计算的安全汇总。
    - ``observer``：同一 Hermes 进程退出时的事件数量和写入故障回执。
    输出：布尔验收结果；空任务、漏回调、孤立结束与未知 token 均不能通过。
    """
    calls = summary["call_lifecycle"]
    events = observer.get("events", {})
    attempts = events.get("pre_api_request", 0)
    terminals = events.get("post_api_request", 0) + events.get("api_request_error", 0)
    return bool(
        attempts > 0 and not observer.get("failures")
        and attempts == terminals == calls["attempted_call_count"]
        and calls["finished_call_count"] == terminals
        and not calls["unclosed_call_count"] and not calls["orphan_finished_call_count"]
        and not summary["conflicts"]
        and observer.get("database_reconciliation", {}).get("status") == "matched"
        and summary["tokens"]["accounted_total"]["quality"] == "exact"
    )


def _host(args: argparse.Namespace) -> int:
    """处理：在专用 Hermes 解释器中装载计量桥后执行原生一次性会话。
    输入：
    - ``args``：外层启动器限定的提示文件、工具集、模型、时间及轮次预算。
    输出：原生 Hermes 退出码和安全 observer 回执；提示与回答不进入 usage 账本。
    """
    from daily_intelligence.hosts.hermes import HermesObserver, install_bridge

    observer = HermesObserver(os.environ)
    install_bridge(observer)
    from hermes_cli.main import main as hermes_main

    sys.argv = ["hermes", "chat", "--query-file", str(args.prompt_file), "--oneshot", "-Q",
                "--ignore-rules", "--max-turns", str(args.max_turns),
                "--run-budget", str(args.timeout), "-t", args.toolsets]
    if args.provider:
        sys.argv.extend(["--provider", args.provider])
    if args.model:
        sys.argv.extend(["-m", args.model])
    try:
        hermes_main()
    finally:
        from hermes_constants import get_hermes_home

        receipt = observer.receipt()
        receipt["database_reconciliation"] = observer.reconcile_database(
            get_hermes_home() / "state.db"
        )
        _write_receipt(args.receipt_dir / "observer.json", receipt)
    return 0


def run_metered(args: argparse.Namespace) -> dict[str, Any]:
    """处理：先创建用量任务再启动 Hermes，进程退出后验证并封存完整调用链。
    输入：
    - ``args``：用户显式指定的 Hermes Python、数据根、提示文件和运行预算。
    输出：host-run 回执；超时或缺失观测封存为 partial，绝不伪造缺失 token。
    """
    args.prompt_file = args.prompt_file.resolve(strict=True)
    args.ledger = args.ledger.resolve()
    ledger = UsageLedger(args.ledger)
    task = (ledger.resolve_task(args.task_id) if args.task_id else ledger.start_task(
        "hermes", source_tag=args.phase, parent_task_id=args.parent_task_id
    ))
    if any(event["event_type"] != "task.started" for event in ledger._events(task)):
        raise ValueError("metered launcher requires an unused open task")
    receipt_dir = args.ledger / "host-runs" / task.task_id
    receipt_dir.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ)
    source_root = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = os.pathsep.join(
        value for value in (source_root, env.get("PYTHONPATH")) if value
    )
    env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
                "SIGNALTRAIL_USAGE_LEDGER": str(args.ledger),
                "SIGNALTRAIL_USAGE_TASK": task.task_id, "SIGNALTRAIL_USAGE_ADAPTER": "hermes",
                "SIGNALTRAIL_USAGE_PHASE": args.phase, "SIGNALTRAIL_USAGE_RUN_ATTEMPT": "1",
                "SIGNALTRAIL_HERMES_PYTHON": str(args.hermes_python.resolve()),
                "SIGNALTRAIL_HERMES_MODEL": args.model or "",
                "SIGNALTRAIL_HERMES_PROVIDER": args.provider or ""})
    env.pop("SIGNALTRAIL_USAGE_EVALUATION_ATTEMPT", None)
    if args.evaluation_attempt:
        env["SIGNALTRAIL_USAGE_EVALUATION_ATTEMPT"] = str(args.evaluation_attempt)
    command = [str(args.hermes_python), "-m", "daily_intelligence.hermes_runner", "_host",
               "--prompt-file", str(args.prompt_file), "--receipt-dir", str(receipt_dir),
               "--max-turns", str(args.max_turns), "--timeout", str(args.timeout),
               "--toolsets", args.toolsets]
    for flag, value in (("--provider", args.provider), ("--model", args.model)):
        if value:
            command.extend([flag, value])
    started = time.monotonic()
    timed_out = False
    returncode = None
    # 只保存本地宿主输出，账本只接收适配器 allowlist；Windows 子进程不弹窗。
    with (receipt_dir / "response.txt").open("x", encoding="utf-8") as stdout, (
        receipt_dir / "stderr.log"
    ).open("x", encoding="utf-8") as stderr:
        try:
            process = subprocess.Popen(
                command, env=env, stdout=stdout, stderr=stderr,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            try:
                returncode = process.wait(timeout=args.timeout + 60)
            except subprocess.TimeoutExpired:
                timed_out = True
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   capture_output=True, check=False, timeout=30)
                else:
                    process.kill()
                returncode = process.wait(timeout=30)
        except OSError:
            returncode = -1
    observer_path = receipt_dir / "observer.json"
    observer = (json.loads(observer_path.read_text(encoding="utf-8"))
                if observer_path.is_file() else {"failures": {"missing_observer_receipt": 1}})
    summary = ledger.summarize_task(task)
    complete = returncode == 0 and not timed_out and coverage_complete(summary, observer)
    ledger.finalize_task(task, status="completed" if complete else "partial")
    summary = ledger.summarize_task(task)
    receipt = {"task_id": task.task_id, "status": "completed" if complete else "partial",
               "returncode": returncode, "timed_out": timed_out,
               "wall_seconds": round(time.monotonic() - started, 3),
               "observer": observer, "summary": summary}
    _write_receipt(receipt_dir / "receipt.json", receipt)
    return receipt


def build_parser() -> argparse.ArgumentParser:
    """处理：分离用户启动入口与只供子进程使用的宿主入口。
    输入：
    - 无显式业务参数：运行参数由 main 交给解析器。
    输出：包含解释器、提示文件和有界运行选项的解析器。
    """
    parser = SafeArgumentParser(prog="signaltrail-hermes")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "_host"):
        child = sub.add_parser(name)
        child.add_argument("--prompt-file", type=Path, required=True)
        child.add_argument("--provider")
        child.add_argument("--model")
        child.add_argument("--toolsets", default="terminal,file,delegation")
        child.add_argument("--max-turns", type=int, default=80)
        child.add_argument("--timeout", type=int, default=3600)
        if name == "_host":
            child.add_argument("--receipt-dir", type=Path, required=True)
        else:
            child.add_argument("--ledger", type=Path, required=True)
            child.add_argument("--hermes-python", type=Path, required=True)
            child.add_argument("--task-id")
            child.add_argument("--parent-task-id")
            child.add_argument("--phase", default="foreground")
            child.add_argument("--evaluation-attempt", type=int)
    return parser


def main() -> int:
    """处理：执行完整计量启动并以安全 JSON 报告验收状态。
    输入：
    - 无显式业务参数：解析当前命令行，只从文件向 Hermes 传递提示。
    输出：成功返回零；计量不全返回一，参数或环境故障返回二。
    """
    try:
        args = build_parser().parse_args()
        if args.timeout <= 0 or args.max_turns <= 0:
            raise ValueError("run budgets must be positive")
        if args.command == "_host":
            return _host(args)
        receipt = run_metered(args)
        print(json.dumps({key: receipt[key] for key in (
            "task_id", "status", "returncode", "wall_seconds"
        )}))
        return 0 if receipt["status"] == "completed" else 1
    except (ValueError, OSError, RuntimeError) as exc:
        print(json.dumps({"error": "hermes_runner_failed", "error_type": type(exc).__name__}),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
