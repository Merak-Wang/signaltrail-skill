"""Shared CLI context and JSON output."""

from __future__ import annotations

import argparse
import json
import sys
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from ..config import AppConfig
from ..utils import read_json

JSON_RECEIPTS: ContextVar[list | None] = ContextVar("json_receipts", default=None)


@dataclass(frozen=True)
class CommandContext:
    """处理：向命令传递已解析的配置和数据根。
    输入：
    - ``config``：配置加载器读取的来源、语言和输出设置。
    - ``data_dir``：入口确认绑定的运行目录；域函数据此校验产物路径。
    - ``parser``：当前命令树；处理函数用它报告依赖多个参数的用法错误。
    输出：不可替换字段的命令上下文；各处理函数按需消费，避免重复初始化。
    """

    config: AppConfig
    data_dir: Path
    parser: argparse.ArgumentParser
    compact: bool = False


def print_json(payload: object, *, indent: int | None = 2) -> None:
    """处理：按终端编码输出 JSON，无法表示的字符改用无损转义。
    输入：
    - ``payload``：域函数返回的结果对象；保持字段和值原样输出。
    - ``indent``：调用命令选择的缩进；None 用于紧凑的单行结果。
    输出：标准输出中的 JSON；宿主可直接解析，函数不写入运行文件。
    """
    if (receipts := JSON_RECEIPTS.get()) is not None:
        receipts.append(payload)
        return
    separators = (",", ":") if indent is None else None
    rendered = json.dumps(payload, ensure_ascii=False, indent=indent, separators=separators)
    try:
        rendered.encode(sys.stdout.encoding or "utf-8")
    except UnicodeEncodeError:
        rendered = json.dumps(payload, ensure_ascii=True, indent=indent, separators=separators)
    print(rendered)


def print_json_file(path: Path) -> None:
    """读取命令生成的 JSON 文件并输出内容。
    输入：``path``：域函数返回的运行或会话文件路径；读取已保存的结果。
    输出：标准输出中的 JSON，便于宿主取得下一步命令与产物路径。
    """
    print_json(read_json(path))


def _selection_summary(run: dict) -> dict:
    """处理：从已保存的索引和协调包提取正文补充选择所需的小回执。
    输入：待选择版次的运行清单；路径指向原有不可变文件。
    输出：冻结窗口、来源状态和最多十二条建议，不新增文件或请求。
    """
    artifacts = run.get("artifacts", {})
    try:
        context_path = artifacts.get("coordinator_path") or artifacts["context_path"]
        coordinator = read_json(Path(context_path))
        index = read_json(Path(artifacts["index_path"]))
    except (KeyError, OSError, ValueError, TypeError):
        return {}
    sources = index.get("sources", [])
    problems = [{"source_id": row.get("source_id"), "status": row.get("status")}
                for row in sources if row.get("status") not in {"success", "no_items"}]
    candidates = {row.get("item_id"): row for row in coordinator.get("candidate_items", [])}
    actions = coordinator.get("enrichment_plan", {}).get("actions", [])[:12]
    suggestions = []
    for action in actions:
        candidate = candidates.get(action.get("item_id"), {})
        suggestions.append({
            "item_id": action.get("item_id"), "source_id": action.get("source_id"),
            "title": candidate.get("title"), "description": candidate.get("description", "")[:600],
            "url": candidate.get("canonical_url"), "domain": action.get("domain"),
            "missing": action.get("missing_claim_or_field"),
            "priority": action.get("priority"),
            "priority_components": action.get("priority_components"),
        })
    return {"collection_window": run.get("collection_window"),
            "source_count": len(sources), "problem_source_count": len(problems),
            "problem_sources": problems, "suggestions": suggestions}


def print_command_result(payload: dict, context: CommandContext,
                         artifact_path: Path | None = None) -> None:
    """处理：按显式选项投影回执，保留下一步操作所需状态和产物路径。
    输入：域函数结果、命令上下文及可选的完整结果文件。
    输出：默认完整 JSON；紧凑模式省略正文和逐批计量，完整数据仍保存在原文件。
    """
    if not context.compact:
        print_json(payload)
        return
    fields = {
        "status", "report_status", "delivery_complete", "pending_steps", "next_action",
        "error", "errors", "coverage", "count", "batch_id", "domain", "stage",
        "missing_batches", "pending_batches", "accepted_batches", "completed_batches",
        "max_news", "exclude_event_ids", "deadline", "analysis_deadline", "required",
        "deadline_at", "analysis_deadline_at", "deadline_exceeded", "remaining_seconds",
        "expected_batches", "reason", "cost_usd", "estimated_cost_usd", "cost_source",
        "input_tokens", "output_tokens", "total_tokens", "submission_attempt", "repair_attempts",
    }

    def project(value: dict) -> dict:
        """处理：递归保留状态和路径，批次数组仅保留每批回执。
        输入：原始结果或其中的嵌套对象。
        输出：不含新闻正文和逐批计量的短对象。
        """
        result = {}
        for key, item in value.items():
            if key in {"coverage", "coverage_targets", "errors", "error", "warnings",
                       "recovered_batches", "rejection_receipts"}:
                result[key] = item
            elif isinstance(item, dict):
                if nested := project(item):
                    result[key] = nested
            elif isinstance(item, list) and item and isinstance(item[0], dict):
                if key in {"batches", "domain_packets"}:
                    result[key] = [project(row) for row in item]
            elif (key in fields
                  or key.endswith(("_path", "_paths", "_count", "_command", "_status"))
                  or key == "command"):
                result[key] = item
        return result

    result = project(payload)
    if payload.get("status") == "awaiting_selection" and (selection := _selection_summary(payload)):
        result["selection"] = selection
    if artifact_path is not None:
        result = {"artifact_path": str(artifact_path), **result}
    print_json(result, indent=None)


def batch_submission_result(rows: list[dict], accepted: list[str], check_only: bool) -> dict:
    """处理：汇总简报和图文共用的批次接收结果，保留接收顺序和逐项错误。
    输入：逐批判定、已接收产物及预检标记。
    输出：命令行和调度器读取的相同收据。
    """
    pending = [row["batch_id"] for row in rows if not row.get("accepted_path")]
    invalid = [row["batch_id"] for row in rows if row["errors"]]
    return {"status": "partial" if invalid else "ready_to_submit" if pending else "ready",
            "check_only": check_only, "accepted": accepted, "pending": pending, "invalid": invalid,
            "expected_paths": [row["expected_path"] for row in rows], "batches": rows}
