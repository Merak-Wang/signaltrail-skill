"""用固定出版方网页评估采集、资格筛选和正文补证。"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from threading import Event, Thread
from time import perf_counter
from unittest.mock import patch
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from PIL import Image, ImageDraw

from signaltrail.adapters import browser_items_from_rows
from signaltrail.article_time import original_publication_time
from signaltrail.brief_selection import select_brief_items
from signaltrail.collector import collect_sources
from signaltrail.config import (
    AppConfig,
    BrowserConfig,
    BudgetConfig,
    CollectionConfig,
    MediaConfig,
    MonitorConfig,
    SourceConfig,
)
from signaltrail.content import (
    PublicationPage,
    _apply_page_publication_time,
    extract_content,
    prepare_publication_content,
)
from signaltrail.content_extraction import observed_source_metadata
from signaltrail.feeds import looks_like_feed, parse_feed_document
from signaltrail.image_policy import select_image_variants
from signaltrail.media import ImageDownloadError, _download_image_batch, download_image
from signaltrail.monitor import refresh_monitor
from signaltrail.news_slides import _index_candidate, select_index_news
from signaltrail.prefetch import html_index_rows
from signaltrail.reporting import reference_time_fields, reference_time_label
from signaltrail.slide_images import enrich_slide_images
from signaltrail.utils import now_iso, read_json

DATE = "2026-07-24"
CUTOFF = f"{DATE}T12:00:00+08:00"
PUBLISHERS = 4
ARTICLES_PER_PUBLISHER = 24
MEDIA_STORIES = 8
SHORT_NOTICE_PATH = "/articles/3/story-22"
VIDEO_FALLBACK_DURATIONS = {
    "/articles/2/story-23": "01:22",
    "/articles/3/story-23": "Video Duration 01 minutes 22 seconds 01:22",
}
ARTICLE_BLOCKS = (
    "The publisher released a written account of the review and the supporting evidence.",
    "The review committee examined the original records and compared the documented findings.",
    "The published findings distinguish the recorded observations from proposed explanations.",
    "The appendix contains the complete measurements, including the closing observation",
)


def _picture(story: int, width: int) -> bytes:
    """生成同图的两种固定尺寸，供生产媒体下载选择。"""
    buffer = BytesIO()
    image = Image.new("RGB", (width, width // 2), (175, 204, 228))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width // 2, width // 4), fill=(30, 58, story))
    image.save(buffer, "PNG")
    return buffer.getvalue()


def _corpus() -> tuple[dict[str, tuple[int, bytes]], dict[str, str]]:
    """构造固定列表、正文响应与可独立核对的全文样本。"""
    routes = {
        "/limited": (429, b"<title>Too many requests</title>"),
        "/unavailable": (503, b"<title>Publisher temporarily unavailable</title>"),
    }
    bodies = {}
    morning = datetime.fromisoformat(f"{DATE}T09:00:00+08:00")
    for publisher in range(PUBLISHERS):
        listing = []
        for number in range(ARTICLES_PER_PUBLISHER):
            path = f"/articles/{publisher}/story-{number:02}"
            title = f"Publisher {publisher} article {number} documents the review"
            listing_time = morning + timedelta(minutes=number)
            publication_time = listing_time
            if number == 22 or (publisher, number) == (0, 19):
                publication_time -= timedelta(days=1)
            if number == 23:
                publication_time += timedelta(hours=5)
            card_time = (
                f'<time datetime="{listing_time.isoformat()}"></time>'
                if number < 22 and number % 2 else "<time>5 minutes ago</time>"
            )
            listing.append(
                f'<article><a href="{path}">{escape(title)}</a>{card_time}</article>'
            )
            if number == 21:
                listing.append(
                    f'<article><a href="{path}?utm_source=duplicate">{escape(title)}</a>'
                    f"{card_time}</article>"
                )
            if (publisher, number) == (0, 21):
                routes[path] = (403, b"<title>Verify you are human</title>")
                continue
            if (publisher, number) == (1, 21):
                routes[path] = (404, b"<title>Article unavailable</title>")
                continue
            paragraphs = [
                f"{paragraph} for publisher {publisher}, article {number}."
                for paragraph in ARTICLE_BLOCKS
            ]
            bodies[path] = "\n\n".join(paragraphs)
            figure = ""
            if publisher == 2 and 12 <= number < 12 + MEDIA_STORIES:
                low, high = f"/images/2-{number:02}.png", f"/images/2-{number:02}-large.png"
                routes[low] = (200, _picture(number, 400))
                routes[high] = (200, _picture(number, 800))
                figure = (
                    f'<figure><img src="{low}" srcset="{low} 400w, {high} 800w" '
                    f'alt="Review evidence"><figcaption>Review chart {number} from the publisher.'
                    '</figcaption></figure>'
                )
                bodies[path] += f"\n\nReview chart {number} from the publisher."
                # 同页推荐卡可能带自己条目的分享图元标签。
                figure += (
                    '<aside><meta property="og:image" content="/images/2-recommendation.png">'
                    '<img src="/images/2-recommendation.png"></aside>'
                )
                routes["/images/2-recommendation.png"] = (200, _picture(99, 800))
            paragraphs_html = "".join(f"<p>{escape(paragraph)}</p>" for paragraph in paragraphs)
            article = f"<article>{paragraphs_html}{figure}</article>"
            if path in VIDEO_FALLBACK_DURATIONS:
                article = f"<main><p>{escape(ARTICLE_BLOCKS[0])}</p></main>"
            elif path == SHORT_NOTICE_PATH:
                article = f"<article><p>{escape(ARTICLE_BLOCKS[0])}</p></article>"
            html = (
                f'<html><head><title>{escape(title)}</title>'
                f'<meta property="og:title" content="{escape(title)}">'
                f'<meta property="article:published_time" '
                f'content="{publication_time.isoformat()}">'
                f'<meta property="og:image" content="/images/{publisher}-{number:02}.png">'
                f'</head><body><nav>Publisher navigation</nav>{article}</body></html>'
            )
            routes[path] = (200, html.encode())
        routes[f"/publishers/{publisher}"] = (
            200, ("<title>Publisher index</title>" + "".join(listing)).encode(),
        )
        if publisher == 0:
            routes["/publishers/section"] = (
                200, ("<title>Publisher section</title>" + "".join(listing[12:])).encode(),
            )
    routes["/feed.xml"] = (200, b"""<rss version="2.0"
    xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
    <title>Publisher Feed</title><item><title>Publisher Feed account of the review</title>
    <link>/articles/1/story-21</link><description>Short Feed description.</description>
    <content:encoded><![CDATA[<p>The full syndicated account supplements listing metadata.</p>]]>
    </content:encoded></item></channel></rss>""")
    routes["/publishers/session"] = (302, b"")
    routes["/publishers/session-target"] = routes["/publishers/2"]
    dates = {
        "aligned": ("2026-07-23", "Thu, 23 Jul 2026 18:32:00 +0000"),
        "conflict": ("2026-07-22", "Thu, 23 Jul 2026 19:10:00 +0000"),
        "exact": ("2026-07-23T18:00:00+08:00", "Thu, 23 Jul 2026 19:30:00 +0000"),
        "later": ("2026-07-24", "Fri, 24 Jul 2026 05:10:00 +0000"),
    }
    cards, feed_items = [], []
    for key, (listing_date, feed_date) in dates.items():
        name = f"Publication date evidence for {key}"
        cards.append(f'<article><a href="/date/{key}">{name}</a>'
                     f'<time datetime="{listing_date}"></time></article>')
        feed_items.append(f"<item><title>{name}</title><link>/date/{key}</link>"
                          f"<pubDate>{feed_date}</pubDate></item>")
    routes["/publication-dates"] = (200, ("<title>Dates</title>" + "".join(cards)).encode())
    routes["/publication-dates.xml"] = (
        200, ("<rss version=\"2.0\"><channel><title>Dates</title>"
              + "".join(feed_items) + "</channel></rss>").encode(),
    )
    return routes, bodies


def _selected_paths(selected: list[dict]) -> list[str]:
    """从选中条目读取有序的固定样本标识。"""
    return [urlsplit(item["url"]).path for item in selected]


def evaluate(work_dir: Path) -> dict:
    """在隔离目录用生产入口执行固定出版方语料并记录收录、耗时和请求。"""
    routes, bodies = _corpus()
    requests: Counter[str] = Counter()

    class Publisher(BaseHTTPRequestHandler):
        """用真实 HTTP 传输提供固定公开网页并记录请求。"""

        def do_GET(self) -> None:
            """读取固定路由并返回对应网页或访问状态。"""
            path = urlsplit(self.path).path
            requests[path] += 1
            code, body = routes.get(path, (404, b"Unknown evaluation route"))
            self.send_response(code)
            if path == "/publishers/session":
                self.send_header("Location", "/publishers/session-target")
                self.send_header("Set-Cookie", "fixture=yes; Path=/publishers/session-target")
            content_type = {
                ".png": "image/png",
                ".xml": "application/rss+xml",
            }.get(Path(path).suffix, "text/html; charset=utf-8")
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            """请求明细保存在计数器中。"""

    with ThreadingHTTPServer(("127.0.0.1", 0), Publisher) as server:
        host = f"http://127.0.0.1:{server.server_port}"
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        thread.start()
        try:
            return _evaluate_corpus(work_dir, host, requests, bodies)
        finally:
            server.shutdown()
            thread.join()


def _check_media_domain_slots(work_dir: Path) -> bool:
    """先到达同域限额时，验证独立域仍能完成请求。"""
    independent_finished = Event()
    slow = [(f"https://same.example/{i}.png", None) for i in range(6)]
    independent = ("https://other.example/image.png", None)

    def fetch(url: str, *_args: object, **_kwargs: object) -> bool:
        if url == independent[0]:
            independent_finished.set()
            return True
        return independent_finished.wait(timeout=2)

    config = MediaConfig(global_concurrency=4, per_domain_concurrency=1)
    with patch("signaltrail.media.download_image", fetch):
        result = _download_image_batch([*slow, independent], work_dir, config, 4096, fetch)
    return result == dict.fromkeys([url for url, _ in [*slow, independent]], True)


def _evaluate_images(work_dir: Path, host: str, items: list[dict], requests: Counter[str]) -> dict:
    """比较正文图片复用和显式重新抓页的真实 HTTP 请求与落盘图片。"""
    articles = [item for item in items if item["source_id"] == "publisher-2"
                and 12 <= int(urlsplit(item["url"]).path[-2:]) < 12 + MEDIA_STORIES]
    # 一个引用换用具有跟踪参数的 URL；同 canonical 仍需重新抓页。
    fallback = articles[-1]["item_id"]
    news = [
        _index_candidate({
            "event_id": f"index-{item['item_id']}",
            "source_refs": [{
                "item_id": item["item_id"],
                "url": item["url"] + (
                    "?utm_source=distinct" if item["item_id"] == fallback else ""
                ),
            }],
        }, {item["item_id"]: item}, work_dir)
        for item in articles
    ]

    def fixture_url_only(url: str) -> None:
        """在评估的独立进程内仅允许固定 HTTP 服务器和语料路由。"""
        parts = urlsplit(url)
        if (f"{parts.scheme}://{parts.netloc}" != host
                or not parts.path.startswith(("/articles/2/", "/images/2-"))):
            raise ImageDownloadError("Unexpected media URL outside the fixed HTTP corpus")

    def image_rows(rows: list[dict], data_dir: Path) -> list[list[tuple]]:
        """从产物文件而非缓存字段计算实际图像指纹。"""
        return [[(
            image["url"], hashlib.sha256((data_dir / image["local_path"]).read_bytes()).hexdigest(),
            image["caption"], image.get("credit"), image["width"], image["height"],
        ) for image in row["images"] if image.get("local_path")] for row in rows]

    recommendation = f"{host}/images/2-recommendation.png"
    # 线上审阅确认这两个地址是中央社站标和 Google News 分享图标。
    cna_template = "https://imgcdn.cna.com.tw/www/images/pic_fb.jpg"
    google_template = (
        "https://lh3.googleusercontent.com/"
        "J6_coFbogxhRI9iM864NL_liGXvsQp2AupsKei7z0cNNfDvGUmWUy20nuUhkREQyrpY4bEeIBuc=s0-w300"
    )
    branding_digest = "872cdca296d04a7be7cba2f91f6825164499491bbbec26e2c6dcadb43859c7b0"
    branded_images = [
        {"url": cna_template + "?v=20261118"},
        {"url": google_template},
        {"url": f"{host}/images/2-redirect.png", "resolved_url": google_template},
        {"url": f"{host}/images/2-cached-platform-cover.png", "sha256": branding_digest},
        {"url": "https://imgcdn.cna.com.tw/www/website/img/ad300x223.jpg"},
        {"url": "https://jingdaily.com/og.png"},
        {"url": "https://ichef.bbci.co.uk/news/1536/cpsprodpb/6133/live/"
                "2bce6ee0-0b00-11f0-97d3-37df2b293ed1.png.webp"},
        {"url": "https://static01.nyt.com/images/2023/04/09/reader-center/"
                "author-david-pierson/author-david-pierson-thumbLarge.png"},
        {"url": "https://static01.nyt.com/images/2018/11/22/multimedia/"
                "author-javier-c-hernandez/author-javier-c-hernandez-thumbStandard-v5.png"},
        {"url": "https://static01.nyt.com/images/2022/08/12/universal/"
                "Keith-Bradsher/Keith-Bradsher-thumbStandard.png"},
    ]
    shared_cover = {"url": f"{host}/images/2-shared-story.png"}
    reported_person = {
        "url": "https://static01.nyt.com/images/2026/11/18/multimedia/"
               "candidate-rally/candidate-rally-thumbStandard.png",
        "alt": "A candidate speaking at the rally",
    }
    different_origin = {"url": f"{host}/www/website/img/ad300x223.jpg"}
    retained_by_story = [
        select_image_variants([shared_cover, reported_person, different_origin, *branded_images]),
        select_image_variants([branded_images[1], shared_cover]),
    ]
    clean_index = all(
        image["url"] != recommendation
        for item in articles for image in item["metadata"]["image_candidate_details"]
    )
    # 模拟此前持久化的错误候选。新页面和已验证页面复用应产生相同的干净图集。
    for item in news:
        item["images"].append({
            "url": recommendation, "source_url": item["sources"][0]["url"],
            "provenance": "page_metadata", "purpose": "publisher_selected",
        })
        item["images"].extend(branded_images[:2] + branded_images[4:])

    # 生产媒体拒绝回环 URL。只在固定评估进程的传输入口注入本地语料白名单。
    with (
        patch("signaltrail.slide_images.assert_public_image_url", fixture_url_only),
        patch.dict(download_image.__kwdefaults__, {"url_validator": fixture_url_only}),
    ):
        metrics = {}
        runs = []
        for name, refresh in (("refresh", True), ("reuse", False)):
            data_dir = work_dir / f"slide-images-{name}"
            before = requests.copy()
            started = perf_counter()
            rows, counters = enrich_slide_images(news, data_dir, MediaConfig(), refresh=refresh)
            metrics[f"slide_images_{name}_seconds"] = perf_counter() - started
            new_requests = requests - before
            metrics[f"slide_images_{name}_page_requests"] = sum(
                count for path, count in new_requests.items() if path.startswith("/articles/")
            )
            metrics[f"slide_images_{name}_download_requests"] = sum(
                count for path, count in new_requests.items() if path.startswith("/images/")
            )
            runs.append((image_rows(rows, data_dir), counters))
    refreshed, reused = runs
    metrics["slide_image_pages_reused"] = reused[1]["source_pages_reused"]
    return {
        "metrics": metrics,
        "checks": {
            "known_site_branding_removed_without_discarding_shared_news_images": (
                retained_by_story == [[shared_cover, reported_person, different_origin],
                                      [shared_cover]]
            ),
            "nested_and_stale_recommendation_images_never_requested": (
                clean_index and not requests["/images/2-recommendation.png"]
            ),
            "slide_images_reuse_complete_page_and_fetch_distinct_url": (
                metrics["slide_images_refresh_page_requests"] == MEDIA_STORIES
                and metrics["slide_images_reuse_page_requests"] == 1
                and metrics["slide_image_pages_reused"] == MEDIA_STORIES - 1
            ),
            "slide_images_preserve_high_resolution_bytes_and_attribution": (
                refreshed[0] == reused[0] and len(reused[0]) == MEDIA_STORIES
                and all(len(row) == 1 and row[0][4:6] == (800, 400)
                        and "Review chart" in row[0][2] and row[0][3] == "Publisher 2"
                        for row in reused[0])
            ),
        },
    }


def _evaluate_body_regions(
    index_path: Path, items: list[dict], config: AppConfig, work_dir: Path, profile: Path,
) -> dict:
    """用真实 HTTP 和固定的浏览器 DOM 响应评估播放器及短公告的正文边界。"""
    paths = {SHORT_NOTICE_PATH, *VIDEO_FALLBACK_DURATIONS}
    ids = [item["item_id"] for item in items if urlsplit(item["url"]).path in paths]

    async def player_page(urls: list[str], **options: object) -> list[dict]:
        """固定浏览器 SDK 的最外层返回，保留后续生产判定和回退流程。"""
        return [
            {"url": url, "status_code": 200, "success": True, "error": None, "media": {},
             "html": '<article><h1>Publisher coverage</h1><p>Now Playing</p>'
                     f'<ul><li>{VIDEO_FALLBACK_DURATIONS[urlsplit(url).path]}</li></ul>'
                     '<p>Video title about the ongoing review.</p>'
                     '</article>'}
            for url in urls
        ]

    started = perf_counter()
    config = replace(config, collection=CollectionConfig(
        browser_extractor="crawl4ai", fallback_extractor="none",
    ))
    with patch("signaltrail.crawl4ai_adapter.crawl_pages", player_page):
        path = extract_content(
            index_path, config, work_dir, ids, max_items=len(paths),
            headed=False, profile_dir=profile,
        )
    index = read_json(path)
    records = {urlsplit(item["url"]).path: item for item in index["items"]}
    notice = records[SHORT_NOTICE_PATH]
    player_checks = {}
    for fixture_path, check in zip(VIDEO_FALLBACK_DURATIONS, (
        "video_player_does_not_replace_partial_article",
        "accessible_video_duration_does_not_replace_partial_article",
    ), strict=True):
        player = records[fixture_path]
        metadata = player["metadata"]
        attempts = metadata["content_attempts"]
        player_checks[check] = (
            player["content_status"] == "partial"
            and metadata["content_completion"]["status"] == "with_gaps"
            and [(attempt["channel"], attempt["status"]) for attempt in attempts] == [
                ("http", "partial"), ("crawl4ai", "metadata_only"),
            ]
            and "video_player_only" in attempts[1]["gaps"]
            and ARTICLE_BLOCKS[0] in Path(player["content_path"]).read_text(encoding="utf-8")
        )
    return {
        "checks": {
            **player_checks,
            "short_standalone_notice_remains_complete": (
                notice["content_status"] == "full_text"
                and notice["metadata"]["content_quality"]["extraction_status"] == "short_complete"
            ),
        },
        "metrics": {"body_region_replay_seconds": perf_counter() - started},
    }


def _evaluate_article_aliases() -> dict:
    """在日报及图文选择入口检查同篇标题路径变化和不同原文的边界。"""
    items = [
        {"item_id": key, "source_id": "dw_world", "url": f"https://www.dw.com/{path}",
         "published_at": f"{DATE}T09:0{minute}:00+08:00",
         "metadata": {"published_precision": "datetime", "source_rank": rank}}
        for rank, (key, path, minute) in enumerate((
            ("old-slug", "en/older-headline/a-79961817?maca=en-rss", 0),
            ("new-slug", "en/updated-headline/a-79961817", 1),
            ("other-story", "en/updated-headline/a-79961818", 2),
            ("other-language", "de/deutscher-titel/a-79961817", 3),
            ("live-feed", "en/india-news/live-79976447?maca=en-rss", 4),
            ("live-direct", "en/india-news/live-79976447", 5),
            ("live-different-id", "en/india-news/live-79976448", 6),
            ("article-same-number", "en/india-news/a-79976447", 7),
        ), 1)
    ]
    expected = [
        "article-same-number", "live-different-id", "live-direct",
        "other-language", "other-story", "new-slug",
    ]
    cbc = "https://www.cbc.ca/news/world/example-story-9."
    cbc_items = [
        {"item_id": key, "source_id": source_id, "url": url,
         "title": "An identical title", "published_at": f"{DATE}T09:00:00+08:00",
         "metadata": {"source_rank": rank}}
        for rank, (key, source_id, url) in enumerate((
            ("cbc-feed", "cbc_world", f"{cbc}12345?cmp=rss"),
            ("cbc-direct", "cbc_world", f"{cbc}12345"),
            ("cbc-different-id", "cbc_world", f"{cbc}12346?cmp=rss"),
            ("cbc-different-query", "cbc_world", f"{cbc}12345?edition=local&cmp=rss"),
            ("cbc-other-source-view", "partner", f"{cbc}12345"),
        ), 1)
    ]
    selected_cbc = select_brief_items(cbc_items, {}, date_value=DATE, cutoff=CUTOFF)
    return {
        "publisher_aliases_share_one_slot_without_rewriting_references": (
            [(item["item_id"], item["metadata"]["source_rank"]) for item in
             select_brief_items(items, {}, date_value=DATE, cutoff=CUTOFF)]
            == list(zip(expected, (8, 7, 6, 4, 3, 2), strict=True))
            and [event["event_id"] for event in
                 select_index_news({"items": items, "date": DATE, "generated_at": CUTOFF})]
            == [f"index-{item_id}" for item_id in expected]
        ),
        "cbc_feed_campaign_alias_shares_one_same_source_slot": selected_cbc == [
            cbc_items[i] for i in (0, 2, 3, 4)
        ],
    }


def _evaluate_cold_listing_reuse(
    work_dir: Path, host: str, requests: Counter[str], config: AppConfig, window: dict[str, str],
) -> dict:
    """在同一语料分别刷新监控并采集，比较完整日报索引和逐页请求。"""
    sources = list(config.sources)
    sources[0] = replace(sources[0], max_items=2, explore_urls=[f"{host}/publishers/section"])
    sources[1] = replace(sources[1], feed_urls=[f"{host}/feed.xml"])
    sources[2] = replace(sources[2], explore_urls=[f"{host}/publishers/session"])
    config = replace(config, sources=sources, monitor=MonitorConfig(auto_discover_feeds=False))
    observed_at = datetime.fromisoformat(now_iso(config.timezone))
    runs = {}
    metrics = {}
    for name, share in (("separate", False), ("shared", True)):
        data_dir = work_dir / f"cold-listing-{name}"
        current_requests = requests.copy()
        started = perf_counter()
        pages = {} if share else None
        refresh_monitor(config, data_dir, now=observed_at, shared_listing_pages=pages)
        path = collect_sources(
            config, data_dir, "daily", False, profile_dir=data_dir / "profile",
            date_value=DATE, collection_window=window, shared_listing_pages=pages,
        )
        run_requests = requests - current_requests
        metrics[f"cold_listing_{name}_seconds"] = perf_counter() - started
        metrics[f"cold_listing_{name}_requests"] = sum(
            count for request_path, count in run_requests.items()
            if request_path.startswith("/publishers/") or request_path in {
                "/limited", "/unavailable",
            }
        )
        runs[name] = (read_json(path), run_requests)

    def index_projection(index: dict) -> tuple:
        """提取逐页结果、收录顺序、时间与原始 Feed 内容摘要。"""
        return (
            [(row["source_id"], row["status"], row["page_results"]) for row in index["sources"]],
            [(item["item_id"], item["title"], item["published_at"], item["content_status"],
              item["metadata"].get("source_rank"), item["metadata"].get("feed_content_sha256"))
             for item in index["items"]],
            index["source_policies"],
        )

    separate, separate_requests = runs["separate"]
    shared, shared_requests = runs["shared"]
    return {
        "checks": {
            "cold_monitor_reuses_complete_listing_pages_only": (
                metrics["cold_listing_separate_requests"] == 17
                and metrics["cold_listing_shared_requests"] == 13
                and shared_requests["/limited"] == separate_requests["/limited"] == 2
                and shared_requests["/unavailable"] == separate_requests["/unavailable"] == 2
                and shared_requests["/publishers/1"] == separate_requests["/publishers/1"] == 1
                and shared_requests["/publishers/section"] == 1
                and shared_requests["/publishers/session"] == 2
                and shared_requests["/publishers/session-target"] == 2
            ),
            "cold_listing_reuse_preserves_coverage_order_and_feed_evidence": (
                index_projection(shared) == index_projection(separate)
                and len(shared["items"]) == PUBLISHERS * ARTICLES_PER_PUBLISHER
                and shared["items"] == [
                    item for row in shared["sources"] for item in row["items"]
                ]
                and any(item["metadata"].get("feed_content_sha256") for item in shared["items"])
            ),
        },
        "metrics": metrics,
    }


def _evaluate_feed_date_precision(work_dir: Path, host: str, window: dict[str, str]) -> dict:
    """用官方 Feed 与列表日期的固定语料验证跨时区资格及拒绝边界。"""
    data_dir = work_dir / "feed-date-precision"
    source = SourceConfig(
        "publication-dates", "Publisher dates", f"{host}/publication-dates",
        article_patterns=[r"/date/"], feed_urls=[f"{host}/publication-dates.xml"],
    )
    config = AppConfig(timezone="Asia/Shanghai", sources=[source], browser=BrowserConfig(),
                       monitor=MonitorConfig(auto_discover_feeds=False))
    started = perf_counter()
    refresh_monitor(config, data_dir)
    path = collect_sources(config, data_dir, "daily", False, profile_dir=data_dir / "profile",
                           date_value=DATE, collection_window=window)
    rows = read_json(path)["items"]
    by_path = {urlsplit(item["url"]).path: item for item in rows}
    ready = select_brief_items(rows, {}, date_value=DATE, cutoff=CUTOFF)
    return {
        "checks": {
            "news_sitemap_uses_original_date_and_article_links": _check_news_sitemap(host),
            "boj_final_results_use_release_day": _check_boj_release_date(),
            "reuters_reprints_keep_aol_provenance": _check_reuters_reprints(),
            "edgar_filing_day_is_distinct_from_acceptance": _check_sec_publication_time(),
            "explicit_social_publication_time": _check_social_publication_time(),
            "abc_live_updates_keep_their_own_publication_time": _check_abc_live_entry_time(),
            "nature_date_precision_is_preserved": _check_nature_date_precision(),
            "arxiv_first_submission_survives_date_only_body": _check_paper_dates(data_dir),
            "xinhua_report_uses_original_header_time": _check_xinhua_publication(data_dir),
            "publisher_feed_time_resolves_same_day_across_timezone": (
                _selected_paths(ready) == ["/date/aligned"]
                and by_path["/date/aligned"]["published_at"] == f"{DATE}T02:32:00+08:00"
                and by_path["/date/aligned"]["metadata"]["published_precision"] == "datetime"
            ),
            "feed_precision_preserves_conflicts_exact_dates_and_cutoff": (
                by_path["/date/conflict"]["published_at"] == "2026-07-22"
                and by_path["/date/exact"]["published_at"] == "2026-07-23T18:00:00+08:00"
                and "/date/later" not in by_path
            ),
        },
        "metrics": {
            "feed_date_precision_seconds": perf_counter() - started,
            "feed_date_precision_eligible": len(ready),
        },
    }


def _check_nature_date_precision() -> bool:
    """核对同日的机器午夜占位不会覆盖 Nature RSS 的日期粒度。"""
    item = {
        "source_id": "nature_news",
        "published_at": "2026-11-18T08:00:00+08:00",
        "metadata": {"published_raw": "2026-11-18", "published_precision": "date",
                     "content_source": {"published_at": "2026-11-18T00:00:00Z"}},
    }
    soup = BeautifulSoup(
        '<meta property="article:published_time" content="2026-11-18T00:00:00Z">'
        '<header><time datetime="2026-11-18">18 November 2026</time></header>',
        "html.parser",
    )
    declared = observed_source_metadata(soup, "https://www.nature.com/articles/d41586-026-03710-y")
    if declared["published_at"] != "2026-11-18" or original_publication_time(item) != "2026-11-18":
        return False
    item["metadata"]["content_source"]["published_at"] = "2026-11-18T02:30:00Z"
    return original_publication_time(item) == "2026-11-18T10:30:00+08:00"


def _check_social_publication_time() -> bool:
    """回放官方社交原文的发布日期，区分同页更新字段。"""
    url = "https://social.anoxinon.de/@Codeberg/117636454915265360"
    stamp = "2026-11-18T08:17:31Z"
    publication = f'<meta property="og:published_time" content="{stamp}">'
    revision = '<meta property="og:updated_time" content="2026-11-19T08:00:00Z">'
    source = observed_source_metadata(BeautifulSoup(publication + revision, "html.parser"), url)
    item = {"source_id": "lobsters", "url": url, "metadata": {"content_source": source}}
    revised = observed_source_metadata(BeautifulSoup(revision, "html.parser"), url)
    return (original_publication_time(item) == "2026-11-18T16:17:31+08:00"
            and revised["published_at"] is None)


def _check_abc_live_entry_time() -> bool:
    """回放 ABC 发布卡片结构，检查母页、同页相邻子条目与缺失编号。"""
    html = """<script type="application/ld+json">
      {"@type":"NewsArticle","datePublished":"2026-11-18T12:52:45.000Z"}
    </script><script>
    window['__abcnews__']={"page":{"content":{"data":{"mainComponents":[
      {"props":{"entries":[
        {"id":"138243636","issued":"2026-11-18T12:12:05Z","modified":"2026-11-18T12:22:00Z"},
        {"id":"138241381","shareBylineData":{"publishedDate":{"date":"2026-11-18T09:57:23Z"}}}
      ]}}
    ]}}}};
    </script>"""
    soup = BeautifulSoup(html, "html.parser")
    parent = "https://abcnews.com/Politics/live-updates/trump-asia-trip-2026/?id=138187702"
    publications = [
        observed_source_metadata(soup, parent + suffix)
        for suffix in ("", "&entryId=138243636", "&entryId=138241381", "&entryId=99999999")
    ]
    item = {"url": parent + "&entryId=138243636"}
    _apply_page_publication_time(item, publications[1], "America/New_York")
    return item["published_at"] == "2026-11-18T07:12:05-05:00" and [
        row["published_at"] for row in publications
    ] == [
        "2026-11-18T12:52:45.000Z", "2026-11-18T12:12:05+00:00",
        "2026-11-18T09:57:23+00:00", None,
    ]


def _check_sec_publication_time() -> bool:
    """核对 EDGAR 账面日期与纽约受理时刻跨北京时间自然日。"""
    url = "https://www.sec.gov/Archives/edgar/data/1045810/1/sample-index.htm"
    source = SourceConfig("sec_edgar_latest", "SEC EDGAR Latest Filings", url)
    atom = f"""<feed xmlns="http://www.w3.org/2005/Atom"><entry>
    <title>NVIDIA files Form 8-K</title><link href="{url}"/>
    <updated>2026-11-17T16:21:30-05:00</updated>
    <summary type="html">Filed: 2026-11-17 AccNo: 1</summary>
    </entry></feed>"""
    [item] = parse_feed_document(
        atom, source, "https://www.sec.gov/feed", "2026-11-18T09:00:00+08:00",
        "Asia/Shanghai", max_items=1,
    )
    soup = BeautifulSoup(
        '<div class="infoHead">Filing Date</div><div class="info">2026-11-17</div>'
        '<div class="infoHead">Accepted</div><div class="info">2026-11-17 16:20:51</div>',
        "html.parser",
    )
    metadata = observed_source_metadata(soup, url)
    return (
        item.published_at is None and item.metadata.get("sec_filing_date") == "2026-11-17"
        and metadata.get("published_at") == "2026-11-17T16:20:51-05:00"
        and original_publication_time({"published_at": metadata["published_at"]})
        == "2026-11-18T05:20:51+08:00"
    )


def _check_reuters_reprints() -> bool:
    """核对路透明确署名的转载入选，混合栏目内其他报道不计入。"""
    source = SourceConfig("reuters", "Reuters", "https://www.reuters.com/")
    _, rows = html_index_rows("""
        <a href="/articles/one.html"><p>Reuters</p><img alt="Reuters" src="/logo.png">
        <p>Central bank raises rates</p></a>
        <a href="/articles/two.html"><p>Associated Press</p><p>Reuters quoted</p></a>
    """)
    items = browser_items_from_rows(rows, source, CUTOFF, "https://www.aol.com/news/")
    return (
        len(items) == 1 and items[0].title == "Central bank raises rates"
        and items[0].url == "https://www.aol.com/articles/one.html"
        and items[0].metadata.get("syndication_provider") == "Reuters"
        and items[0].published_at is None and items[0].image_url is None
    )


def _check_boj_release_date() -> bool:
    """用上一交易日终值表核对发布日和文件名日期的优先级。"""
    source = SourceConfig("boj_news", "Bank of Japan", "https://www.boj.or.jp/en/")
    table = ('<table><tr><td>Jul. 24, 2026</td><td><a href="/en/statistics/market/short/'
             'mutan/d_release/md/2026/md20260723.xlsx">Uncollateralized Overnight Call Rate '
             'for Jul. 23 (Final results)</a></td></tr></table>')
    _, rows = html_index_rows(table)
    items = browser_items_from_rows(rows, source, CUTOFF, source.url)
    return len(items) == 1 and items[0].published_at == DATE


def _check_news_sitemap(host: str) -> bool:
    """用新闻目录的跨日发表、旧稿更新和普通页面核对正式选稿。"""
    source = SourceConfig("publisher", "Publisher", host, article_patterns=[r"/news/"])
    entries = []
    for slug, date in (("new", "2026-07-23T23:05:00Z"), ("old", "2026-07-22T20:00:00Z"),
                       ("navigation", None)):
        news = ""
        if date:
            news = (f"<news:news><news:title>Publisher story {slug}</news:title>"
                    f"<news:publication_date>{date}</news:publication_date></news:news>")
        entries.append(f"<url><loc>{host}/news/{slug}</loc><lastmod>{CUTOFF}</lastmod>{news}</url>")
    xml = ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
           'xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">'
           + "".join(entries) + "</urlset>")
    rows = [item.to_dict() for item in parse_feed_document(
        xml, source, f"{host}/news.xml", CUTOFF, "Asia/Shanghai", max_items=40)]
    selected = select_brief_items(rows, {}, date_value=DATE, cutoff=CUTOFF)
    return (looks_like_feed(xml) and len(rows) == 2 and len(selected) == 1
            and selected[0]["url"] == f"{host}/news/new"
            and selected[0]["published_at"] == f"{DATE}T07:05:00+08:00"
            and selected[0]["metadata"]["feed_format"] == "news_sitemap")


def _check_paper_dates(data_dir: Path) -> bool:
    """用原文与收录链接验证补正文后仍按 arXiv 的首次提交时刻选稿。"""
    publisher = "https://arxiv.org/abs/2607.12345v1"
    timestamp = "2026-07-23T23:05:00Z"
    html = ('<meta name="citation_publication_date" content="2026-07-23">'
            '<article><h1>Publication fixture</h1>'
            + "".join(f"<p>{paragraph}</p>" for paragraph in ARTICLE_BLOCKS) + "</article>")
    page = PublicationPage(html.encode(), "utf-8", publisher, 200, "http")
    sources = [
        SourceConfig("arxiv_ai", "arXiv", "https://arxiv.org"),
        SourceConfig("huggingface_papers", "Hugging Face Papers", "https://huggingface.co"),
    ]
    config = AppConfig(timezone="Asia/Shanghai", sources=sources, browser=BrowserConfig())
    rows = []
    for source, url in zip(sources, (
        publisher.removesuffix("v1"), "https://huggingface.co/papers/2607.12345",
    ), strict=True):
        original = {"url": publisher, "published_at": "2026-07-23"}
        item = {"item_id": source.id, "source_id": source.id, "source_name": source.name,
                "url": url, "title": "Publication fixture", "published_at": "2026-07-23",
                "metadata": {"content_source": original, "publication_time_probe": {
                    "status": "success", "final_url": publisher, "published_at": timestamp,
                }}}
        snapshot = prepare_publication_content(item, page, source, config, data_dir)
        if not snapshot or snapshot["metadata"]["content_source"].get("published_at") != timestamp:
            return False
        item["metadata"].update(snapshot.pop("metadata"))
        item.update(snapshot)
        rows.append(item)
    ready = select_brief_items(rows, {}, date_value=DATE, cutoff=CUTOFF)
    early = select_brief_items(rows, {}, date_value=DATE, cutoff=f"{DATE}T07:04:59+08:00")
    return ready == rows and not early


def _check_xinhua_publication(data_dir: Path) -> bool:
    """从原始稿页补齐索引的日粒度时间，并验证日报展示和冻结截止时间。"""
    publisher = "https://english.news.cn/20260724/abc/c.html"
    source = SourceConfig("xinhua_en", "Xinhua English", "https://english.news.cn/")
    config = AppConfig(timezone="Asia/Shanghai", sources=[source], browser=BrowserConfig())
    item = {"item_id": source.id, "source_id": source.id, "source_name": source.name,
            "url": publisher, "title": "Publication fixture", "published_at": DATE, "metadata": {}}
    page_template = ('<meta itemprop="datePublished" content="' + DATE + '">'
                     '<meta itemprop="dateModified" content="' + DATE + 'T23:30:00+08:00">'
                     '<div class="conTop"><div class="infoBox"><div class="info">'
                     '<p class="time">{stamp}</p></div></div></div>'
                     '<article><h1>Publication fixture</h1>'
                     + "".join(f"<p>{paragraph}</p>" for paragraph in ARTICLE_BLOCKS)
                     + '</article><aside><p class="time">' + DATE + ' 17:30:00</p></aside>')
    expected = f"{DATE}T08:30:45+08:00"
    for clock in ("08:30:45", "00:30:45 UTC"):
        html = page_template.format(stamp=f"{DATE} {clock}")
        page = PublicationPage(html.encode(), "utf-8", publisher, 200, "http")
        snapshot = prepare_publication_content(item, page, source, config, data_dir)
        if not snapshot:
            return False
        enriched = {**item, **snapshot}
        shown = reference_time_label(reference_time_fields(enriched))
        if shown != ("发布时间", expected) or select_brief_items(
            [enriched], {}, date_value=DATE, cutoff=f"{DATE}T08:30:44+08:00",
        ):
            return False
    without_header = page_template.replace('<p class="time">{stamp}</p>', "")
    return observed_source_metadata(
        BeautifulSoup(without_header, "html.parser"), publisher,
    )["published_at"] == DATE


def _evaluate_corpus(
    work_dir: Path, host: str, requests: Counter[str], bodies: dict[str, str],
) -> dict:
    """运行从原始列表到不可变富化索引的流程，并以独立语料预期验收。"""
    sources = [
        SourceConfig(
            f"publisher-{publisher}", f"Publisher {publisher}",
            f"{host}/publishers/{publisher}", article_patterns=[r"/articles/\d+/story-\d+"],
            collect_all_items=True,
        )
        for publisher in range(PUBLISHERS)
    ]
    sources.extend(SourceConfig(name, name, f"{host}/{name}") for name in (
        "limited", "unavailable",
    ))
    config = AppConfig(
        timezone="Asia/Shanghai", browser=BrowserConfig(), sources=sources,
        budget=BudgetConfig(max_fulltext_per_run=15 * PUBLISHERS),
    )
    by_id = {source.id: source for source in sources}
    window = {"start": "2026-07-23T12:00:00+08:00", "end": CUTOFF}
    profile = work_dir / "profile"

    started = perf_counter()
    initial_path = collect_sources(
        config, work_dir, "daily", False, profile_dir=profile,
        date_value=DATE, collection_window=window,
    )
    collect_seconds = perf_counter() - started
    raw = read_json(initial_path)
    selected = select_brief_items(raw["items"], by_id, date_value=DATE, cutoff=CUTOFF)
    initial_request_count = requests.total()
    started = perf_counter()
    intermediate_path = extract_content(
        initial_path, config, work_dir, [item["item_id"] for item in selected],
        max_items=None, headed=False, profile_dir=profile,
    )
    intermediate = read_json(intermediate_path)
    selected_after_date_review = select_brief_items(
        intermediate["items"], by_id, date_value=DATE, cutoff=CUTOFF,
    )
    replacement = {item["item_id"] for item in selected_after_date_review} - {
        item["item_id"] for item in selected
    }
    final_path = (
        extract_content(
            intermediate_path, config, work_dir, sorted(replacement),
            max_items=None, headed=False, profile_dir=profile,
        )
        if replacement else intermediate_path
    )
    enrich_seconds = perf_counter() - started
    final = read_json(final_path)
    final_items = select_brief_items(final["items"], by_id, date_value=DATE, cutoff=CUTOFF)
    expected_paths = [
        f"/articles/{publisher}/story-{number:02}"
        for publisher in range(PUBLISHERS)
        for number in range(21, 5 if publisher == 0 else 6, -1)
        if (publisher, number) != (0, 19)
    ]
    inaccessible = {
        "/articles/0/story-21": ("verification_required", "verification_required"),
        "/articles/1/story-21": ("failed", "access_failed"),
    }
    by_path = {urlsplit(item["url"]).path: item for item in final_items}
    complete = []
    for path in (set(expected_paths) - inaccessible.keys()) & by_path.keys():
        item = by_path[path]
        metadata = item["metadata"]
        body_path = Path(item["content_path"]) if item.get("content_path") else None
        blocks = metadata.get("content_blocks_path")
        body_hash = hashlib.sha256(bodies[path].encode()).hexdigest()
        picture_stem = path.replace("/articles/", "/images/").replace("/story-", "-")
        expected_picture = (
            picture_stem + "-large.png"
            if path.startswith("/articles/2/")
            and 12 <= int(path[-2:]) < 12 + MEDIA_STORIES else picture_stem + ".png"
        )
        if (
            item["content_status"] == "full_text" and body_path and body_path.is_file()
            and blocks and Path(blocks).is_file()
            and metadata.get("content_text_sha256") == body_hash
            and bodies[path].split("\n\n")[-1] in body_path.read_text(encoding="utf-8")
            and item.get("image_url", "").endswith(expected_picture)
        ):
            complete.append(path)
    statuses = {source["source_id"]: source["status"] for source in final["sources"]}
    probe_hits = intermediate["content_metrics"]["publication_probe_hits"]
    reused_paths = {
        urlsplit(item["url"]).path for item in selected
        if item["metadata"].get("publication_probe_content")
    }
    request_count = requests.total()
    probe_reused_once = all(requests[path] == 1 for path in reused_paths)
    images = _evaluate_images(work_dir, host, final_items, requests)
    body_regions = _evaluate_body_regions(final_path, final["items"], config, work_dir, profile)
    cold_listing = _evaluate_cold_listing_reuse(work_dir, host, requests, config, window)
    feed_precision = _evaluate_feed_date_precision(work_dir, host, window)
    return {
        "workload": {
            "name": "fixed-local-publisher-pages",
            "edition_date": DATE,
            "publishers": PUBLISHERS,
            "articles_per_publisher": ARTICLES_PER_PUBLISHER,
            "unavailable_sources": 2,
            "expected_eligible": 60,
            "slide_image_stories": MEDIA_STORIES,
            "body_region_replay_cases": 1 + len(VIDEO_FALLBACK_DURATIONS),
            "article_alias_cases": 13,
        },
        "checks": {
            "all_source_outcomes_preserved": statuses == {
                **{source.id: "success" for source in sources[:PUBLISHERS]},
                "limited": "rate_limited", "unavailable": "failed",
            },
            "frozen_collection_window_survives_enrichment": (
                raw.get("collection_window") == window == final.get("collection_window")
            ),
            "canonical_index_preserves_all_unique_articles": (
                len(raw["items"]) == PUBLISHERS * ARTICLES_PER_PUBLISHER
                and all(len(source["items"]) == ARTICLES_PER_PUBLISHER
                        for source in raw["sources"][:PUBLISHERS])
            ),
            "latest_15_after_original_date_correction": (
                _selected_paths(final_items) == expected_paths and len(replacement) == 1
                and "/articles/0/story-19" in _selected_paths(selected)
            ),
            "full_article_evidence_and_images_preserved": (
                len(complete) == len(expected_paths) - len(inaccessible)
            ),
            "blocked_articles_remain_visible_as_gaps": all(
                path in by_path and by_path[path]["content_status"] == status
                and by_path[path]["metadata"]["content_completion"]["stop_reason"] == reason
                for path, (status, reason) in inaccessible.items()
            ),
            "canonical_and_nested_index_views_agree": final["items"] == [
                item for source in final["sources"] for item in source["items"]
            ],
            "complete_date_response_reused_without_second_request": (
                probe_hits == len(reused_paths) == 28
                and probe_reused_once
                and initial_request_count == 58
                and request_count - initial_request_count == 33
            ),
            "media_domain_limit_preserves_independent_hosts": _check_media_domain_slots(work_dir),
            **images["checks"],
            **body_regions["checks"],
            **_evaluate_article_aliases(),
            **cold_listing["checks"],
            **feed_precision["checks"],
        },
        "metrics": {
            "collect_seconds": collect_seconds,
            "enrich_seconds": enrich_seconds,
            "articles_collected_per_second": len(raw["items"]) / collect_seconds,
            "eligible_articles_per_second": len(final_items) / (collect_seconds + enrich_seconds),
            "raw_articles": len(raw["items"]),
            "eligible_articles": len(final_items),
            "complete_articles": len(complete),
            "enriched_index_bytes": final_path.stat().st_size,
            "http_requests": request_count,
            "collection_http_requests": initial_request_count,
            "enrichment_http_requests": request_count - initial_request_count,
            "publication_probe_hits": probe_hits,
            "publication_probe_reuse_fraction": probe_hits / len(selected),
            **images["metrics"],
            **body_regions["metrics"],
            **cold_listing["metrics"],
            **feed_precision["metrics"],
        },
        "artifacts": {"source_index": str(initial_path), "enriched_index": str(final_path)},
        "limitations": [
            "Fixed loopback HTML measures local processing and actual HTTP request volume.",
            "Publisher network latency, browser rendering, and live source coverage are separate.",
        ],
    }
