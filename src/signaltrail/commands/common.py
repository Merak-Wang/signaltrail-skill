"""Shared CLI context and JSON output."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from ..config import AppConfig
from ..utils import read_json


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
    rendered = json.dumps(payload, ensure_ascii=False, indent=indent)
    try:
        rendered.encode(sys.stdout.encoding or "utf-8")
    except UnicodeEncodeError:
        rendered = json.dumps(payload, ensure_ascii=True, indent=indent)
    print(rendered)


def print_json_file(path: Path) -> None:
    """处理：读取命令生成的 JSON 文件并输出内容。
    输入：
    - ``path``：域函数返回的运行或会话文件路径；读取已保存的结果。
    输出：标准输出中的 JSON，便于宿主取得下一步命令与产物路径。
    """
    print_json(read_json(path))


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
    if artifact_path is not None:
        result = {"artifact_path": str(artifact_path), **result}
    print_json(result, indent=None)
