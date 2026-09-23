from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..models import (
    AdapterRecord,
    TokenRelation,
    TokenUsage,
    UsageObservation,
    estimated,
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
    lineage_hashes,
    nested_mapping,
    nested_value,
    non_negative_int,
    parse_json_object_bytes,
    read_bounded_bytes,
    safe_observation_labels,
    tokens_from_usage,
    tool_call_count_from_payload,
)


class HermesAdapter:
    """处理：规范 Hermes post_api_request hook 和 usage-file 聚合回执。
    输入：Hermes 内存 hook 映射或本地 JSON usage 文件。
    输出：逐调用或显式 aggregate AdapterRecord；不保存原始请求、响应和工具参数。
    """

    name = "hermes"
    version = "1.0"

    def from_hook(
        self,
        payload: Mapping[str, Any],
        *,
        phase: str | None = None,
        call_id: str | None = None,
        source_event_id: str | None = None,
    ) -> list[AdapterRecord]:
        """处理：从一次 Hermes post_api_request payload 提取安全 usage 字段。
        输入：hook 映射、可选 phase/call ID 和宿主事件 ID；原始内容仅在内存中读取。
        输出：恰好一个逐调用 AdapterRecord；没有 usage 映射时抛出 ValueError。
        """

        usage = nested_mapping(
            payload,
            ("usage",),
            ("extra", "usage"),
            ("response", "usage"),
            ("result", "usage"),
            ("data", "usage"),
            ("metrics", "usage"),
        )
        hook_event = safe_label(payload.get("hook_event_name"))
        if usage is None and hook_event not in {
            "pre_api_request",
            "api_request_error",
            "post_api_request",
        }:
            raise ValueError("Hermes hook payload has no supported usage object")
        labels = safe_observation_labels(payload)
        provider = labels["provider"]
        if usage is None:
            approximate_input = non_negative_int(
                nested_value(
                    payload,
                    ("approx_input_tokens",),
                    ("extra", "approx_input_tokens"),
                    ("request", "approx_input_tokens"),
                )
            )
            tokens = TokenUsage(
                input=(
                    estimated(
                        approximate_input,
                        "hermes_hook",
                        "host_approx_input_v1",
                    )
                    if approximate_input is not None
                    else unobservable(
                        "input_tokens_not_exposed",
                        source="host_not_exposed",
                    )
                )
            )
        else:
            cached_relation, write_relation = _provider_relations(provider, usage)
            tokens = tokens_from_usage(
                usage,
                source="hermes_hook",
                cached_relation=cached_relation,
                cache_write_relation=write_relation,
            )
        external_id = source_event_id or nested_value(
            payload,
            ("api_request_id",),
            ("request_id",),
            ("response_id",),
            ("call_id",),
            ("id",),
            ("extra", "api_request_id"),
            ("data", "request_id"),
        )
        safe_signature = {
            "tokens": tokens.to_dict(),
            "provider": provider,
            "model": labels["requested_model"],
            "completed_at": _safe_timestamp(
                payload,
                "completed_at",
                "ended_at",
                "timestamp",
            ),
        }
        lineage = lineage_hashes(payload, "hermes")
        raw_identity = (
            call_id
            or external_id
            or f"signature:{canonical_digest(safe_signature)}"
        )
        identity = canonical_digest(
            {
                "request_id_hash": hash_identifier("hermes-request", raw_identity),
                "session_id_hash": lineage["session_id_hash"],
                "host_task_id_hash": lineage["host_task_id_hash"],
            }
        )
        correlation_hash = hash_identifier("hermes-call", identity)
        observation = UsageObservation(
            adapter=self.name,
            adapter_version=self.version,
            source_kind=hook_event or "post_api_request",
            correlation_id_hash=correlation_hash,
            granularity="call",
            covered_call_count=exact(1, "hermes_hook", "hook_call_count_v1"),
            tokens=tokens,
            tool_call_count=tool_call_count_from_payload(
                payload,
                source="hermes_hook",
            ),
            cost=cost_from_mapping(
                (nested_mapping(usage, ("cost",)) if usage is not None else None)
                or nested_mapping(payload, ("extra", "cost"))
                or nested_mapping(payload, ("cost",)),
                source="hermes_hook",
            ),
            provider=provider,
            requested_model=labels["requested_model"],
            served_model=labels["served_model"],
            phase=safe_label(phase),
            status=(
                "failed"
                if hook_event == "api_request_error"
                else labels["status"]
            ),
            finish_reason=labels["finish_reason"],
            started_at=_safe_timestamp(
                payload,
                "started_at",
                "request_started_at",
            ),
            completed_at=_safe_timestamp(
                payload,
                "completed_at",
                "ended_at",
                "timestamp",
            ),
            latency=_hermes_latency(payload),
            **lineage,
        )
        dedupe_identity = identity
        return [
            AdapterRecord(
                dedupe_key=f"hermes-hook:{hook_event or 'usage'}:{dedupe_identity}",
                observation=observation,
            )
        ]

    def from_path(
        self,
        path: Path,
        *,
        phase: str | None = None,
    ) -> list[AdapterRecord]:
        """处理：导入 Hermes usage JSON 并避免同时重复计算 rows 和 totals。
        输入：调用方明确指定的本地 usage 文件及可选 phase。
        输出：优先逐 row 的 AdapterRecord；有 rows 时顶层 totals 仅作 reconciliation、不计费。
        """

        payload = parse_json_object_bytes(read_bounded_bytes(path), "Hermes usage file")
        rows_value = payload.get("results")
        if rows_value is None:
            rows_value = payload.get("batches")
        rows = (
            [row for row in rows_value if isinstance(row, Mapping)]
            if isinstance(rows_value, list)
            else []
        )
        if rows:
            return self._rows(rows, phase=phase)
        totals = nested_mapping(
            payload,
            ("totals",),
            ("total_usage",),
            ("usage",),
        ) or payload
        return [
            self._aggregate_record(
                totals,
                row=payload,
                phase=phase,
                row_identity=(
                    "top:"
                    + canonical_digest(
                        {
                            "usage": _safe_numeric_signature(totals),
                            "lineage": lineage_hashes(payload, "hermes"),
                        }
                    )
                ),
            )
        ]

    def _rows(
        self,
        rows: list[Mapping[str, Any]],
        *,
        phase: str | None,
    ) -> list[AdapterRecord]:
        """处理：把 usage-file 的批次行转换为独立 aggregate observations。
        输入：JSON results/batches 中的映射行和可选 phase。
        输出：按安全行内容摘要去重的 AdapterRecord 列表。
        """

        output: list[AdapterRecord] = []
        occurrences: dict[str, int] = {}
        for row in rows:
            usage = nested_mapping(row, ("usage",), ("tokens",)) or row
            signature = canonical_digest(
                {
                    "usage": tokens_from_usage(
                        usage,
                        source="hermes_usage_file",
                    ).to_dict(),
                    "row": _safe_numeric_signature(row),
                    "lineage": lineage_hashes(row, "hermes"),
                }
            )
            occurrence = occurrences.get(signature, 0) + 1
            occurrences[signature] = occurrence
            output.append(
                self._aggregate_record(
                    usage,
                    row=row,
                    phase=phase,
                    row_identity=f"row:{signature}:{occurrence}",
                )
            )
        return output

    def _aggregate_record(
        self,
        usage: Mapping[str, Any],
        *,
        row: Mapping[str, Any],
        phase: str | None,
        row_identity: str,
    ) -> AdapterRecord:
        """处理：规范一条 Hermes usage-file 聚合行。
        输入：安全 usage 映射、原行中的 allowlist 标签、phase 和稳定行身份。
        输出：covered calls 明确、逐 call 不足时保持 aggregate 的 AdapterRecord。
        """

        labels = safe_observation_labels(row)
        api_calls = non_negative_int(row.get("api_calls"))
        covered = (
            exact(api_calls, "hermes_usage_file", "reported_api_calls_v1")
            if api_calls is not None
            else unobservable("usage_file_did_not_expose_api_call_count")
        )
        granularity = "call" if api_calls == 1 else "aggregate"
        external_id = nested_value(row, ("request_id",), ("call_id",))
        batch_id = safe_label(row.get("batch_id"))
        correlation_source = external_id or batch_id or row_identity
        lineage = lineage_hashes(row, "hermes")
        correlation_hash = hash_identifier(
            "hermes-call",
            canonical_digest(
                {
                    "source_id_hash": hash_identifier(
                        "hermes-usage-source",
                        correlation_source,
                    ),
                    "session_id_hash": lineage["session_id_hash"],
                    "host_task_id_hash": lineage["host_task_id_hash"],
                }
            ),
        )
        tokens = tokens_from_usage(
            usage,
            source="hermes_usage_file",
            cached_relation=TokenRelation.UNKNOWN,
            cache_write_relation=TokenRelation.UNKNOWN,
        )
        observation = UsageObservation(
            adapter=self.name,
            adapter_version=self.version,
            source_kind="usage_file",
            correlation_id_hash=correlation_hash,
            granularity=granularity,
            covered_call_count=covered,
            tokens=tokens,
            tool_call_count=tool_call_count_from_payload(
                row,
                source="hermes_usage_file",
            ),
            cost=cost_from_mapping(
                nested_mapping(usage, ("cost",)) or nested_mapping(row, ("cost",)),
                source="hermes_usage_file",
            ),
            provider=labels["provider"],
            requested_model=labels["requested_model"],
            served_model=labels["served_model"],
            phase=safe_label(phase),
            status=labels["status"],
            finish_reason=labels["finish_reason"],
            started_at=_safe_timestamp(row, "started_at"),
            completed_at=_safe_timestamp(row, "completed_at", "timestamp"),
            latency=latency_from_payload(row, "hermes_usage_file"),
            batch_id=batch_id,
            task_index=non_negative_int(row.get("task_index")),
            **lineage,
        )
        return AdapterRecord(
            dedupe_key=f"hermes-usage:{row_identity}",
            observation=observation,
        )


def _provider_relations(
    provider: str | None,
    usage: Mapping[str, Any],
) -> tuple[TokenRelation | None, TokenRelation | None]:
    """处理：为 Hermes hook 中已知 Provider 补充缓存包含语义。
    输入：安全 provider 标签和 usage 数字键。
    输出：缓存读取/写入关系；不确定时返回 None 交给字段检测。
    """

    lowered = (provider or "").casefold()
    if all(key in usage for key in ("input_tokens", "cache_read_tokens", "cache_write_tokens")):
        # Hermes CanonicalUsage 的 input 已扣除缓存，与 provider 原始 prompt 语义不同。
        return TokenRelation.ADDITIONAL, TokenRelation.ADDITIONAL
    if "anthropic" in lowered:
        return TokenRelation.ADDITIONAL, TokenRelation.ADDITIONAL
    if nested_value(
        usage,
        ("prompt_tokens_details", "cached_tokens"),
        ("input_tokens_details", "cached_tokens"),
    ) is not None:
        return TokenRelation.SUBSET, TokenRelation.SUBSET
    return None, None


def _safe_timestamp(payload: Mapping[str, Any], *keys: str) -> str | None:
    """处理：把宿主 ISO 时间或 Unix 秒数转为规范带时区时间。
    输入：hook/row 映射和固定时间键名；只读有限数值或短字符串。
    输出：长度受限的规范时间文本；非法、溢出或缺失字段返回 None。
    """

    for key in keys:
        value = nested_value(payload, (key,), ("extra", key))
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            try:
                value = datetime.fromtimestamp(value, UTC).isoformat()
            except (ValueError, OverflowError, OSError):
                continue
        if normalized := normalize_timestamp(value):
            return normalized
    return None


def _hermes_latency(payload: Mapping[str, Any]) -> dict[str, Any]:
    """处理：合并 Hermes 顶层与 extra 中明确报告的单请求耗时。
    输入：一次 request-scoped hook payload；只读取固定 duration/latency 数字字段。
    输出：以毫秒计的测量字典；extra 与顶层缺失时保持空字典，不推断耗时。
    """

    top_level = latency_from_payload(payload, "hermes_hook")
    extra = nested_mapping(payload, ("extra",))
    if extra is None:
        return top_level
    nested = latency_from_payload(extra, "hermes_hook")
    return {**nested, **top_level}


def _safe_numeric_signature(payload: Mapping[str, Any]) -> dict[str, Any]:
    """处理：从 usage row 构造只含计数和短标签的去重签名。
    输入：可能还带摘要或工具轨迹的 Hermes 行。
    输出：不会包含 summary、prompt、response 或 tool arguments 的安全签名。
    """

    allowed_numeric = (
        "api_calls",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "reasoning_tokens",
        "tool_call_tokens",
        "duration_seconds",
        "duration_ms",
        "task_index",
    )
    signature: dict[str, Any] = {
        key: payload.get(key)
        for key in allowed_numeric
        if isinstance(payload.get(key), (int, float))
        and not isinstance(payload.get(key), bool)
    }
    for key in ("batch_id", "model", "provider", "status", "exit_reason"):
        if value := safe_label(payload.get(key)):
            signature[key] = value
    tokens = payload.get("tokens")
    if isinstance(tokens, Mapping):
        signature["tokens"] = {
            key: value
            for key, value in tokens.items()
            if key
            in {
                "input",
                "output",
                "cached_input",
                "cache_read",
                "cache_write",
                "reasoning",
                "tool_call",
                "total",
            }
            and isinstance(value, int)
            and not isinstance(value, bool)
            and value >= 0
        }
    return signature
