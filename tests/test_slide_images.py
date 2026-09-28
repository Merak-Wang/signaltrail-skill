from __future__ import annotations

import threading
import time
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup

from signaltrail.config import MediaConfig
from signaltrail.media import DownloadedImage, ImageDownloadError
from signaltrail.slide_images import _read_page, enrich_slide_images, fetch_article_page


def _news() -> list[dict]:
    return [{
        "event_id": "event-1", "title": "Trump meets Xi Jinping",
        "sources": [{"name": "Guardian", "title": "Trump and Xi", "url": "https://news.example/story"}],
        "images": [{"url": "https://cdn.example/thumb.jpg", "source_url": "https://cdn.example/thumb.jpg",
                    "width": 320, "height": 180, "local_path": "media/images/thumb.jpg"}],
    }]


def test_page_reader_uses_article_picture_srcset_and_ignores_related_images(monkeypatch):
    markup = b"""<html><head><meta property="og:image" content="/hero-wide.jpg"></head><body>
      <article><h1>Trump and Xi</h1><p>Trump will meet Xi Jinping in Beijing.</p>
      <figure><picture><source srcset="/photo-700.jpg 700w, /photo-1400.jpg 1400w">
      <img src="/photo-465.jpg" alt="Trump and Xi at a meeting"></picture>
      <figcaption>Original news caption</figcaption></figure></article>
      <aside class="related"><img src="/related.jpg" alt="Related story"></aside></body></html>"""

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def stream(self, *_args, **_kwargs):
            response = httpx.Response(
                200, content=markup, request=httpx.Request("GET", "https://news.example/story"),
            )
            class Stream:
                def __enter__(self):
                    return response

                def __exit__(self, *_exc):
                    response.close()

            return Stream()

    monkeypatch.setattr("signaltrail.slide_images.httpx.Client", Client)
    monkeypatch.setattr("signaltrail.slide_images.assert_public_image_url", lambda _url: None)
    candidates, final_url = _read_page(
        "https://news.example/story", "Trump and Xi", MediaConfig(),
    )
    urls = {candidate["url"] for candidate in candidates}
    assert final_url == "https://news.example/story"
    assert "https://news.example/photo-1400.jpg" in urls
    assert "https://news.example/hero-wide.jpg" in urls
    assert "https://news.example/related.jpg" not in urls
    caption = next(c for c in candidates if "photo-1400" in c["url"])["caption"]
    assert caption == "Original news caption"


def test_page_reader_extracts_body_image_and_keeps_og_candidate(monkeypatch):
    markup = BeautifulSoup(b'''<html><head>
      <meta property="og:image" content="/image/eye.jpg"></head><body>
      <div class="article"><p>Syncing the Rust GCC backend took two months because
      several repository changes went wrong. This article describes the synchronization.</p>
      <img src="/blog/images/cat-between-legs.jpg" alt="A good illustration of Murphy's law"></div>
      </body></html>''', "html.parser")
    monkeypatch.setattr(
        "signaltrail.slide_images.fetch_article_page",
        lambda *_args: (markup, "https://blog.guillaume-gomez.fr/articles/story"),
    )

    candidates, _final_url = _read_page(
        "https://blog.guillaume-gomez.fr/articles/story", "Syncing Rust GCC backend",
        MediaConfig(),
    )

    body = next(candidate for candidate in candidates
                if candidate["url"].endswith("cat-between-legs.jpg"))
    assert body["provenance"] == "article_body"
    assert any(candidate["url"].endswith("/image/eye.jpg")
               and candidate["provenance"] == "page_metadata" for candidate in candidates)


def test_page_reader_reports_http_200_verification_page(monkeypatch):
    markup = (b"<html><title>One moment, please...</title><body>"
              b"Please wait while your request is being verified...</body></html>")

    class Client:
        def stream(self, _method, url):
            response = httpx.Response(200, content=markup, request=httpx.Request("GET", url))

            class Stream:
                def __enter__(self):
                    return response

                def __exit__(self, *_args):
                    response.close()

            return Stream()

    monkeypatch.setattr("signaltrail.slide_images.assert_public_image_url", lambda _url: None)

    with pytest.raises(
        ImageDownloadError, match="access challenge: your request is being verified",
    ):
        _read_page("https://news.example/story", "A public story", MediaConfig(), Client())


def test_article_page_reader_rejects_http_200_sina_visitor_system(monkeypatch):
    markup = b"<html><title>Sina Visitor System</title><body></body></html>"

    class Client:
        def stream(self, _method, url):
            response = httpx.Response(200, content=markup, request=httpx.Request("GET", url))

            class Stream:
                def __enter__(self):
                    return response

                def __exit__(self, *_args):
                    response.close()

            return Stream()

    monkeypatch.setattr("signaltrail.slide_images.assert_public_image_url", lambda _url: None)
    with pytest.raises(ImageDownloadError, match="access challenge: sina visitor system"):
        fetch_article_page("https://weibo.com/story", MediaConfig(), Client())


def test_arxiv_abstract_follows_explicit_same_paper_html_for_body_images(monkeypatch):
    abstract_url = "https://arxiv.org/abs/2608.23642"
    fulltext_url = "https://arxiv.org/html/2608.23642v3"
    pages = {
        abstract_url: b'''<html><body><main>
          <p>AI Agents Push Humans Out of the Loop</p>
          <a href="/html/2608.23642v3">HTML (experimental)</a>
        </main></body></html>''',
        fulltext_url: b'''<html><body><article><h1>AI Agents Push Humans Out of the Loop</h1>
          <p>AI agents affect human oversight and cognition over time.</p>
          <figure><img src="2608.23642v3/extended_mind.png" alt="Extended mind"
            width="476" height="240">
          <figcaption>Figure 1: The extended mind.</figcaption></figure>
        </article></body></html>''',
    }
    requested = []

    class Client:
        def stream(self, _method, url):
            requested.append(url)
            response = httpx.Response(
                200, content=pages[url], request=httpx.Request("GET", url),
            )

            class Stream:
                def __enter__(self):
                    return response

                def __exit__(self, *_exc):
                    response.close()

            return Stream()

    monkeypatch.setattr("signaltrail.slide_images.assert_public_image_url", lambda _url: None)
    candidates, final_url = _read_page(
        abstract_url, "AI Agents Push Humans Out of the Loop", MediaConfig(), Client(),
    )

    image = next(candidate for candidate in candidates if candidate.get("alt") == "Extended mind")
    assert requested == [abstract_url, fulltext_url]
    assert final_url == abstract_url
    assert image["url"] == "https://arxiv.org/html/2608.23642v3/extended_mind.png"
    assert image["caption"] == "Figure 1: The extended mind."


def test_arxiv_without_explicit_same_paper_html_keeps_abstract_images(monkeypatch):
    abstract_url = "https://arxiv.org/abs/2608.23642"
    markup = b'''<html><body><main><p>AI agents and human oversight.</p>
      <a href="https://other.example/fulltext">Full text</a>
      <a href="/html/2609.99999v1">HTML (experimental)</a>
      <article><p>Original image in selected body.</p>
      <img src="/figure.png" alt="Human oversight figure"></article>
    </main></body></html>'''
    requested = []

    class Client:
        def stream(self, _method, url):
            requested.append(url)
            response = httpx.Response(
                200, content=markup, request=httpx.Request("GET", url),
            )

            class Stream:
                def __enter__(self):
                    return response

                def __exit__(self, *_exc):
                    response.close()

            return Stream()

    monkeypatch.setattr("signaltrail.slide_images.assert_public_image_url", lambda _url: None)
    candidates, _final_url = _read_page(
        abstract_url, "AI agents oversight", MediaConfig(), Client(),
    )

    assert requested == [abstract_url]
    assert "https://arxiv.org/figure.png" in {candidate["url"] for candidate in candidates}


def test_arxiv_fulltext_failure_preserves_images_and_records_source_failure(
    monkeypatch, tmp_path: Path,
):
    abstract_url = "https://arxiv.org/abs/2608.23642"
    fulltext_url = "https://arxiv.org/html/2608.23642v3"
    markup = BeautifulSoup(b'''<html><body><main>
      <p>AI Agents Push Humans Out of the Loop</p>
      <a href="/html/2608.23642v3">HTML (experimental)</a>
      <article><p>Existing abstract-page figure.</p>
      <img src="/original.png" alt="Original existing figure"></article>
    </main></body></html>''', "html.parser")

    def fetch(url, _config, _client):
        if url == abstract_url:
            return markup, url
        assert url == fulltext_url
        raise ImageDownloadError("HTML endpoint unavailable")

    monkeypatch.setattr("signaltrail.slide_images.fetch_article_page", fetch)
    original = "https://arxiv.org/original.png"
    downloaded = DownloadedImage(
        source_url=original, resolved_url=original, local_path="media/images/original.png",
        content_type="image/png", sha256="original", byte_size=100,
        width=1200, height=800, reused=False,
    )
    monkeypatch.setattr(
        "signaltrail.slide_images._download_image_batch",
        lambda rows, *_args, **_kwargs: {url: downloaded for url, _referer in rows},
    )
    news = _news()
    news[0]["title"] = "AI Agents Push Humans Out of the Loop"
    news[0]["sources"][0]["url"] = abstract_url

    result, metrics = enrich_slide_images(news, tmp_path, MediaConfig())

    assert {image["url"] for image in result[0]["images"]} == {
        "https://cdn.example/thumb.jpg", original,
    }
    assert metrics["source_failures"] == [{
        "url": abstract_url,
        "reason": "arXiv HTML full text failed: ImageDownloadError: HTML endpoint unavailable",
    }]


def test_page_reader_uses_image_rich_main_when_selected_article_is_a_task_card(monkeypatch):
    markup = b"""<html><body>
      <header><div class="site-logo"><img src="/stanford-logo.png" alt=""></div></header>
      <main><h1>HomeBody humanoid research project</h1>
      <section><p>""" + (b"The project describes an autonomous humanoid robot. " * 12) + b"""</p>
        <figure><img src="figures/overview.webp" width="1800" alt="Project overview">
        <figcaption>Project overview.</figcaption></figure>
        <figure><img src="figures/architecture.webp" width="1800" alt="System architecture">
        </figure>
        <figure><img src="figures/comparison.webp" width="720" alt="System comparison">
        </figure>
      </section>
      <article class="task-brief"><p>Retrieve the medicine I forgot;
        enough text to be selected.</p></article>
      <aside class="sidebar"><img src="/sidebar-promo.png" alt="Promotion"></aside>
      </main><nav><img src="/nav-icon.png" alt=""></nav></body></html>"""

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def stream(self, *_args, **_kwargs):
            response = httpx.Response(
                200, content=markup, request=httpx.Request("GET", "https://tml.example/homebody/"),
            )
            class Stream:
                def __enter__(self):
                    return response

                def __exit__(self, *_exc):
                    response.close()

            return Stream()

    monkeypatch.setattr("signaltrail.slide_images.httpx.Client", Client)
    monkeypatch.setattr("signaltrail.slide_images.assert_public_image_url", lambda _url: None)
    candidates, _final_url = _read_page(
        "https://tml.example/homebody/", "HomeBody humanoid research project", MediaConfig(),
    )
    urls = {candidate["url"] for candidate in candidates}
    assert "https://tml.example/homebody/figures/overview.webp" in urls
    assert "https://tml.example/homebody/figures/architecture.webp" in urls
    assert "https://tml.example/homebody/figures/comparison.webp" in urls
    assert not any("logo" in url or "sidebar" in url or "nav-icon" in url for url in urls)


def test_enrich_downloads_page_candidates_and_keeps_existing(monkeypatch, tmp_path: Path):
    full = "https://cdn.example/full.jpg"
    monkeypatch.setattr("signaltrail.slide_images._read_page", lambda *_: ([
        {"url": full, "provenance": "article_body", "caption": "原文图注",
         "declared_width": "1600", "declared_height": "900"},
    ], "https://news.example/story"))
    downloaded = DownloadedImage(
        source_url=full, resolved_url=full, local_path="media/images/full.jpg",
        content_type="image/jpeg", sha256="abc", byte_size=1000,
        width=1600, height=900, reused=False,
    )
    monkeypatch.setattr("signaltrail.slide_images._download_image_batch",
                        lambda rows, *_args, **_kwargs: {rows[0][0]: downloaded})
    result, metrics = enrich_slide_images(_news(), tmp_path, MediaConfig())

    images = result[0]["images"]
    assert {image["url"] for image in images} == {
        "https://cdn.example/thumb.jpg", full,
    }
    high = next(image for image in images if image["url"] == full)
    assert high["caption"] == "原文图注"
    assert high["local_path"] == "media/images/full.jpg"
    assert (high["width"], high["height"], high["sha256"]) == (1600, 900, "abc")
    assert metrics["images_downloaded"] == 1
    assert metrics["source_failures"] == []


def test_downloaded_body_image_drops_tiny_og_but_keeps_full_size_og(
    monkeypatch, tmp_path: Path,
):
    article = "https://news.example/story"
    tiny = "https://news.example/image/eye.jpg"
    hero = "https://news.example/image/hero.jpg"
    body = "https://news.example/images/story.jpg"
    news = _news()
    news[0]["sources"][0]["url"] = article
    news[0]["images"] = [
        {"url": tiny, "source_url": article, "provenance": "page_metadata",
         "local_path": "media/images/eye.jpg", "width": 96, "height": 96,
         "sha256": "eye", "byte_size": 100},
        {"url": hero, "source_url": article, "provenance": "page_metadata",
         "local_path": "media/images/hero.jpg", "width": 1200, "height": 675,
         "sha256": "hero", "byte_size": 1000},
    ]
    monkeypatch.setattr("signaltrail.slide_images._read_page", lambda *_: ([{
        "url": body, "provenance": "article_body", "position": 0,
    }], article))
    downloaded = DownloadedImage(
        source_url=body, resolved_url=body, local_path="media/images/story.jpg",
        content_type="image/jpeg", sha256="story", byte_size=2000,
        width=1200, height=800, reused=False,
    )
    monkeypatch.setattr(
        "signaltrail.slide_images._download_image_batch",
        lambda rows, *_args, **_kwargs: {rows[0][0]: downloaded},
    )

    result, _metrics = enrich_slide_images(news, tmp_path, MediaConfig())

    assert {image["url"] for image in result[0]["images"]} == {hero, body}


def test_existing_small_variant_merges_with_new_large_variant(monkeypatch, tmp_path: Path):
    article = "https://news.example/story"
    small = "https://i.guim.co.uk/abc/photo.jpg?width=140&quality=80"
    large = "https://i.guim.co.uk/abc/photo.jpg?width=1400&quality=90"
    news = _news()
    news[0]["sources"][0]["url"] = article
    news[0]["images"] = [{
        "url": small, "source_url": article, "local_path": "media/images/old-thumb.jpg",
        "width": 140, "height": 80, "sha256": "old-thumb", "byte_size": 12,
        "provenance": "article_body", "position": 0,
    }]
    monkeypatch.setattr("signaltrail.slide_images._read_page", lambda *_: ([{
        "url": large, "provenance": "article_body", "position": 0,
        "declared_width": "1400", "declared_height": "800", "caption": "原文图注",
    }], article))
    def download_batch(rows, *_args, **_kwargs):
        return {large: DownloadedImage(
            source_url=large, resolved_url=large, local_path="media/images/new-full.jpg",
            content_type="image/jpeg", sha256="new-full", byte_size=500,
            width=1400, height=800, reused=False,
        )}

    monkeypatch.setattr("signaltrail.slide_images._download_image_batch", download_batch)
    result, _metrics = enrich_slide_images(news, tmp_path, MediaConfig())

    assert len(result[0]["images"]) == 1
    image = result[0]["images"][0]
    assert image["url"] == large
    assert image["source_url"] == article
    assert image["caption"] == "原文图注"
    assert image["local_path"] == "media/images/new-full.jpg"


def test_duplicate_source_pages_fetch_once_and_new_images_download_in_one_batch(
    monkeypatch, tmp_path: Path,
):
    page_url = "https://news.example/story"
    image_urls = [f"https://cdn.example/image-{n}.jpg" for n in range(3)]
    calls = []
    batches = []

    def read_page(url, *_args):
        calls.append(url)
        return ([{"url": image_url, "provenance": "page_metadata"}
                 for image_url in image_urls], url)

    def download_batch(rows, *_args, **_kwargs):
        batches.append(len(rows))
        return {
            url: DownloadedImage(
                source_url=url, resolved_url=url, local_path=f"media/images/{index}.jpg",
                content_type="image/jpeg", sha256=f"sha-{index}", byte_size=10,
                width=1200, height=800, reused=False,
            )
            for index, (url, _referer) in enumerate(rows)
        }

    monkeypatch.setattr("signaltrail.slide_images._read_page", read_page)
    monkeypatch.setattr("signaltrail.slide_images._download_image_batch", download_batch)
    news = _news() * 2
    for item in news:
        item["sources"][0]["url"] = page_url
        item["images"] = []
    result, _metrics = enrich_slide_images(
        news, tmp_path, MediaConfig(global_concurrency=3, max_total_bytes=300),
    )

    assert calls == [page_url]
    assert batches == [3]
    assert len(result[0]["images"]) == 3


def test_article_fetches_reuse_connection_client_and_limit_each_domain(
    monkeypatch, tmp_path: Path,
):
    news = _news()
    news[0]["images"] = []
    urls = [
        "https://one.example/a", "https://one.example/b", "https://one.example/c",
        "https://one.example/d", "https://one.example/e", "https://one.example/f",
        "https://two.example/g",
    ]
    news[0]["sources"] = [{"name": "Example", "title": url, "url": url} for url in urls]
    lock = threading.Lock()
    clients = set()
    active: dict[str, int] = {}
    max_active: dict[str, int] = {}
    other_domain_started = threading.Event()
    first_request_shared_slot = []

    def read_page(url, _title, _config, client):
        host = url.split("/", 3)[2]
        if host == "two.example":
            other_domain_started.set()
        elif url == urls[0]:
            first_request_shared_slot.append(other_domain_started.wait(timeout=1))
        with lock:
            clients.add(id(client))
            active[host] = active.get(host, 0) + 1
            max_active[host] = max(max_active.get(host, 0), active[host])
        time.sleep(0.02)
        with lock:
            active[host] -= 1
        return [], url

    monkeypatch.setattr("signaltrail.slide_images._read_page", read_page)
    result, metrics = enrich_slide_images(
        news, tmp_path, MediaConfig(global_concurrency=4, per_domain_concurrency=1),
    )

    assert len(clients) == 1
    assert first_request_shared_slot == [True]
    assert max_active["one.example"] == 1
    assert max_active["two.example"] == 1
    assert metrics["sources_fetched"] == 7
    assert result[0]["images"] == []


def test_source_failure_keeps_previous_images(monkeypatch, tmp_path: Path):
    def fail(*_args):
        raise OSError("blocked")

    monkeypatch.setattr("signaltrail.slide_images._read_page", fail)
    result, metrics = enrich_slide_images(_news(), tmp_path, MediaConfig())
    assert result[0]["images"][0]["url"] == "https://cdn.example/thumb.jpg"
    assert metrics["source_failures"][0]["url"] == "https://news.example/story"


def test_failed_clear_variant_falls_back_to_cached_same_asset(monkeypatch, tmp_path: Path):
    article = "https://news.example/story"
    small = "https://i.guim.co.uk/abc/photo.jpg?width=140&quality=80"
    large = "https://i.guim.co.uk/abc/photo.jpg?width=1400&quality=90"
    news = _news()
    news[0]["sources"][0]["url"] = article
    news[0]["images"] = [{
        "url": small, "source_url": article, "local_path": "media/images/old-thumb.jpg",
        "width": 140, "height": 80, "sha256": "old-thumb", "byte_size": 12,
        "provenance": "article_body", "position": 0,
    }]
    monkeypatch.setattr("signaltrail.slide_images._read_page", lambda *_: ([{
        "url": large, "provenance": "article_body", "position": 0,
        "declared_width": "1400", "declared_height": "800",
    }], article))

    def fail_download(rows, *_args, **_kwargs):
        return {url: ImageDownloadError("high resolution unavailable") for url, _ in rows}

    monkeypatch.setattr("signaltrail.slide_images._download_image_batch", fail_download)
    result, metrics = enrich_slide_images(news, tmp_path, MediaConfig())

    assert len(result[0]["images"]) == 1
    assert result[0]["images"][0]["url"] == small
    assert result[0]["images"][0]["local_path"] == "media/images/old-thumb.jpg"
    assert metrics["image_failures"][0]["url"] == large


def test_each_page_image_uses_its_own_article_as_download_referer(monkeypatch, tmp_path: Path):
    first_article = "https://news.example/first"
    second_article = "https://news.example/second"
    first_image = "https://cdn.example/first.jpg"
    second_image = "https://cdn.example/second.jpg"
    news = _news()
    news[0]["sources"].append({"name": "Other", "title": "Second", "url": second_article})
    news[0]["sources"][0]["url"] = first_article
    news[0]["images"] = []
    monkeypatch.setattr("signaltrail.slide_images._read_page", lambda url, *_: ([{
        "url": first_image if url == first_article else second_image,
        "provenance": "article_body",
    }], url))
    requested = []

    def download(rows, *_args, **_kwargs):
        requested.extend(rows)
        return {url: DownloadedImage(
            source_url=url, resolved_url=url, local_path=f"media/images/{url.rsplit('/', 1)[-1]}",
            content_type="image/jpeg", sha256=url.rsplit("/", 1)[-1], byte_size=10,
            width=1200, height=800, reused=False,
        ) for url, _ in rows}

    monkeypatch.setattr("signaltrail.slide_images._download_image_batch", download)
    enrich_slide_images(news, tmp_path, MediaConfig())

    assert dict(requested) == {first_image: first_article, second_image: second_article}


def test_download_count_obeys_media_image_budget(monkeypatch, tmp_path: Path):
    full = "https://cdn.example/full.jpg"
    second = "https://cdn.example/second.jpg"
    monkeypatch.setattr("signaltrail.slide_images._read_page", lambda *_: ([
        {"url": full, "provenance": "page_metadata"},
        {"url": second, "provenance": "page_metadata"},
    ], "https://news.example/story"))
    requested = []

    def download(rows, *_args, **_kwargs):
        requested.extend(url for url, _ in rows)
        return {url: DownloadedImage(
            source_url=url, resolved_url=url, local_path=f"media/images/{index}.jpg",
            content_type="image/jpeg", sha256=f"sha-{index}", byte_size=10,
            width=1200, height=800, reused=False,
        ) for index, (url, _referer) in enumerate(rows)}

    monkeypatch.setattr("signaltrail.slide_images._download_image_batch", download)
    news = _news()
    news[0]["images"] = []
    result, _metrics = enrich_slide_images(
        news, tmp_path, MediaConfig(max_images_per_report=1),
    )

    assert len(requested) == 1
    assert sum(bool(image.get("local_path")) for image in result[0]["images"]) == 1


def test_same_content_under_two_urls_fills_one_slide_image(monkeypatch, tmp_path: Path):
    first = "https://cdn.example/first.jpg"
    second = "https://mirror.example/first.jpg"
    monkeypatch.setattr("signaltrail.slide_images._read_page", lambda *_: ([
        {"url": first, "provenance": "page_metadata", "caption": "Publisher caption"},
        {"url": second, "provenance": "article_body", "position": 0},
    ], "https://news.example/story"))

    def download_batch(rows, *_args, **_kwargs):
        return {
            url: DownloadedImage(
                source_url=url, resolved_url=url, local_path="media/images/first.jpg",
                content_type="image/jpeg", sha256="same-content", byte_size=500,
                width=1200, height=800, reused=False,
            )
            for url, _referer in rows
        }

    monkeypatch.setattr("signaltrail.slide_images._download_image_batch", download_batch)
    result, metrics = enrich_slide_images(_news(), tmp_path, MediaConfig())

    urls = [image["url"] for image in result[0]["images"]]
    assert urls.count(first) == 1
    assert second not in urls
    assert metrics["images_deduplicated"] == 1


def test_over_budget_candidate_stays_as_remote_unknown(monkeypatch, tmp_path: Path):
    full = "https://cdn.example/full.jpg"
    monkeypatch.setattr("signaltrail.slide_images._read_page", lambda *_: ([
        {"url": full, "provenance": "page_metadata", "caption": ""},
    ], "https://news.example/story"))
    config = MediaConfig(max_total_bytes=0)
    result, metrics = enrich_slide_images(_news(), tmp_path, config)
    candidate = next(image for image in result[0]["images"] if image["url"] == full)
    assert candidate["width"] is None and candidate["height"] is None
    assert "local_path" not in candidate
    assert metrics["image_failures"] == []
