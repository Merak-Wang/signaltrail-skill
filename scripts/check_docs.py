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
    """列出仓库中参与检查的 Markdown，跳过本地数据、生成目录及历史例外。"""
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


def canonical_records(root: Path = ROOT, documents: list[Path] | None = None) -> list[Path]:
    """列出需要中文镜像的根入口和英文工程文档，供版本与翻译检查使用。"""
    records = [root / name for name in ENTRY_DOCUMENTS]
    records.extend(
        path
        for path in (markdown_files(root) if documents is None else documents)
        if path.is_relative_to(root / "docs")
        and "zh-CN" not in path.relative_to(root / "docs").parts
    )
    return sorted(records)


def translation_path(record: Path, root: Path = ROOT) -> Path:
    """按英文文件的相对目录定位中文镜像，根 AGENTS.md 对应 agent-instructions.md。"""
    relative = Path(record.name) if record.parent == root else record.relative_to(root / "docs")
    if relative == Path("AGENTS.md"):
        relative = Path("agent-instructions.md")
    return root / "docs" / "zh-CN" / relative


def _local_target(document: Path, raw_target: str) -> Path | None:
    """将 Markdown 中的本地链接解析为绝对路径，忽略网页地址与页内锚点。"""
    target = raw_target.strip()
    target = target[1:-1] if target.startswith("<") and target.endswith(">") else target
    if not target or target.startswith("#") or urlsplit(target).scheme or target.startswith("//"):
        return None
    relative = unquote(target.split("#", 1)[0].split("?", 1)[0])
    return (document.parent / relative).resolve() if relative else None


def validate_docs(root: Path = ROOT, *, today: date | None = None) -> list[str]:
    """检查文档元数据、时效、翻译和链接，返回能定位文件的错误。"""
    errors: list[str] = []
    today = today or date.today()
    documents = markdown_files(root)
    for record in canonical_records(root, documents):
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

    for document in documents:
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
    """输出文档检查结果，有错误时返回非零退出码。"""
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
