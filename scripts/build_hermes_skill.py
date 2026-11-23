"""Build a tracked-file-only SignalTrail package."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import warnings
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

SKILL_NAME = "signaltrail"
PACKAGE_FILES = {
    Path(".env.example"),
    Path("AGENTS.md"),
    Path("ARCHITECTURE.md"),
    Path("CHANGELOG.md"),
    Path("LICENSE"),
    Path("README.md"),
    Path("README.en.md"),
    Path("RELEASE_NOTES.md"),
    Path("SECURITY.md"),
    Path("SKILL.md"),
    Path("pyproject.toml"),
    Path("scripts/build_hermes_skill.py"),
    Path("scripts/measure_codex_turn.py"),
    Path("scripts/measure_codex_exec.py"),
    Path("scripts/run_codex_edition.py"),
    Path("scripts/run_signaltrail.py"),
    Path("scripts/build_qwen_worker.py"),
    Path("scripts/install.ps1"),
    Path("scripts/install.sh"),
    Path("scripts/install.py"),
}
PACKAGE_DIRECTORIES = (
    Path("assets/monitor"),
    Path("assets/news-slides"),
    Path("assets/readme"),
    Path("assets/tts"),
    Path("configs"),
    Path("docs"),
    Path("references"),
    Path("schemas"),
    Path("src/signaltrail"),
    Path("templates"),
)
REQUIRED_ROOT_FIELDS = {
    "name",
    "description",
}
FORBIDDEN_COMPONENTS = {
    ".git",
    ".playwright-cli",
    "browser-profile",
    "browser-profiles",
    "data",
    "daily-intel-data",
    "daily-intelligence",
    "raw_html",
    "runs",
    "screenshots",
}
FORBIDDEN_SUFFIXES = (
    ".cookies.json",
    ".har",
    ".storage-state.json",
)
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bsecret_[A-Za-z0-9]{20,}\b"),
)
TEXT_SUFFIXES = {
    ".css",
    ".example",
    ".html",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".sh",
    ".toml",
    ".yaml",
    ".yml",
}
TEXT_FILENAMES = {"LICENSE"}


class PackageError(RuntimeError):
    """发布包内容或输出目录不符合打包要求。"""


def parse_frontmatter(skill_file: Path) -> dict[str, Any]:
    """从 SKILL.md 开头解析 YAML 元数据，要求根值为映射。"""
    text = skill_file.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise PackageError(f"{skill_file} must start with YAML frontmatter")
    try:
        raw_frontmatter, _body = text[4:].split("\n---\n", 1)
    except ValueError as exc:
        raise PackageError(f"{skill_file} has no closing frontmatter delimiter") from exc
    metadata = yaml.safe_load(raw_frontmatter)
    if not isinstance(metadata, dict):
        raise PackageError(f"{skill_file} frontmatter must be a mapping")
    return metadata


def validate_skill_directory(
    skill_dir: Path,
    *,
    require_directory_name: bool = True,
) -> dict[str, Any]:
    """检查技能入口与 frontmatter 的必填字段，返回供打包使用的元数据。"""
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        raise PackageError(f"Missing required file: {skill_file}")
    metadata = parse_frontmatter(skill_file)
    missing = sorted(REQUIRED_ROOT_FIELDS - metadata.keys())
    if missing:
        raise PackageError(f"SKILL.md is missing root fields: {', '.join(missing)}")
    if metadata.get("name") != SKILL_NAME or (
        require_directory_name and skill_dir.name != SKILL_NAME
    ):
        raise PackageError(
            f"Frontmatter name and packaged directory must be {SKILL_NAME!r}: {skill_dir}"
        )
    description = metadata.get("description")
    if not isinstance(description, str) or not description.startswith("Use when "):
        raise PackageError("SKILL.md description must start with the activation phrase 'Use when '")
    metadata.setdefault("metadata", {})
    if not isinstance(metadata["metadata"], dict):
        raise PackageError("SKILL.md metadata must be a mapping")
    return metadata


def package_version(source_root: Path) -> str:
    """从源码根目录的 pyproject.toml 读取发布版本。"""
    try:
        import tomllib

        project = tomllib.loads(
            (source_root / "pyproject.toml").read_text(encoding="utf-8")
        )
        return str(project["project"]["version"])
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise PackageError("Cannot read project version from pyproject.toml") from exc


def tracked_files(
    source_root: Path,
    *,
    include_uncommitted: bool = False,
) -> list[Path]:
    """按路径顺序列出 Git 跟踪的文件，可按开关纳入未跟踪且未被忽略的文件。"""
    command = ["git", "-C", str(source_root), "ls-files", "-z"]
    if include_uncommitted:
        command[4:4] = ["--cached", "--others", "--exclude-standard"]
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise PackageError(f"Cannot enumerate tracked files with git: {detail}")
    paths = [
        Path(raw.decode("utf-8"))
        for raw in result.stdout.split(b"\0")
        if raw
    ]
    if not paths:
        raise PackageError(f"No tracked files found under {source_root}")
    return sorted(paths, key=lambda path: path.as_posix())


def is_packaged(relative_path: Path) -> bool:
    """按包内路径白名单和排除规则决定是否随技能发布。"""
    if relative_path in PACKAGE_FILES:
        return True
    return any(
        relative_path == directory or directory in relative_path.parents
        for directory in PACKAGE_DIRECTORIES
    )


def copy_package_file(relative_path: Path, source: Path, destination: Path) -> int:
    """复制文件并返回实际写入的字节数，文本统一使用 LF 以便跨平台复现。"""
    lowered_parts = {part.casefold() for part in relative_path.parts}
    blocked = sorted(lowered_parts & FORBIDDEN_COMPONENTS)
    if blocked:
        raise PackageError(
            f"Refusing forbidden path component {blocked[0]!r}: {relative_path.as_posix()}"
        )
    lowered_name = relative_path.name.casefold()
    private_env = lowered_name.startswith(".env.") and lowered_name != ".env.example"
    if lowered_name == ".env" or private_env or lowered_name.endswith(FORBIDDEN_SUFFIXES):
        raise PackageError(f"Refusing credential/runtime file: {relative_path.as_posix()}")
    if source.stat().st_size > 10 * 1024 * 1024:
        raise PackageError(f"Refusing file larger than 10 MiB: {relative_path.as_posix()}")
    content = source.read_bytes()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        pass
    else:
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                raise PackageError(f"Potential secret in {relative_path.as_posix()}")
    if relative_path.suffix.casefold() in TEXT_SUFFIXES or relative_path.name in TEXT_FILENAMES:
        content = content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    destination.write_bytes(content)
    shutil.copystat(source, destination)
    return len(content)


def validate_output_target(source_root: Path, output_dir: Path) -> None:
    """检查输出目录名称与位置，避免替换源码目录或其祖先。"""
    source_root = source_root.resolve()
    output_dir = output_dir.resolve()
    if output_dir.name != SKILL_NAME:
        raise PackageError(f"Output directory must be named {SKILL_NAME!r}: {output_dir}")
    if output_dir == source_root or output_dir in source_root.parents:
        raise PackageError(f"Refusing source or source ancestor as output: {output_dir}")
    if output_dir.parent == Path(output_dir.anchor):
        raise PackageError(f"Refusing a drive/filesystem-root child as output: {output_dir}")
    if output_dir.exists() and not output_dir.is_dir():
        raise PackageError(f"Output exists and is not a directory: {output_dir}")


def replace_directory_atomically(staging: Path, output_dir: Path) -> None:
    """把已构建的目录切换到发布位置，切换失败时恢复旧包，成功后回收备份。"""
    backup = output_dir.with_name(f".{SKILL_NAME}.previous")
    if backup.exists():
        raise PackageError(
            f"Previous package backup exists; inspect and remove it before retrying: {backup}"
        )
    moved_previous = False
    try:
        if output_dir.exists():
            os.replace(output_dir, backup)
            moved_previous = True
        os.replace(staging, output_dir)
    except Exception:
        if moved_previous and backup.exists() and not output_dir.exists():
            os.replace(backup, output_dir)
        raise
    if moved_previous:
        try:
            from send2trash import send2trash

            send2trash(str(backup))
        except (ImportError, OSError):
            warnings.warn(
                f"New package is ready at {output_dir}; previous package remains at {backup} "
                "because recycling failed",
                RuntimeWarning,
                stacklevel=2,
            )


def build_package(
    source_root: Path,
    output_dir: Path,
    *,
    include_uncommitted: bool = False,
) -> dict[str, Any]:
    """从源码工作树复制已列入发布清单的文件，在暂存目录完成校验后替换输出包。
    返回包名、版本、位置、文件数、字节数和来源模式。
    """
    source_root = source_root.resolve()
    output_dir = output_dir.resolve()
    validate_output_target(source_root, output_dir)
    validate_skill_directory(source_root, require_directory_name=False)

    selected = [
        path
        for path in tracked_files(
            source_root,
            include_uncommitted=include_uncommitted,
        )
        if is_packaged(path) and (source_root / path).is_file()
    ]
    missing = sorted(path.as_posix() for path in PACKAGE_FILES if path not in selected)
    if missing:
        raise PackageError(f"Required tracked package files are missing: {', '.join(missing)}")

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{SKILL_NAME}-build-",
        dir=output_dir.parent,
    ) as temporary_parent:
        staging = Path(temporary_parent) / SKILL_NAME
        staging.mkdir()
        total_bytes = 0
        for relative_path in selected:
            destination = staging / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            total_bytes += copy_package_file(
                relative_path, source_root / relative_path, destination
            )
        metadata = validate_skill_directory(staging)
        replace_directory_atomically(staging, output_dir)

    return {
        "status": "built",
        "name": metadata["name"],
        "version": package_version(source_root),
        "output": str(output_dir),
        "files": len(selected),
        "bytes": total_bytes,
        "source_mode": "working_tree" if include_uncommitted else "tracked",
    }


def build_parser() -> argparse.ArgumentParser:
    """声明打包器的源码、输出目录和纳入未跟踪文件的选项。"""
    parser = argparse.ArgumentParser(
        description="Build an allowlisted, tracked-file-only SignalTrail skill package."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root; defaults to the parent of scripts/.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output directory, which must be named signaltrail. Defaults to dist/signaltrail.",
    )
    parser.add_argument(
        "--include-uncommitted",
        action="store_true",
        help="Include non-ignored working-tree files for pre-commit validation.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """按命令行选项构建技能包，并向终端输出构建回执。"""
    args = build_parser().parse_args(argv)
    source_root = args.source.expanduser().resolve()
    output_dir = (
        args.output.expanduser().resolve()
        if args.output
        else source_root / "dist" / SKILL_NAME
    )
    try:
        result = build_package(
            source_root,
            output_dir,
            include_uncommitted=args.include_uncommitted,
        )
    except PackageError as exc:
        raise SystemExit(f"Package validation failed: {exc}") from exc
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
