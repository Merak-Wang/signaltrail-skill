from copy import deepcopy
from hashlib import sha256

import pytest
from bs4 import BeautifulSoup
from PIL import Image

from daily_intelligence.narrative import submit_script
from daily_intelligence.narrative_store import load_artifact
from daily_intelligence.story_stream import (
    build_story_stream,
    render_story,
    render_story_html,
    submit_visual_review,
)
from tests.test_narrative import explainer_case as explainer_case
from tests.test_narrative_verification import bilingual_case


def test_bilingual_story_preserves_text_and_safe_diagram_fallback(explainer_case):
    c = explainer_case
    zh, receipt, _ = bilingual_case(c)
    parent_bytes = c["report"].read_bytes()
    story = build_story_stream([zh, c["script"]], c["root"], bilingual_path=receipt)
    result = render_story(story, c["root"])
    from pathlib import Path

    html = Path(result["html_path"]).read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    assert len(soup.select("article.chapter")) == 2
    assert len(soup.select("figure.diagram")) == 2
    assert not soup.select("img")
    assert [s["lang"] for s in soup.select("[data-edition]")] == ["zh-CN", "en"]
    assert c["script_draft"]["title"]["text"] in soup.get_text()
    assert c["report"].read_bytes() == parent_bytes
    assert render_story(story, c["root"]) == result
    with pytest.raises(ValueError, match="Current admission blocked"):
        render_story(story, c["root"], mode="current")


def test_old_bilingual_receipt_cannot_admit_new_script(explainer_case):
    c = explainer_case
    zh, receipt, _ = bilingual_case(c)
    changed = deepcopy(c["script_draft"])
    changed["title"]["text"] = "A materially different heading"
    en = submit_script(c["ledger"], changed, c["root"], author_context="author")
    with pytest.raises(ValueError, match="other script revisions"):
        build_story_stream([zh, en], c["root"], bilingual_path=receipt)


def test_untrusted_text_and_urls_cannot_execute_in_html(explainer_case):
    c = explainer_case
    path = build_story_stream([c["script"]], c["root"])
    story = load_artifact(path, c["root"])["payload"]
    story["scripts"][0]["title"]["text"] = '<script>alert("evil")</script>'
    story["evidence"][0]["url"] = "javascript:alert(1)"
    html = render_story_html(story)
    assert '<script>alert("evil")</script>' not in html
    assert "&lt;script&gt;" in html
    assert "javascript:" not in html


def test_visual_review_requires_exact_projection_and_every_card(explainer_case):
    c = explainer_case
    story = build_story_stream([c["script"]], c["root"])
    result = render_story(story, c["root"])
    from pathlib import Path

    projection = Path(result["projection_path"])
    screenshot = c["root"] / "screen.png"
    Image.new("RGB", (4, 4)).save(screenshot)
    review = {
        "projection_sha256": sha256(Path(result["html_path"]).read_bytes()).hexdigest(),
        "screenshots": ["screen.png"],
        "cards": [
            {
                "card_id": "en-chapter-1",
                "desktop": "pass",
                "mobile": "unavailable",
                "note": "Mobile not observed",
            }
        ],
    }
    path = submit_visual_review(projection, review, c["root"])
    assert load_artifact(path, c["root"])["payload"]["status"] == "pending_or_failed"
    review["projection_sha256"] = "wrong"
    with pytest.raises(ValueError, match="another projection"):
        submit_visual_review(projection, review, c["root"])


def test_projection_failure_leaves_story_and_report_available(explainer_case, monkeypatch):
    c = explainer_case
    story = build_story_stream([c["script"]], c["root"])

    def fail(*args, **kwargs):
        raise OSError("Disk unavailable")

    monkeypatch.setattr("daily_intelligence.story_stream.write_text_atomic", fail)
    with pytest.raises(OSError):
        render_story(story, c["root"])
    assert load_artifact(story, c["root"])["kind"] == "story"
    assert c["report"].is_file()
