import base64
import shutil
import subprocess
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfReader

from daily_intelligence.config import OutputConfig, load_config, validate_output_config
from daily_intelligence.local_output import write_local_outputs


def _report() -> dict:
    return {
        "schema_version": "2.0",
        "report_id": "daily-2026-07-25-morning-r1",
        "date": "2026-07-25",
        "edition": "morning",
        "revision": 1,
        "title": "每日情报晨报 — 2026年7月25日",
        "generated_at": "2026-07-25T06:11:02+08:00",
        "executive_summary": [],
        "sections": [
            {
                "id": "information.international",
                "module": "information",
                "title": "国际",
                "briefs": [
                    {
                        "title": "Public source headline",
                        "title_zh": "公开来源标题",
                        "tldr": "这是一条公开来源摘要。",
                        "importance": 80,
                        "source_rank": 1,
                        "primary_source": {
                            "id": "example",
                            "name": "Example",
                            "url": "https://news.example/",
                        },
                        "source_ref": {"url": "https://news.example/story"},
                        "image": {
                            "local_path": "media/images/aa/example.jpg",
                            "source_url": "https://news.example/example.jpg",
                            "content_type": "image/jpeg",
                            "caption": "Public image",
                            "credit": "Example",
                        },
                    }
                ],
            }
        ],
        "analyses": [],
        "pending_verifications": [],
    }


def _jpeg_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (64, 36), color=(35, 74, 112)).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_repository_config_delivers_html_to_desktop_by_default():
    config = load_config()

    assert config.output.copy_html_to_desktop is True
    assert config.output.desktop_dir is None


def test_desktop_directory_override_must_be_absolute():
    with pytest.raises(ValueError, match="desktop_dir must be an absolute path"):
        validate_output_config(
            OutputConfig(copy_html_to_desktop=True, desktop_dir="relative/Desktop")
        )


def test_html_projection_is_atomically_delivered_to_configured_desktop(
    tmp_path: Path,
):
    data_dir = tmp_path / "data"
    desktop_dir = tmp_path / "Desktop"
    config = OutputConfig(
        formats=["html", "pdf"],
        pdf_engine="reportlab",
        copy_html_to_desktop=True,
        desktop_dir=str(desktop_dir.resolve()),
    )
    image_bytes = _jpeg_bytes()
    image_path = data_dir / "media" / "images" / "aa" / "example.jpg"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(image_bytes)

    outputs = write_local_outputs(_report(), data_dir, config)

    desktop_path = Path(outputs["desktop_html_path"])
    assert desktop_path == (
        desktop_dir / "daily-intelligence-2026-07-25-morning-r1.html"
    )
    assert desktop_path.exists()
    assert not desktop_path.with_suffix(".html.tmp").exists()
    html = desktop_path.read_text(encoding="utf-8")
    assert (data_dir / "reports" / "index.html").resolve().as_uri() in html
    assert (
        data_dir / "reports" / "2026-07-25" / "morning-r1.pdf"
    ).resolve().as_uri() in html
    embedded = f"data:image/jpeg;base64,{base64.b64encode(image_bytes).decode('ascii')}"
    assert embedded in html
    assert f'{data_dir.resolve().as_uri()}/media/images/aa/example.jpg' not in html
    assert "../../media/images/aa/example.jpg" not in html
    assert html.index('class="brief-heading"') < html.index("<figure>")
    assert ".analysis-domain>h3{break-after:avoid}" in html
    assert ".analysis-card{break-inside:auto}" in html
    reader = PdfReader(outputs["pdf_path"])
    assert sum(len(page.images) for page in reader.pages) >= 1
    assert outputs["pdf_projection_seconds"] >= 0
    assert outputs["pdf_bytes"] == Path(outputs["pdf_path"]).stat().st_size
    assert outputs["pdf_size_budget_status"] == "within_budget"


def test_edge_pdf_receives_embedded_images_instead_of_relative_media(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    data_dir = tmp_path / "data"
    image_path = data_dir / "media" / "images" / "aa" / "example.jpg"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(_jpeg_bytes())
    captured: dict[str, str] = {}

    def fake_edge_pdf(
        _html_path: Path,
        output_path: Path,
        *,
        html_document: str | None = None,
    ) -> None:
        captured["html"] = html_document or ""
        output_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    monkeypatch.setattr("daily_intelligence.local_output._edge_pdf", fake_edge_pdf)
    outputs = write_local_outputs(
        _report(),
        data_dir,
        OutputConfig(
            formats=["html", "pdf"],
            pdf_engine="edge",
            copy_html_to_desktop=False,
        ),
    )

    assert outputs["pdf_engine"] == "edge"
    assert "data:image/jpeg;base64," in captured["html"]
    assert "../../media/images/aa/example.jpg" not in captured["html"]


def test_desktop_delivery_failure_is_explicit_without_losing_local_html(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    config = OutputConfig(
        formats=["html"],
        copy_html_to_desktop=True,
        desktop_dir=str((tmp_path / "Desktop").resolve()),
    )
    monkeypatch.setattr(
        "daily_intelligence.local_output.write_desktop_html",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("denied")),
    )

    outputs = write_local_outputs(_report(), tmp_path / "data", config)

    assert Path(outputs["html_path"]).exists()
    assert "PermissionError: denied" in outputs["desktop_html_error"]
    assert outputs["desktop_html_error"] in outputs["warnings"]


def test_evaluation_refresh_reuses_existing_pdf_and_renders_only_when_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    data_dir = tmp_path / "data"
    config = OutputConfig(
        formats=["html", "pdf"],
        pdf_engine="reportlab",
        copy_html_to_desktop=False,
    )
    calls = 0

    def fake_pdf(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        output_path = _args[1]
        output_path.write_bytes(f"pdf-{calls}".encode())
        return "fake", None

    monkeypatch.setattr(
        "daily_intelligence.local_output.render_pdf_from_html",
        fake_pdf,
    )
    initial = write_local_outputs(_report(), data_dir, config)
    pdf_path = Path(initial["pdf_path"])
    initial_bytes = pdf_path.read_bytes()
    initial_mtime = pdf_path.stat().st_mtime_ns

    refreshed = write_local_outputs(
        _report(),
        data_dir,
        config,
        evaluation={
            "total_score": 33,
            "dimensions": [],
            "main_defects": [],
            "improvements": [],
            "continuity_decision": "accept",
        },
        regenerate_pdf=False,
    )

    assert calls == 1
    assert refreshed["pdf_reused"] is True
    assert pdf_path.read_bytes() == initial_bytes
    assert pdf_path.stat().st_mtime_ns == initial_mtime
    assert "<strong>33</strong><span>/ 45</span>" in Path(
        refreshed["html_path"]
    ).read_text(encoding="utf-8")

    pdf_path.unlink()
    regenerated = write_local_outputs(
        _report(),
        data_dir,
        config,
        regenerate_pdf=False,
    )
    assert calls == 2
    assert "pdf_reused" not in regenerated
    assert Path(regenerated["pdf_path"]).read_bytes() == b"pdf-2"


def test_pdf_size_budget_is_explicit_and_non_destructive(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    def fake_pdf(*args, **_kwargs):
        args[1].write_bytes(b"0123456789")
        return "fake", None

    monkeypatch.setattr(
        "daily_intelligence.local_output.render_pdf_from_html",
        fake_pdf,
    )
    outputs = write_local_outputs(
        _report(),
        tmp_path / "data",
        OutputConfig(
            formats=["html", "pdf"],
            pdf_engine="reportlab",
            pdf_max_bytes=5,
        ),
    )

    assert Path(outputs["pdf_path"]).read_bytes() == b"0123456789"
    assert outputs["pdf_size_budget_status"] == "exceeded"
    assert outputs["pdf_size_budget_bytes"] == 5
    assert "PDF size budget exceeded" in outputs["warnings"][0]


@pytest.mark.skipif(shutil.which("pdftoppm") is None, reason="Poppler is unavailable")
def test_reportlab_pdf_page_rasterization_is_visually_nonblank(tmp_path: Path):
    outputs = write_local_outputs(
        _report(),
        tmp_path / "data",
        OutputConfig(
            formats=["html", "pdf"],
            pdf_engine="reportlab",
            copy_html_to_desktop=False,
        ),
    )
    prefix = tmp_path / "rendered-page"
    subprocess.run(
        [
            str(shutil.which("pdftoppm")),
            "-png",
            "-f",
            "1",
            "-singlefile",
            outputs["pdf_path"],
            str(prefix),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    image = Image.open(prefix.with_suffix(".png")).convert("L")

    assert image.width >= 1000
    assert image.height >= 1000
    low, high = image.getextrema()
    assert low < 245
    assert high == 255
