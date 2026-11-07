from pathlib import Path

import pytest
from pypdf import PdfReader

from signaltrail.config import OutputConfig
from signaltrail.reports import save_report
from signaltrail.state import update_continuity_state
from signaltrail.utils import read_json, write_json
from tests.report_helpers import load_sample_report, write_report_index


def test_text_revision_preserves_parent_image_instead_of_reselecting_crop(tmp_path, monkeypatch):
    import hashlib
    from io import BytesIO

    from PIL import Image

    from signaltrail import media
    from signaltrail.config import MediaConfig

    report = load_sample_report(Path(__file__).resolve().parents[1])
    report["schema_version"] = "1.5"
    analysis = report["analyses"][0]
    report["analyses"] = [{**analysis, "domain": domain, "analysis_id": analysis_id}
                          for domain, analysis_id in (("geopolitics", "TH-GEO-001"),
                              ("ai_technology", "TH-AI-001"), ("markets", "TH-MKT-001"))]
    section = next(section for section in report["sections"] if section["items"])
    event = section["items"][0]
    ref = event["source_refs"][0]
    section["briefs"] = [{"item_id": ref["item_id"], "title": ref["title"],
                           "title_zh": event["title"], "tldr": event["tldr"],
                           "importance": 80, "status": "NEW",
                           "primary_source": event["primary_source"], "source_ref": ref}]
    draft = write_json(tmp_path / "draft.json", report)
    index_path = write_report_index(report, tmp_path / "index.json")
    index = read_json(index_path)
    original_url = "https://cdn.example/original.png"
    cropped_url = "https://cdn.example/alternate-crop.png"
    index["items"][0]["image_url"] = original_url
    write_json(index_path, index)
    data_dir = tmp_path / "data"
    calls = []

    def download(url, root, config, **kwargs):
        calls.append(url)
        width, height = (1199, 674) if url == original_url else (992, 434)
        output = BytesIO()
        Image.new("RGB", (width, height), (40, 80, 120)).save(output, format="PNG")
        content = output.getvalue()
        digest = hashlib.sha256(content).hexdigest()
        local = f"media/images/{digest[:2]}/{digest}.png"
        path = root / local
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return media.DownloadedImage(url, url, local, "image/png", digest, len(content),
                                      width, height, False)

    original = media.materialize_report_images
    monkeypatch.setattr("signaltrail.reports.materialize_report_images",
                        lambda *args, **kwargs: original(*args, downloader=download, **kwargs))
    config = OutputConfig(formats=["html"])
    first = save_report(draft, index_path, data_dir, output_config=config)
    saved = read_json(Path(first["json_path"]))
    brief = next(brief for section in saved["sections"] for brief in section.get("briefs", [])
                 if brief.get("image"))
    expected = dict(brief["image"])
    index["items"][0]["image_url"] = cropped_url
    write_json(index_path, index)
    saved["executive_summary"][0] += " 补充文字修订。"
    revision = write_json(tmp_path / "revision.json", saved)
    second = save_report(revision, index_path, data_dir, output_config=config,
                         media_config=MediaConfig())
    revised = read_json(Path(second["json_path"]))
    actual = next(brief["image"] for section in revised["sections"]
                  for brief in section.get("briefs", []) if brief.get("image"))
    assert actual == expected and calls == [original_url]
    assert revised["media_metrics"]["attached"] == 1
    assert revised["media_metrics"]["total_bytes"] == expected["byte_size"]
    refreshed = save_report(revision, index_path, data_dir, output_config=config,
                            refresh_images=True)
    refreshed_report = read_json(Path(refreshed["json_path"]))
    image = next(brief["image"] for section in refreshed_report["sections"]
                 for brief in section.get("briefs", []) if brief.get("image"))
    assert (image["width"], image["height"]) == (992, 434)
    assert calls == [original_url, cropped_url]
    for media_config in (MediaConfig(enabled=False), MediaConfig(max_images_per_report=0),
                         MediaConfig(max_image_bytes=1, max_total_bytes=expected["byte_size"] - 1)):
        limited = read_json(Path(second["json_path"]))
        original(limited, index, data_dir, media_config, downloader=download,
                 preserved_images={brief["item_id"]: expected})
        assert all("image" not in item for section in limited["sections"]
                   for item in section.get("briefs", []))


def test_save_report_writes_markdown_and_continuity_state(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    report = load_sample_report(root)
    draft = write_json(tmp_path / "draft.json", report)
    index = write_report_index(report, tmp_path / "index.json")

    artifacts = save_report(
        draft,
        index,
        tmp_path / "data",
        output_config=OutputConfig(formats=["html", "pdf"], pdf_engine="reportlab"),
    )

    saved = read_json(Path(artifacts["json_path"]))
    markdown = Path(artifacts["markdown_path"]).read_text(encoding="utf-8")
    assert saved["report_id"].endswith("-r1")
    assert "## 资讯" in markdown
    assert "## 技术" in markdown
    assert "## 研判" in markdown
    assert "### 国内新闻" in markdown
    assert "### 今日值得关注的开源项目" in markdown
    assert "#### [Example News](https://news.example/)" in markdown
    assert "**1. [人工智能竞争转向更低成本、更高效率的系统]" in markdown
    assert [line for line in markdown.splitlines() if line.startswith("## ")] == [
        "## 资讯",
        "## 技术",
        "## 研判",
        "## 质量评估与用户反馈",
    ]
    assert "反证与不确定性" in markdown
    assert "发布时间：2026-07-12" in markdown
    html = Path(artifacts["html_path"]).read_text(encoding="utf-8")
    assert "日报中心" in html
    assert "download-feedback" in html
    assert "从 AI 研究/开发工程师的角度" in html
    assert Path(artifacts["pdf_path"]).exists()
    assert len(PdfReader(artifacts["pdf_path"]).pages) >= 1
    assert Path(artifacts["local_index_path"]).exists()
    assert artifacts["pdf_engine"] == "reportlab"
    assert artifacts["save_metrics"]["total_seconds"] >= 0
    assert artifacts["save_metrics"]["media_seconds"] >= 0
    archive = Path(artifacts["local_index_path"]).read_text(encoding="utf-8")
    assert report["title"] in archive
    assert "阅读 HTML" in archive

    events = read_json(tmp_path / "data" / "state" / "events.json")
    theses = read_json(tmp_path / "data" / "state" / "theses.json")
    assert events["items"] == []
    assert theses["items"][0]["status"] == "active"


def test_continuity_migrates_legacy_analysis_identity_without_losing_history(
    tmp_path: Path,
):
    root = Path(__file__).resolve().parents[1]
    report = load_sample_report(root)
    data_dir = tmp_path / "data"
    state_dir = data_dir / "state"
    generated_at = "2026-07-11T06:00:00+08:00"
    write_json(
        state_dir / "theses.json",
        {
            "schema_version": "1.0",
            "updated_at": generated_at,
            "items": [
                {
                    "analysis_id": "TH-AI-001",
                    "domain": "ai_technology",
                    "claim": "旧论点",
                    "confidence": 0.5,
                    "status": "active",
                    "history": [{"report_id": "legacy-report"}],
                }
            ],
        },
    )
    write_json(
        state_dir / "watchlist.json",
        {
            "schema_version": "1.0",
            "updated_at": generated_at,
            "items": [
                {
                    "watch_id": "WATCH-LEGACY",
                    "analysis_id": "TH-AI-001",
                    "signal": "旧观察信号",
                    "status": "active",
                }
            ],
        },
    )

    update_continuity_state(report, data_dir)

    theses = read_json(state_dir / "theses.json")["items"]
    legacy = next(row for row in theses if row["analysis_id"] == "TH-AI-001")
    assert legacy["status"] == "active"
    assert legacy["identity_scope"] == "legacy_unresolved"
    assert "superseded_by" not in legacy
    assert legacy["history"] == [{"report_id": "legacy-report"}]
    current = next(row for row in theses if row.get("thesis_id"))
    assert current["analysis_id"] == "ANALYSIS-AI_TECHNOLOGY"
    assert current["status"] == "active"
    watchlist = {row["watch_id"]: row for row in read_json(state_dir / "watchlist.json")["items"]}
    assert watchlist["WATCH-LEGACY"]["status"] == "active"
    assert "closure_reason" not in watchlist["WATCH-LEGACY"]


def test_save_report_validates_before_network_media(monkeypatch, tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    report = load_sample_report(root)
    report["title"] = "English-only report title"
    draft = write_json(tmp_path / "invalid-draft.json", report)
    index = write_report_index(report, tmp_path / "invalid-index.json")

    def unexpected_media(*_args, **_kwargs):
        raise AssertionError("media must not run before semantic validation")

    monkeypatch.setattr(
        "signaltrail.reports.materialize_report_images",
        unexpected_media,
    )

    with pytest.raises(ValueError, match="Report validation failed"):
        save_report(draft, index, tmp_path / "data")


def test_save_report_keeps_local_truth_when_html_projection_fails(
    monkeypatch,
    tmp_path: Path,
):
    root = Path(__file__).resolve().parents[1]
    report = load_sample_report(root)
    draft = write_json(tmp_path / "draft.json", report)
    index = write_report_index(report, tmp_path / "index.json")
    monkeypatch.setattr(
        "signaltrail.reports.write_local_outputs",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk projection error")),
    )

    artifacts = save_report(
        draft,
        index,
        tmp_path / "data",
        output_config=OutputConfig(formats=["html"]),
    )

    assert Path(artifacts["json_path"]).is_file()
    assert Path(artifacts["markdown_path"]).is_file()
    assert "disk projection error" in artifacts["local_output_error"]
    assert any("projection failed" in warning for warning in artifacts["warnings"])


def test_report_must_match_index_edition(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    report = load_sample_report(root)
    draft = write_json(tmp_path / "draft.json", report)
    index = write_report_index(report, tmp_path / "index.json")
    payload = read_json(index)
    payload["edition"] = "evening"
    write_json(index, payload)

    with pytest.raises(ValueError, match="must match"):
        save_report(draft, index, tmp_path / "data")
