from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Any

SAFE_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,159}$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_CREDENTIAL_PATTERNS = (
    re.compile(r"^sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{8,}$", re.I),
    re.compile(r"^(?:gh[pousr]|github_pat)_[A-Za-z0-9_]{8,}$", re.I),
    re.compile(r"^xox[baprs]-[A-Za-z0-9-]{8,}$", re.I),
    re.compile(r"^AIza[0-9A-Za-z_-]{20,}$"),
    re.compile(r"^[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}$"),
)
_WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


class ObservationQuality(StrEnum):
    """处理：声明用量数值的证据等级。
    输入：无显式业务参数；成员由适配器按宿主回执能力选择。
    输出：``exact``、``estimated`` 或 ``unobservable``，供汇总时保留未知量。
    """

    EXACT = "exact"
    ESTIMATED = "estimated"
    UNOBSERVABLE = "unobservable"


class TokenRelation(StrEnum):
    """处理：声明缓存 token 相对 input 总量的包含关系。
    输入：无显式业务参数；成员来自提供商计数语义。
    输出：子集、额外量或未知关系，防止跨提供商重复求和。
    """

    SUBSET = "subset_of_input"
    ADDITIONAL = "additional_to_input"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Measurement:
    """处理：保存一个非负数值及其精确、估算或不可观测证据。
    输入：``value`` 来自宿主回执或本地算法；``quality``、来源和方法描述其可信级别。
    输出：可安全序列化的测量对象；未知值必须保持 None，不能降格为零。
    """

    value: int | float | None
    quality: ObservationQuality
    source: str
    method: str | None = None
    reason: str | None = None
    lower_bound: int | float | None = None
    upper_bound: int | float | None = None

    def __post_init__(self) -> None:
        """处理：校验测量值、区间和不可观测语义。
        输入：当前实例中由适配器构造的数值与证据字段。
        输出：合法实例不变；负数、非有限值或 unknown 携带数值时抛出 ValueError。
        """

        quality = ObservationQuality(self.quality)
        object.__setattr__(self, "quality", quality)
        if not safe_label(self.source):
            raise ValueError("Measurement source must be a bounded safe label")
        if self.method is not None and not safe_label(self.method):
            raise ValueError("Measurement method must be a bounded safe label")
        if quality is ObservationQuality.UNOBSERVABLE:
            if self.value is not None:
                raise ValueError("Unobservable measurements must use value=None")
            if not safe_label(self.reason):
                raise ValueError(
                    "Unobservable measurements require a bounded safe reason"
                )
            return
        if self.value is None:
            raise ValueError("Exact and estimated measurements require a value")
        _validate_non_negative_number(self.value, "Measurement value")
        if quality is ObservationQuality.EXACT and (
            self.lower_bound is not None or self.upper_bound is not None
        ):
            raise ValueError("Exact measurements cannot carry estimate bounds")
        for label, bound in (
            ("lower_bound", self.lower_bound),
            ("upper_bound", self.upper_bound),
        ):
            if bound is not None:
                _validate_non_negative_number(bound, label)
        if self.lower_bound is not None and self.lower_bound > self.value:
            raise ValueError("lower_bound cannot exceed value")
        if self.upper_bound is not None and self.upper_bound < self.value:
            raise ValueError("upper_bound cannot be below value")

    def to_dict(self) -> dict[str, Any]:
        """处理：把测量对象转换为不包含多余空字段的 JSON 字典。
        输入：当前测量实例的数值、证据等级和可选估算区间。
        输出：供不可变事件和汇总使用的安全字典。
        """

        payload: dict[str, Any] = {
            "value": self.value,
            "quality": self.quality.value,
            "source": self.source,
        }
        for name in ("method", "reason", "lower_bound", "upper_bound"):
            value = getattr(self, name)
            if value is not None:
                payload[name] = value
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Measurement:
        """处理：从已校验事件字典恢复测量对象。
        输入：本地 ledger 事件中的 measurement 映射。
        输出：重新执行不变量校验后的 Measurement 实例。
        """

        return cls(
            value=payload.get("value"),
            quality=ObservationQuality(str(payload["quality"])),
            source=str(payload["source"]),
            method=_optional_text(payload.get("method")),
            reason=_optional_text(payload.get("reason")),
            lower_bound=payload.get("lower_bound"),
            upper_bound=payload.get("upper_bound"),
        )


def exact(value: int | float, source: str, method: str | None = None) -> Measurement:
    """处理：构造由宿主或确定性推导提供的精确测量。
    输入：非负数值、受控来源标签和可选方法版本。
    输出：quality 为 exact 的 Measurement。
    """

    return Measurement(value, ObservationQuality.EXACT, source, method=method)


def estimated(
    value: int | float,
    source: str,
    method: str,
    *,
    lower_bound: int | float | None = None,
    upper_bound: int | float | None = None,
) -> Measurement:
    """处理：构造本地 tokenizer 或启发式方法产生的估算测量。
    输入：估算值、来源、算法版本及可选上下界。
    输出：quality 为 estimated 且保留方法证据的 Measurement。
    """

    return Measurement(
        value,
        ObservationQuality.ESTIMATED,
        source,
        method=method,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
    )


def unobservable(reason: str, source: str = "not_exposed") -> Measurement:
    """处理：构造明确不可观测且不伪造零值的测量。
    输入：宿主未暴露或记录粒度不足的短原因和来源标签。
    输出：value 为 None、quality 为 unobservable 的 Measurement。
    """

    return Measurement(None, ObservationQuality.UNOBSERVABLE, source, reason=reason)


def _unknown_token() -> Measurement:
    """处理：为适配器尚未提供的 token 字段生成默认未知值。
    输入：无显式业务参数。
    输出：不会在汇总时被当成零的 unobservable Measurement。
    """

    return unobservable("adapter_did_not_expose_field")


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """处理：保存跨提供商可比较的 token 分解与包含语义。
    输入：input、缓存、output、reasoning、tool-call 和提供商 total 的字段级测量。
    输出：保留 reasoning/tool-call 为 output 子集、缓存关系显式化的 token 记录。
    """

    input: Measurement = field(default_factory=_unknown_token)
    cached_input: Measurement = field(default_factory=_unknown_token)
    cache_write_input: Measurement = field(default_factory=_unknown_token)
    output: Measurement = field(default_factory=_unknown_token)
    reasoning_output: Measurement = field(default_factory=_unknown_token)
    tool_call_output: Measurement = field(default_factory=_unknown_token)
    reported_total: Measurement = field(default_factory=_unknown_token)
    cached_input_relation: TokenRelation = TokenRelation.UNKNOWN
    cache_write_input_relation: TokenRelation = TokenRelation.UNKNOWN

    def __post_init__(self) -> None:
        """处理：校验所有可观测 token 都是整数且包含关系合法。
        输入：当前 token 分解中的七个 measurement 和两个缓存关系。
        输出：合法实例不变；非整数 token 或非法关系抛出 ValueError。
        """

        object.__setattr__(
            self,
            "cached_input_relation",
            TokenRelation(self.cached_input_relation),
        )
        object.__setattr__(
            self,
            "cache_write_input_relation",
            TokenRelation(self.cache_write_input_relation),
        )
        for name in TOKEN_FIELDS:
            measurement = getattr(self, name)
            if measurement.value is not None and (
                isinstance(measurement.value, bool)
                or not isinstance(measurement.value, int)
            ):
                raise ValueError(f"{name} token measurement must be an integer")
            for bound in (measurement.lower_bound, measurement.upper_bound):
                if bound is not None and (
                    isinstance(bound, bool) or not isinstance(bound, int)
                ):
                    raise ValueError(f"{name} token estimate bounds must be integers")

    def to_dict(self) -> dict[str, Any]:
        """处理：序列化 token 分解并固定输出子集关系。
        输入：当前实例的字段级测量和缓存包含语义。
        输出：可由 schema 校验且不会重复累加 reasoning/tool-call 的字典。
        """

        return {
            **{name: getattr(self, name).to_dict() for name in TOKEN_FIELDS},
            "relationships": {
                "cached_input": self.cached_input_relation.value,
                "cache_write_input": self.cache_write_input_relation.value,
                "reasoning_output": "subset_of_output",
                "tool_call_output": "subset_of_output",
            },
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> TokenUsage:
        """处理：从本地事件恢复 token 分解并重新校验子集语义。
        输入：usage.observed 事件中的 tokens 字典。
        输出：TokenUsage 实例；reasoning/tool-call 仍只作为 output 诊断子集。
        """

        relationships = payload.get("relationships", {})
        return cls(
            **{
                name: Measurement.from_dict(dict(payload[name]))
                for name in TOKEN_FIELDS
            },
            cached_input_relation=TokenRelation(
                str(relationships.get("cached_input", TokenRelation.UNKNOWN))
            ),
            cache_write_input_relation=TokenRelation(
                str(relationships.get("cache_write_input", TokenRelation.UNKNOWN))
            ),
        )

    def accounted_total(self) -> Measurement:
        """处理：按提供商包含关系计算一次调用的不重复 token 总量。
        输入：当前 input/output、缓存量和 provider-reported total。
        输出：采用内部一致的 reported_total；异常零值回退到不重叠字段且不重复加输出子集。
        """

        if self.reported_total.value is not None:
            known_floor = (
                int(self.input.value) + int(self.output.value)
                if self.input.value is not None and self.output.value is not None
                else None
            )
            if known_floor is None or int(self.reported_total.value) >= known_floor:
                return self.reported_total
            derived = self._derived_total()
            if derived.value is not None:
                return Measurement(
                    int(derived.value),
                    derived.quality,
                    "derived",
                    method="inconsistent_reported_total_fallback_v1",
                )
            return unobservable(
                "reported_total_below_known_input_output",
                source="derived",
            )
        return self._derived_total()

    def _derived_total(self) -> Measurement:
        """处理：在没有可信 provider total 时从明确不重叠的 token 桶求和。
        输入：当前 input/output 以及两个缓存量相对 input 的包含关系。
        输出：关系和数值完整时返回派生总量；任何必要字段未知时保持不可观测。
        """

        components = [self.input, self.output]
        for relation, measurement in (
            (self.cached_input_relation, self.cached_input),
            (self.cache_write_input_relation, self.cache_write_input),
        ):
            if relation is TokenRelation.UNKNOWN:
                return unobservable(
                    "provider_input_cache_relationship_unknown",
                    source="derived",
                )
            if relation is TokenRelation.ADDITIONAL:
                components.append(measurement)
        if any(item.value is None for item in components):
            return unobservable("required_total_component_unobservable", source="derived")
        quality = (
            ObservationQuality.ESTIMATED
            if any(item.quality is ObservationQuality.ESTIMATED for item in components)
            else ObservationQuality.EXACT
        )
        value = sum(int(item.value) for item in components if item.value is not None)
        if quality is ObservationQuality.ESTIMATED:
            return estimated(value, "derived", "non_overlapping_token_sum_v1")
        return exact(value, "derived", "non_overlapping_token_sum_v1")


TOKEN_FIELDS = (
    "input",
    "cached_input",
    "cache_write_input",
    "output",
    "reasoning_output",
    "tool_call_output",
    "reported_total",
)


@dataclass(frozen=True, slots=True)
class CostMeasurement:
    """处理：保存提供商回执或本地价目表计算出的货币成本。
    输入：十进制金额文本、币种、证据等级和来源；未知金额保持 None。
    输出：不使用二进制浮点且可追溯质量的成本记录。
    """

    amount: str | None
    currency: str | None
    quality: ObservationQuality
    source: str
    method: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        """处理：校验成本金额、币种和不可观测语义。
        输入：当前实例中的十进制金额与证据字段。
        输出：合法实例不变；负金额、非法币种或 unknown 携带金额时抛错。
        """

        quality = ObservationQuality(self.quality)
        object.__setattr__(self, "quality", quality)
        if not safe_label(self.source):
            raise ValueError("Cost source must be a bounded safe label")
        if self.method is not None and not safe_label(self.method):
            raise ValueError("Cost method must be a bounded safe label")
        if quality is ObservationQuality.UNOBSERVABLE:
            if self.amount is not None or self.currency is not None:
                raise ValueError(
                    "Unobservable cost must use amount=None and currency=None"
                )
            if not safe_label(self.reason):
                raise ValueError("Unobservable cost requires a bounded safe reason")
            return
        if self.amount is None or self.currency is None:
            raise ValueError("Observable cost requires amount and currency")
        try:
            parsed = Decimal(self.amount)
        except InvalidOperation as exc:
            raise ValueError("Cost amount must be a decimal string") from exc
        if not parsed.is_finite() or parsed < 0:
            raise ValueError("Cost amount must be finite and non-negative")
        currency = self.currency.upper()
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise ValueError("Cost currency must be a three-letter code")
        object.__setattr__(self, "currency", currency)

    def to_dict(self) -> dict[str, Any]:
        """处理：将成本测量转换为安全 JSON 字典。
        输入：当前金额、币种和证据字段。
        输出：金额仍为十进制字符串的可持久化映射。
        """

        payload: dict[str, Any] = {
            "amount": self.amount,
            "currency": self.currency,
            "quality": self.quality.value,
            "source": self.source,
        }
        if self.method is not None:
            payload["method"] = self.method
        if self.reason is not None:
            payload["reason"] = self.reason
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CostMeasurement:
        """处理：从 ledger 事件恢复成本测量。
        输入：事件中通过 allowlist 保存的 cost 字典。
        输出：重新校验金额精度和币种后的 CostMeasurement。
        """

        return cls(
            amount=_optional_text(payload.get("amount")),
            currency=_optional_text(payload.get("currency")),
            quality=ObservationQuality(str(payload["quality"])),
            source=str(payload["source"]),
            method=_optional_text(payload.get("method")),
            reason=_optional_text(payload.get("reason")),
        )


def unknown_cost(reason: str = "host_did_not_expose_cost") -> CostMeasurement:
    """处理：生成不会被误认为零费用的不可观测成本。
    输入：宿主未提供账单金额的短原因。
    输出：amount 和 currency 均为空的 unobservable CostMeasurement。
    """

    return CostMeasurement(
        None,
        None,
        ObservationQuality.UNOBSERVABLE,
        "not_exposed",
        reason=reason,
    )


@dataclass(frozen=True, slots=True)
class UsageObservation:
    """处理：表示一个逐调用或聚合宿主回执的安全规范记录。
    输入：适配器元数据、哈希关联键、token/cost、时间和受限状态字段。
    输出：不含 prompt、response、reasoning 文本或工具参数的 observation。
    """

    adapter: str
    adapter_version: str
    source_kind: str
    correlation_id_hash: str
    granularity: str
    covered_call_count: Measurement
    tokens: TokenUsage
    tool_call_count: Measurement = field(
        default_factory=lambda: unobservable("tool_call_count_not_exposed")
    )
    cost: CostMeasurement = field(default_factory=unknown_cost)
    session_id_hash: str | None = None
    turn_id_hash: str | None = None
    parent_session_id_hash: str | None = None
    host_task_id_hash: str | None = None
    provider: str | None = None
    requested_model: str | None = None
    served_model: str | None = None
    phase: str | None = None
    status: str | None = None
    finish_reason: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    latency: dict[str, Measurement] = field(default_factory=dict)
    batch_id: str | None = None
    task_index: int | None = None
    agent_role: str | None = None
    run_attempt: int | None = None
    repair_attempt: int | None = None
    evaluation_attempt: int | None = None

    def __post_init__(self) -> None:
        """处理：限制 observation 的字符串、粒度、计数和 latency 字段。
        输入：适配器刚完成规范化的全部安全字段。
        输出：满足持久化 allowlist 的实例；可疑自由文本或非法计数被拒绝。
        """

        for name in ("adapter", "adapter_version", "source_kind"):
            if not safe_label(str(getattr(self, name))):
                raise ValueError(f"{name} must be a bounded safe label")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.correlation_id_hash):
            raise ValueError("correlation_id_hash must be a SHA-256 label")
        for name in (
            "session_id_hash",
            "turn_id_hash",
            "parent_session_id_hash",
            "host_task_id_hash",
        ):
            value = getattr(self, name)
            if value is not None and not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
                raise ValueError(f"{name} must be a SHA-256 label")
        if self.granularity not in {"call", "aggregate"}:
            raise ValueError("granularity must be call or aggregate")
        if self.covered_call_count.value is not None and (
            isinstance(self.covered_call_count.value, bool)
            or not isinstance(self.covered_call_count.value, int)
        ):
            raise ValueError("covered_call_count must be an integer measurement")
        for name in (
            "provider",
            "requested_model",
            "served_model",
            "phase",
            "status",
            "finish_reason",
            "batch_id",
            "agent_role",
        ):
            value = getattr(self, name)
            if value is not None and not safe_label(value):
                raise ValueError(f"{name} must be a bounded safe label")
        for name in ("started_at", "completed_at"):
            value = getattr(self, name)
            if value is None:
                continue
            normalized = normalize_timestamp(value)
            if normalized is None:
                raise ValueError(f"{name} must be a timezone-aware ISO-8601 timestamp")
            object.__setattr__(self, name, normalized)
        for name in (
            "task_index",
            "run_attempt",
            "repair_attempt",
            "evaluation_attempt",
        ):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(f"{name} must be a non-negative integer")
        allowed_latency = {
            "wall_ms",
            "queue_ms",
            "first_token_ms",
            "prefill_ms",
            "decode_ms",
        }
        if set(self.latency) - allowed_latency:
            raise ValueError("Observation latency contains an unsupported field")

    def to_dict(self) -> dict[str, Any]:
        """处理：将规范 observation 序列化为严格 allowlist 字典。
        输入：当前实例中已经校验的数值、短标签和哈希关联信息。
        输出：不会包含宿主原始 payload 或对话内容的事件数据。
        """

        payload: dict[str, Any] = {
            "adapter": self.adapter,
            "adapter_version": self.adapter_version,
            "source_kind": self.source_kind,
            "correlation_id_hash": self.correlation_id_hash,
            "granularity": self.granularity,
            "covered_call_count": self.covered_call_count.to_dict(),
            "tokens": self.tokens.to_dict(),
            "tool_call_count": self.tool_call_count.to_dict(),
            "cost": self.cost.to_dict(),
            "latency": {
                key: value.to_dict() for key, value in sorted(self.latency.items())
            },
        }
        for name in (
            "provider",
            "requested_model",
            "served_model",
            "phase",
            "status",
            "finish_reason",
            "started_at",
            "completed_at",
            "batch_id",
            "task_index",
            "agent_role",
            "run_attempt",
            "repair_attempt",
            "evaluation_attempt",
            "session_id_hash",
            "turn_id_hash",
            "parent_session_id_hash",
            "host_task_id_hash",
        ):
            value = getattr(self, name)
            if value is not None:
                payload[name] = value
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> UsageObservation:
        """处理：从不可变事件恢复规范 observation。
        输入：usage.observed 事件中的 allowlist data。
        输出：重新执行 token、成本和字符串限制后的 UsageObservation。
        """

        observation = cls(
            adapter=str(payload["adapter"]),
            adapter_version=str(payload["adapter_version"]),
            source_kind=str(payload["source_kind"]),
            correlation_id_hash=str(payload["correlation_id_hash"]),
            granularity=str(payload["granularity"]),
            covered_call_count=Measurement.from_dict(
                dict(payload["covered_call_count"])
            ),
            tokens=TokenUsage.from_dict(dict(payload["tokens"])),
            tool_call_count=Measurement.from_dict(dict(payload["tool_call_count"])),
            cost=CostMeasurement.from_dict(dict(payload["cost"])),
            session_id_hash=_optional_text(payload.get("session_id_hash")),
            turn_id_hash=_optional_text(payload.get("turn_id_hash")),
            parent_session_id_hash=_optional_text(
                payload.get("parent_session_id_hash")
            ),
            host_task_id_hash=_optional_text(payload.get("host_task_id_hash")),
            provider=_optional_text(payload.get("provider")),
            requested_model=_optional_text(payload.get("requested_model")),
            served_model=_optional_text(payload.get("served_model")),
            phase=_optional_text(payload.get("phase")),
            status=_optional_text(payload.get("status")),
            finish_reason=_optional_text(payload.get("finish_reason")),
            started_at=_optional_text(payload.get("started_at")),
            completed_at=_optional_text(payload.get("completed_at")),
            latency={
                str(key): Measurement.from_dict(dict(value))
                for key, value in dict(payload.get("latency", {})).items()
            },
            batch_id=_optional_text(payload.get("batch_id")),
            task_index=payload.get("task_index"),
            agent_role=_optional_text(payload.get("agent_role")),
            run_attempt=payload.get("run_attempt"),
            repair_attempt=payload.get("repair_attempt"),
            evaluation_attempt=payload.get("evaluation_attempt"),
        )
        for timestamp_key in ("started_at", "completed_at"):
            historical_timestamp = payload.get(timestamp_key)
            if (
                isinstance(historical_timestamp, str)
                and normalize_timestamp(historical_timestamp) is not None
            ):
                # Reading preserves immutable v1.0 provider precision; direct construction
                # still normalizes all newly written adapter observations to whole seconds.
                object.__setattr__(observation, timestamp_key, historical_timestamp)
        return observation


@dataclass(frozen=True, slots=True)
class AdapterRecord:
    """处理：把适配器输出与不可变事件的去重键配对。
    输入：不含秘密的稳定 dedupe key 和规范 UsageObservation。
    输出：ledger 可原子写入且重复导入保持幂等的记录。
    """

    dedupe_key: str
    observation: UsageObservation


@dataclass(frozen=True, slots=True)
class TaskHandle:
    """处理：携带已创建 usage task 的本地定位信息。
    输入：数据根、task ID、UTC 日期和任务目录。
    输出：供后续 call、import、summary 和 finalize API 使用的不可变句柄。
    """

    data_dir: Path
    task_id: str
    date: str
    path: Path


@dataclass(frozen=True, slots=True)
class CallHandle:
    """处理：携带一次已开始模型调用的任务和 call 标识。
    输入：父 TaskHandle、call ID、phase 和 started_at。
    输出：供 hook 回执关联或显式 finish/fail 使用的不可变句柄。
    """

    task: TaskHandle
    call_id: str
    phase: str
    started_at: str
    batch_id: str | None = None
    agent_role: str | None = None
    run_attempt: int | None = None
    repair_attempt: int | None = None
    evaluation_attempt: int | None = None
    parent_session_id_hash: str | None = None


def safe_label(value: object) -> str | None:
    """处理：仅接受不会承载 prompt 或秘密的短机器标签。
    输入：宿主回执中的 provider、model、状态或 phase 候选值。
    输出：匹配受限字符集的字符串；自由文本、空值或超长值返回 None。
    """

    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if any(pattern.fullmatch(candidate) for pattern in _CREDENTIAL_PATTERNS):
        return None
    return candidate if SAFE_LABEL_RE.fullmatch(candidate) else None


def normalize_timestamp(value: object) -> str | None:
    """处理：严格解析宿主时间并规范为 UTC 秒级 ISO 文本。
    输入：适配器固定时间字段中的候选值；不接受无时区文本或任意标签。
    输出：合法时间的 UTC 字符串；缺失或非法值返回 None，避免把秘密写进时间字段。
    """

    if not isinstance(value, str) or not 1 <= len(value) <= 64:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC).isoformat(timespec="seconds")


def validate_id(value: str, label: str) -> str:
    """处理：校验 task/call 等文件路径标识，阻止路径穿越。
    输入：待用于目录或文件名的 ID 及错误标签。
    输出：原安全 ID；非法字符、分隔符或超长值抛出 ValueError。
    """

    if not SAFE_ID_RE.fullmatch(value) or value.endswith("."):
        raise ValueError(f"{label} must be a bounded filesystem-safe identifier")
    if value.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_NAMES:
        raise ValueError(f"{label} uses a reserved filesystem identifier")
    return value


def _validate_non_negative_number(value: int | float, label: str) -> None:
    """处理：拒绝布尔、负数和非有限测量值。
    输入：宿主回执解析出的数值及错误标签。
    输出：合法时无返回；非法时抛出 ValueError，避免污染账本。
    """

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    if not math.isfinite(float(value)) or value < 0:
        raise ValueError(f"{label} must be finite and non-negative")


def _optional_text(value: object) -> str | None:
    """处理：将本地事件中的可选标量恢复为字符串。
    输入：反序列化字典中的可选字段。
    输出：None 或字符串值；不读取任何外部内容。
    """

    return None if value is None else str(value)
