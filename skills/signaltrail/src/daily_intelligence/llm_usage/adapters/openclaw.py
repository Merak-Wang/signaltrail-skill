from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..models import (
    AdapterRecord,
    Measurement,
    TokenRelation,
    UsageObservation,
    exact,
    normalize_timestamp,
    safe_label,
    unobservable,
)
from .base import (
    canonical_digest,
    cost_from_mapping,
    hash_identifier,
    latency_from_payload,
    nested_mapping,
    nested_value,
    non_negative_int,
    parse_jsonl_bytes,
    read_bounded_bytes,
    safe_observation_labels,
    tokens_from_usage,
    tool_call_count_from_payload,
)

_SQLITE_MAGIC = b"SQLite format 3\x00"
_SQLITE_SUFFIXES = frozenset({".db", ".sqlite", ".sqlite3"})

# OpenClaw main at the verification date uses per-agent schema 17. Supporting a
# new number requires inspecting its canonical schema rather than optimistically
# reading columns that happen to share names.
_SUPPORTED_AGENT_SCHEMA_VERSIONS = frozenset({17})
_REQUIRED_SQLITE_COLUMNS = {
    "schema_meta": {
        "meta_key",
        "role",
        "schema_version",
        "agent_id",
        "app_version",
        "created_at",
        "updated_at",
    },
    "session_nodes": {
        "session_key",
        "current_session_id",
        "parent_session_key",
        "spawned_by",
    },
    "session_windows": {
        "session_id",
        "session_key",
        "model_provider",
        "model",
        "parent_session_key",
        "spawned_by",
    },
    "transcript_events": {"session_id", "seq", "event_json", "created_at"},
}


@dataclass(frozen=True, slots=True)
class _SessionContext:
    """处理：保存 OpenClaw header 或关系表提供的安全会话上下文。
    输入：已哈希的 session/turn/parent/task 标识及 provider/model 安全标签。
    输出：供后续 usage 事件继承的内存对象，不携带原始会话标识或正文。
    """

    session_id_hash: str | None
    turn_id_hash: str | None
    parent_session_id_hash: str | None
    host_task_id_hash: str | None
    agent_id_hash: str | None
    provider: str | None
    requested_model: str | None
    served_model: str | None


class OpenClawAdapter:
    """处理：规范 OpenClaw 当前 SQLite 转录、旧 JSONL 与 usage hook 回执。
    输入：单条内存 hook 映射或调用方明确提供的本地会话数据库/JSONL。
    输出：仅含计数、耗时、成本、安全标签和哈希 lineage 的 AdapterRecord。
    """

    name = "openclaw"
    version = "1.1"

    def from_hook(
        self,
        payload: Mapping[str, Any],
        *,
        phase: str | None = None,
        call_id: str | None = None,
        source_event_id: str | None = None,
    ) -> list[AdapterRecord]:
        """处理：从一条 OpenClaw usage hook 对象提取安全计量字段。
        输入：payload、phase 及可选 call/event 标识；原始正文只在内存中存在。
        输出：一条 hook 来源记录；usage 缺失时抛出 ValueError。
        """

        usage = _usage_mapping(payload)
        if usage is None:
            raise ValueError("OpenClaw payload has no supported usage object")
        context = _context_from_payload(payload)
        external_identity = source_event_id or call_id or nested_value(
            payload,
            ("request_id",),
            ("call_id",),
            ("event_id",),
            ("id",),
            ("message", "id"),
        )
        if external_identity is None:
            external_identity = canonical_digest(_safe_usage_signature(usage, payload))
        identity = _scoped_identity(
            context.session_id_hash,
            context.agent_id_hash,
            external_identity,
        )
        context = _with_turn_identity(context, payload, identity)
        return [
            AdapterRecord(
                dedupe_key=f"openclaw-hook:{identity}",
                observation=_observation(
                    payload,
                    usage,
                    identity=identity,
                    phase=phase,
                    source_kind="usage_hook",
                    source="openclaw_hook",
                    context=context,
                ),
            )
        ]

    def from_path(
        self,
        path: Path,
        *,
        phase: str | None = None,
    ) -> list[AdapterRecord]:
        """处理：按文件签名导入当前 agent SQLite 或兼容旧 session JSONL。
        输入：本地只读数据库/JSONL 路径和可选 phase；未知 SQLite schema 被拒绝。
        输出：按 agent/session/event 身份稳定去重的规范记录列表，不保存正文。
        """

        resolved = Path(path)
        if _is_sqlite_input(resolved):
            return self._from_sqlite(resolved, phase=phase)
        return self._from_legacy_jsonl(resolved, phase=phase)

    def _from_legacy_jsonl(
        self,
        path: Path,
        *,
        phase: str | None,
    ) -> list[AdapterRecord]:
        """处理：导入仅用于兼容或迁移的 OpenClaw session JSONL。
        输入：调用方指定的旧 JSONL 路径和可选 phase。
        输出：继承 session header lineage 的 aggregate/call 记录列表。
        """

        records: list[AdapterRecord] = []
        context: _SessionContext | None = None
        file_scope = hash_identifier("openclaw-legacy-file", path.resolve())
        rows = parse_jsonl_bytes(read_bounded_bytes(path), "OpenClaw legacy session")
        for _, payload, line_identity in rows:
            header = _context_from_header(payload)
            if header is not None:
                context = _merge_context(header, context)

            usage = _usage_mapping(payload)
            if usage is None:
                continue
            direct = _context_from_payload(payload)
            effective = _merge_context(direct, context)
            raw_identity = nested_value(
                payload,
                ("request_id",),
                ("call_id",),
                ("event_id",),
                ("id",),
                ("message", "id"),
            ) or line_identity
            identity = _scoped_identity(
                effective.session_id_hash or file_scope,
                effective.agent_id_hash,
                raw_identity,
            )
            effective = _with_turn_identity(effective, payload, identity)
            records.append(
                AdapterRecord(
                    dedupe_key=f"openclaw-legacy-session:{identity}",
                    observation=_observation(
                        payload,
                        usage,
                        identity=identity,
                        phase=phase,
                        source_kind="legacy_session_jsonl",
                        source="openclaw_legacy_session",
                        context=effective,
                    ),
                )
            )
        return records

    def _from_sqlite(
        self,
        path: Path,
        *,
        phase: str | None,
    ) -> list[AdapterRecord]:
        """处理：在只读事务中流式读取当前 OpenClaw per-agent SQLite 转录。
        输入：SQLite 路径和可选 phase；schema 元数据、版本、表和列均须匹配。
        输出：以 agent/session/seq 为身份的用量记录；损坏事件使导入整体失败。
        """

        connection = _open_read_only_sqlite(path)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            connection.execute("BEGIN")
            agent_id = _validate_sqlite_schema(connection)
            agent_hash = _optional_identifier_hash("openclaw-agent", agent_id)
            records: list[AdapterRecord] = []
            contexts: dict[str, _SessionContext] = {}
            cursor = connection.execute(
                """
                SELECT
                    transcript_events.session_id AS session_id,
                    transcript_events.seq AS seq,
                    transcript_events.event_json AS event_json,
                    transcript_events.created_at AS event_created_at,
                    session_windows.model_provider AS model_provider,
                    session_windows.model AS model,
                    parent_node.current_session_id AS parent_session_id
                FROM transcript_events
                JOIN session_windows
                  ON session_windows.session_id = transcript_events.session_id
                LEFT JOIN session_nodes AS child_node
                  ON child_node.session_key = session_windows.session_key
                LEFT JOIN session_nodes AS parent_node
                  ON parent_node.session_key = COALESCE(
                      session_windows.parent_session_key,
                      child_node.parent_session_key
                  )
                ORDER BY transcript_events.session_id, transcript_events.seq
                """
            )
            for row in cursor:
                payload = _parse_sqlite_event(row["event_json"])
                session_id = _required_identifier(row["session_id"], "session_id")
                seq = _required_sequence(row["seq"])
                base_context = _sqlite_context(
                    agent_id=agent_id,
                    agent_hash=agent_hash,
                    session_id=session_id,
                    parent_session_id=row["parent_session_id"],
                    provider=row["model_provider"],
                    model=row["model"],
                )
                header = _context_from_header(payload, default_agent_id=agent_id)
                if header is not None:
                    contexts[session_id] = _merge_context(header, base_context)
                effective = _merge_context(contexts.get(session_id), base_context)

                usage = _usage_mapping(payload)
                if usage is None:
                    continue
                event_identity = nested_value(
                    payload,
                    ("request_id",),
                    ("call_id",),
                    ("event_id",),
                    ("id",),
                    ("message", "id"),
                )
                identity = canonical_digest(
                    {
                        "agent_id_hash": effective.agent_id_hash,
                        "session_id_hash": effective.session_id_hash,
                        "seq": seq,
                        "event_id_hash": _optional_identifier_hash(
                            "openclaw-event",
                            event_identity,
                        ),
                    }
                )
                effective = _with_turn_identity(effective, payload, identity)
                records.append(
                    AdapterRecord(
                        dedupe_key=f"openclaw-agent-sqlite:{identity}",
                        observation=_observation(
                            payload,
                            usage,
                            identity=identity,
                            phase=phase,
                            source_kind="agent_sqlite_transcript",
                            source="openclaw_agent_sqlite",
                            context=effective,
                            completed_at_fallback=_epoch_millis_timestamp(
                                row["event_created_at"]
                            ),
                        ),
                    )
                )
            return records
        except ValueError:
            raise
        except sqlite3.Error as exc:
            raise ValueError("OpenClaw SQLite database could not be read safely") from exc
        finally:
            if connection.in_transaction:
                connection.rollback()
            connection.close()


def _is_sqlite_input(path: Path) -> bool:
    """处理：依据 SQLite 文件签名识别输入，并拒绝伪装的数据库扩展名。
    输入：调用方明确指定且尚未解析的本地路径。
    输出：真实 SQLite 返回 True；普通文件返回 False；伪数据库抛出 ValueError。
    """

    with path.open("rb") as handle:
        signature = handle.read(len(_SQLITE_MAGIC))
    if signature == _SQLITE_MAGIC:
        return True
    if path.suffix.casefold() in _SQLITE_SUFFIXES:
        raise ValueError("OpenClaw SQLite input has an invalid database header")
    return False


def _open_read_only_sqlite(path: Path) -> sqlite3.Connection:
    """处理：以 URI 只读模式打开数据库，禁止适配器创建或修改输入文件。
    输入：已验证 SQLite 签名的本地文件路径。
    输出：启用只读模式的 sqlite3 连接；打开失败时返回不含路径的安全错误。
    """

    try:
        return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise ValueError("OpenClaw SQLite database could not be opened read-only") from exc


def _validate_sqlite_schema(connection: sqlite3.Connection) -> str:
    """处理：验证当前 OpenClaw agent DB 的双版本、角色和必需列契约。
    输入：已处于只读事务中的 SQLite 连接。
    输出：合法数据库的 agent_id；未知版本、全局库或结构漂移均 fail closed。
    """

    version_row = connection.execute("PRAGMA user_version").fetchone()
    user_version = version_row[0] if version_row else None
    if user_version not in _SUPPORTED_AGENT_SCHEMA_VERSIONS:
        raise ValueError("Unsupported OpenClaw agent SQLite schema version")

    for table, required in _REQUIRED_SQLITE_COLUMNS.items():
        table_row = connection.execute(
            "SELECT type FROM sqlite_master WHERE name = ?",
            (table,),
        ).fetchone()
        if table_row is None or table_row[0] != "table":
            raise ValueError("OpenClaw agent SQLite schema is missing a required table")
        columns = {
            str(row[1])
            for row in connection.execute(f'PRAGMA table_info("{table}")')
        }
        if not required.issubset(columns):
            raise ValueError("OpenClaw agent SQLite schema has unsupported columns")

    metadata = connection.execute(
        """
        SELECT role, schema_version, agent_id
        FROM schema_meta
        WHERE meta_key = 'primary'
        """
    ).fetchone()
    if metadata is None or metadata[0] != "agent" or metadata[1] != user_version:
        raise ValueError("OpenClaw SQLite schema metadata does not identify this agent schema")
    return _required_identifier(metadata[2], "agent_id")


def _parse_sqlite_event(value: object) -> dict[str, Any]:
    """处理：解析 transcript_events.event_json 且不把损坏内容降格为无用量。
    输入：SQLite 当前行的 event_json 文本。
    输出：转录事件映射；非法 JSON 或非对象值抛出安全 ValueError。
    """

    if not isinstance(value, str):
        raise ValueError("OpenClaw SQLite transcript event is not JSON text")
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("OpenClaw SQLite contains invalid transcript event JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("OpenClaw SQLite transcript event must be a JSON object")
    return payload


def _required_identifier(value: object, label: str) -> str:
    """处理：验证只在内存参与哈希的 OpenClaw 数据库标识。
    输入：固定数据库列读取的值及安全错误标签。
    输出：长度受限的标识文本；对象、空值、换行或超长内容被拒绝。
    """

    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"OpenClaw SQLite {label} is invalid")
    text = str(value)
    if not 1 <= len(text) <= 512 or "\n" in text or "\r" in text:
        raise ValueError(f"OpenClaw SQLite {label} is invalid")
    return text


def _required_sequence(value: object) -> int:
    """处理：验证 transcript_events.seq 是非负整数。
    输入：SQLite 当前事件的 seq 列值。
    输出：可参与稳定事件身份的整数；非法值抛出 ValueError。
    """

    parsed = non_negative_int(value)
    if parsed is None:
        raise ValueError("OpenClaw SQLite transcript sequence is invalid")
    return parsed


def _usage_mapping(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """处理：只从 OpenClaw 已知 usage 路径读取映射。
    输入：转录事件或 usage hook payload。
    输出：首个 usage 映射或 None；不递归遍历任何正文对象。
    """

    return nested_mapping(
        payload,
        ("usage",),
        ("message", "usage"),
        ("payload", "usage"),
        ("response", "usage"),
        ("data", "usage"),
    )


def _observation(
    payload: Mapping[str, Any],
    usage: Mapping[str, Any],
    *,
    identity: object,
    phase: str | None,
    source_kind: str,
    source: str,
    context: _SessionContext,
    completed_at_fallback: str | None = None,
) -> UsageObservation:
    """处理：将 OpenClaw usage 和继承上下文映射为统一 observation。
    输入：事件、usage、哈希身份、来源、phase 与 header/关系表上下文。
    输出：逐调用或聚合记录；无显式 provider-call 数时保持不可观测。
    """

    labels = safe_observation_labels(payload)
    covered = _covered_call_count(payload, usage, source=source)
    read_relation, write_relation = _cache_relations(
        labels["provider"] or context.provider,
        usage,
    )
    tokens = tokens_from_usage(
        usage,
        source=source,
        cached_relation=read_relation,
        cache_write_relation=write_relation,
    )
    return UsageObservation(
        adapter="openclaw",
        adapter_version="1.1",
        source_kind=source_kind,
        correlation_id_hash=hash_identifier("openclaw-usage-event", identity),
        granularity="call" if covered.value == 1 else "aggregate",
        covered_call_count=covered,
        tokens=tokens,
        tool_call_count=tool_call_count_from_payload(payload, source=source),
        cost=cost_from_mapping(
            nested_mapping(usage, ("cost",))
            or nested_mapping(payload, ("cost",)),
            source=source,
        ),
        provider=labels["provider"] or context.provider,
        requested_model=labels["requested_model"] or context.requested_model,
        served_model=labels["served_model"] or context.served_model,
        phase=safe_label(phase),
        status=labels["status"],
        finish_reason=labels["finish_reason"],
        completed_at=_safe_timestamp(payload) or completed_at_fallback,
        latency=latency_from_payload(payload, source),
        session_id_hash=context.session_id_hash,
        turn_id_hash=context.turn_id_hash,
        parent_session_id_hash=context.parent_session_id_hash,
        host_task_id_hash=context.host_task_id_hash,
    )


def _covered_call_count(
    payload: Mapping[str, Any],
    usage: Mapping[str, Any],
    *,
    source: str,
) -> Measurement:
    """处理：只接受宿主显式 provider-call 数，不把一个 turn 当作一次调用。
    输入：转录/hook 事件、usage 映射和计量来源标签。
    输出：显式非负数为 exact；缺失时为 unobservable，绝不默认成 1。
    """

    value = nested_value(
        payload,
        ("api_calls",),
        ("apiCalls",),
        ("model_call_count",),
        ("modelCallCount",),
        ("calls",),
        ("message", "api_calls"),
        ("message", "apiCalls"),
        ("message", "model_call_count"),
        ("message", "modelCallCount"),
        ("message", "calls"),
    )
    if value is None:
        value = nested_value(
            usage,
            ("api_calls",),
            ("apiCalls",),
            ("model_call_count",),
            ("modelCallCount",),
            ("calls",),
        )
    parsed = non_negative_int(value)
    if parsed is None:
        return unobservable(
            "openclaw_turn_may_span_multiple_provider_calls",
            source=source,
        )
    return exact(parsed, source, "reported_provider_call_count_v1")


def _cache_relations(
    provider: str | None,
    usage: Mapping[str, Any],
) -> tuple[TokenRelation, TokenRelation]:
    """处理：区分 OpenClaw 规范缓存桶与 provider 原始缓存字段的包含关系。
    输入：安全 provider 标签和固定 usage 映射。
    输出：cache-read/cache-write 各自关系；未暴露字段保持 unknown。
    """

    del provider
    normalized_read = nested_value(
        usage,
        ("cacheRead",),
        ("cacheReadTokens",),
    )
    anthropic_read = nested_value(
        usage,
        ("cache_read_input_tokens",),
        ("cache_read_tokens",),
    )
    subset_read = nested_value(
        usage,
        ("cached_input_tokens",),
        ("cached_tokens",),
        ("prompt_tokens_details", "cached_tokens"),
        ("input_tokens_details", "cached_tokens"),
    )
    if normalized_read is not None or anthropic_read is not None:
        read_relation = TokenRelation.ADDITIONAL
    elif subset_read is not None:
        read_relation = TokenRelation.SUBSET
    else:
        read_relation = TokenRelation.UNKNOWN

    normalized_write = nested_value(
        usage,
        ("cacheWrite",),
        ("cacheWriteTokens",),
    )
    provider_write = nested_value(
        usage,
        ("cache_write_input_tokens",),
        ("cache_creation_input_tokens",),
        ("cache_write_tokens",),
        ("cache_creation_tokens",),
    )
    write_relation = (
        TokenRelation.ADDITIONAL
        if normalized_write is not None or provider_write is not None
        else TokenRelation.UNKNOWN
    )
    return read_relation, write_relation


def _context_from_header(
    payload: Mapping[str, Any],
    *,
    default_agent_id: object = None,
) -> _SessionContext | None:
    """处理：识别 session header 并提取当前及父转录的哈希 lineage。
    输入：JSONL/SQLite 事件和关系数据库提供的默认 agent ID。
    输出：安全 session context；非 header 返回 None，正文不会被扫描。
    """

    event_type = nested_value(payload, ("type",), ("payload", "type"))
    if not isinstance(event_type, str) or event_type.casefold() not in {
        "session",
        "session_header",
        "session_start",
    }:
        return None
    agent_id = nested_value(
        payload,
        ("agent_id",),
        ("agentId",),
        ("transcriptScope", "agentId"),
    ) or default_agent_id
    session_id = nested_value(
        payload,
        ("session_id",),
        ("sessionId",),
        ("transcriptScope", "sessionId"),
        ("id",),
    )
    parent_agent_id = nested_value(
        payload,
        ("parentTranscriptScope", "agentId"),
        ("parent_transcript_scope", "agent_id"),
    ) or agent_id
    parent_session_id = nested_value(
        payload,
        ("parentTranscriptScope", "sessionId"),
        ("parent_transcript_scope", "session_id"),
        ("parentSession",),
        ("parent_session_id",),
        ("parentSessionId",),
    )
    labels = safe_observation_labels(payload)
    return _SessionContext(
        session_id_hash=_scoped_identifier_hash("session", agent_id, session_id),
        turn_id_hash=None,
        parent_session_id_hash=_scoped_identifier_hash(
            "session",
            parent_agent_id,
            parent_session_id,
        ),
        host_task_id_hash=_optional_identifier_hash(
            "openclaw-host-task",
            nested_value(payload, ("task_id",), ("taskId",)),
        ),
        agent_id_hash=_optional_identifier_hash("openclaw-agent", agent_id),
        provider=labels["provider"],
        requested_model=labels["requested_model"],
        served_model=labels["served_model"],
    )


def _context_from_payload(payload: Mapping[str, Any]) -> _SessionContext:
    """处理：从非 header 事件的固定 lineage 路径提取安全上下文。
    输入：OpenClaw hook 或转录事件映射。
    输出：可与 header/SQLite context 合并的哈希和安全标签集合。
    """

    agent_id = nested_value(
        payload,
        ("agent_id",),
        ("agentId",),
        ("meta", "agent_id"),
        ("metadata", "agent_id"),
    )
    session_id = nested_value(
        payload,
        ("session_id",),
        ("sessionId",),
        ("meta", "session_id"),
        ("metadata", "session_id"),
    )
    parent_agent_id = nested_value(
        payload,
        ("parentTranscriptScope", "agentId"),
        ("parent_transcript_scope", "agent_id"),
    ) or agent_id
    parent_session_id = nested_value(
        payload,
        ("parentTranscriptScope", "sessionId"),
        ("parent_transcript_scope", "session_id"),
        ("parent_session_id",),
        ("parentSessionId",),
        ("meta", "parent_session_id"),
        ("metadata", "parent_session_id"),
    )
    labels = safe_observation_labels(payload)
    return _SessionContext(
        session_id_hash=_scoped_identifier_hash("session", agent_id, session_id),
        turn_id_hash=_scoped_turn_hash(
            _scoped_identifier_hash("session", agent_id, session_id),
            nested_value(payload, ("turn_id",), ("turnId",)),
        ),
        parent_session_id_hash=_scoped_identifier_hash(
            "session",
            parent_agent_id,
            parent_session_id,
        ),
        host_task_id_hash=_optional_identifier_hash(
            "openclaw-host-task",
            nested_value(
                payload,
                ("task_id",),
                ("taskId",),
                ("meta", "task_id"),
                ("metadata", "task_id"),
            ),
        ),
        agent_id_hash=_optional_identifier_hash("openclaw-agent", agent_id),
        provider=labels["provider"],
        requested_model=labels["requested_model"],
        served_model=labels["served_model"],
    )


def _sqlite_context(
    *,
    agent_id: str,
    agent_hash: str | None,
    session_id: str,
    parent_session_id: object,
    provider: object,
    model: object,
) -> _SessionContext:
    """处理：把 OpenClaw 关系表列转换为可继承的安全 session context。
    输入：schema_meta agent、session ID、已解析父 session ID 及模型列。
    输出：SQLite 行的哈希 lineage 与安全模型标签。
    """

    return _SessionContext(
        session_id_hash=_scoped_identifier_hash("session", agent_id, session_id),
        turn_id_hash=None,
        parent_session_id_hash=_scoped_identifier_hash(
            "session",
            agent_id,
            parent_session_id,
        ),
        host_task_id_hash=None,
        agent_id_hash=agent_hash,
        provider=safe_label(provider),
        requested_model=safe_label(model),
        served_model=None,
    )


def _merge_context(
    preferred: _SessionContext | None,
    fallback: _SessionContext | None,
) -> _SessionContext:
    """处理：逐字段合并事件/header/关系表上下文并保留更具体来源。
    输入：优先上下文和可选回退上下文。
    输出：所有可用安全 lineage 与标签的内存合并结果。
    """

    preferred = preferred or _empty_context()
    fallback = fallback or _empty_context()
    return _SessionContext(
        session_id_hash=preferred.session_id_hash or fallback.session_id_hash,
        turn_id_hash=preferred.turn_id_hash or fallback.turn_id_hash,
        parent_session_id_hash=preferred.parent_session_id_hash
        or fallback.parent_session_id_hash,
        host_task_id_hash=preferred.host_task_id_hash or fallback.host_task_id_hash,
        agent_id_hash=preferred.agent_id_hash or fallback.agent_id_hash,
        provider=preferred.provider or fallback.provider,
        requested_model=preferred.requested_model or fallback.requested_model,
        served_model=preferred.served_model or fallback.served_model,
    )


def _empty_context() -> _SessionContext:
    """处理：构造不把缺失 lineage 伪装成标识或零值的空上下文。
    输入：无显式业务参数。
    输出：全部字段为 None 的 _SessionContext，供合并逻辑作为中性值。
    """

    return _SessionContext(None, None, None, None, None, None, None, None)


def _with_turn_identity(
    context: _SessionContext,
    payload: Mapping[str, Any],
    fallback_identity: object,
) -> _SessionContext:
    """处理：为 usage 事件补充 session-scoped turn 身份并保留原上下文。
    输入：已合并上下文、当前事件和无事件 ID 时的安全回退身份。
    输出：除 turn_id_hash 外等同输入的上下文副本。
    """

    raw_turn = nested_value(
        payload,
        ("turn_id",),
        ("turnId",),
        ("message", "turn_id"),
        ("message", "turnId"),
        ("id",),
        ("message", "id"),
    ) or fallback_identity
    return _SessionContext(
        session_id_hash=context.session_id_hash,
        turn_id_hash=_scoped_turn_hash(context.session_id_hash, raw_turn),
        parent_session_id_hash=context.parent_session_id_hash,
        host_task_id_hash=context.host_task_id_hash,
        agent_id_hash=context.agent_id_hash,
        provider=context.provider,
        requested_model=context.requested_model,
        served_model=context.served_model,
    )


def _optional_identifier_hash(namespace: str, value: object) -> str | None:
    """处理：只哈希长度受限标量，拒绝把正文对象误当成 lineage。
    输入：固定命名空间和从 allowlist 路径读取的候选标识。
    输出：SHA-256 标签或 None；原始宿主 ID 不会离开本次调用。
    """

    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value)
    if not 1 <= len(text) <= 512 or "\n" in text or "\r" in text:
        return None
    return hash_identifier(namespace, text)


def _scoped_identifier_hash(
    kind: str,
    agent_id: object,
    value: object,
) -> str | None:
    """处理：把 agent 与 session 标识共同纳入不可逆 lineage 身份。
    输入：固定身份类别、可选 agent ID 和 session/parent ID。
    输出：跨 agent 不碰撞的 SHA-256 标签；无合法 session 值时为 None。
    """

    value_hash = _optional_identifier_hash(f"openclaw-{kind}", value)
    if value_hash is None:
        return None
    agent_hash = _optional_identifier_hash("openclaw-agent", agent_id)
    return hash_identifier(
        f"openclaw-{kind}-scope",
        canonical_digest({"agent_id_hash": agent_hash, "value_hash": value_hash}),
    )


def _scoped_turn_hash(session_id_hash: str | None, value: object) -> str | None:
    """处理：在 session 范围内哈希 turn/event 标识，避免跨会话碰撞。
    输入：已哈希 session 标识和当前事件的短标量身份。
    输出：SHA-256 turn 标签；候选身份非法时为 None。
    """

    value_hash = _optional_identifier_hash("openclaw-turn", value)
    if value_hash is None:
        return None
    return hash_identifier(
        "openclaw-turn-scope",
        canonical_digest(
            {"session_id_hash": session_id_hash, "turn_id_hash": value_hash}
        ),
    )


def _scoped_identity(
    session_id_hash: str | None,
    agent_id_hash: str | None,
    value: object,
) -> str:
    """处理：为 hook/JSONL 事件构造 agent/session 范围内的去重身份。
    输入：可选 agent/session 哈希和只在内存使用的事件身份。
    输出：稳定十六进制摘要；不同子 session 的同名事件不会折叠。
    """

    return canonical_digest(
        {
            "agent_id_hash": agent_id_hash,
            "session_id_hash": session_id_hash,
            "source_event_id_hash": hash_identifier("openclaw-source-event", value),
        }
    )


def _safe_usage_signature(
    usage: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """处理：为缺少 ID 的 OpenClaw hook 构造无正文去重签名。
    输入：usage 数字和仅用于安全标签、调用数提取的 payload。
    输出：可哈希且不含 prompt/response/reasoning/tool arguments 的字典。
    """

    labels = safe_observation_labels(payload)
    read_relation, write_relation = _cache_relations(labels["provider"], usage)
    tokens = tokens_from_usage(
        usage,
        source="openclaw_hook",
        cached_relation=read_relation,
        cache_write_relation=write_relation,
    )
    return {
        "tokens": tokens.to_dict(),
        "labels": labels,
        "covered_call_count": _covered_call_count(
            payload,
            usage,
            source="openclaw_hook",
        ).to_dict(),
    }


def _safe_timestamp(payload: Mapping[str, Any]) -> str | None:
    """处理：严格解析 OpenClaw 事件的已知 ISO 或毫秒时间字段。
    输入：转录/hook 映射；仅访问 timestamp/completedAt/message.timestamp。
    输出：UTC 秒级 ISO 时间；缺失、无时区或非法值返回 None。
    """

    value = nested_value(
        payload,
        ("timestamp",),
        ("completed_at",),
        ("completedAt",),
        ("message", "timestamp"),
    )
    if isinstance(value, str):
        return normalize_timestamp(value)
    return _epoch_millis_timestamp(value)


def _epoch_millis_timestamp(value: object) -> str | None:
    """处理：把 OpenClaw 数据库/消息的非负 epoch 毫秒规范为 UTC 时间。
    输入：created_at 或 message.timestamp 固定字段的整数/浮点值。
    输出：UTC 秒级 ISO 文本；布尔、负数、非有限值或越界值返回 None。
    """

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < 0 or value != value or value in {float("inf"), float("-inf")}:
        return None
    try:
        return datetime.fromtimestamp(float(value) / 1000, UTC).isoformat(
            timespec="seconds"
        )
    except (OverflowError, OSError, ValueError):
        return None
