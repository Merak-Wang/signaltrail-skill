import asyncio
import copy
import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup

from daily_intelligence.collection_diagnostics import has_local_content
from daily_intelligence.config import load_config
from daily_intelligence.content import (
    _apply_http_document,
    _extract_one,
    _extract_pipeline,
    extract_content,
)
from daily_intelligence.content_extraction import extract_document, extract_with_fallback
from daily_intelligence.utils import read_json, write_json


def _item():
    return {"item_id": "story", "source_id": "bbc_world", "title": "Service update",
            "url": "https://www.bbc.com/news/articles/story", "metadata": {}}


def _apply(item, markup, config, tmp_path, **kwargs):
    return _apply_http_document(
        item, config.source_by_id(item["source_id"]), markup, item["url"], 200,
        config, tmp_path, **kwargs,
    )


def test_lineage_hashes_original_response_and_both_derived_artifacts(tmp_path):
    item = _item()
    config = load_config()
    config.collection.retain_public_html = True
    raw = ("<html lang='zh-CN'><head><meta name='author' content='编辑部'>"
           "<meta property='og:site_name' content='Example'></head><body><article>"
           "<p>现有用户从下月起继续使用目前的服务方案，价格与权益均保持不变。</p>"
           "</article></body></html>").encode("gb18030")
    _apply(item, raw.decode("gb18030"), config, tmp_path, raw_content=raw)
    metadata = item["metadata"]
    structured = read_json(Path(metadata["content_blocks_path"]))
    assert structured["input"]["kind"] == "http_response_body"
    assert structured["input"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert structured["source_metadata"]["author"] == "编辑部"
    assert structured["source_metadata"]["independent_origin"] is None
    assert structured["source_metadata"]["language"] == "zh-CN"
    assert Path(metadata["content_artifacts"]["raw_path"]).read_bytes() == raw
    assert has_local_content(item, tmp_path)
    Path(metadata["content_blocks_path"]).write_text("tampered", encoding="utf-8")
    assert not has_local_content(item, tmp_path)


def test_raw_retention_is_opt_in_and_challenges_are_not_archived(tmp_path):
    item = _item()
    config = load_config()
    _apply(item, "<article><p>The service remains available under the current terms.</p></article>",
           config, tmp_path)
    assert item["metadata"]["content_artifacts"]["raw_retained"] is False
    config.collection.retain_public_html = True
    _apply_http_document(_item(), config.source_by_id("bbc_world"), "Access denied",
                         item["url"], 403, config, tmp_path)
    assert list(tmp_path.rglob("*.response.bin")) == []


def test_numeric_table_without_headers_retains_cells_but_leaves_gap():
    markup = ("<article><h1>Service update</h1><p>Monthly service prices are set out below.</p>"
              "<table><tr><td>10</td><td>20</td></tr></table></article>")
    result = extract_document(BeautifulSoup(markup, "html.parser"), ["article"],
                              expected_title="Service update")
    assert result.status == "partial"
    assert result.quality["numeric_tables_without_headers"] == ["block-3"]
    assert result.quality["title_overlap"] == 1.0
    assert result.quality["key_fields_verified"] is None
    assert result.quality["media_verified"] is None
    assert result.blocks[-1]["rows"][0][0]["text"] == "10"


def test_builtin_short_complete_does_not_invoke_optional_provider(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("Provider must not run")

    monkeypatch.setitem(sys.modules, "trafilatura", SimpleNamespace(extract=fail))
    result = extract_with_fallback(BeautifulSoup(
        "<article><p>Current customers keep the existing plan and price next month.</p></article>",
        "html.parser"), ["article"], fallback="trafilatura")
    assert result.status == "full_text"
    assert "fallback" not in result.quality


@pytest.mark.parametrize("failure", ["missing", "exception", "empty"])
def test_optional_provider_failure_keeps_baseline(monkeypatch, failure):
    def extract(*args, **kwargs):
        if failure == "exception":
            raise RuntimeError("Extractor failed")
        return None

    monkeypatch.setitem(sys.modules, "trafilatura",
                        None if failure == "missing" else SimpleNamespace(extract=extract))
    monkeypatch.setattr("daily_intelligence.content_extraction.version", lambda _: "test")
    result = extract_with_fallback(BeautifulSoup(
        "<body><p>The announcement describes the unchanged service terms.</p></body>",
        "html.parser"), [], fallback="trafilatura")
    assert result.status == "partial"
    assert "unchanged service terms" in result.text
    assert result.quality["fallback"]["status"] == {
        "missing": "unavailable", "exception": "failed", "empty": "no_content",
    }[failure]


def test_provider_only_receives_cleaned_html_and_does_not_prove_completeness(monkeypatch):
    def extract(markup, **kwargs):
        assert "HIDDEN" not in markup and "SECRET_SCRIPT" not in markup
        assert kwargs["include_tables"] is True and kwargs["include_comments"] is False
        return "<body><p>The announcement describes the unchanged service terms.</p></body>"

    monkeypatch.setitem(sys.modules, "trafilatura", SimpleNamespace(extract=extract))
    monkeypatch.setattr("daily_intelligence.content_extraction.version", lambda _: "test")
    result = extract_with_fallback(BeautifulSoup(
        "<body><p>The announcement describes the unchanged service terms.</p>"
        "<p hidden>HIDDEN</p><script>SECRET_SCRIPT</script></body>", "html.parser"), [],
        fallback="trafilatura", truncated=True)
    assert result.status == "partial"
    assert result.quality["extractor"] == "trafilatura"
    assert result.quality["response_truncated"] is True


def test_real_trafilatura_adapter_is_local_and_returns_audited_candidate():
    pytest.importorskip("trafilatura")
    markup = "<html><body><div>" + "".join(
        f"<p>Announcement {i}: The service remains available to current customers. "
        "The plan retains its existing terms and the next billing period is unchanged.</p>"
        for i in range(8)
    ) + "</div></body></html>"
    result = extract_with_fallback(BeautifulSoup(markup, "html.parser"), [],
                                   fallback="trafilatura")
    assert result.status == "partial"
    assert result.quality["fallback"]["status"] == "selected"
    assert result.quality["extractor_version"]
    assert len(result.blocks) >= 4


def test_fallback_cannot_hide_table_loss(monkeypatch):
    monkeypatch.setitem(sys.modules, "trafilatura", SimpleNamespace(extract=lambda *args, **kwargs:
        "<body><p>The announcement describes the unchanged service terms.</p></body>"))
    monkeypatch.setattr("daily_intelligence.content_extraction.version", lambda _: "test")
    result = extract_with_fallback(BeautifulSoup(
        "<body><p>The announcement describes the unchanged service terms.</p>"
        "<table><tr><th>Price</th></tr><tr><td>10</td></tr></table></body>", "html.parser"), [],
        fallback="trafilatura")
    assert result.quality["extractor"] == "builtin"
    assert result.quality["fallback"]["reason"] == "table_retention_unconfirmed"
    assert result.blocks[-1]["rows"][-1][0]["text"] == "10"


@pytest.mark.parametrize("ready", [True, False])
def test_browser_waits_for_text_and_keeps_timeout_explicit(tmp_path, ready):
    class Locator:
        async def count(self):
            return 0

        async def inner_text(self, **kwargs):
            return "Loading"

        async def evaluate_all(self, expression):
            pass

    class Page:
        url = "https://www.bbc.com/news/articles/story"
        markup = "<body><main>Loading</main></body>"
        closed = False

        async def goto(self, *args, **kwargs):
            return SimpleNamespace(status=200)

        async def wait_for_function(self, expression, *, arg, timeout):
            if not ready:
                raise TimeoutError("The article did not load")
            self.markup = ("<body><article><p>Current customers keep the existing plan and price."
                           "</p></article></body>")

        async def title(self):
            return "Service update"

        def locator(self, selector):
            return Locator()

        async def content(self):
            return self.markup

        async def close(self):
            self.closed = True

    page = Page()

    class Context:
        async def new_page(self):
            return page

    item = _item()
    asyncio.run(_extract_one(Context(), item, load_config(), tmp_path))
    assert page.closed
    assert item["content_status"] == ("full_text" if ready else "metadata_only")
    if ready:
        assert "existing plan" in Path(item["content_path"]).read_text(encoding="utf-8")
    else:
        assert item["metadata"]["content_quality"]["incomplete_marker"] is True


@pytest.mark.parametrize("browser_outcome", ["success", "blocked", "launch_failure"])
def test_partial_body_escalates_once_and_browser_failure_preserves_evidence(
    monkeypatch, tmp_path, browser_outcome,
):
    config = load_config()
    item = _item()
    original = "<body><p>The service remains available to current customers.</p></body>"
    _apply(item, original, config, tmp_path)
    old_path = item["content_path"]
    counts = {"http": 0, "browser": 0}

    async def http(targets, *_args):
        counts["http"] += 1
        assert _apply(targets[0], original, config, tmp_path) is True
        return targets

    async def browser(targets, *_args):
        counts["browser"] += 1
        if browser_outcome == "launch_failure":
            raise RuntimeError("Browser not installed")
        if browser_outcome == "blocked":
            targets[0]["content_status"] = "verification_required"
            targets[0]["metadata"]["content_challenge"] = {"required": True}
        else:
            _apply(targets[0], original.replace("body", "article"), config, tmp_path)

    monkeypatch.setattr("daily_intelligence.content._run_http_extraction", http)
    monkeypatch.setattr("daily_intelligence.content._extract_with_browser", browser)
    metrics = asyncio.run(_extract_pipeline([item], config, tmp_path, False, tmp_path / "profile",
                                           None))
    assert counts == {"http": 1, "browser": 1}
    assert metrics["cache_hits"] == 0
    assert metrics["http_successful"] == 1
    assert has_local_content(item, tmp_path)
    attempts = item["metadata"]["content_attempts"]
    assert len(attempts) == 2
    completion = item["metadata"]["content_completion"]
    if browser_outcome == "success":
        assert item["content_status"] == "full_text"
        assert metrics["complete"] == 1
        assert completion["stop_reason"] == "evidence_sufficient"
    else:
        assert item["content_status"] == "partial"
        assert item["content_path"] == old_path
        assert metrics["with_gaps"] == 1
        assert attempts[-1]["input"] is None
        assert completion["stop_reason"] == (
            "verification_required" if browser_outcome == "blocked" else "access_failed"
        )


def test_enriched_revision_keeps_original_and_synchronizes_nested_evidence(monkeypatch, tmp_path):
    config = load_config()
    item = _item()
    payload = {"date": "2026-09-11", "edition": "morning", "revision": 1, "items": [item],
               "sources": [{"source_id": item["source_id"], "items": [copy.deepcopy(item)]}]}
    original = write_json(tmp_path / "indexes" / payload["date"] / "morning-r1.json", payload)
    original_bytes = original.read_bytes()

    async def http(targets, *_args):
        for target in targets:
            _apply(
                target, "<article><p>The service is available under current terms.</p></article>",
                config, tmp_path,
            )
        return []

    monkeypatch.setattr("daily_intelligence.content._run_http_extraction", http)
    result = read_json(extract_content(original, config, tmp_path, [item["item_id"]], 1, False,
                                       tmp_path / "profile"))
    assert original.read_bytes() == original_bytes
    assert result["revision"] == 2
    assert result["items"][0] == result["sources"][0]["items"][0]
    assert result["items"][0]["metadata"]["content_input"]["sha256"]
    assert result["content_metrics"]["complete"] == 1
