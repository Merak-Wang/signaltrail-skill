import asyncio
from pathlib import Path

import httpx
import pytest

from daily_intelligence.config import SourceConfig
from daily_intelligence.feeds import (
    discover_feed_urls,
    fetch_feed,
    looks_like_feed,
    parse_feed_document,
)
from daily_intelligence.utils import read_json


def _source() -> SourceConfig:
    return SourceConfig(
        id="example",
        name="Example News",
        url="https://news.example/",
        include_domains=["news.example"],
        module="information",
        category="international",
        tier=1,
        role="primary",
    )


def test_rss_parser_preserves_time_image_and_missing_time_fallback():
    rss = b"""<?xml version="1.0"?>
    <rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
      <channel>
        <item>
          <title>Major policy update changes the regional outlook</title>
          <link>https://news.example/policy-update</link>
          <pubDate>Fri, 24 Jul 2026 01:30:00 GMT</pubDate>
          <description><![CDATA[<p>A concrete public summary.</p>]]></description>
          <media:thumbnail
            url="https://static.example/assets/grey-placeholder.png"/>
          <media:content url="https://news.example/images/policy.jpg" type="image/jpeg"/>
        </item>
        <item>
          <title>Second detailed report without a publication timestamp</title>
          <link>https://news.example/second-report</link>
          <description>A second public summary.</description>
        </item>
      </channel>
    </rss>"""

    items = parse_feed_document(
        rss,
        _source(),
        "https://news.example/feed.xml",
        "2026-07-24T10:00:00+08:00",
        "Asia/Shanghai",
        max_items=10,
    )

    assert len(items) == 2
    assert items[0].published_at == "2026-07-24T09:30:00+08:00"
    assert items[0].image_url == "https://news.example/images/policy.jpg"
    assert items[0].description == "A concrete public summary."
    assert items[1].published_at is None
    assert items[1].metadata["publication_time_missing"] is True
    assert items[1].discovered_at == "2026-07-24T10:00:00+08:00"


def test_atom_parser_drops_future_dated_entry_and_keeps_provider():
    atom = b"""<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Valid research update with reproducible benchmark details</title>
        <link href="https://news.example/research"/>
        <published>2026-07-24T01:00:00Z</published>
        <summary>Benchmark details are available publicly.</summary>
        <source><title>Original Lab</title><link href="https://lab.example/"/></source>
      </entry>
      <entry>
        <title>Impossible future report should not enter the index</title>
        <link href="https://news.example/future"/>
        <published>2026-07-25T12:00:00Z</published>
      </entry>
    </feed>"""

    items = parse_feed_document(
        atom,
        _source(),
        "https://news.example/atom.xml",
        "2026-07-24T10:00:00+08:00",
        "Asia/Shanghai",
        max_items=10,
    )

    assert [item.title for item in items] == [
        "Valid research update with reproducible benchmark details"
    ]
    assert items[0].original_provider == "Original Lab"
    assert items[0].metadata["original_provider_url"] == "https://lab.example/"


def test_feed_parser_can_choose_publication_order_without_losing_top_rank():
    rss = b"""<rss><channel>
      <item>
        <title>Older article is the original first feed result</title>
        <link>https://news.example/original-first</link>
        <pubDate>Tue, 12 Sep 2023 01:00:00 GMT</pubDate>
      </item>
      <item>
        <title>Newer article is the original second feed result</title>
        <link>https://news.example/newer-second</link>
        <pubDate>Fri, 24 Jul 2026 01:00:00 GMT</pubDate>
      </item>
    </channel></rss>"""
    source = _source()
    source.item_order = "published_at"

    items = parse_feed_document(
        rss,
        source,
        "https://news.example/feed.xml",
        "2026-07-24T10:00:00+08:00",
        "Asia/Shanghai",
        max_items=1,
    )

    assert [item.url for item in items] == ["https://news.example/newer-second"]
    assert items[0].metadata["source_rank"] == 2


def test_feed_sniffing_and_html_discovery():
    html = """
    <html><head>
      <link rel="alternate" type="application/rss+xml" href="/rss.xml">
      <link rel="alternate" type="application/atom+xml" href="https://cdn.example/atom">
    </head></html>
    """

    assert looks_like_feed("<rss><channel/></rss>")
    assert not looks_like_feed("<!doctype html><html><body>captcha</body></html>")
    assert discover_feed_urls(html, "https://news.example/") == [
        "https://news.example/rss.xml",
        "https://cdn.example/atom",
    ]


def test_feed_html_image_prefers_srcset_over_low_resolution_src():
    rss = b"""<rss><channel><item>
      <title>A sufficiently detailed public news headline</title>
      <link>https://news.example/story</link>
      <description><![CDATA[<p>Public description.</p>
        <img src='/small.jpg' srcset='/large.jpg 2x, /small.jpg 1x'>
      ]]></description></item></channel></rss>"""
    items = parse_feed_document(
        rss, _source(), "https://news.example/rss.xml", "2026-09-11T06:00:00+08:00",
        "Asia/Shanghai", max_items=10,
    )
    assert items[0].image_url == "https://news.example/large.jpg"


def test_conditional_feed_cache_reuses_304_items(tmp_path: Path):
    requests: list[httpx.Request] = []
    rss = b"""<rss><channel><item>
      <title>A sufficiently detailed cached news headline</title>
      <link>https://news.example/cached</link>
      <pubDate>Fri, 24 Jul 2026 01:00:00 GMT</pubDate>
    </item></channel></rss>"""

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                200,
                content=rss,
                headers={"etag": '"feed-v1"', "content-type": "application/rss+xml"},
            )
        return httpx.Response(304)

    async def run() -> tuple:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            first = await fetch_feed(
                client,
                _source(),
                "https://news.example/rss.xml",
                tmp_path,
                "Asia/Shanghai",
                max_bytes=100_000,
                max_items=10,
                refresh_interval_minutes=30,
                force=True,
            )
            second = await fetch_feed(
                client,
                _source(),
                "https://news.example/rss.xml",
                tmp_path,
                "Asia/Shanghai",
                max_bytes=100_000,
                max_items=10,
                refresh_interval_minutes=30,
                force=True,
            )
            return first, second

    first, second = asyncio.run(run())

    assert len(first.items) == 1
    assert len(second.items) == 1
    assert second.cache_state == "not_modified"
    assert requests[1].headers["if-none-match"] == '"feed-v1"'


def _parse_saved(content, tmp_path):
    return parse_feed_document(
        content, _source(), "https://news.example/rss.xml", "2026-09-20T10:00:00+08:00",
        "Asia/Shanghai", max_items=10, data_dir=tmp_path,
    )[0]


def test_long_feed_content_preserves_tail_without_expanding_candidates(tmp_path):
    from daily_intelligence.context import _compact_candidates

    prefix = "A public report provides observations and measurements. " * 30

    def rss(tail):
        return f"""<rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
          <item><title>A long report with an important final condition</title>
          <link>https://news.example/report</link><description>Short summary.</description>
          <content:encoded><![CDATA[<h2>Observations</h2><p>{prefix}</p>
          <p>{tail}</p><table><tr><th>Year</th><th>Value</th></tr>
          <tr><td>2026</td><td>10</td></tr></table>]]></content:encoded>
          </item></channel></rss>"""

    first = _parse_saved(rss("Only valid under controlled conditions."), tmp_path)
    path = Path(first.metadata["feed_content_path"])
    before = path.stat().st_mtime_ns
    record = read_json(path)
    assert "Only valid under controlled conditions." in record["text"]
    assert {block["type"] for block in record["blocks"]} >= {"heading", "paragraph", "table"}
    assert record["truncated"] is False
    assert len(first.description) == 600
    assert first.content_status == "not_fetched"
    assert first.content_path is None
    repeated = _parse_saved(rss("Only valid under controlled conditions."), tmp_path)
    assert repeated.metadata == first.metadata
    assert path.stat().st_mtime_ns == before
    second = _parse_saved(rss("The condition was revised."), tmp_path)
    assert second.item_id == first.item_id
    assert second.metadata["feed_content_path"] != str(path)
    assert "Only valid under controlled conditions." in read_json(path)["text"]
    compact = _compact_candidates({"items": [first.to_dict()]}, 25, {_source().id: 15}, set())
    assert compact[0]["description"] == first.description
    assert "feed_content_path" not in compact[0]
    assert "blocks" not in compact[0]


def test_atom_xhtml_preserves_nested_images_caption_and_xml_base(tmp_path):
    atom = """<feed xmlns="http://www.w3.org/2005/Atom"
        xml:base="https://news.example/" xml:lang="en">
      <entry xml:base="reports/"><title>An illustrated public research report</title>
        <link xml:base="../articles/" href="one"/>
        <content type="xhtml" xml:base="../assets/">
          <div xmlns="http://www.w3.org/1999/xhtml">
            <p>The result remains preliminary and needs independent replication.</p>
            <figure xml:base="photos/">
              <picture><source srcset="large.jpg 1600w, medium.jpg 800w"/>
                <img src="small.jpg" alt="The research instrument"/></picture>
              <figcaption>Instrument shown during the September test.</figcaption>
            </figure>
          </div>
        </content>
      </entry></feed>"""
    item = _parse_saved(atom, tmp_path)
    record = read_json(Path(item.metadata["feed_content_path"]))
    assert item.url == "https://news.example/articles/one"
    assert item.image_url == "https://news.example/assets/photos/large.jpg"
    assert record["mime_type"] == "application/xhtml+xml"
    assert record["language"] == "en"
    assert record["images"][0]["caption"] == "Instrument shown during the September test."
    assert record["quality"]["article_completeness"] == "unknown"


@pytest.mark.parametrize("kind, value, expected", [
    ("text", "Use &lt;limit&gt; literally in text.", "Use <limit> literally in text."),
    ("html", "&lt;p&gt;An actual &lt;b&gt;HTML&lt;/b&gt; paragraph.&lt;/p&gt;",
     "An actual HTML paragraph."),
])
def test_atom_text_and_html_have_distinct_semantics(tmp_path, kind, value, expected):
    item = _parse_saved(f"""<feed xmlns="http://www.w3.org/2005/Atom"><entry>
      <title>A report with typed Atom content</title><link href="https://news.example/story"/>
      <content type="{kind}">{value}</content></entry></feed>""", tmp_path)
    assert read_json(Path(item.metadata["feed_content_path"]))["text"] == expected


def test_feed_preserves_declared_encoding_and_missing_body(tmp_path):
    rss = '''<?xml version="1.0" encoding="iso-8859-1"?><rss><channel><item>
      <title>Café publishes a detailed research update</title><link>https://news.example/cafe</link>
      <description>Résumé of the café's observations.</description></item></channel></rss>'''
    assert "Résumé" in _parse_saved(rss.encode("iso-8859-1"), tmp_path).description
    empty = _parse_saved("""<rss><channel><item><title>Report without supplied body content</title>
      <link>https://news.example/empty</link></item></channel></rss>""", tmp_path)
    assert "feed_content_path" not in empty.metadata
    assert empty.content_status == "not_fetched"


def test_image_only_feed_keeps_picture_without_claiming_body(tmp_path):
    item = _parse_saved("""<rss><channel><item><title>Report with only a supplied image</title>
      <link>https://news.example/picture</link><description><![CDATA[
      <picture><source data-srcset="/large.jpg 1600w"><img src="/small.jpg"></picture>
      ]]></description></item></channel></rss>""", tmp_path)
    assert item.image_url == "https://news.example/large.jpg"
    assert not item.description
    assert "feed_content_path" not in item.metadata


def test_failed_refresh_remains_stale_during_backoff(tmp_path):
    responses = iter([
        httpx.Response(200, text="""<rss><channel><item>
          <title>A valid cached public report</title><link>https://news.example/story</link>
          </item></channel></rss>"""),
        httpx.Response(429, headers={"Retry-After": "600"}),
    ])

    async def run():
        transport = httpx.MockTransport(lambda _: next(responses))
        async with httpx.AsyncClient(transport=transport) as client:
            args = (client, _source(), "https://news.example/rss.xml", tmp_path, "Asia/Shanghai")
            kwargs = dict(max_bytes=10000, max_items=10, refresh_interval_minutes=30)
            await fetch_feed(*args, **kwargs, force=True)
            failed = await fetch_feed(*args, **kwargs, force=True)
            cached = await fetch_feed(*args, **kwargs)
            return failed, cached

    failed, cached = asyncio.run(run())
    assert failed.status == cached.status == "partial"
    assert failed.stale and cached.stale
    assert cached.http_status == 429
