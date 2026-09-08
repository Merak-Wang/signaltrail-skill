"""Check current Markdown sources, translations, metadata, and local links."""

from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
IGNORED_PARTS = {
    ".git",
    ".agents",
    ".codex",
    ".playwright-cli",
    ".pytest_cache",
    ".ruff_cache",
    ".nox",
    ".tox",
    ".venv",
    "venv",
    "env",
    "build",
    "dist",
    "output",
    "tmp",
    "data",
    "skills",
    "node_modules",
    "__pycache__",
}
ENTRY_DOCUMENTS = ("AGENTS.md", "ARCHITECTURE.md")
MAX_VERIFICATION_AGE_DAYS = 180
VERIFIED_PATTERN = re.compile(r"\*\*Last verified:\*\* (\d{4}-\d{2}-\d{2})")
STATUS_PATTERN = re.compile(r"\*\*Status:\*\* (\w+)")
LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\((<[^>]+>|[^\s)]+)(?:\s+[^)]*)?\)")
HTML_LINK_PATTERN = re.compile(r"""(?:src|href)=["']([^"']+)["']""")
PROHIBITED_MARKDOWN_PATTERNS = {
    "personal Windows user path": re.compile(r"(?i)\b[A-Z]:[/\\]Users[/\\][^/\\\s<`]+"),
    "personal workspace path": re.compile(r"(?i)\b[A-Z]:[/\\]ai_project[/\\]"),
    "Codex browser-session residue": re.compile(r"(?i)Codex (?:in-app browser|应用内浏览器)"),
}


def markdown_files(root: Path = ROOT) -> list[Path]:
    """处理：枚举当前文档，并在遍历前排除快照、运行数据和依赖目录。
    输入：
    - ``root``：仓库根或测试目录；扫描其中的 Markdown，不跟随目录符号链接。
    输出：需要检查的文档路径；不含本地计划、宿主审计和生成副本。
    """
    files = []
    for directory, folders, names in os.walk(root):
        folders[:] = sorted(name for name in folders if name not in IGNORED_PARTS)
        for name in names:
            path = Path(directory) / name
            if path.suffix != ".md" or path == root / "plan.md":
                continue
            if name.endswith("-hermes-and-cost-audit.md"):
                continue
            files.append(path)
    return sorted(files)


def canonical_records(root: Path = ROOT) -> list[Path]:
    """处理：列出根入口与需要同步中文译文的英文工程记录。
    输入：
    - ``root``：仓库根或测试目录；采用同一文档发现规则排除生成和本地文件。
    输出：英文记录路径，供元数据及翻译配对检查使用，包含历史记录。
    """
    records = [root / name for name in ENTRY_DOCUMENTS]
    records.extend(
        path
        for path in markdown_files(root / "docs")
        if "zh-CN" not in path.relative_to(root / "docs").parts
    )
    return sorted(records)


def translation_path(record: Path, root: Path = ROOT) -> Path:
    """处理：定位英文工程记录对应的中文镜像。
    输入：
    - ``record``：根入口或 docs 下的英文文件；消费相对目录和文件名。
    - ``root``：仓库根；决定 docs/zh-CN 的位置。
    输出：预期译文路径，供缺失译文检查和错误提示使用。
    """
    relative = record.name if record.parent == root else record.relative_to(root / "docs")
    return root / "docs" / "zh-CN" / relative


def _local_target(document: Path, raw_target: str) -> Path | None:
    """处理：将相对链接转为本地路径，跳过网页和页内锚点。
    输入：
    - ``document``：包含链接的 Markdown 路径；其父目录是相对链接的基准。
    - ``raw_target``：提取的 URL 或尖括号路径；解码百分号并去掉查询和锚点。
    输出：需要确认存在的路径；外部 URL、内嵌数据和页内锚点返回 None。
    """
    target = raw_target.strip()
    target = target[1:-1] if target.startswith("<") and target.endswith(">") else target
    if not target or target.startswith("#") or urlsplit(target).scheme or target.startswith("//"):
        return None
    relative = unquote(target.split("#", 1)[0].split("?", 1)[0])
    return (document.parent / relative).resolve() if relative else None


def validate_docs(root: Path = ROOT, *, today: date | None = None) -> list[str]:
    """处理：检查文档大小、元数据、翻译、隐私痕迹和本地链接。
    输入：
    - ``root``：仓库根或测试夹具目录；所有发现和配对使用同一根。
    - ``today``：检查日期；默认系统日期，测试可固定它以验证过期行为。
    输出：可定位文件的错误列表；空列表表示当前文档检查通过。
    """
    errors: list[str] = []
    today = today or date.today()
    for record in canonical_records(root):
        relative = record.relative_to(root)
        if not record.is_file():
            errors.append(f"Missing canonical record: {relative}")
            continue
        text = record.read_text(encoding="utf-8")
        translation = translation_path(record, root)
        if not translation.is_file():
            errors.append(f"Missing Chinese translation: {translation.relative_to(root)}")
        if record.name == "AGENTS.md":
            if len(text.splitlines()) > 110:
                errors.append(f"{relative} exceeds 110 lines")
            continue
        status = STATUS_PATTERN.search(text)
        if not status or status.group(1) not in {
            "Verified",
            "Draft",
            "Active",
            "Historical",
            "Generated",
        }:
            errors.append(f"Missing or invalid status: {relative}")
        if not re.search(r"\*\*Owner:\*\* \S", text):
            errors.append(f"Missing owner: {relative}")
        match = VERIFIED_PATTERN.search(text)
        if not match:
            errors.append(f"Missing verification date: {relative}")
            continue
        try:
            verified = date.fromisoformat(match.group(1))
        except ValueError:
            errors.append(f"Invalid verification date: {relative}: {match.group(1)}")
            continue
        age = (today - verified).days
        historical = status and status.group(1) in {"Historical", "Generated"}
        if age < 0 or (not historical and age > MAX_VERIFICATION_AGE_DAYS):
            errors.append(f"Stale verification date: {relative}: {verified} ({age} days old)")

    for document in markdown_files(root):
        text = document.read_text(encoding="utf-8")
        relative = document.relative_to(root)
        for label, pattern in PROHIBITED_MARKDOWN_PATTERNS.items():
            if pattern.search(text):
                errors.append(f"Prohibited {label} in {relative}")
        # 图片与 HTML 内嵌资源也是读者路径；代码块中的示例不当作实际链接。
        prose = re.sub(r"(?ms)^```[^\n]*\n.*?^```\s*$", "", text)
        for raw_target in [*LINK_PATTERN.findall(prose), *HTML_LINK_PATTERN.findall(prose)]:
            target = _local_target(document, raw_target)
            if target is not None and not target.exists():
                errors.append(f"Broken local link in {relative}: {raw_target}")
    return errors


def main() -> int:
    """处理：执行文档检查并打印可直接修复的错误。
    输入：
    - 无显式业务参数：从脚本位置定位仓库，检查当前文档和中文镜像。
    输出：终端检查结果和退出码；有错误时返回 1，全部通过返回 0。
    """
    errors = validate_docs()
    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        return 1
    print(
        f"Documentation checks passed: {len(canonical_records())} records, "
        f"{len(markdown_files())} Markdown files."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
