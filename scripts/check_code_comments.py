"""Enforce concise Chinese input/output/logic notes on maintained Python definitions."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHINESE_PATTERN = re.compile(r"[\u3400-\u9fff]")
MAINTENANCE_SCRIPTS = (
    "build_hermes_skill.py",
    "check_code_comments.py",
    "check_docs.py",
)
EMPTY_DESCRIPTION_PATTERNS = (
    "类型的处理结果",
    "其字段和方法共同承担上述职责",
    "副作用限于该处理声明的受控对象或产物",
    "键值表达该处理定义的业务记录或查找关系",
    "元素结构见调用处",
    "参与“",
    "上述处理通过更新",
    "数据来自当前实例、外层受控作用域",
    "身份、状态、指标或映射关系",
    "有序领域对象列表",
    "每项只包含下游契约需要的字段",
    "主结果与伴随状态的固定结构数据",
    "领域对象；供调用方进入下一业务步骤",
    "的核心流程",
    "的内部处理步骤",
    "的单项处理",
    "当前步骤所需的",
    "对应的文本或标识",
    "默认语义由函数签名",
    "具体结构由",
    "描述上述处理状态",
)


def python_targets(root: Path = ROOT) -> list[Path]:
    """列出规范包及维护脚本中需要检查中文说明的 Python 文件。"""
    source_files = sorted((root / "src" / "signaltrail").rglob("*.py"))
    script_files = [root / "scripts" / name for name in MAINTENANCE_SCRIPTS]
    return [*source_files, *script_files]


def definition_errors(path: Path, root: Path = ROOT) -> list[str]:
    """检查源码中函数和类的中文说明，返回带相对路径、行号和定义名的问题。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    errors: list[str] = []
    relative = path.relative_to(root)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        docstring = ast.get_docstring(node, clean=False)
        label = f"{relative}:{node.lineno} {node.name}"
        if not docstring:
            errors.append(f"{label}: missing docstring")
            continue
        summary = docstring.splitlines()[0]
        if not CHINESE_PATTERN.search(summary.removeprefix("处理：")):
            errors.append(f"{label}: explain the behavior in Chinese")
        if f"``{node.name}``" in summary:
            errors.append(f"{label}: summary must explain behavior, not repeat its identifier")
        # 复杂契约可分段说明；简单转换在一句话中写清输入、行为和用途。
        for marker, following in (("输入：", "输出："), ("输出：", None)):
            _, present, section = docstring.partition(marker)
            if following:
                section = section.partition(following)[0]
            if present and not CHINESE_PATTERN.search(section):
                errors.append(f"{label}: {marker} needs a concrete Chinese description")
        for empty_pattern in EMPTY_DESCRIPTION_PATTERNS:
            if empty_pattern in docstring:
                errors.append(
                    f"{label}: docstring contains empty template wording {empty_pattern!r}"
                )
    return errors


def validate_code_comments(root: Path = ROOT) -> list[str]:
    """汇总规范包与维护脚本的缺失文件和注释错误。"""
    errors: list[str] = []
    for path in python_targets(root):
        if not path.is_file():
            errors.append(f"Missing Python target: {path.relative_to(root)}")
            continue
        errors.extend(definition_errors(path, root))
    return errors


def main() -> int:
    """输出注释检查结果，有错误时返回非零退出码。"""
    errors = validate_code_comments()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(
        "Chinese code-comment checks passed: "
        f"{len(python_targets())} maintained Python files."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
