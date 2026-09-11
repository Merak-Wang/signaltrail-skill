import importlib.util
from datetime import date
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_docs",
    ROOT / "scripts" / "check_docs.py",
)
assert SPEC and SPEC.loader
DOCS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DOCS)


def test_repository_documentation_map_is_complete_and_linked():
    assert DOCS.validate_docs() == []


@pytest.fixture
def documentation_root(tmp_path):
    for relative in ("AGENTS.md", "ARCHITECTURE.md", "docs/README.md"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# Guide\n\n**Status:** Verified · **Owner:** Maintainers · "
            "**Last verified:** 2026-09-08\n\nExplains this subsystem.\n",
            encoding="utf-8",
        )
        translated = DOCS.translation_path(path, tmp_path)
        translated.parent.mkdir(parents=True, exist_ok=True)
        translated.write_text("# 指南\n", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    ("status", "verified", "error"),
    [
        ("Verified", "2026-09-08", None),
        ("Verified", "2020-01-01", "Stale verification date"),
        ("Historical", "2020-01-01", None),
        ("Draft", "2026-99-01", "Invalid verification date"),
        ("Historical", "2027-01-01", "Stale verification date"),
        ("Unknown", "2026-09-08", "invalid status"),
    ],
)
def test_record_dates_distinguish_current_and_historical(
    documentation_root, status, verified, error
):
    path = documentation_root / "ARCHITECTURE.md"
    path.write_text(
        f"**Status:** {status}\n**Owner:** Maintainers\n**Last verified:** {verified}\n",
        encoding="utf-8",
    )
    errors = DOCS.validate_docs(documentation_root, today=date(2026, 9, 8))
    assert (errors == []) if error is None else any(error in message for message in errors)


def test_missing_translation_and_markdown_or_html_images_are_reported(documentation_root):
    (documentation_root / "docs/zh-CN/ARCHITECTURE.md").unlink()
    (documentation_root / "docs/README.md").write_text(
        (documentation_root / "docs/README.md").read_text(encoding="utf-8")
        + '\n![preview](missing.png)\n<img src="also-missing.png">\n',
        encoding="utf-8",
    )
    errors = DOCS.validate_docs(documentation_root, today=date(2026, 9, 8))
    assert len(errors) == 3
    assert any("Missing Chinese translation" in error for error in errors)
    assert any(": missing.png" in error for error in errors)
    assert any(": also-missing.png" in error for error in errors)


def test_local_links_support_spaces_encoding_and_external_resources(documentation_root):
    target = documentation_root / "docs/a guide.md"
    target.write_text("", encoding="utf-8")
    document = documentation_root / "docs/README.md"
    assert DOCS._local_target(document, "<a guide.md>") == target
    assert DOCS._local_target(document, "a%20guide.md#section") == target
    for link in ("https://example.com", "mailto:author@example.com", "#local", "data:image/png,a"):
        assert DOCS._local_target(document, link) is None


def test_runtime_and_release_snapshots_do_not_enter_current_document_checks(tmp_path):
    for folder in ("data", "skills", "dist", "build", "node_modules"):
        path = tmp_path / folder / "README.md"
        path.parent.mkdir()
        path.write_text("[stale link](missing.md)", encoding="utf-8")
    assert DOCS.markdown_files(tmp_path) == []


def test_markdown_discovery_excludes_repository_virtual_environments(
    tmp_path: Path,
):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    tracked = docs_dir / "tracked.md"
    tracked.write_text("[missing](missing.md)", encoding="utf-8")
    nested_plan = docs_dir / "plan.md"
    nested_plan.write_text("tracked documentation plan", encoding="utf-8")
    virtualenv_markdown = tmp_path / ".venv" / "site-packages" / "dependency.md"
    virtualenv_markdown.parent.mkdir(parents=True)
    virtualenv_markdown.write_text("[third-party missing](missing.yml)", encoding="utf-8")
    conventional_venv = tmp_path / "venv" / "dependency.md"
    conventional_venv.parent.mkdir()
    conventional_venv.write_text("third party", encoding="utf-8")
    local_plan = tmp_path / "plan.md"
    local_plan.write_text("local development notes", encoding="utf-8")

    discovered = DOCS.markdown_files(tmp_path)

    assert tracked in discovered
    assert nested_plan in discovered
    assert nested_plan in DOCS.canonical_records(tmp_path)
    assert virtualenv_markdown not in discovered
    assert conventional_venv not in discovered
    assert local_plan not in discovered


def test_public_markdown_hygiene_patterns_cover_session_and_personal_paths():
    prohibited = [
        "C:/Users/example/AppData/Local/report.json",
        r"E:\ai_project\signaltrail\tmp",
        "Codex in-app browser rejected the page",
        "Codex 应用内浏览器拒绝了页面",
    ]
    allowed = [
        "%LOCALAPPDATA%\\hermes\\daily-intelligence",
        "Codex and OpenClaw have built-in usage adapters.",
    ]

    assert all(
        any(pattern.search(sample) for pattern in DOCS.PROHIBITED_MARKDOWN_PATTERNS.values())
        for sample in prohibited
    )
    assert all(
        not any(pattern.search(sample) for pattern in DOCS.PROHIBITED_MARKDOWN_PATTERNS.values())
        for sample in allowed
    )


def test_readme_showcase_assets_match_the_current_schema_v20_gallery():
    readmes = [
        (ROOT / "README.md").read_text(encoding="utf-8"),
        (ROOT / "README.en.md").read_text(encoding="utf-8"),
    ]
    expected_images = {
        "morning-report-preview.png": (1440, 1200),
        "analysis-synthesis-preview.png": (1440, 1200),
        "quality-evaluation-preview.png": (1440, 1200),
        "mobile-report-preview.png": (390, 1000),
    }
    for filename, expected_size in expected_images.items():
        image_path = ROOT / "assets" / "readme" / filename
        assert image_path.is_file()
        with Image.open(image_path) as preview:
            assert preview.size == expected_size
            preview.verify()
        assert all(filename in readme for readme in readmes)

    gallery_path = ROOT / "examples" / "reports" / "2026-08-25-morning-r1.html"
    gallery = gallery_path.read_text(encoding="utf-8")
    document = BeautifulSoup(gallery, "html.parser")
    assert len(document.select("section.source-group")) == 30
    assert len(document.select("article.brief")) == 424
    assert len(document.select('img[loading="lazy"]')) == 136
    assert len(document.select("article.analysis-card:not(.synthesis-card)")) == 3
    assert len(document.select("article.analysis-card.synthesis-card")) == 1
    assert 'id="analysis-synthesis"' in gallery
    assert "<strong>37</strong><span>/ 45</span>" in gallery
    assert "file://" not in gallery
    assert "C:\\Users" not in gallery
    assert "AppData" not in gallery
