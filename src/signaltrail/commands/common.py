"""Shared CLI context and JSON output."""

from __future__ import annotations

import argparse
import json
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


def print_json(payload: object, *, indent: int | None = 2) -> None:
    """处理：向终端输出保留中文字符的 JSON。
    输入：
    - ``payload``：域函数返回的结果对象；保持字段和值原样输出。
    - ``indent``：调用命令选择的缩进；None 用于紧凑的单行结果。
    输出：标准输出中的 JSON；宿主可直接解析，函数不写入运行文件。
    """
    print(json.dumps(payload, ensure_ascii=False, indent=indent))


def print_json_file(path: Path) -> None:
    """处理：读取命令生成的 JSON 文件并输出内容。
    输入：
    - ``path``：域函数返回的运行或会话文件路径；读取已保存的结果。
    输出：标准输出中的 JSON，便于宿主取得下一步命令与产物路径。
    """
    print_json(read_json(path))
