"""用固定出版方网页评估采集、资格筛选和正文补证。"""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import datetime, timedelta
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from threading import Thread
from time import perf_counter
from unittest.mock import patch
from urllib.parse import urlsplit

from PIL import Image, ImageDraw

from signaltrail.brief_selection import select_brief_items
from signaltrail.collector import collect_sources
from signaltrail.config import AppConfig, BrowserConfig, BudgetConfig, MediaConfig, SourceConfig
from signaltrail.content import extract_content
from signaltrail.media import ImageDownloadError, download_image
from signaltrail.news_slides import _index_candidate
from signaltrail.slide_images import enrich_slide_images
from signaltrail.utils import read_json

DATE = "2026-07-24"
CUTOFF = f"{DATE}T12:00:00+08:00"
PUBLISHERS = 4
ARTICLES_PER_PUBLISHER = 24
MEDIA_STORIES = 8
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
            html = (
                f'<html><head><title>{escape(title)}</title>'
                f'<meta property="og:title" content="{escape(title)}">'
                f'<meta property="article:published_time" '
                f'content="{publication_time.isoformat()}">'
                f'<meta property="og:image" content="/images/{publisher}-{number:02}.png">'
                f'</head><body><nav>Publisher navigation</nav><article>'
                + "".join(f"<p>{escape(paragraph)}</p>" for paragraph in paragraphs) + figure
                + "</article></body></html>"
            )
            routes[path] = (200, html.encode())
        routes[f"/publishers/{publisher}"] = (
            200, ("<title>Publisher index</title>" + "".join(listing)).encode(),
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
            content_type = "image/png" if path.endswith(".png") else "text/html; charset=utf-8"
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
    return {
        "workload": {
            "name": "fixed-local-publisher-pages",
            "edition_date": DATE,
            "publishers": PUBLISHERS,
            "articles_per_publisher": ARTICLES_PER_PUBLISHER,
            "unavailable_sources": 2,
            "expected_eligible": 60,
            "slide_image_stories": MEDIA_STORIES,
        },
        "checks": {
            "all_source_outcomes_preserved": statuses == {
                **{source.id: "success" for source in sources[:PUBLISHERS]},
                "limited": "rate_limited", "unavailable": "failed",
            },
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
            **images["checks"],
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
        },
        "artifacts": {"source_index": str(initial_path), "enriched_index": str(final_path)},
        "limitations": [
            "Fixed loopback HTML measures local processing and actual HTTP request volume.",
            "Publisher network latency, browser rendering, and live source coverage are separate.",
        ],
    }
