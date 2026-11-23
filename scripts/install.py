"""把项目同步到 Hermes 技能目录，并用当前 Python 安装。"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

EXCLUDE = shutil.ignore_patterns(
    ".agents", ".code-review-graph", ".codex", ".git", ".github", ".idea", ".playwright-cli",
    ".pytest_cache", ".ruff_cache", ".vscode", "__pycache__", ".venv", "venv", "env",
    "blob-report", "build", "dist", "data", "daily-intelligence", "daily-intel-data",
    "browser-profile", "browser-profiles", "edge-profile", "htmlcov", "output",
    "playwright-report", "raw_html", "screenshots", "test-results", "tmp", "*.egg-info", "skills",
    ".env", ".env.*", "*.cookies.json", "*.har", "*.storage-state.json", "brief*.json",
)


def synchronize(source: Path, target: Path) -> None:
    """更新技能文件，保留目标目录内用户另存的文件。"""
    if source == target:
        return

    def ignore(directory: str, names: list[str]) -> set[str]:
        """跳过本地数据、凭据及嵌套安装目录，保留示例环境配置。"""
        blocked = EXCLUDE(directory, names)
        blocked.discard(".env.example")
        if source == Path(directory):
            blocked.update({"benchmarks", "plan.md", "runs", "indexes", "context", "content",
                            "content-checkpoints", "reports", "evaluations", "publishing", "state",
                            "challenges", "locks", "retrospectives", "usage", "narratives"})
        if target.parent == Path(directory):
            blocked.add(target.name)
        return blocked

    shutil.copytree(source, target, ignore=ignore, dirs_exist_ok=True)


def main() -> None:
    """安装同步后的技能或可编辑源码，非 Windows 主机同时准备 Chromium。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--editable", action="store_true")
    parser.add_argument("--dev", action="store_true")
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    if os.name == "nt":
        local_app_data = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local")
        default_home = local_app_data / "hermes"
    else:
        default_home = Path.home() / ".hermes"
    hermes_home = Path(os.environ.get("HERMES_HOME") or default_home).expanduser().resolve()
    skills_root = (hermes_home / "skills").resolve()
    target = (skills_root / "research/signaltrail").resolve()
    if not target.is_relative_to(skills_root):
        raise ValueError(f"Skill destination is outside {skills_root}: {target}")
    synchronize(source, target)
    package = str(source if args.editable else target) + ("[dev]" if args.dev else "")
    subprocess.run([sys.executable, "-m", "pip", "install", "-e", package], check=True)
    if os.name != "nt":
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    subprocess.run([sys.executable, "-m", "signaltrail.cli", "--help"], check=True,
                   stdout=subprocess.DEVNULL)
    print(f"Synchronized SignalTrail skill: {target}")
    print("Installed SignalTrail. Run: signaltrail --help")


if __name__ == "__main__":
    main()
