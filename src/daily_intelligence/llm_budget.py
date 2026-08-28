from __future__ import annotations

from pathlib import Path
from typing import Any

from .llm_usage import UsageLedger
from .utils import now_iso

EVALUATOR_BASELINE_TOKENS = 2_884_621
EVALUATOR_CONTINGENCY_TOKENS = 288_463


def evaluate_llm_budget(
    run: dict[str, Any],
    data_dir: Path,
    phase: str,
) -> dict[str, Any]:
    """处理：按不可变 usage 事件与下游预留判断下一模型阶段能否分发。
    输入：
    - ``run``：当前运行清单；提供 max_agent_tokens 与已绑定 usage task ID。
    - ``data_dir``：当前运行唯一数据根；用来只读重建不可变用量摘要。
    - ``phase``：即将分发的 brief、analysis、repair 或 evaluation 安全短标签。
    输出：含已观测下界、覆盖状态、预留、上限和 allowed 的确定性门禁回执。
    """

    maximum = int(run.get("budget", {}).get("max_agent_tokens") or 0)
    tasks = run.get("llm_usage", {}).get("tasks", [])
    if maximum <= 0:
        return _budget_receipt(
            phase,
            maximum,
            observed=0,
            reserve=0,
            coverage="not_configured",
            allowed=True,
            task_count=0,
            reason="max_agent_tokens_not_configured",
        )
    if not isinstance(tasks, list) or not tasks:
        # 保留无宿主 hook 的旧版/手工工作流，但明确它不能形成精确优化基线。
        return _budget_receipt(
            phase,
            maximum,
            observed=0,
            reserve=_phase_reserve(maximum, phase),
            coverage="unmetered",
            allowed=True,
            task_count=0,
            reason="no_usage_task_bound",
        )

    ledger = UsageLedger(data_dir)
    observed = 0
    partial = False
    resolved = 0
    seen: set[str] = set()
    for row in tasks:
        if not isinstance(row, dict) or not row.get("task_id"):
            partial = True
            continue
        task_id = str(row["task_id"])
        if task_id in seen:
            continue
        seen.add(task_id)
        try:
            summary = ledger.summarize_task(task_id)
        except (FileNotFoundError, RuntimeError, TypeError, ValueError):
            partial = True
            continue
        resolved += 1
        measurement = summary.get("tokens", {}).get("accounted_total", {})
        value = measurement.get("known_value")
        if value is None:
            value = measurement.get("value")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            observed += int(value)
        quality = str(measurement.get("quality") or "unobservable")
        if quality == "unobservable" and int(measurement.get("unobservable_observations") or 0):
            partial = True
        if summary.get("conflicts"):
            partial = True

    reserve = _phase_reserve(maximum, phase)
    projected = observed + reserve
    coverage = "partial" if partial or resolved != len(seen) else "complete"
    allowed = projected <= maximum and not (
        coverage == "partial" and observed >= maximum
    )
    reason = (
        "observed_plus_reserve_exceeds_max_agent_tokens"
        if projected > maximum
        else (
            "partial_usage_coverage_observed_lower_bound_only"
            if coverage == "partial"
            else "within_budget"
        )
    )
    return _budget_receipt(
        phase,
        maximum,
        observed=observed,
        reserve=reserve,
        coverage=coverage,
        allowed=allowed,
        task_count=resolved,
        reason=reason,
    )


def append_budget_receipt(run: dict[str, Any], receipt: dict[str, Any]) -> None:
    """处理：把一次门禁判断幂等追加到运行清单的 LLM 预算轨迹。
    输入：
    - ``run``：当前可变运行清单；接收 llm_budget 检查轨迹和耗尽标记。
    - ``receipt``：evaluate_llm_budget 返回的不含模型正文的安全门禁回执。
    输出：无返回值；同阶段、时间和数值完全相同的回执不会重复追加。
    """

    budget_state = run.setdefault(
        "llm_budget",
        {"schema_version": "1.0", "checks": []},
    )
    checks = budget_state.setdefault("checks", [])
    if not checks or checks[-1] != receipt:
        checks.append(dict(receipt))
    budget_state["latest"] = dict(receipt)
    if not receipt.get("allowed"):
        run["budget_exhausted"] = True


def _phase_reserve(maximum: int, phase: str) -> int:
    """处理：按阶段保留评估、分析和一次有界修复的保守 token 容量。
    输入：
    - ``maximum``：运行配置允许的 agent token 硬上限。
    - ``phase``：待分发阶段短标签；决定仍需保留的下游工作。
    输出：版本化固定基线与上限比例共同得到的非负下游预留量。
    """

    normalized = phase.casefold().replace("-", "_")
    evaluator = EVALUATOR_BASELINE_TOKENS + EVALUATOR_CONTINGENCY_TOKENS
    if normalized in {"evaluation", "evaluator"}:
        return 0
    if "brief" in normalized and "repair" not in normalized:
        return min(maximum, evaluator + round(maximum * 0.15))
    if "analysis" in normalized and "repair" not in normalized:
        return min(maximum, evaluator + round(maximum * 0.05))
    if "repair" in normalized:
        return min(maximum, evaluator + round(maximum * 0.02))
    return min(maximum, evaluator)


def _budget_receipt(
    phase: str,
    maximum: int,
    *,
    observed: int,
    reserve: int,
    coverage: str,
    allowed: bool,
    task_count: int,
    reason: str,
) -> dict[str, Any]:
    """处理：构造不会把未知用量伪装为零的预算门禁安全结构。
    输入：
    - ``phase``：当前门禁对应的模型阶段短标签。
    - ``maximum``：运行允许的 agent token 上限。
    - ``observed``：usage 事件可证明的已核算 token 下界。
    - ``reserve``：当前阶段之后仍需保留的 token 容量。
    - ``coverage``：complete、partial、unmetered 或 not_configured 证据状态。
    - ``allowed``：已观测加预留是否允许继续分发。
    - ``task_count``：成功解析并参与本次计算的 usage task 数量。
    - ``reason``：不会包含宿主正文的稳定机器原因。
    输出：可写入运行清单或拒绝回执的 schema 1.0 字典。
    """

    return {
        "schema_version": "1.0",
        "checked_at": now_iso("UTC"),
        "phase": phase,
        "max_agent_tokens": maximum,
        "observed_accounted_tokens": observed if coverage != "unmetered" else None,
        "observed_quality": (
            "unobservable"
            if coverage == "unmetered"
            else "lower_bound"
            if coverage == "partial"
            else "exact"
        ),
        "downstream_reserve_tokens": reserve,
        "projected_tokens": (
            observed + reserve if coverage != "unmetered" else None
        ),
        "task_count": task_count,
        "coverage": coverage,
        "allowed": allowed,
        "reason": reason,
        "policy": "measured_downstream_reserve_v1",
    }
