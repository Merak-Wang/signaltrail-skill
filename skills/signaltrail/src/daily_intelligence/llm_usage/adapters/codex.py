from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..models import (
    TOKEN_FIELDS,
    AdapterRecord,
    TokenRelation,
    TokenUsage,
    UsageObservation,
    exact,
    safe_label,
)
from .base import (
    canonical_digest,
    cost_from_mapping,
    delta_tokens,
    hash_identifier,
    latency_from_payload,
    lineage_hashes,
    nested_mapping,
    nested_value,
    parse_jsonl_bytes,
    read_bounded_bytes,
    safe_observation_labels,
    tokens_from_usage,
    tool_call_count_from_payload,
)


@dataclass(frozen=True, slots=True)
class _SessionContext:
    """处理：保存 Codex session header 的安全继承上下文。
    输入：只含不可逆 lineage 哈希和受限 provider/model 标签。
    输出：供后续 token_count 行复用的内存状态，不保留原始宿主 ID 或正文。
    """

    session_id_hash: str | None
    parent_session_id_hash: str | None
    host_task_id_hash: str | None
    provider: str | None
    requested_model: str | None
    served_model: str | None


class CodexAdapter:
    """处理：规范 Codex rollout JSONL 中的 token usage 事件。
    输入：单条 hook 映射或调用方指定的本地 rollout JSONL。
    输出：逐调用/增量 AdapterRecord；消息正文、reasoning 和工具参数不会离开内存。
    """

    name = "codex"
    version = "1.0"

    def from_hook(
        self,
        payload: Mapping[str, Any],
        *,
        phase: str | None = None,
        call_id: str | None = None,
        source_event_id: str | None = None,
    ) -> list[AdapterRecord]:
        """处理：从 Codex token_count/hook 对象提取一条安全 usage 记录。
        输入：宿主 payload、可选 phase、call ID 和事件 ID；只读取固定 usage 路径。
        输出：一条规范记录；找不到受支持的 usage 对象时抛出 ValueError。
        """

        usage, source_kind = _usage_mapping(payload)
        if usage is None:
            raise ValueError("Codex payload has no supported usage object")
        raw_identity = source_event_id or nested_value(
            payload,
            ("id",),
            ("event_id",),
            ("payload", "id"),
            ("payload", "call_id"),
        )
        if raw_identity is None:
            raw_identity = canonical_digest(_safe_usage_signature(usage, payload))
        lineage = lineage_hashes(payload, "codex")
        identity = _scoped_identity(lineage["session_id_hash"], raw_identity)
        dedupe_identity = _scoped_identity(
            lineage["session_id_hash"],
            call_id or raw_identity,
        )
        observation = _observation(
            payload,
            usage,
            source_kind=source_kind,
            identity=identity,
            phase=phase,
            lineage=lineage,
        )
        return [
            AdapterRecord(
                dedupe_key=f"codex-hook:{dedupe_identity}",
                observation=observation,
            )
        ]

    def from_path(
        self,
        path: Path,
        *,
        phase: str | None = None,
    ) -> list[AdapterRecord]:
        """处理：导入 Codex rollout JSONL，并把累计快照转成非负增量。
        输入：调用方指定的只读 JSONL 路径和可选 phase。
        输出：每个 usage 行一条稳定去重记录；纯消息行被忽略且不持久化。
        """

        records: list[AdapterRecord] = []
        current_context: _SessionContext | None = None
        previous_cumulative: dict[str, TokenUsage] = {}
        seen_events: set[str] = set()
        file_scope = hash_identifier("codex-rollout-file", path.resolve())
        rows = parse_jsonl_bytes(read_bounded_bytes(path), "Codex rollout")
        for _, payload, line_identity in rows:
            if (header := _session_context_from_header(payload)) is not None:
                current_context = header
                continue

            last, cumulative, direct = _usage_mappings(payload)
            if last is None and cumulative is None and direct is None:
                continue

            lineage = _effective_lineage(payload, current_context)
            session_scope = lineage["session_id_hash"] or file_scope
            snapshot = cumulative or last or direct
            if snapshot is None:
                continue
            identity = _rollout_event_identity(
                payload,
                snapshot,
                session_scope=session_scope,
                line_identity=line_identity,
            )
            if identity in seen_events:
                continue
            seen_events.add(identity)

            if cumulative is not None:
                current = _tokens_from_codex_usage(cumulative)
                previous = previous_cumulative.get(session_scope)
                incremental = _cumulative_increment(
                    current,
                    previous,
                    first_last_usage=last,
                )
                previous_cumulative[session_scope] = current
                if not _has_positive_tokens(incremental):
                    continue
                usage = last or cumulative
                source_kind = "rollout_cumulative_delta"
                tokens = incremental
            else:
                usage = last or direct
                if usage is None:
                    continue
                source_kind = "rollout_last_usage" if last is not None else "rollout_usage"
                tokens = _tokens_from_codex_usage(usage)

            observation = _observation(
                payload,
                usage,
                source_kind=source_kind,
                identity=identity,
                phase=phase,
                tokens=tokens,
                lineage=lineage,
                inherited=current_context,
            )
            records.append(
                AdapterRecord(
                    dedupe_key=f"codex-rollout:{identity}",
                    observation=observation,
                )
            )
        return records


def _usage_mapping(
    payload: Mapping[str, Any],
) -> tuple[Mapping[str, Any] | None, str]:
    """处理：仅从 Codex 已知 token_count 路径选择逐次或累计 usage。
    输入：一行 rollout 对象或 hook payload。
    输出：usage 映射及其计数语义；不会递归扫描对话内容。
    """

    last, cumulative, direct = _usage_mappings(payload)
    if last is not None:
        return last, "rollout_last_usage"
    if cumulative is not None:
        return cumulative, "rollout_cumulative_usage"
    return direct, "rollout_usage"


def _usage_mappings(
    payload: Mapping[str, Any],
) -> tuple[
    Mapping[str, Any] | None,
    Mapping[str, Any] | None,
    Mapping[str, Any] | None,
]:
    """处理：同时读取 Codex 的 last、cumulative 和 direct usage 槽位。
    输入：单条 rollout/hook 映射；只访问官方及兼容格式的固定字段路径。
    输出：三个独立映射，供文件导入用 cumulative 状态判重而不丢弃 last 回执。
    """

    last = nested_mapping(
        payload,
        ("last_token_usage",),
        ("payload", "last_token_usage"),
        ("payload", "info", "last_token_usage"),
        ("info", "last_token_usage"),
    )
    cumulative = nested_mapping(
        payload,
        ("total_token_usage",),
        ("payload", "total_token_usage"),
        ("payload", "info", "total_token_usage"),
        ("info", "total_token_usage"),
    )
    direct = nested_mapping(
        payload,
        ("usage",),
        ("payload", "usage"),
        ("response", "usage"),
    )
    return last, cumulative, direct


def _observation(
    payload: Mapping[str, Any],
    usage: Mapping[str, Any],
    *,
    source_kind: str,
    identity: object,
    phase: str | None,
    tokens: TokenUsage | None = None,
    lineage: Mapping[str, str | None] | None = None,
    inherited: _SessionContext | None = None,
) -> UsageObservation:
    """处理：把已选中的 Codex usage 映射规范化为安全 observation。
    输入：原行、usage 数字、计数语义、仅用于哈希的身份和 phase。
    输出：call 粒度的 UsageObservation；输出细分永远只作 output 子集。
    """

    labels = safe_observation_labels(payload)
    resolved_tokens = tokens or _tokens_from_codex_usage(usage)
    resolved_lineage = dict(lineage or lineage_hashes(payload, "codex"))
    return UsageObservation(
        adapter="codex",
        adapter_version="1.0",
        source_kind=source_kind,
        correlation_id_hash=hash_identifier("codex-call", identity),
        granularity="call",
        covered_call_count=exact(1, "codex_rollout", "usage_event_count_v1"),
        tokens=resolved_tokens,
        tool_call_count=tool_call_count_from_payload(
            payload,
            source="codex_rollout",
        ),
        cost=cost_from_mapping(
            nested_mapping(usage, ("cost",))
            or nested_mapping(payload, ("cost",)),
            source="codex_rollout",
        ),
        provider=labels["provider"] or (inherited.provider if inherited else None) or "openai",
        requested_model=labels["requested_model"]
        or (inherited.requested_model if inherited else None),
        served_model=labels["served_model"] or (inherited.served_model if inherited else None),
        phase=safe_label(phase),
        status=labels["status"],
        finish_reason=labels["finish_reason"],
        completed_at=_safe_timestamp(payload),
        latency=latency_from_payload(payload, "codex_rollout"),
        **resolved_lineage,
    )


def _safe_usage_signature(
    usage: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """处理：为缺少事件 ID 的 Codex hook 构造只含 usage 与短标签的身份材料。
    输入：已选择的 usage 映射和宿主 payload。
    输出：不含消息或工具内容的规范字典，供哈希去重。
    """

    tokens = _tokens_from_codex_usage(usage)
    labels = safe_observation_labels(payload)
    return {"tokens": tokens.to_dict(), "labels": labels}


def _tokens_from_codex_usage(usage: Mapping[str, Any]) -> TokenUsage:
    """处理：按 Codex/OpenAI 包含关系规范一个 usage 数字映射。
    输入：last、total 或 direct usage 槽位中的 allowlist 数字。
    输出：cached/cache-write 均作为 input 子集的 TokenUsage；缺字段仍不可观测。
    """

    return tokens_from_usage(
        usage,
        source="codex_rollout",
        cached_relation=TokenRelation.SUBSET,
        cache_write_relation=TokenRelation.SUBSET,
    )


def _session_context_from_header(payload: Mapping[str, Any]) -> _SessionContext | None:
    """处理：从 session_meta/session header 提取可继承且无明文 ID 的上下文。
    输入：一条 JSONL 映射；仅读取固定 header 类型、ID、父线程和模型字段。
    输出：安全上下文；非 header 返回 None，正文和动态工具配置不会被扫描。
    """

    header_types = {
        value.casefold()
        for value in (
            nested_value(payload, ("type",)),
            nested_value(payload, ("payload", "type")),
        )
        if isinstance(value, str)
    }
    if not header_types.intersection({
        "session",
        "session_header",
        "session_meta",
        "session_start",
    }):
        return None

    current_id = nested_value(
        payload,
        ("payload", "id"),
        ("payload", "thread_id"),
        ("id",),
        ("thread_id",),
        ("payload", "session_id"),
        ("session_id",),
    )
    root_session_id = nested_value(
        payload,
        ("payload", "session_id"),
        ("session_id",),
    )
    parent_id = nested_value(
        payload,
        ("payload", "parent_thread_id"),
        ("payload", "parent_session_id"),
        ("parent_thread_id",),
        ("parent_session_id",),
    )
    if parent_id is None and _different_identifiers(current_id, root_session_id):
        parent_id = root_session_id
    task_id = nested_value(payload, ("payload", "task_id"), ("task_id",))
    return _SessionContext(
        session_id_hash=_optional_identifier_hash("codex-session_id_hash", current_id),
        parent_session_id_hash=_optional_identifier_hash(
            "codex-parent_session_id_hash",
            parent_id,
        ),
        host_task_id_hash=_optional_identifier_hash("codex-host_task_id_hash", task_id),
        provider=safe_label(
            nested_value(
                payload,
                ("payload", "model_provider"),
                ("payload", "provider"),
                ("model_provider",),
                ("provider",),
            )
        ),
        requested_model=safe_label(
            nested_value(
                payload,
                ("payload", "requested_model"),
                ("payload", "model"),
                ("requested_model",),
                ("model",),
            )
        ),
        served_model=safe_label(
            nested_value(
                payload,
                ("payload", "served_model"),
                ("payload", "response_model"),
                ("served_model",),
                ("response_model",),
            )
        ),
    )


def _effective_lineage(
    payload: Mapping[str, Any],
    inherited: _SessionContext | None,
) -> dict[str, str | None]:
    """处理：把行内 lineage 与最近 session header 的哈希上下文合并。
    输入：当前 usage 行和可选 header 上下文；header 的线程身份优先。
    输出：四个 schema lineage 哈希；任何宿主原始 ID 均不会返回。
    """

    direct = lineage_hashes(payload, "codex")
    if inherited is None:
        return direct
    return {
        "session_id_hash": inherited.session_id_hash or direct["session_id_hash"],
        "turn_id_hash": direct["turn_id_hash"],
        "parent_session_id_hash": inherited.parent_session_id_hash
        or direct["parent_session_id_hash"],
        "host_task_id_hash": inherited.host_task_id_hash or direct["host_task_id_hash"],
    }


def _optional_identifier_hash(namespace: str, value: object) -> str | None:
    """处理：只哈希短标量宿主 ID，拒绝把任意对象当成 lineage。
    输入：固定哈希命名空间和 header 固定路径读出的候选值。
    输出：SHA-256 标签或 None；原始 ID 只在本次调用内存在。
    """

    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value)
    if not 1 <= len(text) <= 256 or "\n" in text or "\r" in text:
        return None
    return hash_identifier(namespace, text)


def _different_identifiers(left: object, right: object) -> bool:
    """处理：安全判断两个候选 header ID 是否是不同短标量。
    输入：当前线程和根 session 固定字段的内存值。
    输出：两者均合法且不同时为 True；不序列化或返回任一原始值。
    """

    left_hash = _optional_identifier_hash("codex-header-compare", left)
    right_hash = _optional_identifier_hash("codex-header-compare", right)
    return left_hash is not None and right_hash is not None and left_hash != right_hash


def _scoped_identity(session_id_hash: str | None, identity: object) -> str:
    """处理：为 hook 调用构造包含 session 范围的无明文身份摘要。
    输入：可选 session 哈希和只在内存使用的 call/event 身份。
    输出：稳定十六进制摘要；相同外部 ID 在不同子 session 不会碰撞。
    """

    return canonical_digest(
        {
            "session_id_hash": session_id_hash,
            "source_event_id_hash": hash_identifier("codex-source-event", identity),
        }
    )


def _rollout_event_identity(
    payload: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    *,
    session_scope: str,
    line_identity: str,
) -> str:
    """处理：为 token_count 快照生成跨路径、跨行号稳定的 session-scoped 摘要。
    输入：当前行、累计/逐次 usage、哈希 session 范围和仅含哈希的行后备身份。
    输出：不含原始 ID/正文的摘要；同 session 重叠导入幂等，不同 session 隔离。
    """

    raw_event_id = nested_value(
        payload,
        ("id",),
        ("event_id",),
        ("payload", "id"),
        ("payload", "call_id"),
    )
    event_id_hash = _optional_identifier_hash("codex-source-event", raw_event_id)
    timestamp = _safe_timestamp(payload)
    timestamp_hash = (
        hash_identifier("codex-event-timestamp", timestamp) if timestamp is not None else None
    )
    material: dict[str, Any] = {
        "session_id_hash": session_scope,
        "source_event_id_hash": event_id_hash,
        "timestamp_hash": timestamp_hash,
        "cumulative_snapshot": _tokens_from_codex_usage(snapshot).to_dict(),
    }
    if event_id_hash is None and timestamp_hash is None:
        material["line_identity"] = line_identity
    return canonical_digest(material)


def _cumulative_increment(
    current: TokenUsage,
    previous: TokenUsage | None,
    *,
    first_last_usage: Mapping[str, Any] | None,
) -> TokenUsage:
    """处理：把单个 session 的累计快照转换为安全非负增量。
    输入：当前/上一累计量及首个快照可用的 last 回执。
    输出：正常增长用累计 delta；计数器回退视为新段；截断导入首行优先 last。
    """

    if previous is None:
        if first_last_usage is not None:
            last = _tokens_from_codex_usage(first_last_usage)
            if _has_positive_tokens(last):
                return _as_cumulative_delta(last)
        return _as_cumulative_delta(current)
    if _cumulative_counter_reset(current, previous):
        return _as_cumulative_delta(current)
    return delta_tokens(current, previous)


def _as_cumulative_delta(tokens: TokenUsage) -> TokenUsage:
    """处理：把首段/重置段规范成与普通累计差值相同的测量来源。
    输入：首个 last/total 或计数器回退后的完整当前段。
    输出：数值不变且 method 为 cumulative_delta_v1 的 TokenUsage，保证重叠导入一致。
    """

    zero = TokenUsage(
        **{
            name: exact(0, "derived", "cumulative_zero_v1")
            for name in TOKEN_FIELDS
        },
        cached_input_relation=tokens.cached_input_relation,
        cache_write_input_relation=tokens.cache_write_input_relation,
    )
    return delta_tokens(tokens, zero)


def _cumulative_counter_reset(current: TokenUsage, previous: TokenUsage) -> bool:
    """处理：识别任一可观测累计 token 计数器回退。
    输入：同一哈希 session 相邻累计快照。
    输出：出现回退时 True，使整个当前快照作为新累计段而非逐字段混合相减。
    """

    for name in TOKEN_FIELDS:
        now = getattr(current, name).value
        before = getattr(previous, name).value
        if now is not None and before is not None and int(now) < int(before):
            return True
    return False


def _has_positive_tokens(tokens: TokenUsage) -> bool:
    """处理：判定一个累计 delta 是否包含任何已观测 token 增长。
    输入：规范 TokenUsage；未知字段保持未知且不被当成零值写入账本。
    输出：至少一个 token 字段大于零时 True；全零/全未知快照为 False。
    """

    return any(
        measurement.value is not None and int(measurement.value) > 0
        for measurement in (getattr(tokens, name) for name in TOKEN_FIELDS)
    )


def _safe_timestamp(payload: Mapping[str, Any]) -> str | None:
    """处理：从 Codex 固定时间字段选择长度受限的字符串。
    输入：rollout 行映射。
    输出：安全时间文本或 None；正文中的时间样式文本不会被扫描。
    """

    value = nested_value(payload, ("timestamp",), ("payload", "timestamp"))
    if isinstance(value, str) and 1 <= len(value) <= 64 and "\n" not in value:
        return value
    return None
