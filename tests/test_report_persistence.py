from pathlib import Path

import pytest
from pypdf import PdfReader

from daily_intelligence.config import OutputConfig
from daily_intelligence.reports import save_report
from daily_intelligence.state import update_continuity_state
from daily_intelligence.utils import read_json, write_json
from tests.report_helpers import load_sample_report, write_report_index


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
        "daily_intelligence.reports.materialize_report_images",
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
        "daily_intelligence.reports.write_local_outputs",
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
