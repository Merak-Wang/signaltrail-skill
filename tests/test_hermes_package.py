import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "build_hermes_skill",
    ROOT / "scripts" / "build_hermes_skill.py",
)
assert SPEC and SPEC.loader
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


def test_skill_metadata_matches_hermes_and_agent_skill_contract():
    metadata = BUILD.parse_frontmatter(ROOT / "SKILL.md")
    hermes = metadata["metadata"]["hermes"]
    body = (ROOT / "SKILL.md").read_text(encoding="utf-8").split("\n---\n", 1)[1]

    assert metadata["name"] == "signaltrail"
    assert metadata["description"].startswith("Use when ")
    assert len(metadata["description"]) <= 1024
    assert metadata["version"] == "2.0.0"
    assert metadata["author"] == "Wang Mingfeng"
    assert metadata["license"] == "MIT"
    assert metadata["platforms"] == ["windows", "macos", "linux"]
    assert hermes["category"] == "research"
    assert hermes["requires_toolsets"] == ["terminal", "delegation"]
    assert "version" not in hermes
    assert "author" not in hermes
    assert "platforms" not in hermes
    assert "required_environment_variables" in metadata
    assert len(body.splitlines()) < 220


def test_community_package_contains_runtime_and_excludes_repository_state(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for relative in BUILD.PACKAGE_FILES:
        origin = ROOT / relative
        destination = source / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, destination)
    for directory in BUILD.PACKAGE_DIRECTORIES:
        origin = ROOT / directory
        if origin.exists():
            shutil.copytree(origin, source / directory)
    readme = source / "README.md"
    readme.write_bytes(
        readme.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    )
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(["git", "-C", str(source), "add", "-A"], check=True)

    output = tmp_path / "release" / "signaltrail"
    result = BUILD.build_package(source, output)

    assert result["status"] == "built"
    assert result["name"] == "signaltrail"
    assert (output / "SKILL.md").is_file()
    assert (output / "src" / "daily_intelligence" / "cli.py").is_file()
    assert (output / "src" / "daily_intelligence" / "usage_cli.py").is_file()
    assert (output / "src" / "daily_intelligence" / "commands" / "editions.py").is_file()
    assert (output / "src" / "daily_intelligence" / "llm_usage" / "__init__.py").is_file()
    assert (output / "configs" / "sources.yaml").is_file()
    assert (output / "schemas" / "report.schema.json").is_file()
    assert (output / "schemas" / "llm-usage.schema.json").is_file()
    assert (output / "references" / "llm-usage.md").is_file()
    assert (output / "AGENTS.md").is_file()
    assert (output / "ARCHITECTURE.md").is_file()
    assert (output / "docs" / "README.md").is_file()
    assert (output / "docs" / "zh-CN" / "README.md").is_file()
    assert (output / "assets" / "readme" / "morning-report-preview.png").is_file()
    assert (output / "RELEASE_NOTES.md").is_file()
    assert (output / "scripts" / "install.ps1").is_file()
    assert b"\r\n" not in (output / "README.md").read_bytes()
    assert not (output / ".git").exists()
    assert not (output / "tests").exists()
    assert not (output / "examples").exists()
    assert not (output / "wiki").exists()
    assert not (output / "data").exists()


def test_windows_installer_excludes_nested_skill_snapshots():
    text = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")
    excluded_dirs = text.split("$excludedDirs = @(", 1)[1].split(")", 1)[0]
    legacy_entries = text.split("$legacyRuntimeEntries = @(", 1)[1].split(")", 1)[0]

    assert '"skills"' in excluded_dirs
    assert '"skills"' in legacy_entries
    assert "/XD $excludedDirs" in text


def test_community_package_rejects_secret_like_content(tmp_path):
    suspicious = tmp_path / "credential.txt"
    suspicious.write_text(
        "-----BEGIN PRIVATE KEY-----\nnot-a-real-key\n",
        encoding="utf-8",
    )

    with pytest.raises(BUILD.PackageError, match="Potential secret"):
        BUILD.inspect_package_file(Path("references/credential.txt"), suspicious)


def test_installers_sync_into_platform_hermes_skill_roots_and_exclude_repo_state():
    root = Path(__file__).resolve().parents[1]
    powershell = (root / "scripts" / "install.ps1").read_text(encoding="utf-8")
    shell = (root / "scripts" / "install.sh").read_text(encoding="utf-8")

    assert 'Join-Path $env:LOCALAPPDATA "hermes"' in powershell
    assert '"skills"' in powershell
    assert r'"research\signaltrail"' in powershell
    assert '".git"' in powershell
    assert '"build"' in powershell
    assert '".code-review-graph"' in powershell
    assert '"output"' in powershell
    assert '"tmp"' in powershell
    assert "if (-not $sameDirectory)" in powershell
    assert "post-install artifact" in powershell
    assert '${HOME}/.hermes' in shell
    assert 'skills_root="${hermes_home}/skills"' in shell
    assert 'target_dir="${skills_root}/research/signaltrail"' in shell
    assert "if source != target:" in shell
    assert "shutil.copytree(source, target, ignore=ignore)" in shell
    assert '".code-review-graph"' in shell
    assert '"output"' in shell
    assert '"tmp"' in shell
    assert "post-install artifact" in shell
