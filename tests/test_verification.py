from pathlib import Path

from daily_intelligence.collector import (
    detect_challenge,
)
from daily_intelligence.config import load_config
from daily_intelligence.models import ArticleItem, SourceResult
from daily_intelligence.utils import write_json
from daily_intelligence.verification import (
    capture_verified_page,
    run_pending_verification,
    update_verification_portal,
    wait_for_visible_verification,
)


def test_pending_verification_noops_without_pending_pages(tmp_path: Path):
    data_dir = tmp_path / "data"
    index_path = write_json(
        data_dir / "indexes" / "2026-07-17" / "morning-r1.json",
        {
            "date": "2026-07-17",
            "edition": "morning",
            "sources": [{"source_id": "bbc_world", "status": "success"}],
            "items": [],
        },
    )

    result = run_pending_verification(index_path, load_config(), data_dir)

    assert result["status"] == "no_pending_pages"
    assert result["captured_pages"] == 0
    assert result["queue_html"] is None


def test_visible_verification_wait_handles_success_and_timeout(monkeypatch):
    class FakePage:
        def is_closed(self):
            return False

        def wait_for_timeout(self, _milliseconds):
            return None

    page = FakePage()
    monkeypatch.setattr(
        "daily_intelligence.verification.detect_challenge",
        lambda _page, _status: {"required": False},
    )
    captured = []
    success = wait_for_visible_verification(
        [("source", page, 200)],
        0,
        on_verified=lambda source_id, _page: captured.append(source_id),
    )
    assert success["source"]["required"] is False
    assert success["source"]["captured"] is True
    assert captured == ["source"]

    monkeypatch.setattr(
        "daily_intelligence.verification.detect_challenge",
        lambda _page, _status: {"required": True},
    )
    timeout = wait_for_visible_verification([("source", page, 200)], 0)
    assert timeout["source"]["timed_out"] is True


def test_closed_verification_tab_is_skipped_not_treated_as_success():
    class ClosedPage:
        def is_closed(self):
            return True

    result = wait_for_visible_verification([("source", ClosedPage(), 403)], 0)

    assert result["source"]["required"] is True
    assert result["source"]["closed_by_user"] is True
    assert result["source"]["skipped"] is True


def test_visible_verification_stops_immediately_when_rate_limited(monkeypatch):
    class Page:
        def is_closed(self):
            return False

    monkeypatch.setattr(
        "daily_intelligence.verification.detect_challenge",
        lambda _page, _status: {"required": True, "rate_limited": True},
    )

    result = wait_for_visible_verification([("reuters", Page(), 429)], 30)

    assert result["reuters"]["status"] == "rate_limited"
    assert result["reuters"]["stopped"] is True


def test_reuters_temporary_access_limit_is_detected_as_rate_limited():
    class Locator:
        def __init__(self, text="", count=0):
            self.text = text
            self.value = count

        def inner_text(self, timeout):
            return self.text

        def count(self):
            return self.value

    class Page:
        def title(self):
            return "Reuters"

        def locator(self, selector):
            if selector == "body":
                return Locator("Your access to Reuters has been temporarily limited.")
            return Locator(count=0)

    result = detect_challenge(Page(), 200)

    assert result["required"] is True
    assert result["rate_limited"] is True
    assert result["matched_text"] == "temporarily limited"


def test_verified_page_is_extracted_without_second_navigation(monkeypatch):
    class CurrentPage:
        def __init__(self):
            self.waits = []

        def wait_for_timeout(self, milliseconds):
            self.waits.append(milliseconds)

    page = CurrentPage()
    config = load_config()
    source = config.source_by_id("bbc_world")
    expected = SourceResult(
        source_id=source.id,
        source_name=source.name,
        source_url=source.url,
        status="success",
        collected_at="2026-07-14T06:00:00+08:00",
        items=[
            ArticleItem(
                item_id="bbc-verified",
                source_id=source.id,
                source_name=source.name,
                title="A sufficiently long verified BBC headline",
                url="https://www.bbc.com/news/articles/verified",
                canonical_url="https://bbc.com/news/articles/verified",
                discovered_at="2026-07-14T06:00:00+08:00",
            )
        ],
    )
    calls = []
    monkeypatch.setattr(
        "daily_intelligence.verification.collect_loaded_page",
        lambda current, current_source, current_config, status: (
            calls.append((current, current_source, current_config, status)) or expected
        ),
    )

    result = capture_verified_page(page, source, config)

    assert result is expected
    assert page.waits
    assert calls == [(page, source, config, None)]


def test_verification_portal_receives_connection_and_capture_status():
    class Portal:
        def __init__(self):
            self.calls = []

        def evaluate(self, expression, argument):
            self.calls.append((expression, argument))

    portal = Portal()

    update_verification_portal(portal, connected=True)
    update_verification_portal(
        portal,
        "huggingface_papers--0",
        "captured",
        "已提取结构化新闻条目。",
    )

    assert portal.calls[0][1] is True
    assert portal.calls[1][1] == {
        "key": "huggingface_papers--0",
        "status": "captured",
        "detail": "已提取结构化新闻条目。",
    }
