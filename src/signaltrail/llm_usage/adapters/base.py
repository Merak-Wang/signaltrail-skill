from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol

from ..models import (
    AdapterRecord,
    CostMeasurement,
    Measurement,
    ObservationQuality,
    TokenRelation,
    TokenUsage,
    UsageObservation,
    exact,
    safe_label,
    unknown_cost,
    unobservable,
)

MAX_USAGE_FILE_BYTES = 64 * 1024 * 1024


class UsageAdapter(Protocol):
    """处理：定义宿主 hook 与本地 usage 文件的纯解析接口。
    输入：宿主提供的内存映射或只读文件路径，不接收网络客户端和凭据。
    输出：仅含安全 allowlist 数值与短标签的 AdapterRecord 序列。
    """

    name: str
    version: str

    def from_hook(
        self,
        payload: Mapping[str, Any],
        *,
        phase: str | None = None,
        call_id: str | None = None,
        source_event_id: str | None = None,
    ) -> list[AdapterRecord]:
        """处理：将单次宿主 Hook 转为允许持久化的用量记录。
        输入：payload 来自宿主；phase、call_id、source_event_id 由调用方补充关联信息。
        输出：只含允许字段的记录序列，供账本去重并追加事件。
        """
        ...

    def from_path(
        self,
        path: Path,
        *,
        phase: str | None = None,
    ) -> list[AdapterRecord]:
        """处理：从调用方指定的本地文件解析宿主用量。
        输入：path 是待审计日志路径，phase 是调用方提供的阶段标签。
        输出：通过格式和字段白名单检查的记录序列，供账本导入。
        """
        ...


def read_bounded_bytes(path: Path) -> bytes:
    """处理：在固定大小上限内读取宿主 usage 文件。
    输入：调用方明确提供的 JSON、JSONL 或数据库导出路径。
    输出：本地文件字节；文件过大时在解析前拒绝，且不输出其内容。
    """

    size = path.stat().st_size
    if size > MAX_USAGE_FILE_BYTES:
        raise ValueError(f"Usage file exceeds {MAX_USAGE_FILE_BYTES} bytes")
    return path.read_bytes()


def parse_json_object_bytes(content: bytes, label: str) -> dict[str, Any]:
    """处理：解析 UTF-8 JSON 并要求根值为对象。
    输入：本地 usage 文件字节和不会包含正文的错误标签。
    输出：仅供适配器内存筛选的映射；错误不回显原始 payload。
    """

    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be a UTF-8 JSON object") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def parse_jsonl_bytes(content: bytes, label: str) -> list[tuple[int, dict[str, Any], str]]:
    """处理：逐行解析 JSONL 并为重复行生成稳定无内容指纹。
    输入：本地 rollout/session 字节和安全错误标签。
    输出：行号、对象和 SHA-256 occurrence key；不会返回或持久化原始行文本。
    """

    rows: list[tuple[int, dict[str, Any], str]] = []
    occurrences: dict[str, int] = {}
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} must be UTF-8 JSONL") from exc
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label} contains invalid JSON at line {line_number}") from exc
        if not isinstance(payload, dict):
            continue
        digest = hashlib.sha256(raw_line.encode("utf-8")).hexdigest()
        occurrence = occurrences.get(digest, 0) + 1
        occurrences[digest] = occurrence
        rows.append((line_number, payload, f"sha256:{digest}:{occurrence}"))
    return rows


def nested_mapping(payload: Mapping[str, Any], *paths: tuple[str, ...]) -> Mapping[str, Any] | None:
    """处理：只沿适配器声明的固定键路径查找映射。
    输入：宿主 payload 和安全 allowlist 路径集合。
    输出：首个匹配映射或 None；不会递归扫描 prompt/response 正文。
    """

    for path in paths:
        current: object = payload
        for key in path:
            if not isinstance(current, Mapping):
                current = None
                break
            current = current.get(key)
        if isinstance(current, Mapping):
            return current
    return None


def nested_value(payload: Mapping[str, Any], *paths: tuple[str, ...]) -> object:
    """处理：只沿固定 allowlist 路径读取一个标量。
    输入：宿主 payload 和适配器声明的键路径。
    输出：首个非空标量或 None，避免任意递归收集敏感字段。
    """

    for path in paths:
        current: object = payload
        for key in path:
            if not isinstance(current, Mapping):
                current = None
                break
            current = current.get(key)
        if current is not None:
            return current
    return None


def non_negative_int(value: object) -> int | None:
    """处理：把宿主 usage 数值安全解析为非负整数。
    输入：固定 token 字段读取出的标量。
    输出：合法整数或 None；布尔、负数、浮点和自由文本均不接受。
    """

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return int(value)
    return None


def non_negative_float(value: object) -> float | None:
    """处理：把宿主耗时标量解析为有限非负浮点数。
    输入：固定 duration/latency 字段的数字或纯数字文本。
    输出：合法浮点数或 None；不解释带单位或其他自由文本。
    """

    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float, str)):
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    if parsed < 0 or parsed in {float("inf"), float("-inf")} or parsed != parsed:
        return None
    return parsed


def hash_identifier(namespace: str, value: object) -> str:
    """处理：将宿主 request/session ID 转为不可逆关联键。
    输入：固定命名空间和只在内存中读取的外部标识。
    输出：``sha256:<hex>``；账本不会保存原始外部 ID。
    """

    digest = hashlib.sha256(f"{namespace}\0{value}".encode()).hexdigest()
    return f"sha256:{digest}"


def lineage_hashes(
    payload: Mapping[str, Any],
    namespace: str,
) -> dict[str, str | None]:
    """处理：从固定元数据路径提取宿主 lineage，并只返回不可逆哈希。
    输入：hook/session/rollout 映射和宿主命名空间。
    输出：session/turn/parent-session/task 四个可选 SHA-256 字段。
    """

    aliases = {
        "session_id_hash": (
            ("session_id",),
            ("sessionId",),
            ("extra", "session_id"),
            ("meta", "session_id"),
            ("metadata", "session_id"),
        ),
        "turn_id_hash": (
            ("turn_id",),
            ("turnId",),
            ("extra", "turn_id"),
            ("meta", "turn_id"),
            ("metadata", "turn_id"),
        ),
        "parent_session_id_hash": (
            ("parent_session_id",),
            ("parentSessionId",),
            ("extra", "parent_session_id"),
            ("meta", "parent_session_id"),
            ("metadata", "parent_session_id"),
        ),
        "host_task_id_hash": (
            ("task_id",),
            ("taskId",),
            ("extra", "task_id"),
            ("meta", "task_id"),
            ("metadata", "task_id"),
        ),
    }
    return {
        name: (
            hash_identifier(f"{namespace}-{name}", value)
            if (value := nested_value(payload, *paths)) is not None
            else None
        )
        for name, paths in aliases.items()
    }


def tool_call_count_from_payload(
    payload: Mapping[str, Any],
    *,
    source: str,
) -> Measurement:
    """处理：只读取显式计数或在已知 content/output 数组中计算工具调用节点。
    输入：宿主事件映射和安全来源标签；工具名及参数不会被保存。
    输出：exact 工具调用数；没有可判定字段时保持 unobservable。
    """

    explicit = nested_value(
        payload,
        ("assistant_tool_call_count",),
        ("tool_call_count",),
        ("extra", "assistant_tool_call_count"),
        ("usage", "tool_call_count"),
    )
    parsed = non_negative_int(explicit)
    if parsed is not None:
        return exact(parsed, source, "reported_tool_call_count_v1")
    containers = (
        nested_value(payload, ("message", "content")),
        nested_value(payload, ("payload", "message", "content")),
        nested_value(payload, ("response", "output")),
        nested_value(payload, ("output",)),
    )
    tool_types = {
        "tool_call",
        "tool_use",
        "function_call",
        "custom_tool_call",
        "toolCall",
    }
    for container in containers:
        if isinstance(container, list):
            count = sum(
                1
                for item in container
                if isinstance(item, Mapping) and item.get("type") in tool_types
            )
            return exact(count, source, "content_node_tool_call_count_v1")
    return unobservable("tool_call_count_not_exposed")


def canonical_digest(payload: object) -> str:
    """处理：为已筛选的安全结构生成稳定内容摘要。
    输入：只含数值、短标签和空值的规范对象。
    输出：SHA-256 十六进制摘要，用于幂等去重而不保存原始内容。
    """

    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def token_measurement(
    usage: Mapping[str, Any],
    aliases: Iterable[tuple[str, ...]],
    *,
    source: str,
    missing_reason: str,
) -> Measurement:
    """处理：从固定 token 键别名中提取首个非负整数。
    输入：usage 映射、allowlist 路径、证据来源和缺失原因。
    输出：provider/host exact measurement；未暴露时返回明确 unobservable。
    """

    value = nested_value(usage, *tuple(aliases))
    parsed = non_negative_int(value)
    if parsed is None:
        return unobservable(missing_reason, source="host_not_exposed")
    return exact(parsed, source, "reported_usage_v1")


def tokens_from_usage(
    usage: Mapping[str, Any],
    *,
    source: str,
    cached_relation: TokenRelation | None = None,
    cache_write_relation: TokenRelation | None = None,
) -> TokenUsage:
    """处理：把常见 Provider usage 数字映射为统一 token 分解。
    输入：适配器选中的 usage 映射、证据来源和可选缓存语义覆盖。
    输出：缺字段保持 unobservable、reasoning/tool-call 固定为 output 子集的 TokenUsage。
    """

    input_measure = token_measurement(
        usage,
        (
            ("input_tokens",),
            ("prompt_tokens",),
            ("input",),
            ("prompt",),
            ("inputTokens",),
            ("inputTokenCount",),
            ("promptTokenCount",),
        ),
        source=source,
        missing_reason="input_tokens_not_exposed",
    )
    cached = token_measurement(
        usage,
        (
            ("cached_input_tokens",),
            ("cache_read_input_tokens",),
            ("cache_read_tokens",),
            ("cached_tokens",),
            ("cacheRead",),
            ("cacheReadTokens",),
            ("prompt_tokens_details", "cached_tokens"),
            ("input_tokens_details", "cached_tokens"),
        ),
        source=source,
        missing_reason="cached_input_tokens_not_exposed",
    )
    cache_write = token_measurement(
        usage,
        (
            ("cache_write_input_tokens",),
            ("cache_creation_input_tokens",),
            ("cache_write_tokens",),
            ("cache_creation_tokens",),
            ("cacheWrite",),
            ("cacheWriteTokens",),
        ),
        source=source,
        missing_reason="cache_write_tokens_not_exposed",
    )
    output = token_measurement(
        usage,
        (
            ("output_tokens",),
            ("completion_tokens",),
            ("output",),
            ("completion",),
            ("outputTokens",),
            ("outputTokenCount",),
            ("candidatesTokenCount",),
        ),
        source=source,
        missing_reason="output_tokens_not_exposed",
    )
    reasoning = token_measurement(
        usage,
        (
            ("reasoning_output_tokens",),
            ("reasoning_tokens",),
            ("reasoningTokens",),
            ("output_tokens_details", "reasoning_tokens"),
            ("completion_tokens_details", "reasoning_tokens"),
        ),
        source=source,
        missing_reason="reasoning_tokens_not_exposed",
    )
    tool_call = token_measurement(
        usage,
        (
            ("tool_call_output_tokens",),
            ("tool_call_tokens",),
            ("toolCallTokens",),
            ("output_tokens_details", "tool_call_tokens"),
            ("completion_tokens_details", "tool_call_tokens"),
        ),
        source=source,
        missing_reason="tool_call_tokens_not_exposed",
    )
    reported_total = token_measurement(
        usage,
        (
            ("total_tokens",),
            ("totalTokens",),
            ("totalTokenCount",),
            ("total",),
        ),
        source=source,
        missing_reason="provider_total_tokens_not_exposed",
    )

    resolved_cached = cached_relation or _detect_cached_relation(usage)
    resolved_write = cache_write_relation or _detect_cache_write_relation(usage)
    return TokenUsage(
        input=input_measure,
        cached_input=cached,
        cache_write_input=cache_write,
        output=output,
        reasoning_output=reasoning,
        tool_call_output=tool_call,
        reported_total=reported_total,
        cached_input_relation=resolved_cached,
        cache_write_input_relation=resolved_write,
    )


def delta_tokens(current: TokenUsage, previous: TokenUsage | None) -> TokenUsage:
    """处理：把 Codex 累计 token 快照转换为本次增量。
    输入：当前累计 TokenUsage 和同一 rollout 上一累计快照。
    输出：字段级非负 delta；计数回退视为新累计段，未知仍保持未知。
    """

    if previous is None:
        return current

    def delta(name: str) -> Measurement:
        """处理：计算一个累计 token 字段的安全增量。
        输入：TokenUsage 中固定的字段名。
        输出：两个 exact/estimated 数值的差；缺失时保留 unobservable。
        """

        now = getattr(current, name)
        before = getattr(previous, name)
        if now.value is None or before.value is None:
            return unobservable("cumulative_delta_component_unobservable")
        value = int(now.value)
        prior = int(before.value)
        resolved = value - prior if value >= prior else value
        quality = (
            ObservationQuality.ESTIMATED
            if ObservationQuality.ESTIMATED in {now.quality, before.quality}
            else ObservationQuality.EXACT
        )
        if quality is ObservationQuality.EXACT:
            return exact(resolved, "derived", "cumulative_delta_v1")
        return Measurement(
            resolved,
            ObservationQuality.ESTIMATED,
            "derived",
            method="cumulative_delta_v1",
        )

    return TokenUsage(
        **{name: delta(name) for name in (
            "input",
            "cached_input",
            "cache_write_input",
            "output",
            "reasoning_output",
            "tool_call_output",
            "reported_total",
        )},
        cached_input_relation=current.cached_input_relation,
        cache_write_input_relation=current.cache_write_input_relation,
    )


def cost_from_mapping(
    payload: Mapping[str, Any] | None,
    *,
    source: str,
) -> CostMeasurement:
    """处理：从固定 amount/total/currency 字段提取宿主报告成本。
    输入：usage 内的 cost 映射或 None，以及证据来源。
    输出：exact 十进制成本；缺失或非法时为 unobservable，绝不推断为零。
    """

    if not isinstance(payload, Mapping):
        return unknown_cost()
    amount = nested_value(payload, ("amount",), ("total",), ("total_cost",))
    currency = nested_value(payload, ("currency",), ("currency_code",)) or "USD"
    if isinstance(amount, bool) or not isinstance(amount, (int, float, str)):
        return unknown_cost()
    try:
        parsed = Decimal(str(amount))
    except InvalidOperation:
        return unknown_cost("host_cost_was_not_decimal")
    if not parsed.is_finite() or parsed < 0:
        return unknown_cost("host_cost_was_invalid")
    currency_label = safe_label(str(currency).upper())
    if currency_label is None or len(currency_label) != 3:
        return unknown_cost("host_currency_was_invalid")
    return CostMeasurement(
        format(parsed, "f"),
        currency_label,
        ObservationQuality.EXACT,
        source,
        method="reported_cost_v1",
    )


def latency_from_payload(payload: Mapping[str, Any], source: str) -> dict[str, Measurement]:
    """处理：提取宿主明确报告的 wall、queue、首 token、prefill 和 decode 耗时。
    输入：固定 hook/usage row 映射和证据来源。
    输出：只含已观测 latency 的毫秒 measurement；缺失字段不伪造零。
    """

    aliases: dict[str, tuple[tuple[str, ...], ...]] = {
        "wall_ms": (
            ("duration_ms",),
            ("latency_ms",),
            ("elapsed_ms",),
            ("api_duration",),
        ),
        "queue_ms": (("queue_ms",), ("queue_seconds",)),
        "first_token_ms": (("first_token_ms",), ("first_token_seconds",)),
        "prefill_ms": (("prefill_ms",), ("prefill_seconds",)),
        "decode_ms": (("decode_ms",), ("decode_seconds",)),
    }
    seconds_names = {
        "wall_ms": "api_duration",
        "queue_ms": "queue_seconds",
        "first_token_ms": "first_token_seconds",
        "prefill_ms": "prefill_seconds",
        "decode_ms": "decode_seconds",
    }
    output: dict[str, Measurement] = {}
    for target, paths in aliases.items():
        raw = nested_value(payload, *paths)
        parsed = non_negative_float(raw)
        if parsed is None:
            continue
        if target in seconds_names and seconds_names[target] in payload:
            parsed *= 1000
        output[target] = exact(round(parsed, 3), source, "reported_latency_v1")
    if "wall_ms" not in output:
        seconds = non_negative_float(payload.get("duration_seconds"))
        if seconds is not None:
            output["wall_ms"] = exact(
                round(seconds * 1000, 3), source, "reported_latency_v1"
            )
    return output


def safe_observation_labels(payload: Mapping[str, Any]) -> dict[str, str | None]:
    """处理：从固定路径提取 provider/model/status 等短标签。
    输入：宿主 hook 或 session row 映射。
    输出：只含安全字符的标签；自由文本和可能含秘密的值被丢弃。
    """

    provider = safe_label(
        nested_value(
            payload,
            ("provider",),
            ("api_provider",),
            ("extra", "provider"),
            ("payload", "provider"),
            ("message", "provider"),
        )
    )
    requested_model = safe_label(
        nested_value(
            payload,
            ("requested_model",),
            ("model",),
            ("extra", "model"),
            ("payload", "model"),
            ("message", "model"),
        )
    )
    served_model = safe_label(
        nested_value(
            payload,
            ("served_model",),
            ("response_model",),
            ("extra", "response_model"),
            ("usage", "model"),
        )
    )
    return {
        "provider": provider,
        "requested_model": requested_model,
        "served_model": served_model,
        "status": safe_label(
            nested_value(
                payload,
                ("status",),
                ("extra", "status"),
                ("payload", "status"),
            )
        ),
        "finish_reason": safe_label(
            nested_value(
                payload,
                ("finish_reason",),
                ("stop_reason",),
                ("extra", "finish_reason"),
                ("payload", "finish_reason"),
            )
        ),
    }


def replace_observation_tokens(
    observation: UsageObservation,
    tokens: TokenUsage,
) -> UsageObservation:
    """处理：为累计日志 observation 替换成确定性 delta token。
    输入：已规范化 observation 和同语义关系的增量 TokenUsage。
    输出：除 tokens 外字段保持不变的新 UsageObservation。
    """

    return replace(observation, tokens=tokens)


def _detect_cached_relation(usage: Mapping[str, Any]) -> TokenRelation:
    """处理：根据明确的 Provider 字段名判断 cache-read 是否包含在 input 中。
    输入：只读 usage 数字映射。
    输出：OpenAI-style 为 subset，Anthropic-style 为 additional，其余为 unknown。
    """

    if nested_value(
        usage,
        ("prompt_tokens_details", "cached_tokens"),
        ("input_tokens_details", "cached_tokens"),
        ("cached_input_tokens",),
        ("cacheRead",),
        ("cacheReadTokens",),
    ) is not None:
        return TokenRelation.SUBSET
    if nested_value(
        usage,
        ("cache_read_input_tokens",),
        ("cache_creation_input_tokens",),
        ("cacheWrite",),
        ("cacheWriteTokens",),
    ) is not None:
        return TokenRelation.ADDITIONAL
    return TokenRelation.UNKNOWN


def _detect_cache_write_relation(usage: Mapping[str, Any]) -> TokenRelation:
    """处理：根据 cache-creation 字段判断写缓存量是否是额外 input。
    输入：只读 usage 数字映射。
    输出：显式 cache creation 为 additional；否则保持 unknown。
    """

    if nested_value(
        usage,
        ("cache_write_input_tokens",),
        ("cache_creation_input_tokens",),
        ("cache_write_tokens",),
        ("cache_creation_tokens",),
    ) is not None:
        return TokenRelation.ADDITIONAL
    return TokenRelation.UNKNOWN
