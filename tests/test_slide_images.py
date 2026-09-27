from __future__ import annotations

import threading
import time
from pathlib import Path

import httpx

from signaltrail.config import MediaConfig
from signaltrail.media import DownloadedImage, ImageDownloadError
from signaltrail.slide_images import _read_page, enrich_slide_images


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
