import importlib.util
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from daily_intelligence import __version__

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
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert metadata["version"] == project["project"]["version"] == __version__
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
    assert (output / "assets" / "news-slides" / "template.html").is_file()
    assert (output / "templates" / "news-slide-style" / "SKILL.md").is_file()
    assert (output / "RELEASE_NOTES.md").is_file()
    assert (output / "scripts" / "install.ps1").is_file()
    assert b"\r\n" not in (output / "README.md").read_bytes()
    assert not (output / ".git").exists()
    assert not (output / "tests").exists()
    assert not (output / "examples").exists()
    assert not (output / "wiki").exists()
    assert not (output / "data").exists()
    assert not (output / "skills").exists()
    for directory in ("src", "configs", "schemas", "templates", "references", "assets"):
        originals = {
            path.relative_to(source)
            for path in (source / directory).rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        }
        packaged = {
            path.relative_to(output)
            for path in (output / directory).rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        }
        assert packaged == originals
        for relative in originals:
            expected = (source / relative).read_bytes()
            if relative.suffix in BUILD.TEXT_SUFFIXES:
                expected = expected.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            assert (output / relative).read_bytes() == expected


@pytest.mark.parametrize(
    ("installer", "editable"), [("powershell", False), ("powershell", True), ("shell", False)],
)
def test_installer_copies_complete_project_and_excludes_local_environments(
    tmp_path, monkeypatch, installer, editable,
):
    source = tmp_path / "source"
    target = tmp_path / "hermes" / "skills" / "research" / "signaltrail"
    resources = (
        "SKILL.md", "pyproject.toml", "src/daily_intelligence/__init__.py",
        "configs/sources.yaml", "schemas/report.schema.json", "templates/report-contract.md",
        "references/runbook.md", "assets/monitor/index.html",
    )
    excluded = (".venv", "venv", "env", "skills", "data", ".git")
    for relative in (*resources, *(f"{name}/sentinel" for name in excluded)):
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    if installer == "powershell":
        if sys.platform != "win32":
            pytest.skip("Windows installer requires robocopy")
        shell = shutil.which("pwsh") or shutil.which("powershell")
        assert shell
        script = source / "scripts" / "install.ps1"
        script.parent.mkdir()
        shutil.copy2(ROOT / "scripts/install.ps1", script)
        marker = tmp_path / "pip-arguments.json"
        monkeypatch.setenv("SIGNALTRAIL_TEST_INSTALLER", str(script))
        monkeypatch.setenv("SIGNALTRAIL_TEST_PIP_ARGUMENTS", str(marker))
        command = (
            "function python { ConvertTo-Json -InputObject @($args) -Compress | "
            "Set-Content -LiteralPath $env:SIGNALTRAIL_TEST_PIP_ARGUMENTS; "
            "$global:LASTEXITCODE = 0 }; "
            "& $env:SIGNALTRAIL_TEST_INSTALLER" + (" -Editable" if editable else "")
        )
        subprocess.run(
            [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            check=True, capture_output=True,
        )
        arguments = json.loads(marker.read_text(encoding="utf-8-sig"))
        expected = ["-m", "pip", "install", *(["-e"] if editable else [])]
        assert arguments == [*expected, str(source if editable else target)]
    else:
        script = (ROOT / "scripts/install.sh").read_text(encoding="utf-8")
        sync_code = script.split("<<'PY'\n", 1)[1].split("\nPY", 1)[0]
        subprocess.run(
            [sys.executable, "-c", sync_code, str(source), str(target.parents[1]), str(target)],
            check=True, capture_output=True,
        )
    for relative in resources:
        assert (target / relative).read_bytes() == (source / relative).read_bytes()
    assert all(not (target / name).exists() for name in excluded)


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
