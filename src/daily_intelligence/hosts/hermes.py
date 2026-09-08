"""Process-local bridge for Hermes 0.21 API observers and synchronous delegation."""

from __future__ import annotations

import os
import re
import shlex
import sqlite3
import threading
import time
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path, PureWindowsPath
from typing import Any
from uuid import uuid4

from daily_intelligence.llm_usage import UsageLedger

API_EVENTS = frozenset({"pre_api_request", "post_api_request", "api_request_error"})
FILE_WORKER_PHASE = re.compile(
    r"\[signaltrail-phase:(brief-authoring|analysis-authoring|repair)\]"
)


def bounded_delegation_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """处理：收紧 Hermes 已解析的委派配置，不嵌套第二层 delegation。
    输入：宿主委派配置节，包含最大轮次和并发数等字段。
    输出：保留路由与其他配置的副本，轮次上限四十、并发上限三。
    """
    return {**config, "max_iterations": min(int(config.get("max_iterations", 40)), 40),
            "max_concurrent_children": min(int(config.get("max_concurrent_children", 3)), 3)}


def file_worker_tasks(tasks: Any) -> tuple[Any, bool]:
    """处理：移除文件写作任务的额外口头回执 schema，避免整轮写作重复。
    输入：模型派发的 task 列表；仅处理全部带 SignalTrail 写作阶段标记的波次。
    输出：任务副本及是否已采用文件契约；未匹配任务不变，包内输出校验始终保留。
    """
    if not isinstance(tasks, list) or not tasks or not all(
        isinstance(task, dict) and FILE_WORKER_PHASE.match(str(task.get("goal") or ""))
        for task in tasks
    ):
        return tasks, False
    return [{key: value for key, value in task.items() if key != "output_schema"}
            for task in tasks], True


def is_usage_command(command: object) -> bool:
    """处理：只识别已有 SignalTrail 计量命令，保留其他 shell hook。
    输入：配置中的 command 字符串；仅比较可执行文件名与唯一子命令。
    输出：是否可被本进程的等价内存观察器替代。
    """
    if not isinstance(command, str) or "\n" in command or "\r" in command:
        return False
    try:
        argv = shlex.split(command, posix=False)
    except ValueError:
        return False
    return (len(argv) == 2 and argv[1] == "hook"
            and PureWindowsPath(argv[0].strip('"')).name
            in {"signaltrail-usage", "signaltrail-usage.exe"})


class HermesObserver:
    """处理：串行写入并发 Hermes 请求回执并保留失败计数。
    输入：已创建任务的环境映射；仅使用 SIGNALTRAIL_USAGE 定位和关联字段。
    输出：每次事件同步落盘，收尾回执提供可核对的事件数量与谱系。
    """

    def __init__(self, environ: Mapping[str, str]) -> None:
        """处理：在首次模型请求前绑定唯一且尚未封存的本地任务。
        输入：启动器提供的账本根、任务 ID、阶段和尝试序号环境。
        输出：持锁观察器；没有任何模型或外部服务调用。
        """
        self.ledger = UsageLedger(environ["SIGNALTRAIL_USAGE_LEDGER"])
        self.task = self.ledger.resolve_task(environ["SIGNALTRAIL_USAGE_TASK"])
        self.phase = environ.get("SIGNALTRAIL_USAGE_PHASE", "foreground")
        self.attempt = int(environ.get("SIGNALTRAIL_USAGE_RUN_ATTEMPT", "1"))
        self.evaluation_attempt = environ.get("SIGNALTRAIL_USAGE_EVALUATION_ATTEMPT")
        self.lock = threading.RLock()
        self.parents: dict[str, tuple[str, str]] = {}
        self.counts: Counter[str] = Counter()
        self.failures: Counter[str] = Counter()
        self.sessions: set[str] = set()

    def observe(self, event: str, payload: Mapping[str, Any]) -> None:
        """处理：从宿主事件读取父子关系或规范化单次请求，异常只计类型。
        输入：Hermes 内存 hook 名和映射；正文不复制到持久化记录。
        输出：不改变宿主指令；写入失败会让最终验收明确失败。
        """
        with self.lock:
            if event == "subagent_start":
                child = payload.get("child_session_id")
                parent = payload.get("parent_session_id")
                goal = str(payload.get("child_goal") or "")
                phase = FILE_WORKER_PHASE.search(goal)
                if child and parent:
                    self.parents[str(child)] = (
                        str(parent), phase.group(1) if phase else self.phase
                    )
            if event not in API_EVENTS:
                return
            self.counts[event] += 1
            if session := payload.get("session_id"):
                self.sessions.add(str(session))
            parent, phase = self.parents.get(str(payload.get("session_id")), (None, self.phase))
            if payload.get("auxiliary_task"):
                phase = "auxiliary"
            try:
                self.ledger.ingest_hook(
                    self.task, "hermes", {"hook_event_name": event, **payload},
                    phase=phase, parent_session_id=parent,
                    agent_role="worker" if parent else (
                        "independent-evaluator" if self.evaluation_attempt else "coordinator"
                    ),
                    run_attempt=self.attempt,
                    evaluation_attempt=(int(self.evaluation_attempt)
                                        if self.evaluation_attempt else None),
                )
            except Exception as exc:
                self.failures[type(exc).__name__] += 1

    def receipt(self) -> dict[str, Any]:
        """处理：汇总宿主事件分发与写入故障，不输出原始会话标识。
        输入：观察器持有的数字计数与父子关系映射。
        输出：可与最终账本逐项核对的安全收尾信息。
        """
        with self.lock:
            return {"events": dict(self.counts), "failures": dict(self.failures),
                    "worker_count": len(self.parents), "bridge": "hermes-0.21-foreground-v3"}

    def reconcile_database(self, path: Path) -> dict[str, Any]:
        """处理：只读核对本次会话的宿主按模型计数，发现辅助请求或会话遗漏。
        输入：Hermes 状态数据库路径；会话范围只来自本观察器内存。
        输出：不含会话原值的计数、token 和对账结论；不把宿主累计数写成逐调用证据。
        """
        try:
            with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
                db.execute("PRAGMA query_only=ON")
                totals = [0, 0]
                for session in self.sessions:
                    row = db.execute(
                        "SELECT SUM(api_call_count), "
                        "SUM(input_tokens + output_tokens + cache_read_tokens "
                        "+ cache_write_tokens) "
                        "FROM session_model_usage WHERE session_id=?", (session,),
                    ).fetchone()
                    totals[0] += row[0] or 0
                    totals[1] += row[1] or 0
            summary = self.ledger.summarize_task(self.task)
            matches = (
                totals[0] == summary["call_lifecycle"]["finished_call_count"]
                and totals[1] == summary["tokens"]["accounted_total"]["value"]
            )
            return {"status": "matched" if matches else "mismatch",
                    "api_call_count": totals[0], "accounted_tokens": totals[1]}
        except (OSError, sqlite3.Error):
            return {"status": "unavailable"}


def install_auxiliary_bridge(observer: HermesObserver) -> None:
    """处理：覆盖辅助模型的同步及异步请求和恢复尝试，计入标题与压缩等开销。
    输入：已绑定本次任务的观察器；请求仅在内存通过原有 Hermes 客户端。
    输出：辅助请求具备开始、结束或错误事件；不支持的原始流明确阻止精确验收。
    """
    from agent import aux_accounting, auxiliary_client
    from agent.usage_pricing import normalize_usage

    original_sync = auxiliary_client._relay_sync_completion
    original_async = auxiliary_client._relay_async_completion
    original_stream = auxiliary_client._relay_sync_stream

    def compatible_request(kwargs: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
        """处理：避免已实测不支持结构化输出的 Go 标题请求先失败再重试。
        输入：辅助请求与 provider 选项，只匹配已验证的模型及标题用途。
        输出：沿用 Hermes 官方格式降级函数的副本，其他请求原样返回。
        """
        route = auxiliary_client._RELAY_AUX_CALL_CONTEXT.get() or {}
        if (options.get("provider") == "opencode-go"
                and kwargs.get("model") == "deepseek-v4-flash-vision-exp"
                and route.get("task") == "title_generation"):
            return auxiliary_client._without_structured_output_format(kwargs) or kwargs
        return kwargs

    def begin(kwargs: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
        """处理：在辅助传输前分配独立调用标识并关联当前会话。
        输入：模型请求参数和传输选项；只读取模型与 provider 标签。
        输出：供结束事件配对的安全内存字段，不含请求正文。
        """
        context = aux_accounting._accounting.get()
        route = auxiliary_client._RELAY_AUX_CALL_CONTEXT.get() or {}
        session = context[1] if context else auxiliary_client._runtime_main_value("session_id")
        payload = {"api_request_id": f"aux-{uuid4().hex}", "session_id": session or "",
                   "model": kwargs.get("model"), "provider": options.get("provider"),
                   "auxiliary_task": route.get("task") or "auxiliary", "started_at": time.time()}
        if not session or str(route.get("task", "")).startswith("moa_"):
            observer.failures["unsupported_auxiliary_lineage"] += 1
        observer.observe("pre_api_request", payload)
        return payload

    def finish(payload: dict[str, Any], response: Any = None, *, failed: bool = False) -> None:
        """处理：归一化辅助返回的 token 和计时，异常调用保持未知用量。
        输入：开始字段、原始内存响应或失败标记。
        输出：终态事件；计价表推算金额不作为宿主实际账单写入。
        """
        end = time.time()
        usage = getattr(response, "usage", None)
        normalized = None
        if usage is not None:
            canonical = normalize_usage(usage, provider=payload.get("provider"))
            normalized = asdict(canonical)
            normalized.pop("raw_usage", None)
            normalized["total_tokens"] = canonical.total_tokens
            normalized["prompt_tokens"] = canonical.prompt_tokens
        observer.observe("api_request_error" if failed else "post_api_request", {
            **payload, "ended_at": end, "api_duration": end - payload["started_at"],
            "usage": normalized, "response_model": getattr(response, "model", None),
        })

    def sync(client: Any, kwargs: dict[str, Any], **options: Any) -> Any:
        """处理：配对一次辅助同步传输，异常在记账后原样传播。
        输入：原生客户端、内存请求和 Hermes 传输选项。
        输出：未经更改的响应或异常，模型行为不因计量改变。
        """
        kwargs = compatible_request(kwargs, options)
        payload = begin(kwargs, options)
        try:
            response = original_sync(client, kwargs, **options)
        except BaseException:
            finish(payload, failed=True)
            raise
        finish(payload, response)
        return response

    async def asynchronous(client: Any, kwargs: dict[str, Any], **options: Any) -> Any:
        """处理：配对一次辅助异步传输，取消与错误都保留终态。
        输入：原生异步客户端、内存请求和 Hermes 传输选项。
        输出：未经更改的响应或异常，各协程保持自己的请求标识。
        """
        kwargs = compatible_request(kwargs, options)
        payload = begin(kwargs, options)
        try:
            response = await original_async(client, kwargs, **options)
        except BaseException:
            finish(payload, failed=True)
            raise
        finish(payload, response)
        return response

    def stream(*args: Any, **kwargs: Any) -> Any:
        """处理：识别尚未审计的原始辅助流，防止遗漏被标记为完整覆盖。
        输入：Hermes 原始流传输参数；不复制到回执。
        输出：原始流照常返回，但本次计量验收必须失败。
        """
        observer.failures["unsupported_raw_auxiliary_stream"] += 1
        return original_stream(*args, **kwargs)

    auxiliary_client._relay_sync_completion = sync
    auxiliary_client._relay_async_completion = asynchronous
    auxiliary_client._relay_sync_stream = stream


def install_iteration_summary_bridge(observer: HermesObserver) -> None:
    """处理：覆盖绕过常规 transport 的轮次耗尽总结，补齐亲和 header 与计量。
    输入：本次任务观察器；仅包装 Hermes 已有总结请求入口。
    输出：每次实际总结传输都有终态；成功 usage 通过宿主原生辅助计量接口落库。
    """
    from agent import chat_completion_helpers
    from agent.opencode_affinity import merge_opencode_session_headers

    original = chat_completion_helpers._managed_summary_call
    original_handle = chat_completion_helpers.handle_max_iterations

    def managed(agent: Any, request_id: str, request: dict, callback: Any,
                *, retry_count: int) -> Any:
        """处理：在 relay 的实际回调边界计量总结，重试各自拥有唯一标识。
        输入：宿主 agent、总结参数及原传输回调，不持久化正文或 headers。
        输出：原生响应或异常；失败请求未知 token，不以数据库缺行判零。
        """
        def transfer(kwargs: dict) -> Any:
            """处理：为一次实际传输补齐关联、开始和结束事件。
            输入：relay 交给客户端的内存请求参数。
            输出：请求结果及安全 usage 事件；宿主数据库写入失败阻止完整验收。
            """
            kwargs = merge_opencode_session_headers(
                dict(kwargs), agent.provider, agent.base_url, agent.session_id
            )
            payload = {"api_request_id": f"iteration-summary-{uuid4().hex}",
                       "session_id": agent.session_id, "model": agent.model,
                       "provider": agent.provider, "auxiliary_task": "iteration_summary",
                       "started_at": time.time()}
            observer.observe("pre_api_request", payload)
            try:
                response = callback(kwargs)
            except BaseException:
                end = time.time()
                observer.observe("api_request_error", {
                    **payload, "ended_at": end, "api_duration": end - payload["started_at"]})
                raise
            end = time.time()
            usage = agent._usage_summary_for_api_request_hook(response)
            observer.observe("post_api_request", {
                **payload, "ended_at": end, "api_duration": end - payload["started_at"],
                "usage": usage, "response_model": getattr(response, "model", None),
                "tool_call_count": 0,
            })
            try:
                if usage is None:
                    raise ValueError("summary usage unavailable")
                agent._session_db.record_auxiliary_usage(
                    agent.session_id, task="iteration_summary", api_call_count=1,
                    model=getattr(response, "model", None) or agent.model,
                    billing_provider=agent.provider, billing_base_url=agent.base_url,
                    **{key: usage[key] for key in (
                        "input_tokens", "output_tokens", "cache_read_tokens",
                        "cache_write_tokens", "reasoning_tokens")},
                )
            except Exception as exc:
                observer.failures[f"summary_accounting_{type(exc).__name__}"] += 1
            return response

        return original(agent, request_id, request, transfer, retry_count=retry_count)

    def handle(agent: Any, messages: list, call_count: int) -> str:
        """处理：明确拒绝未审计的总结 transport 被标记为精确覆盖。
        输入：宿主当前 API 模式、消息及调用计数。
        输出：原总结文本；未经过 managed 入口的模式保留覆盖故障。
        """
        if agent.api_mode not in {"chat_completions", "anthropic_messages"}:
            observer.failures["unsupported_iteration_summary_transport"] += 1
        return original_handle(agent, messages, call_count)

    chat_completion_helpers._managed_summary_call = managed
    chat_completion_helpers.handle_max_iterations = handle


def install_bridge(observer: HermesObserver) -> None:
    """处理：在独立进程接通同步观察器和前台委派，不修改 Hermes 安装源码。
    输入：启动器创建的观察器；当前解释器必须安装 Hermes 0.21 的相关接口。
    输出：只影响本次进程的兼容桥；其他插件、审批和服务配置继续走宿主原逻辑。
    """
    import cli
    from agent import shell_hooks
    from hermes_cli import lifecycle
    from run_agent import AIAgent
    from tools import delegate_tool
    from tools.delegate_tool import _strip_model_hidden_task_fields, delegate_task

    original_invoke = lifecycle.invoke_hook
    original_has = lifecycle.has_hook
    original_register = shell_hooks.register_from_config
    original_delegate_config = delegate_tool._load_config
    original_max_children = delegate_tool._get_max_concurrent_children
    original_finalize = cli._finalize_single_query

    def finalize(host: Any) -> None:
        """处理：在关闭会话数据库前等待本进程的标题生成线程完成计量。
        输入：Hermes 一次性 CLI 对象；仅等待固定命名的宿主标题线程。
        输出：最多额外等待三十秒，随后执行原清理；超时会由账本未闭合门禁拒绝验收。
        """
        deadline = time.monotonic() + 30
        for thread in threading.enumerate():
            if thread.name == "auto-title" and thread is not threading.current_thread():
                thread.join(timeout=max(0, deadline - time.monotonic()))
        original_finalize(host)

    def bounded_config() -> dict[str, Any]:
        """处理：为本次独立运行限制工作线程数量及子任务最大模型轮次。
        输入：Hermes 读取的用户配置；只覆盖本进程的委派预算。
        输出：最多三个并发子任务且每个最多四十轮，其余设置保留。
        """
        return bounded_delegation_config(original_delegate_config())

    def bounded_children() -> int:
        """处理：约束宿主独立读取的并发配置，避免绕过委派配置副本。
        输入：宿主配置或环境变量解析后的有效并发值。
        输出：保持更低用户上限，并将单个工作波次限定为最多三个任务。
        """
        return min(original_max_children(), 3)

    def invoke(event: str, **kwargs: Any) -> list[Any]:
        """处理：先可靠落盘计量，再保持原有生命周期回调返回值。
        输入：宿主发出的事件名和内存字段。
        输出：原有插件结果，不增加模型指令或更改审批。
        """
        observer.observe(event, kwargs)
        return original_invoke(event, **kwargs)

    def has(event: str) -> bool:
        """处理：让宿主在没有其他插件时仍发出三种请求计量事件。
        输入：宿主查询的生命周期事件名称。
        输出：计量事件为真，其他事件沿用原有注册状态。
        """
        return event in API_EVENTS or original_has(event)

    def register(cfg: dict[str, Any] | None, **kwargs: Any) -> list[Any]:
        """处理：移除被内存桥替代的三个 shell 计量回调以避免重复和并发跳过。
        输入：宿主配置副本与原注册参数；其他命令不变。
        输出：原始注册器的结果，不写回用户配置文件。
        """
        if isinstance(cfg, dict) and isinstance(cfg.get("hooks"), dict):
            hooks = dict(cfg["hooks"])
            for event in API_EVENTS:
                entries = hooks.get(event)
                if isinstance(entries, list):
                    hooks[event] = [entry for entry in entries if not (
                        isinstance(entry, dict) and is_usage_command(entry.get("command"))
                    )]
            cfg = {**cfg, "hooks": hooks}
        return original_register(cfg, **kwargs)

    def dispatch(agent: Any, args: dict[str, Any]) -> str:
        """处理：按官方 Python 委派接口等待整个工作波次，避免 oneshot 提前退出。
        输入：Hermes agent 及模型提供的委派参数；隐藏字段仍经宿主过滤。
        输出：同一工具的完整结果，子任务完成后才返回给协调器。
        """
        tasks, file_contract = file_worker_tasks(
            _strip_model_hidden_task_fields(args.get("tasks"))
        )
        return delegate_task(
            goal=args.get("goal"), context=args.get("context"),
            tasks=tasks,
            max_iterations=args.get("max_iterations"), role=args.get("role"),
            background=False, action=args.get("action"), subagent_id=args.get("subagent_id"),
            message=args.get("message"),
            output_schema=None if file_contract else args.get("output_schema"),
            parent_agent=agent,
        )

    lifecycle.invoke_hook = invoke
    lifecycle.has_hook = has
    shell_hooks.register_from_config = register
    AIAgent._dispatch_delegate_task = dispatch
    delegate_tool._load_config = bounded_config
    delegate_tool._get_max_concurrent_children = bounded_children
    cli._finalize_single_query = finalize
    install_auxiliary_bridge(observer)
    install_iteration_summary_bridge(observer)
    os.environ["PYTHONIOENCODING"] = "utf-8"
