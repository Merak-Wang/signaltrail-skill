import importlib.util
from pathlib import Path

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


def test_agent_map_stays_small_and_every_record_has_a_translation():
    assert len((ROOT / "AGENTS.md").read_text(encoding="utf-8").splitlines()) <= 110
    assert all(
        DOCS.translation_path(record).is_file()
        for record in DOCS.canonical_records()
    )


def test_markdown_discovery_excludes_repository_virtual_environments(
    monkeypatch,
    tmp_path: Path,
):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    tracked = docs_dir / "tracked.md"
    tracked.write_text("[missing](missing.md)", encoding="utf-8")
    virtualenv_markdown = tmp_path / ".venv" / "site-packages" / "dependency.md"
    virtualenv_markdown.parent.mkdir(parents=True)
    virtualenv_markdown.write_text("[third-party missing](missing.yml)", encoding="utf-8")
    conventional_venv = tmp_path / "venv" / "dependency.md"
    conventional_venv.parent.mkdir()
    conventional_venv.write_text("third party", encoding="utf-8")
    monkeypatch.setattr(DOCS, "ROOT", tmp_path)

    discovered = DOCS.markdown_files()

    assert tracked in discovered
    assert virtualenv_markdown not in discovered
    assert conventional_venv not in discovered


def test_readme_showcase_assets_match_the_current_schema_v20_gallery():
    readmes = [
        (ROOT / "README.md").read_text(encoding="utf-8"),
        (ROOT / "README.en.md").read_text(encoding="utf-8"),
    ]
    expected_images = {
        "morning-report-preview.png": (1440, 900),
        "analysis-synthesis-preview.png": (1440, 900),
        "quality-evaluation-preview.png": (1440, 900),
        "mobile-report-preview.png": (390, 844),
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
    assert gallery.count('<section class="source-group"') == 30
    assert gallery.count('<article class="brief') == 424
    assert gallery.count('<img loading="lazy"') == 136
    assert gallery.count('<article class="analysis-card"') == 3
    assert gallery.count('<article class="analysis-card synthesis-card"') == 1
    assert 'id="analysis-synthesis"' in gallery
    assert '<strong>37</strong><span>/ 45</span>' in gallery
    assert "file://" not in gallery
    assert "C:\\Users" not in gallery
    assert "AppData" not in gallery
