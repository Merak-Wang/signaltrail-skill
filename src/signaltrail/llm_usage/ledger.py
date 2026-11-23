from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
from bisect import insort
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from operator import itemgetter
from pathlib import Path
from typing import Any, BinaryIO, TextIO
from uuid import uuid4

from signaltrail.storage import write_immutable_json
from signaltrail.utils import read_json_object

from .adapters import CodexAdapter, HermesAdapter, OpenClawAdapter, UsageAdapter
from .adapters.base import canonical_digest, hash_identifier
from .models import (
    TOKEN_FIELDS,
    AdapterRecord,
    CallHandle,
    Measurement,
    ObservationQuality,
    TaskHandle,
    UsageObservation,
    normalize_timestamp,
    safe_label,
    unobservable,
    validate_id,
)

SCHEMA_VERSION = "1.0"
MAX_HOOK_BYTES = 1024 * 1024
EVENT_ROOT_KEYS = frozenset(
    {
        "schema_version",
        "event_id",
        "event_type",
        "task_id",
        "recorded_at",
        "dedupe_hash",
        "payload_hash",
        "data",
    }
)
SUCCESS_CALL_STATUSES = frozenset({"completed", "success", "succeeded", "ok"})
_TASK_LOCKS_GUARD = threading.Lock()
_TASK_LOCKS: dict[str, threading.RLock] = {}
DEFAULT_ADAPTERS: dict[str, type[UsageAdapter]] = {
    "hermes": HermesAdapter,
    "codex": CodexAdapter,
    "openclaw": OpenClawAdapter,
}

_CORRELATION_LABELS = ("batch_id", "agent_role")
_CORRELATION_ATTEMPTS = ("run_attempt", "repair_attempt", "evaluation_attempt")
_CORRELATION_FIELDS = (*_CORRELATION_LABELS, *_CORRELATION_ATTEMPTS, "parent_session_id_hash")
USAGE_CORRELATION_ENV = {
    "batch_id": "SIGNALTRAIL_USAGE_BATCH",
    "agent_role": "SIGNALTRAIL_USAGE_AGENT_ROLE",
    "run_attempt": "SIGNALTRAIL_USAGE_RUN_ATTEMPT",
    "repair_attempt": "SIGNALTRAIL_USAGE_REPAIR_ATTEMPT",
    "evaluation_attempt": "SIGNALTRAIL_USAGE_EVALUATION_ATTEMPT",
    "parent_session_id": "SIGNALTRAIL_USAGE_PARENT_SESSION",
}



class UsageLedger:
    """处理：管理本地、不可变、可去重的 LLM usage 事件目录。
    输入：SignalTrail data 根或其 usage 子目录；不接触网络和模型服务。
    输出：任务/call 句柄、事件路径和 unknown-preserving 汇总。
    """

    def __init__(self, data_dir: str | Path) -> None:
        """处理：解析 data/usage 根但不创建任务或写入事件。
        输入：数据根路径；若路径名为 usage，则直接把它视为 usage 根。
        输出：可供 start/import/summarize/finalize 调用的 UsageLedger。
        """

        candidate = Path(data_dir).expanduser().resolve()
        self._transaction_state = threading.local()
        if candidate.name == "usage":
            self.data_dir = candidate.parent
            self.usage_root = candidate
        else:
            self.data_dir = candidate
            self.usage_root = candidate / "usage"

    def start_task(
        self,
        agent: str,
        *,
        task_id: str | None = None,
        source_tag: str | None = None,
        parent_task_id: str | None = None,
        started_at: str | None = None,
    ) -> TaskHandle:
        """处理：创建一次计量任务的不可变起始事件。
        输入：安全 agent 标签、可选 task/source/parent 标识和 UTC 时间。
        输出：后续 hook、导入和 finalize 共享的 TaskHandle；同 ID 重放幂等。
        """

        agent_label = _required_label(agent, "agent")
        task_value = validate_id(task_id or f"task-{uuid4().hex}", "task_id")
        parent_value = (
            validate_id(parent_task_id, "parent_task_id")
            if parent_task_id is not None
            else None
        )
        source_value = safe_label(source_tag)
        if source_tag is not None and source_value is None:
            raise ValueError("source_tag must be a bounded safe label")
        with self._task_id_guard(task_value):
            handle = self._existing_task_handle(task_value)
            if handle is None:
                timestamp = _timestamp(started_at)
                date = timestamp[:10]
                handle = self._canonical_task_handle(
                    TaskHandle(
                        self.data_dir, task_value, date, self.usage_root / date / task_value
                    )
                )
            else:
                existing_start = next(
                    event for event in self._events_unlocked(handle)
                    if event["event_type"] == "task.started"
                )
                timestamp = (
                    _timestamp(started_at)
                    if started_at is not None
                    else existing_start["data"]["started_at"]
                )
            data: dict[str, Any] = {"agent": agent_label, "started_at": timestamp}
            if source_value is not None:
                data["source_tag"] = source_value
            if parent_value is not None:
                data["parent_task_id"] = parent_value
            self._write_event_unlocked(
                handle,
                "task.started",
                dedupe_key=f"task-start:{task_value}",
                data=data,
            )
            return handle

    def start_call(
        self,
        task: TaskHandle | str,
        phase: str,
        *,
        call_id: str | None = None,
        started_at: str | None = None,
        adapter: str | None = None,
        batch_id: str | None = None,
        agent_role: str | None = None,
        run_attempt: int | None = None,
        repair_attempt: int | None = None,
        evaluation_attempt: int | None = None,
        parent_session_id: str | None = None,
    ) -> CallHandle:
        """处理：记录宿主即将发起一次 LLM call 的生命周期边界。
        输入：任务、phase、可选 call ID/时间/适配器短标签。
        输出：可交给 ingest_hook 和 finish_call 的 CallHandle。
        """

        handle = self.resolve_task(task)
        phase_label = _required_label(phase, "phase")
        call_value = validate_id(call_id or f"call-{uuid4().hex}", "call_id")
        safe_adapter = _optional_label(adapter, "adapter")
        metadata = _correlation_fields(
            batch_id=batch_id, agent_role=agent_role, run_attempt=run_attempt,
            repair_attempt=repair_attempt, evaluation_attempt=evaluation_attempt,
            parent_session_id=parent_session_id,
        )
        with self._task_guard(handle):
            events = self._open_events(handle)
            existing = _call_event_data(events, "call.started", call_value)
            timestamp = (
                _timestamp(started_at)
                if started_at is not None or existing is None
                else existing["started_at"]
            )
            data: dict[str, Any] = {
                "call_id": call_value,
                "phase": phase_label,
                "started_at": timestamp,
            }
            if safe_adapter is not None:
                data["adapter"] = safe_adapter
            data.update(metadata)
            self._write_event_unlocked(
                handle,
                "call.started",
                dedupe_key=f"call-start:{call_value}",
                data=data,
            )
        return _call_handle_from_data(handle, data)

    def finish_call(
        self,
        call: CallHandle,
        *,
        status: str = "completed",
        completed_at: str | None = None,
    ) -> Path:
        """处理：写入 call 的完成/失败边界，不推断任何 token 数值。
        输入：CallHandle、安全状态标签和可选结束时间。
        输出：不可变 call.finished 事件路径；重复写相同语义保持幂等。
        """

        handle = self._canonical_task_handle(call.task)
        call_id = validate_id(call.call_id, "call_id")
        phase = _required_label(call.phase, "phase")
        status_label = _required_label(status, "status")
        with self._task_guard(handle):
            events = self._open_events(handle)
            existing = _call_event_data(events, "call.finished", call_id)
            timestamp = (
                _timestamp(completed_at)
                if completed_at is not None or existing is None
                else existing["completed_at"]
            )
            data = {
                "call_id": call_id,
                "phase": phase,
                "status": status_label,
                "completed_at": timestamp,
            }
            _validate_call_finish(data, events)
            return self._write_event_unlocked(
                handle,
                "call.finished",
                dedupe_key=f"call-finish:{call_id}",
                data=data,
            )

    def ingest_hook(
        self,
        task: TaskHandle | str,
        adapter: str | UsageAdapter,
        payload: Mapping[str, Any],
        *,
        phase: str | None = None,
        call_id: str | None = None,
        source_event_id: str | None = None,
        batch_id: str | None = None,
        agent_role: str | None = None,
        run_attempt: int | None = None,
        repair_attempt: int | None = None,
        evaluation_attempt: int | None = None,
        parent_session_id: str | None = None,
    ) -> list[Path]:
        """处理：以内存 allowlist 适配一次 hook 回执并原子写入 observation。
        输入：任务、适配器、宿主 payload 及可选关联标签；payload 不会原样落盘。
        输出：新建或确认幂等存在的 usage.observed 事件路径列表。
        """

        handle = self.resolve_task(task)
        selected = self._adapter(adapter)
        records = selected.from_hook(
            payload,
            phase=phase,
            call_id=call_id,
            source_event_id=source_event_id,
        )
        records = _correlate_records(
            records,
            batch_id=batch_id,
            agent_role=agent_role,
            run_attempt=run_attempt,
            repair_attempt=repair_attempt,
            evaluation_attempt=evaluation_attempt,
            parent_session_id=parent_session_id,
        )
        # 一个 hook 的生命周期和 usage 共享同一锁及已验证快照；退出后立即丢弃。
        with self._task_guard(handle):
            return self._ingest_hook_records(handle, records, call_id=call_id)

    def _ingest_hook_records(
        self,
        task: TaskHandle,
        records: list[AdapterRecord],
        *,
        call_id: str | None,
    ) -> list[Path]:
        """处理：把请求级 hook 自动关联为不可变 call 生命周期和 usage observation。
        输入：规范任务、适配器记录及宿主包装器可选提供的显式本地 call ID。
        输出：按 hook 顺序创建的事件路径；缺少 pre 时保留未关联 observation 而不伪造 start。
        """

        if call_id is not None:
            return self._ingest_records(task, records, call_id=call_id)
        output: list[Path] = []
        for record in records:
            observation = record.observation
            derived_call_id = _hook_call_id(observation)
            if derived_call_id is None:
                output.extend(self._ingest_records(task, [record]))
                continue
            if observation.source_kind == "pre_api_request":
                self.start_call(
                    task,
                    observation.phase or "host-request",
                    call_id=derived_call_id,
                    started_at=observation.started_at,
                    adapter=observation.adapter,
                    batch_id=observation.batch_id,
                    agent_role=observation.agent_role,
                    run_attempt=observation.run_attempt,
                    repair_attempt=observation.repair_attempt,
                    evaluation_attempt=observation.evaluation_attempt,
                )
                output.extend(
                    self._ingest_records(task, [record], call_id=derived_call_id)
                )
                continue
            start = _call_event_data(self._open_events(task), "call.started", derived_call_id)
            linked_call_id = derived_call_id if start is not None else None
            output.extend(self._ingest_records(task, [record], call_id=linked_call_id))
            if start is not None:
                self.finish_call(
                    _call_handle_from_data(task, start),
                    status="failed" if observation.source_kind == "api_request_error"
                    else "completed",
                    completed_at=observation.completed_at,
                )
        return output

    def import_usage_file(
        self,
        task: TaskHandle | str,
        adapter: str | UsageAdapter,
        path: str | Path,
        *,
        phase: str | None = None,
        batch_id: str | None = None,
        agent_role: str | None = None,
        run_attempt: int | None = None,
        repair_attempt: int | None = None,
        evaluation_attempt: int | None = None,
        parent_session_id: str | None = None,
    ) -> list[Path]:
        """处理：只读导入宿主 JSON/JSONL usage 文件并持久化安全字段。
        输入：任务、适配器、本地文件路径和可选 phase；不发起网络或 LLM 调用。
        输出：全部新建或幂等确认的 usage.observed 事件路径。
        """

        handle = self.resolve_task(task)
        records = self._adapter(adapter).from_path(Path(path), phase=phase)
        records = _correlate_records(
            records,
            batch_id=batch_id,
            agent_role=agent_role,
            run_attempt=run_attempt,
            repair_attempt=repair_attempt,
            evaluation_attempt=evaluation_attempt,
            parent_session_id=parent_session_id,
        )
        return self._ingest_records(handle, records)

    def summarize_task(self, task: TaskHandle | str) -> dict[str, Any]:
        """处理：从不可变事件重建任务用量并保留所有未知/冲突。
        输入：TaskHandle 或当前 usage 根下唯一的 task ID。
        输出：逐 observation 明细、token/call/latency/cost 汇总和覆盖诊断字典。
        """

        handle = self.resolve_task(task)
        with self._task_guard(handle):
            events, observations, sealed_summary = self._load_events(handle)
            return sealed_summary or _summarize_events(handle.task_id, events, observations)

    def finalize_task(
        self,
        task: TaskHandle | str,
        *,
        status: str = "completed",
        completed_at: str | None = None,
    ) -> Path:
        """处理：把当前确定性汇总封存为不可变 task.finalized 事件。
        输入：任务、安全结束状态和可选完成时间。
        输出：finalized 事件路径；封存后拒绝新增 call/usage 事件。
        """

        handle = self.resolve_task(task)
        status_label = _required_label(status, "status")
        completion_timestamp = _timestamp(completed_at)
        with self._task_guard(handle):
            events, observations, _ = self._load_events(handle)
            finalized = [
                event for event in events if event["event_type"] == "task.finalized"
            ]
            if finalized:
                existing = finalized[0]
                if existing["data"]["status"] != status_label:
                    raise RuntimeError(
                        f"Usage task was finalized with another status: {handle.task_id}"
                    )
                if (
                    completed_at is not None
                    and existing["data"]["completed_at"] != completion_timestamp
                ):
                    raise RuntimeError(
                        f"Usage task was finalized with another completion time: "
                        f"{handle.task_id}"
                    )
                return _event_path(handle, existing)
            summary = _summarize_events(
                handle.task_id,
                events,
                observations,
                completed_at_override=completion_timestamp,
            )
            if (
                status_label == "completed"
                and summary["call_lifecycle"]["unclosed_call_count"]
            ):
                raise RuntimeError(
                    f"Cannot finalize completed usage task with unclosed calls: "
                    f"{handle.task_id}"
                )
            return self._write_event_unlocked(
                handle,
                "task.finalized",
                dedupe_key=f"task-finalize:{handle.task_id}",
                data={
                    "status": status_label,
                    "completed_at": completion_timestamp,
                    "summary": summary,
                },
            )

    def resolve_task(self, task: TaskHandle | str) -> TaskHandle:
        """处理：验证句柄归属或按唯一 task ID 定位任务目录。
        输入：TaskHandle 或文件系统安全 task ID。
        输出：属于当前 ledger 的句柄；缺失/重复/跨根句柄会失败。
        """

        if isinstance(task, TaskHandle):
            return self._canonical_task_handle(task)
        task_id = validate_id(task, "task_id")
        handle = self._existing_task_handle(task_id)
        if handle is None:
            raise FileNotFoundError(f"Usage task does not exist: {task_id}")
        return handle

    def _existing_task_handle(self, task_id: str) -> TaskHandle | None:
        """处理：定位已有账本目录并确认任务 ID 唯一。
        输入：创建或查询入口提供的规范任务 ID。
        输出：任务句柄；任务尚未创建时返回 None。
        """
        matches = [path.parent for path in self.usage_root.glob(f"*/{task_id}/events")]
        if not matches:
            return None
        if len(matches) > 1:
            raise ValueError(f"Usage task ID is not unique across dates: {task_id}")
        task_path = matches[0]
        return self._canonical_task_handle(
            TaskHandle(self.data_dir, task_id, task_path.parent.name, task_path)
        )

    def _canonical_task_handle(self, task: TaskHandle) -> TaskHandle:
        """处理：把外部构造的任务句柄约束到当前 ledger 的规范目录。
        输入：可能由调用方保存、恢复或自行构造的 TaskHandle。
        输出：data/date/task 三段均匹配当前 usage 根的规范句柄；越界或伪造路径失败。
        """

        try:
            data_dir = Path(task.data_dir).expanduser().resolve()
            task_path = Path(task.path).expanduser().resolve()
        except (OSError, TypeError) as exc:
            raise ValueError("TaskHandle contains an invalid path") from exc
        if data_dir != self.data_dir:
            raise ValueError("TaskHandle belongs to a different usage ledger")
        task_id = validate_id(task.task_id, "task_id")
        date = _task_date(task.date)
        expected = (self.usage_root / date / task_id).resolve()
        usage_root = self.usage_root.resolve()
        if task_path != expected or not task_path.is_relative_to(usage_root):
            raise ValueError("TaskHandle path does not match its ledger/date/task identity")
        return TaskHandle(self.data_dir, task_id, date, expected)

    @contextmanager
    def _task_guard(self, task: TaskHandle) -> Iterator[None]:
        """处理：以进程内锁和 OS 字节锁串行化一个 task 的读写与封存。
        输入：已通过当前 ledger 规范路径校验的 TaskHandle。
        输出：持锁上下文；进程异常退出时 OS 自动释放，常驻锁文件不产生 stale owner。
        """

        snapshots = getattr(self._transaction_state, "snapshots", None)
        if snapshots is None:
            snapshots = self._transaction_state.snapshots = {}
        if task.task_id in snapshots:
            yield
            return
        with self._task_id_guard(task.task_id):
            snapshots[task.task_id] = None
            try:
                yield
            finally:
                snapshots.pop(task.task_id)

    @contextmanager
    def _task_id_guard(self, task_id: str) -> Iterator[None]:
        """处理：以规范 task ID 获取跨日期共享的线程锁与 OS 文件锁。
        输入：已经通过 validate_id 的 task ID；可在首次 task 目录建立前使用。
        输出：持锁上下文；同 ID 的创建、普通写入和 seal 在所有 UTC 日期上线性化。
        """

        safe_task_id = validate_id(task_id, "task_id")
        lock_path = self.usage_root / ".locks" / f"{safe_task_id}.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        local_lock = _local_task_lock(lock_path)
        with local_lock, lock_path.open("a+b") as lock_file:
            _ensure_lock_byte(lock_file)
            _acquire_file_lock(lock_file)
            try:
                yield
            finally:
                _release_file_lock(lock_file)

    def _adapter(self, adapter: str | UsageAdapter) -> UsageAdapter:
        """处理：解析内置适配器名称或接受符合协议的实例。
        输入：hermes/codex/openclaw 名称或调用方扩展适配器。
        输出：仅执行本地 from_hook/from_path 的适配器实例。
        """

        if not isinstance(adapter, str):
            return adapter
        try:
            adapter_type = DEFAULT_ADAPTERS[adapter.casefold()]
        except KeyError as exc:
            raise ValueError(f"Unsupported usage adapter: {adapter}") from exc
        return adapter_type()

    def _ingest_records(
        self,
        task: TaskHandle,
        records: list[AdapterRecord],
        *,
        call_id: str | None = None,
    ) -> list[Path]:
        """处理：将适配器记录转成统一 usage.observed 事件。
        输入：任务、规范记录和可选本地 call ID。
        输出：不可变事件路径列表；原始外部去重键只以哈希形式持久化。
        """

        safe_call_id = validate_id(call_id, "call_id") if call_id else None
        output: list[Path] = []
        with self._task_guard(task):
            self._open_events(task)
            for record in records:
                data: dict[str, Any] = {"observation": record.observation.to_dict()}
                if safe_call_id is not None:
                    data["call_id"] = safe_call_id
                output.append(
                    self._write_event_unlocked(
                        task,
                        "usage.observed",
                        dedupe_key=f"usage:{record.dedupe_key}",
                        data=data,
                    )
                )
        return output

    def _write_event_unlocked(
        self,
        task: TaskHandle,
        event_type: str,
        *,
        dedupe_key: str,
        data: Mapping[str, Any],
    ) -> Path:
        """处理：在调用方已持有 task guard 时排他创建并核验一个事件。
        输入：规范任务、事件类型、内存去重材料和已脱敏 data。
        输出：新建事件路径，或内容完全一致的既有事件路径；冲突及篡改立即失败。
        """

        if event_type not in EVENT_TYPES:
            raise ValueError(f"Unsupported usage event type: {event_type}")
        dedupe_hash = hash_identifier("event-dedupe", dedupe_key)
        event_id = _event_id(task.task_id, event_type, dedupe_hash)
        payload_hash = f"sha256:{canonical_digest(data)}"
        path = task.path / "events" / f"{event_id}.json"
        event = {
            "schema_version": SCHEMA_VERSION,
            "event_id": f"sha256:{event_id}",
            "event_type": event_type,
            "task_id": task.task_id,
            "recorded_at": _timestamp(None),
            "dedupe_hash": dedupe_hash,
            "payload_hash": payload_hash,
            "data": dict(data),
        }
        _, observation = _validate_event_envelope(task, path, event)
        try:
            result = write_immutable_json(path, event)
            snapshot = getattr(self._transaction_state, "snapshots", {}).get(task.task_id)
            if snapshot is not None:
                insort(snapshot[0], event, key=itemgetter("event_id"))
                if observation is not None:
                    snapshot[1][event["event_id"]] = observation
            return result
        except FileExistsError:
            existing, pending_legacy_hash, _ = _read_validated_event(task, path)
            if pending_legacy_hash:
                raise RuntimeError(
                    f"Legacy finalized event requires full-task validation: {path.name}"
                ) from None
            if (
                existing.get("event_type") == event_type
                and existing.get("dedupe_hash") == dedupe_hash
                and existing.get("payload_hash") == payload_hash
            ):
                return path
            raise RuntimeError(f"Conflicting immutable usage event: {path.name}") from None

    def _events(self, task: TaskHandle) -> list[dict[str, Any]]:
        """处理：按路径顺序读取任务的本地不可变事件。
        输入：已定位 TaskHandle。
        输出：根级对象列表；损坏或非对象事件立即失败而非静默跳过。
        """

        handle = self._canonical_task_handle(task)
        with self._task_guard(handle):
            return self._events_unlocked(handle)

    def _events_unlocked(self, task: TaskHandle) -> list[dict[str, Any]]:
        """处理：读取事务中的事件，供生命周期操作使用。
        输入：持有任务锁的规范 TaskHandle。
        输出：按文件名排序的事件。
        """
        return self._load_events(task)[0]

    def _open_events(self, task: TaskHandle) -> list[dict[str, Any]]:
        """处理：读取未封存任务的持锁快照。
        输入：已规范化并持锁的任务。
        输出：校验后的有序事件，已封存时拒绝写入。
        """
        events, _, sealed = self._load_events(task)
        if sealed is not None:
            raise RuntimeError(f"Usage task is already finalized: {task.task_id}")
        return events

    def _load_events(
        self, task: TaskHandle
    ) -> tuple[list[dict[str, Any]], dict[str, UsageObservation], dict[str, Any] | None]:
        """处理：验证不可变事件并在持锁快照内复用解析完成的观测。
        输入：持有任务锁的规范 TaskHandle。
        输出：按文件名排序的事件、按事件 ID 索引的观测及可用的封存摘要。
        """
        event_dir = task.path / "events"
        snapshots = getattr(self._transaction_state, "snapshots", {})
        if (snapshot := snapshots.get(task.task_id)) is not None:
            return snapshot
        if not event_dir.exists():
            raise FileNotFoundError(f"Usage task has no event directory: {task.task_id}")
        events: list[dict[str, Any]] = []
        observations: dict[str, UsageObservation] = {}
        pending_legacy_hashes: set[str] = set()
        for path in sorted(event_dir.glob("*.json")):
            event, pending_legacy_hash, observation = _read_validated_event(task, path)
            events.append(event)
            if observation is not None:
                observations[event["event_id"]] = observation
            if pending_legacy_hash:
                pending_legacy_hashes.add(event["event_id"])
        summary = _validate_event_set(task, events, observations, pending_legacy_hashes)
        snapshot = (events, observations, summary)
        if task.task_id in snapshots:
            snapshots[task.task_id] = snapshot
        return snapshot


def _correlate_records(
    records: list[AdapterRecord],
    *,
    batch_id: str | None,
    agent_role: str | None,
    run_attempt: int | None,
    repair_attempt: int | None,
    evaluation_attempt: int | None,
    parent_session_id: str | None,
) -> list[AdapterRecord]:
    """处理：把宿主外部传入的工作流关联信息附加到安全 observation。
    输入：适配器记录，以及 batch/Agent/运行/修复/评估次数和可选父会话原始标识。
    输出：只增加短标签、非负整数和父会话哈希的记录；宿主标识原文不会落盘。
    """

    metadata = _correlation_fields(
        batch_id=batch_id, agent_role=agent_role, run_attempt=run_attempt,
        repair_attempt=repair_attempt, evaluation_attempt=evaluation_attempt,
        parent_session_id=parent_session_id,
    )
    if not metadata:
        return records
    return [
        AdapterRecord(record.dedupe_key, replace(record.observation, **metadata))
        for record in records
    ]


def _correlation_fields(
    *, batch_id: str | None, agent_role: str | None, run_attempt: int | None,
    repair_attempt: int | None, evaluation_attempt: int | None, parent_session_id: str | None,
) -> dict[str, Any]:
    """处理：统一规范 call 与 usage 事件的任务关联字段。
    输入：调用方提供的批次、角色、各阶段尝试次数和父会话。
    输出：已验证的短字段和父会话摘要，省略未赋值字段。
    """
    values = {
        "batch_id": _optional_label(batch_id, "batch_id"),
        "agent_role": _optional_label(agent_role, "agent_role"),
        "run_attempt": _optional_non_negative_int(run_attempt, "run_attempt"),
        "repair_attempt": _optional_non_negative_int(repair_attempt, "repair_attempt"),
        "evaluation_attempt": _optional_non_negative_int(evaluation_attempt, "evaluation_attempt"),
        "parent_session_id_hash": (
            hash_identifier("parent-session", parent_session_id)
            if parent_session_id is not None else None
        ),
    }
    return {name: value for name, value in values.items() if value is not None}


def _call_handle_from_data(task: TaskHandle, data: Mapping[str, Any]) -> CallHandle:
    """处理：从写入或重放的 call.started 数据恢复调用句柄。
    输入：规范任务与本地起始事件数据。
    输出：可用于完成和关联 usage 的调用句柄。
    """
    return CallHandle(
        task, data["call_id"], data["phase"], data["started_at"],
        **{name: data.get(name) for name in _CORRELATION_FIELDS},
    )


def _local_task_lock(path: Path) -> threading.RLock:
    """处理：为同一规范锁路径复用进程内可重入锁。
    输入：usage/.locks 下的 task-ID 锁文件路径。
    输出：只负责当前进程线程串行化的 RLock；跨进程互斥另由 OS 文件锁完成。
    """

    key = os.path.normcase(str(path.resolve()))
    with _TASK_LOCKS_GUARD:
        return _TASK_LOCKS.setdefault(key, threading.RLock())


def _ensure_lock_byte(handle: BinaryIO) -> None:
    """处理：确保 Windows 字节区间锁有一个稳定的首字节可锁。
    输入：以追加二进制模式打开的常驻 task 锁文件。
    输出：文件至少含一个字节且游标回到开头；不承载 owner 或业务数据。
    """

    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)


def _acquire_file_lock(handle: BinaryIO) -> None:
    """处理：阻塞获取当前 task 锁文件首字节的跨进程排他锁。
    输入：已确保存在首字节的二进制文件句柄。
    输出：没有业务返回值；返回时 Windows/POSIX 同机进程均不能并发进入临界区。
    """

    if os.name == "nt":
        import msvcrt

        while True:
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                time.sleep(0.01)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _release_file_lock(handle: BinaryIO) -> None:
    """处理：释放 task 锁文件首字节的跨进程排他锁。
    输入：当前进程已经成功持锁的二进制文件句柄。
    输出：没有业务返回值；常驻锁文件保留，进程崩溃时 close 也会由 OS 自动解锁。
    """

    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _event_id(task_id: str, event_type: str, dedupe_hash: str) -> str:
    """处理：从事件身份三元组重建稳定的十六进制事件 ID。
    输入：规范 task ID、受支持事件类型和 SHA-256 去重标签。
    输出：与事件文件名及根级 event_id 一致的 64 位小写十六进制摘要。
    """

    return hashlib.sha256(f"{task_id}\0{event_type}\0{dedupe_hash}".encode()).hexdigest()


def _event_path(task: TaskHandle, event: Mapping[str, Any]) -> Path:
    """处理：把已验证事件的 event_id 映射回当前任务事件路径。
    输入：规范 TaskHandle 和已通过 envelope 校验的事件对象。
    输出：task/events 下与 event_id 完全一致的 JSON 路径。
    """

    return task.path / "events" / f"{str(event['event_id'])[7:]}.json"


def _read_validated_event(
    task: TaskHandle,
    path: Path,
) -> tuple[dict[str, Any], bool, UsageObservation | None]:
    """处理：读取一个事件并验证路径、身份、内容 hash 和事件专属安全结构。
    输入：规范 TaskHandle 与其 events 目录中的候选 JSON 路径。
    输出：事件对象、旧版封存复核标志和已解析的用量观测。
    """

    event = read_json_object(path, "LLM usage event")
    pending_legacy_hash, observation = _validate_event_envelope(task, path, event)
    return event, pending_legacy_hash, observation


def _validate_event_envelope(
    task: TaskHandle,
    path: Path,
    event: Mapping[str, Any],
) -> tuple[bool, UsageObservation | None]:
    """处理：验证单个事件的规范 envelope、派生 ID、payload hash 与 data allowlist。
    输入：任务身份、实际文件路径和解析后的根映射。
    输出：旧版封存复核标志和用于汇总的规范观测。
    """

    try:
        if set(event) != EVENT_ROOT_KEYS:
            raise ValueError("root fields are not the canonical allowlist")
        if event["schema_version"] != SCHEMA_VERSION:
            raise ValueError("schema_version is unsupported")
        event_type = event["event_type"]
        if not isinstance(event_type, str) or event_type not in EVENT_TYPES:
            raise ValueError("event_type is unsupported")
        if event["task_id"] != task.task_id:
            raise ValueError("task_id does not match the task path")
        _canonical_timestamp(event["recorded_at"], "recorded_at")
        dedupe_hash = event["dedupe_hash"]
        payload_hash = event["payload_hash"]
        if not _is_hash_label(dedupe_hash) or not _is_hash_label(payload_hash):
            raise ValueError("dedupe_hash or payload_hash is not SHA-256")
        expected_id = _event_id(task.task_id, event_type, dedupe_hash)
        if event["event_id"] != f"sha256:{expected_id}":
            raise ValueError("event_id does not match task/type/dedupe_hash")
        if path.parent != task.path / "events" or path.name != f"{expected_id}.json":
            raise ValueError("event filename does not match event_id/task path")
        data = event["data"]
        if not isinstance(data, dict):
            raise ValueError("data must be an object")
        observation = _validate_event_data(task, event_type, dedupe_hash, data)
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Invalid LLM usage event structure: {path.name}") from exc

    expected_payload_hash = f"sha256:{canonical_digest(data)}"
    if payload_hash == expected_payload_hash:
        return False, observation
    summary = data.get("summary") if event_type == "task.finalized" else None
    if isinstance(summary, dict) and "timing" not in summary:
        return True, None
    raise RuntimeError(f"LLM usage event payload hash mismatch: {path.name}")


def _validate_event_data(
    task: TaskHandle,
    event_type: str,
    dedupe_hash: str,
    data: Mapping[str, Any],
) -> UsageObservation | None:
    """处理：按事件类型重建安全 data，拒绝额外字段、错误类型和悬空自由文本。
    输入：任务、事件类型、envelope 去重 hash 和 data 映射。
    输出：用量事件的规范观测，用于汇总；不符合持久化契约时抛出 ValueError。
    """

    required, optional, dedupe_format = _EVENT_DATA_FIELDS[event_type]
    if not required.keys() <= data.keys() or data.keys() - required.keys() - optional.keys():
        raise ValueError("event data fields do not match the canonical allowlist")
    normalized = {
        name: validator(data[name], name)
        for fields in (required, optional)
        for name, validator in fields.items()
        if name in data
    }
    observation = None
    if event_type == "usage.observed":
        observation = normalized["observation"]
        normalized["observation"] = observation.to_dict()
    if data != normalized:
        raise ValueError(f"{event_type} data is not canonical")
    if dedupe_format and dedupe_hash != hash_identifier(
        "event-dedupe", dedupe_format.format(task=task.task_id, call=normalized.get("call_id"))
    ):
        raise ValueError(f"{event_type} dedupe hash is not canonical")
    return observation


def _validate_event_set(
    task: TaskHandle,
    events: list[dict[str, Any]],
    observations: Mapping[str, UsageObservation],
    pending_legacy_hashes: set[str],
) -> dict[str, Any] | None:
    """处理：验证 task 事件集合的唯一生命周期根和 finalized 派生摘要。
    输入：任务、逐个已验证事件和待恢复验证的旧版 finalized event_id 集合。
    输出：已重建的封存摘要；开放任务返回空，事件不一致时失败。
    """

    started = [event for event in events if event["event_type"] == "task.started"]
    if len(started) != 1:
        raise RuntimeError(f"Usage task must contain exactly one task.started: {task.task_id}")
    finalized = [event for event in events if event["event_type"] == "task.finalized"]
    if len(finalized) > 1:
        raise RuntimeError(f"Usage task contains multiple finalized seals: {task.task_id}")
    if finalized:
        return _validate_finalized_summary(
            task,
            finalized[0],
            [event for event in events if event["event_type"] != "task.finalized"],
            observations,
            finalized[0]["event_id"] in pending_legacy_hashes,
        )
    _call_lifecycle(events)
    if pending_legacy_hashes:
        raise RuntimeError(f"Usage task contains an invalid legacy event: {task.task_id}")
    return None


def _validate_finalized_summary(
    task: TaskHandle,
    finalized: Mapping[str, Any],
    non_final_events: list[dict[str, Any]],
    observations: Mapping[str, UsageObservation],
    pending_legacy_hash: bool,
) -> dict[str, Any]:
    """处理：重建 finalized summary 并验证旧版兼容投影及缺 timing 的历史 hash。
    输入：任务、唯一 seal、seal 前事件快照和是否存在旧版待验证 payload hash。
    输出：经校验的当前格式摘要，补齐旧版摘要缺少的字段。
    """

    data = dict(finalized["data"])
    expected = _summarize_events(
        task.task_id,
        non_final_events,
        observations,
        completed_at_override=data["completed_at"],
    )
    stored = dict(data["summary"])
    compatible = dict(expected)
    for optional_key in (
        "timing",
        "call_lifecycle",
        "usage_coverage",
        "lineage_coverage",
    ):
        if optional_key not in stored:
            compatible.pop(optional_key, None)
    if stored != compatible:
        # Python 3.12 改变了 float sum；只接受已验证观测按旧顺序累加的延迟值。
        legacy = _summarize_events(
            task.task_id,
            non_final_events,
            observations,
            completed_at_override=data["completed_at"],
            legacy_latency_sum=True,
        )
        compatible["latency_ms"] = legacy["latency_ms"]
        if stored != compatible:
            raise RuntimeError(f"Finalized usage summary does not match events: {task.task_id}")
    if data["status"] == "completed" and expected["call_lifecycle"]["unclosed_call_count"]:
        raise RuntimeError(f"Completed usage task has unclosed calls: {task.task_id}")
    if pending_legacy_hash:
        repaired_summary = dict(stored)
        repaired_summary["timing"] = expected["timing"]
        repaired_data = {**data, "summary": repaired_summary}
        if finalized["payload_hash"] != f"sha256:{canonical_digest(repaired_data)}":
            raise RuntimeError(
                f"Legacy finalized usage payload hash mismatch: {task.task_id}"
            )

    return expected


def _hook_call_id(observation: UsageObservation) -> str | None:
    """处理：把请求级 hook 的安全关联哈希转换成稳定本地 call ID。
    输入：已脱敏且通过模型校验的 usage observation。
    输出：pre/post/error 请求的文件系统安全 ID；聚合或其他 hook 返回 None。
    """

    if observation.granularity != "call" or observation.source_kind not in {
        "pre_api_request",
        "post_api_request",
        "api_request_error",
    }:
        return None
    return f"hook-{observation.correlation_id_hash.removeprefix('sha256:')}"


def _call_event_data(
    events: list[dict[str, Any]],
    event_type: str,
    call_id: str,
) -> dict[str, Any] | None:
    """处理：在已验证快照中查找指定调用的生命周期事件。
    输入：同一任务的事件、生命周期类型和调用 ID。
    输出：已有的 start 或 finish 数据；没有匹配时返回 None。
    """
    return next(
        (event["data"] for event in events
         if event["event_type"] == event_type and event["data"]["call_id"] == call_id),
        None,
    )


def _validate_call_finish(data: Mapping[str, Any], events: list[dict[str, Any]]) -> None:
    """处理：确保待写入的结束边界对应已有调用并且时间顺序正确。
    输入：finish_call 已规范化的事件数据及持锁快照。
    输出：无返回值；缺少起点、阶段不同或时间倒序时抛出 RuntimeError。
    """
    call_id = data["call_id"]
    started = _call_event_data(events, "call.started", call_id)
    if started is None:
        raise RuntimeError(f"Cannot finish call without call.started: {call_id}")
    if started["phase"] != data["phase"]:
        raise RuntimeError(f"Cannot finish call with another phase: {call_id}")
    if datetime.fromisoformat(data["completed_at"]) < datetime.fromisoformat(
        started["started_at"]
    ):
        raise RuntimeError(f"Cannot finish call before it started: {call_id}")


def _string_label(value: object, label: str) -> str:
    """处理：拒绝类型强转并验证一个事件短标签。
    输入：本地事件中的候选值和安全错误字段名。
    输出：原字符串安全标签；数字、对象和自由文本均失败。
    """

    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    return _required_label(value, label)


def _string_id(value: object, label: str) -> str:
    """处理：拒绝类型强转并验证一个事件路径/关联 ID。
    输入：本地事件中的候选值和安全错误字段名。
    输出：原文件系统安全 ID；非字符串或路径穿越形式失败。
    """

    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    return validate_id(value, label)


def _canonical_timestamp(value: object, label: str) -> str:
    """处理：验证事件时间是带时区、秒级且可无损重放的 ISO 文本。
    输入：本地事件时间候选值和安全错误字段名。
    输出：保留原偏移的合法文本；新写入仍使用 UTC，旧版本地偏移事件继续可审计。
    """

    if not isinstance(value, str) or len(value) > 64:
        raise ValueError(f"{label} must be a bounded timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.microsecond:
        raise ValueError(f"{label} must include a timezone at whole-second precision")
    return value


def _is_hash_label(value: object) -> bool:
    """处理：验证根级 hash 是规范 SHA-256 标签而不解析其来源。
    输入：event_id/dedupe_hash/payload_hash 候选值。
    输出：仅 `sha256:` 加 64 位小写十六进制时为 True。
    """

    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _event_object(value: object, label: str) -> dict[str, Any]:
    """处理：读取事件内的 JSON 对象。
    输入：对象候选值和字段名。
    输出：原对象；其他 JSON 类型抛出 ValueError。
    """
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _event_observation(value: object, label: str) -> UsageObservation:
    """处理：从事件对象解析已持久化的用量记录。
    输入：单条事件的观测字段和字段名。
    输出：用于规范化比较及后续汇总的同一条观测。
    """
    return UsageObservation.from_dict(_event_object(value, label))


def _event_hash(value: object, label: str) -> object:
    """处理：验证事件引用的 SHA-256 标签。
    输入：事件哈希字段候选值和字段名。
    输出：合法标签原值。
    """
    if not _is_hash_label(value):
        raise ValueError(f"{label} must be SHA-256")
    return value


def _task_date(value: object) -> str:
    """处理：验证 TaskHandle 日期为规范公历 YYYY-MM-DD。
    输入：调用方构造句柄中的 date 候选值。
    输出：与输入相同的 ISO 日期；类型、格式或不存在日期失败。
    """

    if not isinstance(value, str):
        raise ValueError("TaskHandle date must be a string")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("TaskHandle date must be YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise ValueError("TaskHandle date must be canonical YYYY-MM-DD")
    return value


def _summarize_events(
    task_id: str,
    events: list[dict[str, Any]],
    observations_by_event: Mapping[str, UsageObservation],
    *,
    completed_at_override: str | None = None,
    legacy_latency_sum: bool = False,
) -> dict[str, Any]:
    """处理：从同一持锁快照派生 token、调用生命周期、覆盖率、耗时和成本。
    输入：规范 task ID、已验证事件、完成时间覆盖及仅重放旧延迟累加时的兼容开关。
    输出：unknown-preserving summary；调用事件计数不会伪造任何未知 token 为零。
    """

    usage_events = [event for event in events if event["event_type"] == "usage.observed"]
    observations = [observations_by_event[event["event_id"]] for event in usage_events]
    selected, conflicts = _reconcile_observations(observations)
    token_summary = {
        name: _sum_measurements(getattr(item.tokens, name) for item in selected)
        for name in TOKEN_FIELDS
    }
    accounted = _sum_measurements(item.tokens.accounted_total() for item in selected)
    call_count = _sum_measurements(item.covered_call_count for item in selected)
    tool_call_count = _sum_measurements(item.tool_call_count for item in selected)
    missing_latency = unobservable("latency_dimension_not_exposed")
    latency = {
        name: _sum_measurements((item.latency.get(name, missing_latency) for item in selected),
                                legacy_float_sum=legacy_latency_sum)
        for name in sorted({key for item in selected for key in item.latency})
    }
    lifecycle, started_call_ids = _call_lifecycle(events)
    coverage = _usage_coverage(usage_events, observations, started_call_ids, call_count)
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "timing": _task_timing(events, completed_at_override=completed_at_override),
        "observation_count": len(selected),
        "raw_observation_count": len(observations),
        "deduplicated_observation_count": len(observations) - len(selected),
        "conflicts": conflicts,
        "call_lifecycle": lifecycle,
        "usage_coverage": coverage,
        "lineage_coverage": _lineage_coverage(selected),
        "covered_call_count": call_count,
        "tool_call_count": tool_call_count,
        "tokens": {**token_summary, "accounted_total": accounted},
        "latency_ms": latency,
        "costs": _sum_costs(selected),
        "observations": [item.to_dict() for item in selected],
    }


def _call_lifecycle(
    events: list[dict[str, Any]],
) -> tuple[dict[str, int], set[str]]:
    """处理：配对 call.started/call.finished 并报告失败、未闭合和孤立结束记录。
    输入：同一任务内已经完成单事件结构验证的事件快照。
    输出：不含 call ID 的精确计数字典，以及供 usage linkage 使用的 started call ID 集合。
    """

    started: dict[str, Mapping[str, Any]] = {}
    finished: dict[str, Mapping[str, Any]] = {}
    for event in events:
        if event["event_type"] not in {"call.started", "call.finished"}:
            continue
        data = event["data"]
        call_id = data["call_id"]
        target = started if event["event_type"] == "call.started" else finished
        if call_id in target:
            raise RuntimeError(f"Duplicate {event['event_type']} lifecycle event")
        target[call_id] = data
    for call_id in started.keys() & finished.keys():
        if started[call_id]["phase"] != finished[call_id]["phase"]:
            raise RuntimeError("Call lifecycle phase mismatch")
        start_time = datetime.fromisoformat(started[call_id]["started_at"])
        finish_time = datetime.fromisoformat(finished[call_id]["completed_at"])
        if finish_time < start_time:
            raise RuntimeError("Call lifecycle completed before it started")
    failed = sum(
        str(data["status"]).casefold() not in SUCCESS_CALL_STATUSES
        for data in finished.values()
    )
    lifecycle = {
        "attempted_call_count": len(started),
        "finished_call_count": len(finished),
        "failed_call_count": failed,
        "unclosed_call_count": len(started.keys() - finished.keys()),
        "orphan_finished_call_count": len(finished.keys() - started.keys()),
    }
    return lifecycle, set(started)


def _usage_coverage(
    usage_events: list[dict[str, Any]],
    observations: list[UsageObservation],
    started_call_ids: set[str],
    covered_call_count: Mapping[str, Any],
) -> dict[str, Any]:
    """处理：关联本地 call ID 与 usage observations，并区分 token 可观测性。
    输入：usage 事件、同序已解析 observations、started call ID 和 covered-call 测量。
    输出：精确 linkage 计数及保持 unknown 的 usage_covered_call_count 测量。
    """

    observed_call_ids: set[str] = set()
    accounted_call_ids: set[str] = set()
    unlinked_observations = 0
    for event, observation in zip(usage_events, observations, strict=True):
        call_id = event["data"].get("call_id")
        if call_id is None:
            unlinked_observations += 1
            continue
        observed_call_ids.add(call_id)
        if observation.tokens.accounted_total().value is not None:
            accounted_call_ids.add(call_id)
    return {
        "usage_covered_call_count": dict(covered_call_count),
        "calls_with_observation_count": len(started_call_ids & observed_call_ids),
        "calls_with_accounted_tokens_count": len(
            started_call_ids & accounted_call_ids
        ),
        "calls_without_observation_count": len(started_call_ids - observed_call_ids),
        "calls_without_accounted_tokens_count": len(
            started_call_ids - accounted_call_ids
        ),
        "orphan_usage_call_count": len(observed_call_ids - started_call_ids),
        "unlinked_observation_count": unlinked_observations,
    }


def _lineage_coverage(observations: list[UsageObservation]) -> dict[str, Any]:
    """处理：报告每个工作流关联字段的覆盖数量与安全阶段分布。
    输入：去重后的规范 usage observations。
    输出：只含计数和短标签的覆盖摘要；缺失字段保持为缺失计数而非推断默认值。
    """

    fields = (
        "phase",
        "agent_role",
        "batch_id",
        "run_attempt",
        "repair_attempt",
        "evaluation_attempt",
        "session_id_hash",
        "parent_session_id_hash",
    )
    total = len(observations)
    present = {
        name: sum(getattr(item, name) is not None for item in observations)
        for name in fields
    }
    by_phase: dict[str, int] = defaultdict(int)
    for observation in observations:
        if observation.phase is not None:
            by_phase[observation.phase] += 1
    return {
        "observation_count": total,
        "fields": {
            name: {"present": count, "missing": total - count}
            for name, count in present.items()
        },
        "by_phase": dict(sorted(by_phase.items())),
    }


def ingest_hook_from_env(
    payload: Mapping[str, Any] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stdin: TextIO | None = None,
) -> list[Path]:
    """处理：供宿主 hook 从环境定位账本并安全消费 stdin JSON。
    输入：可选 payload；否则读取至多 1 MiB stdin，并读取账本、任务和工作流关联环境变量。
    输出：usage.observed 路径；不打印 payload，缺少必需环境变量时明确失败。
    """

    env = os.environ if environ is None else environ
    root = env.get("SIGNALTRAIL_USAGE_LEDGER")
    task_id = env.get("SIGNALTRAIL_USAGE_TASK")
    if not root or not task_id:
        raise ValueError(
            "SIGNALTRAIL_USAGE_LEDGER and SIGNALTRAIL_USAGE_TASK are required"
        )
    selected_payload = payload
    if selected_payload is None:
        stream = stdin if stdin is not None else sys.stdin
        content = stream.read(MAX_HOOK_BYTES + 1)
        if len(content.encode("utf-8")) > MAX_HOOK_BYTES:
            raise ValueError(f"Hook payload exceeds {MAX_HOOK_BYTES} bytes")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError("Hook stdin must be one JSON object") from exc
        if not isinstance(parsed, dict):
            raise ValueError("Hook stdin must be one JSON object")
        selected_payload = parsed
    return UsageLedger(root).ingest_hook(
        task_id,
        env.get("SIGNALTRAIL_USAGE_ADAPTER", "hermes"),
        selected_payload,
        phase=env.get("SIGNALTRAIL_USAGE_PHASE"),
        call_id=env.get("SIGNALTRAIL_USAGE_CALL"),
        source_event_id=env.get("SIGNALTRAIL_USAGE_EVENT"),
        **{name: env.get(key) for name, key in USAGE_CORRELATION_ENV.items()},
    )


def _reconcile_observations(
    observations: list[UsageObservation],
) -> tuple[list[UsageObservation], list[dict[str, Any]]]:
    """处理：按哈希调用身份去重，并显式报告 exact 数值冲突。
    输入：任务中的规范 observations。
    输出：每个关联键的最佳记录及不包含原始内容的冲突诊断。
    """

    groups: dict[str, list[UsageObservation]] = defaultdict(list)
    for item in observations:
        groups[item.correlation_id_hash].append(item)
    selected: list[UsageObservation] = []
    conflicts: list[dict[str, Any]] = []
    for correlation, group in sorted(groups.items()):
        exact_conflicts = _token_conflicts(group)
        if exact_conflicts:
            conflicts.append(
                {"correlation_id_hash": correlation, "fields": exact_conflicts}
            )
        selected.append(max(group, key=_observation_score))
    return selected, conflicts


def _observation_score(observation: UsageObservation) -> tuple[int, int, int]:
    """处理：为同一调用的多个宿主回执建立确定性优先级。
    输入：一个规范 observation。
    输出：exact 字段数、可观测字段数和逐调用粒度组成的排序元组。
    """

    measurements = [
        *(getattr(observation.tokens, name) for name in TOKEN_FIELDS),
        observation.covered_call_count,
        observation.tool_call_count,
        *observation.latency.values(),
    ]
    exact_count = sum(item.quality is ObservationQuality.EXACT for item in measurements)
    observed_count = sum(item.value is not None for item in measurements)
    return exact_count, observed_count, int(observation.granularity == "call")


def _token_conflicts(group: list[UsageObservation]) -> list[str]:
    """处理：识别同一关联键上互不相同的 exact token 数值。
    输入：同一 correlation_id_hash 的 observations。
    输出：发生冲突的 token 字段名；未知和估算不会伪造成冲突。
    """

    conflicts: list[str] = []
    for name in TOKEN_FIELDS:
        values = {
            getattr(item.tokens, name).value
            for item in group
            if getattr(item.tokens, name).quality is ObservationQuality.EXACT
        }
        if len(values) > 1:
            conflicts.append(name)
    return conflicts


def _sum_measurements(
    values: Iterable[Measurement], *, legacy_float_sum: bool = False
) -> dict[str, Any]:
    """处理：汇总字段测量，同时让任一未知值使总量保持不可观测。
    输入：同一字段的观测序列；复核历史耗时时保留旧版浮点累加顺序。
    输出：value/quality、已知上下界和未知观测数；unknown 永远不会变成零。
    """

    numbers = []
    unknown_count = 0
    estimated = False
    for value in values:
        if value.value is None:
            unknown_count += 1
        else:
            numbers.append(value.value)
            estimated |= value.quality is ObservationQuality.ESTIMATED
    if not numbers:
        known_total = None
    elif legacy_float_sum:
        # 保持旧封存摘要的浮点累加顺序。
        known_total = 0
        for number in numbers:
            known_total += number
    elif any(isinstance(number, float) for number in numbers):
        known_total = float(sum((Decimal(str(number)) for number in numbers), Decimal(0)))
    else:
        known_total = sum(numbers)

    reason = None
    if not numbers and not unknown_count:
        reason = "no_observations"
    elif unknown_count:
        reason = "one_or_more_observations_unobservable"
    if reason:
        return {
            "value": None, "quality": "unobservable", "reason": reason,
            "known_value": known_total, "unobservable_observations": unknown_count,
        }
    return {
        "value": known_total,
        "quality": "estimated" if estimated else "exact",
        "known_value": known_total,
        "unobservable_observations": 0,
    }


def _task_timing(
    events: list[dict[str, Any]],
    *,
    completed_at_override: str | None = None,
) -> dict[str, Any]:
    """处理：从任务生命周期事件计算耗时，开放任务绝不以当前时刻代替结束。
    输入：本地事件列表；finalize 可传入将写入同一事件的规范完成时间。
    输出：开始/完成 UTC 时间和 unknown-preserving wall_ms 汇总。
    """

    # 事件校验已保证唯一 task.started 及合法、带时区的生命周期时间。
    start = next(event["data"]["started_at"] for event in events
                 if event["event_type"] == "task.started")
    end = completed_at_override or next(
        (event["data"]["completed_at"] for event in events
         if event["event_type"] == "task.finalized"), None,
    )
    started_at, completed_at = normalize_timestamp(start), normalize_timestamp(end)
    if completed_at is None:
        wall_ms = _unobservable_aggregate("task_not_finalized")
    elif completed_at < started_at:
        wall_ms = _unobservable_aggregate("task_completed_before_started")
    else:
        elapsed = datetime.fromisoformat(completed_at) - datetime.fromisoformat(started_at)
        value = round(elapsed.total_seconds() * 1000, 3)
        wall_ms = {
            "value": value,
            "quality": "exact",
            "known_value": value,
            "unobservable_observations": 0,
        }
    return {
        "started_at": started_at,
        "completed_at": completed_at,
        "wall_ms": wall_ms,
    }


def _unobservable_aggregate(reason: str) -> dict[str, Any]:
    """处理：构造不会把未知任务耗时伪装成零的汇总测量。
    输入：描述生命周期缺口的稳定原因标签。
    输出：value/known_value 均为 None 的 unobservable aggregate。
    """

    return {
        "value": None,
        "quality": "unobservable",
        "reason": reason,
        "known_value": None,
        "unobservable_observations": 1,
    }


def _sum_costs(observations: list[UsageObservation]) -> list[dict[str, Any]]:
    """处理：按币种汇总成本并保留未报告金额的 observation 数。
    输入：去重后的 observations。
    输出：每币种十进制已知金额及总体未知数；不会把未知成本改成 0。
    """

    totals: dict[str, Decimal] = defaultdict(Decimal)
    qualities: dict[str, set[ObservationQuality]] = defaultdict(set)
    unknown_count = 0
    for item in observations:
        cost = item.cost
        if cost.amount is None or cost.currency is None:
            unknown_count += 1
            continue
        totals[cost.currency] += Decimal(cost.amount)
        qualities[cost.currency].add(cost.quality)
    output = [
        {
            "currency": currency,
            "amount": format(amount, "f"),
            "quality": (
                "unobservable"
                if unknown_count
                else (
                    "estimated"
                    if ObservationQuality.ESTIMATED in qualities[currency]
                    else "exact"
                )
            ),
            "unobservable_observations": unknown_count,
        }
        for currency, amount in sorted(totals.items())
    ]
    if not output:
        output.append(
            {
                "currency": None,
                "amount": None,
                "quality": "unobservable",
                "unobservable_observations": unknown_count,
            }
        )
    return output


def _timestamp(value: str | None) -> str:
    """处理：生成或验证带时区的秒级 ISO 时间。
    输入：可选调用方时间；None 使用当前 UTC。
    输出：规范 ISO 字符串；无时区或非法时间明确失败。
    """

    if value is None:
        return datetime.now(UTC).isoformat(timespec="seconds")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(UTC).isoformat(timespec="seconds")


def _required_label(value: str, label: str) -> str:
    """处理：要求生命周期元数据是受限短标签。
    输入：候选值和错误字段名。
    输出：安全标签；自由文本和潜在秘密被拒绝。
    """

    result = safe_label(value)
    if result is None:
        raise ValueError(f"{label} must be a bounded safe label")
    return result


def _optional_label(value: str | None, label: str) -> str | None:
    """处理：校验可选工作流短标签而不把自由文本写入账本。
    输入：可选标签值及错误字段名。
    输出：缺失时为 None；存在时为 safe_label 认可的规范字符串。
    """

    return None if value is None else _required_label(value, label)


def _optional_non_negative_int(value: int | str | None, label: str) -> int | None:
    """处理：把环境变量或 API 参数中的可选次数转成非负整数。
    输入：run/repair/evaluation attempt 候选值及字段名。
    输出：缺失时为 None；合法整数原值，否则抛出不回显输入的 ValueError。
    """

    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a non-negative integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a non-negative integer") from exc
    if parsed < 0 or str(value).strip() not in {str(parsed), f"+{parsed}"}:
        raise ValueError(f"{label} must be a non-negative integer")
    return parsed


_EventField = Callable[[Any, str], Any]
_EVENT_DATA_FIELDS: dict[str, tuple[dict[str, _EventField], dict[str, _EventField], str]] = {
    "task.started": (
        {"agent": _string_label, "started_at": _canonical_timestamp},
        {"source_tag": _string_label, "parent_task_id": _string_id},
        "task-start:{task}",
    ),
    "call.started": (
        {"call_id": _string_id, "phase": _string_label, "started_at": _canonical_timestamp},
        {
            "adapter": _string_label,
            **dict.fromkeys(_CORRELATION_LABELS, _string_label),
            **dict.fromkeys(_CORRELATION_ATTEMPTS, _optional_non_negative_int),
            "parent_session_id_hash": _event_hash,
        },
        "call-start:{call}",
    ),
    "call.finished": (
        {
            "call_id": _string_id, "phase": _string_label, "status": _string_label,
            "completed_at": _canonical_timestamp,
        },
        {},
        "call-finish:{call}",
    ),
    "usage.observed": ({"observation": _event_observation}, {"call_id": _string_id}, ""),
    "task.finalized": (
        {"status": _string_label, "completed_at": _canonical_timestamp, "summary": _event_object},
        {},
        "task-finalize:{task}",
    ),
}
EVENT_TYPES = frozenset(_EVENT_DATA_FIELDS)
