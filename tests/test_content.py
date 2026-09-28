from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup

from signaltrail.access import classify_access_text
from signaltrail.config import load_config
from signaltrail.content import (
    _apply_http_document,
    _extract_pipeline,
    _ordered_targets,
    _run_http_extraction,
    _run_parallel_extraction,
    extract_content,
    extract_visible_text,
    synchronize_nested_items,
)
from signaltrail.content_extraction import extract_document, observed_source_metadata
from signaltrail.content_images import article_image_candidates
from signaltrail.models import ContentStatus
from signaltrail.utils import read_json, write_json


def test_access_classifier_recognizes_verified_request_challenge_text():
    result = classify_access_text(200, "One moment, please...",
                                 "Please wait while your request is being verified...")

    assert result["required"] is True
    assert result["matched_text"] == "your request is being verified"


@pytest.mark.parametrize("attribute", ["property", "name"])
def test_source_publication_date_uses_article_published_meta(attribute):
    soup = BeautifulSoup(
        f'<html><head><meta {attribute}="article:published_time" '
        'content="2026-09-27T02:22:41Z"></head></html>',
        "html.parser",
    )

    assert observed_source_metadata(soup)["published_at"] == "2026-09-27T02:22:41Z"


@pytest.mark.parametrize("markup", [
    '<time itemprop="datePublished" datetime="2026-09-27T01:00:00Z"></time>',
    '<meta itemprop="datePublished" content="2026-09-27">',
])
def test_source_publication_date_uses_date_published_itemprop(markup):
    soup = BeautifulSoup(f"<html><head>{markup}</head></html>", "html.parser")

    assert observed_source_metadata(soup)["published_at"] == (
        "2026-09-27T01:00:00Z" if "datetime" in markup else "2026-09-27"
    )


@pytest.mark.parametrize("article_type", [
    "Article", "NewsArticle", "BlogPosting", "ScholarlyArticle",
])
def test_source_publication_date_uses_typed_json_ld_graph(article_type):
    payload = {
        "@graph": [
            {"@type": "WebPage", "datePublished": "2026-09-25"},
            {"@type": ["Thing", article_type], "datePublished": "2026-09-27"},
        ]
    }
    soup = BeautifulSoup(
        '<html><head><script type="application/ld+json">'
        + json.dumps(payload)
        + "</script></head></html>",
        "html.parser",
    )

    assert observed_source_metadata(soup)["published_at"] == "2026-09-27"


@pytest.mark.parametrize("name", ["citation_publication_date", "citation_date"])
def test_source_publication_date_uses_citation_meta(name):
    soup = BeautifulSoup(
        f'<html><head><meta name="{name}" content="2026-09-19"></head></html>',
        "html.parser",
    )

    assert observed_source_metadata(soup)["published_at"] == "2026-09-19"


def test_source_publication_date_ignores_modified_generic_time_and_url_date():
    soup = BeautifulSoup(
        '<html><head><meta property="article:modified_time" '
        'content="2026-09-27"><meta property="og:updated_time" content="2026-09-27">'
        '<meta itemprop="dateModified" content="2026-09-27">'
        '<time datetime="2026-09-27T08:00:00Z"></time>'
        '<script type="application/ld+json">{"@type":"WebPage",'
        '"datePublished":"2026-09-27"}</script></head></html>',
        "html.parser",
    )

    assert observed_source_metadata(soup)["published_at"] is None


@pytest.mark.parametrize("after_index_write", [False, True])
def test_extraction_resumes_index_commit_without_repeating_acquisition(
    monkeypatch, tmp_path, after_index_write,
):
    import signaltrail.content as module

    item = _item()
    index_path = write_json(tmp_path / "indexes" / "2026-09-12" / "morning-r1.json", {
        "date": "2026-09-12", "edition": "morning", "items": [item],
        "sources": [{"items": [dict(item)]}],
    })
    calls = []

    async def extract(targets, *_args):
        calls.append(1)
        targets[0]["content_status"] = "verification_required"
        return {"selected": 1, "successful": 0}

    immutable = module.write_immutable_json

    def fail_index(path, payload):
        if path.name == "morning-r2.json":
            if after_index_write:
                immutable(path, payload)
            raise OSError("simulated index commit interruption")
        return immutable(path, payload)

    monkeypatch.setattr(module, "_extract_pipeline", extract)
    monkeypatch.setattr(module, "resolve_profile_dir", lambda *_args: tmp_path / "profile")
    monkeypatch.setattr(module, "write_immutable_json", fail_index)
    kwargs = dict(
        index_path=index_path, config=load_config(), data_dir=tmp_path,
        selected_ids=[item["item_id"]], max_items=1, headed=False,
        checkpoint_path=tmp_path / "content-checkpoints" / "operation.json",
    )
    with pytest.raises(OSError, match="commit interruption"):
        extract_content(**kwargs)
    monkeypatch.setattr(module, "write_immutable_json", immutable)
    output = extract_content(**kwargs)
    assert output.name == "morning-r2.json"
    assert calls == [1]
    payload = read_json(output)
    assert payload["items"][0]["content_status"] == "verification_required"
    assert payload["sources"][0]["items"][0] == payload["items"][0]
    assert read_json(index_path)["items"][0]["content_status"] == "not_fetched"
    assert extract_content(**kwargs) == output
    changed = read_json(index_path)
    changed["items"][0]["title"] = "Different input"
    write_json(index_path, changed)
    with pytest.raises(ValueError, match="checkpoint does not match"):
        extract_content(**kwargs)


def test_short_article_beats_long_related_body_and_preserves_structured_evidence(tmp_path):
    document = (
        "<html><body><article><h1>正式公告</h1>"
        "<p>自2026年9月12日起，服务价格调整为每月10元，其他条件不变。</p>"
        "<p>现有用户在当前订阅期内继续适用原价格，无需额外操作。</p>"
        "<ul><li>适用地区：中国。</li><li>结算单位：人民币。</li></ul>"
        "<table><tr><th>方案</th><th>价格（元/月）</th></tr>"
        "<tr><td>标准</td><td>10</td></tr></table></article><div>"
        + "RELATED_STORY " * 300 + "</div></body></html>"
    )
    config = load_config()
    item = _item()
    retry = _apply_http_document(
        item, config.source_by_id(item["source_id"]), document, item["url"], 200,
        config, tmp_path,
    )
    assert retry is False
    assert item["content_status"] == ContentStatus.FULL_TEXT
    assert item["metadata"]["content_quality"]["extraction_status"] == "short_complete"
    assert item["metadata"]["content_selector"] == "article"
    text = Path(item["content_path"]).read_text(encoding="utf-8")
    assert "RELATED_STORY" not in text
    assert "条件不变。\n\n现有用户" in text
    blocks = read_json(Path(item["metadata"]["content_blocks_path"]))["blocks"]
    assert [block["type"] for block in blocks] == [
        "heading", "paragraph", "paragraph", "list_item", "list_item", "table",
    ]
    assert [cell["text"] for cell in blocks[-1]["rows"][0]] == ["方案", "价格（元/月）"]
    assert [cell["text"] for cell in blocks[-1]["rows"][1]] == ["标准", "10"]


@pytest.mark.parametrize(("markup", "status", "quality"), [
    ("<body>" + "Long but unbounded page content. " * 100 + "</body>",
     ContentStatus.PARTIAL, "partial"),
    ("<article><h1>A headline with no article body at all</h1></article>",
     ContentStatus.METADATA_ONLY, "insufficient"),
    ("<article>Loading</article>", ContentStatus.METADATA_ONLY, "insufficient"),
    ("<article><p>Available opening paragraph about the announcement.</p>"
     "<p>Subscribe to read the full article.</p></article>", ContentStatus.PARTIAL, "partial"),
    ("<article>" + "<a href='/other'>Linked recommendation without body</a>" * 100
     + "</article>", ContentStatus.METADATA_ONLY, "insufficient"),
])
def test_content_quality_does_not_equate_length_or_successful_access_with_full_text(
    markup, status, quality,
):
    result = extract_document(BeautifulSoup(markup, "html.parser"), ["article", "main"])
    assert result.status == status
    assert result.quality["extraction_status"] == quality


def test_multiple_article_candidates_ignore_link_farm_and_hidden_recommendations():
    soup = BeautifulSoup(
        "<body><article><a href='/x'>" + "Recommendations " * 200 + "</a></article>"
        "<article><p>The service will resume on Monday, with the existing terms unchanged.</p>"
        "<div class='related-content'>UNRELATED</div><p hidden>HIDDEN</p></article></body>",
        "html.parser",
    )
    result = extract_document(soup, ["body", "article"])
    assert result.status == ContentStatus.FULL_TEXT
    assert result.text == "The service will resume on Monday, with the existing terms unchanged."


def test_inline_words_chinese_and_table_spans_survive_extraction():
    result = extract_document(BeautifulSoup(
        "<article><p>价格为<strong>10</strong>元；un<strong>changed</strong> terms remain.</p>"
        "<table><tr><th colspan='2'>Monthly price</th></tr>"
        "<tr><td>Plan A</td><td>10 USD</td></tr></table></article>", "html.parser",
    ), ["article"])
    assert "价格为10元；unchanged terms remain." in result.text
    assert result.blocks[-1]["rows"][0][0]["colspan"] == "2"


def test_nested_list_paragraphs_quotes_and_preformatted_text_keep_structure():
    result = extract_document(BeautifulSoup(
        "<article><ol><li><p>First ordered condition remains applicable.</p>"
        "<ul><li>A nested exception.</li></ul></li></ol>"
        "<blockquote><p>The source explicitly states this qualification.</p></blockquote>"
        "<pre>if ready:\n    publish()\n</pre></article>", "html.parser",
    ), ["article"])
    assert result.blocks[0]["type"] == "list_item"
    assert result.blocks[0]["ordered"] is True
    assert result.blocks[1]["list_depth"] == 2
    assert result.blocks[2]["type"] == "quote"
    assert result.blocks[3]["text"] == "if ready:\n    publish()\n"


def test_browser_and_static_paths_use_the_same_short_article_rule():
    markup = (
        "<body><article><p>The official announcement takes effect tomorrow at noon.</p>"
        "<p>Existing subscriptions retain the agreed price until renewal.</p></article>"
        + "Other news " * 400 + "</body>"
    )

    class PageSnapshot:
        def locator(self, _selector):
            return self

        async def evaluate_all(self, _script):
            pass

        async def content(self):
            return markup

    result = extract_document(BeautifulSoup(markup, "html.parser"), ["article"])
    text, selector = asyncio.run(extract_visible_text(PageSnapshot(), ["article"]))
    assert (text, selector) == (result.text, "article")
    assert "Other news" not in text


def test_http_byte_limit_records_partial_content(monkeypatch, tmp_path):
    from signaltrail import content

    config = load_config()
    item = _item()
    original_read = content._read_bounded_html

    async def bounded(response):
        return await original_read(response, max_bytes=1800)

    monkeypatch.setattr(content, "_read_bounded_html", bounded)
    transport = httpx.MockTransport(lambda _: httpx.Response(
        200, text="<article>" + "Official document paragraph. " * 200 + "</article>",
    ))
    asyncio.run(_run_http_extraction([item], config, tmp_path, transport=transport))
    assert item["content_status"] == ContentStatus.PARTIAL
    assert item["metadata"]["content_quality"]["response_truncated"] is True


def test_image_selection_uses_article_caption_before_unrelated_metadata(tmp_path):
    config = load_config()
    item = _item()
    item["title"] = "Orion reactor begins operation"
    markup = (
        "<head><meta property='og:image' content='/generic-brand.jpg'></head><body>"
        "<article><p>Orion reactor began operation on Monday after commissioning tests.</p>"
        "<img src='/brand.jpg' alt='Company logo'>"
        "<figure><img src='/small.jpg' srcset='/large.jpg 1600w, /small.jpg 400w' "
        "alt='Orion reactor'><figcaption>Orion reactor commissioning test.</figcaption></figure>"
        "<aside><img src='/unrelated.jpg'></aside></article></body>"
    )
    _apply_http_document(
        item, config.source_by_id(item["source_id"]), markup, item["url"], 200,
        config, tmp_path,
    )
    assert item["image_url"] == "https://www.bbc.com/large.jpg"
    details = item["metadata"]["image_candidate_details"]
    assert details[0]["caption"] == "Orion reactor commissioning test."
    assert details[0]["provenance"] == "article_body"
    assert details[0]["relevance_score"] > 0
    assert details[0]["semantic_verification"] == "not_performed"
    assert next(row for row in details if row["url"].endswith("/small.jpg"))["caption"] == (
        "Orion reactor commissioning test."
    )
    metadata_image = next(row for row in details if row["url"].endswith("/generic-brand.jpg"))
    assert metadata_image["caption"] == ""
    assert not any(entry["url"].endswith(("/brand.jpg", "/unrelated.jpg")) for entry in details)


def test_picture_sources_choose_highest_effective_pixel_width_first(tmp_path):
    config = load_config()
    item = _item()
    markup = (
        "<article><p>The leaders arrived for a bilateral summit on Wednesday.</p>"
        "<figure><picture>"
        "<source srcset='/img/master.jpg?width=620&amp;dpr=2' media='large-retina'>"
        "<source srcset='/img/master.jpg?width=700&amp;dpr=2' media='tablet-retina'>"
        "<source srcset='/img/master.jpg?width=465&amp;dpr=1' media='mobile'>"
        "<img src='/img/master.jpg?width=465&amp;dpr=1' alt='Summit arrival'>"
        "</picture><figcaption>Leaders arrive for the summit.</figcaption></figure></article>"
    )
    _apply_http_document(
        item, config.source_by_id(item["source_id"]), markup, item["url"], 200,
        config, tmp_path,
    )

    details = item["metadata"]["image_candidate_details"]
    assert details[0]["url"] == "https://www.bbc.com/img/master.jpg?width=700&dpr=2"
    assert details[0]["variant"] == 0
    assert details[0]["caption"] == "Leaders arrive for the summit."


def test_article_images_exclude_games_promotions_and_recommended_cards(tmp_path):
    config = load_config()
    item = _item()
    markup = (
        "<article class='node node--article-content'>"
        "<section class='block detail-hero-media'><figure class='figure block'>"
        "<img src='/hero.jpg' alt='Australia says OpenAI agent hacked into a government website'>"
        "<figcaption>Prime Minister Anthony Albanese speaks to reporters.</figcaption>"
        "</figure></section>"
        "<div class='text-long'>"
        "<p>Australia said an OpenAI agent reached a public government portal.</p>"
        "<div class='in-article-games trimmed-content'><div class='game-list'>"
        "<a class='game-tile'><div class='game-img'>"
        "<img src='/game-wordrow.png' alt='Guess Word' width='100' height='100'>"
        "</div></a></div></div>"
        "<div class='referenced-card'><div class='media-object'>"
        "<div class='media-object__figure'><a class='link'>"
        "<img src='/recommended.jpg' alt='' width='747' height='598'>"
        "</a></div></div></div>"
        "<section class='block-type--subscription_cta_block widget-subscription'>"
        "<div class='widget-subscription__cta'>"
        "<img src='/inbox-large.png' alt='Inbox'></div></section>"
        "<section class='block-type--subscription_cta_block get-app'>"
        "<div class='get-app__cta'><img src='/get-app.png' alt='App-get'></div></section>"
        "<section class='block-type--subscription_cta_block whatsapp-group'>"
        "<div class='whatsapp-group__cta'><img src='/whatsapp.png' alt='Whatsapp'></div></section>"
        "<figure class='game-analysis'><img src='/game-analysis.jpg' "
        "alt='The game analysis in the article'></figure>"
        "<p>Officials said no restricted files were published.</p>"
        "</div></article>"
    )
    _apply_http_document(
        item, config.source_by_id(item["source_id"]), markup, item["url"], 200,
        config, tmp_path,
    )

    details = item["metadata"]["image_candidate_details"]
    assert [entry["url"] for entry in details] == [
        "https://www.bbc.com/hero.jpg",
        "https://www.bbc.com/game-analysis.jpg",
    ]
    assert details[0]["caption"] == "Prime Minister Anthony Albanese speaks to reporters."


def test_article_images_exclude_publisher_sidebar_and_recommendation_widgets(tmp_path):
    config = load_config()
    item = _item("aviationist-like")
    item["source_id"] = "the_aviationist"
    item["source_name"] = "The Aviationist"
    item["url"] = "https://theaviationist.com/2026/09/26/example-story/"
    markup = (
        "<article class='mv-content-wrapper'>"
        "<div class='entry-content'><p>" + "A substantive story paragraph. " * 8 + "</p>"
        "<figure><img src='/story.jpg' alt='Story aircraft'>"
        "<figcaption>Aircraft in the story.</figcaption></figure></div>"
        "<div class='block-wrap'><figure><img src='/body-callout.jpg' "
        "alt='Body callout image'></figure></div>"
        "<div class='entry-pagination'><img src='/previous-story.jpg' alt='Previous story'></div>"
        "<div class='block-wrap block-list'><div class='p-wrap'>"
        "<img src='/recommended-story.jpg' alt='Recommended story'></div></div>"
        "<div class='author-wrapper meta-avatar'><img src='/author-avatar.jpg' alt=''></div>"
        "<div class='sidebar-wrap single-sidebar'><div id='media_image-6' "
        "class='widget rb-section widget_media_image'>"
        "<h4>Work With Us</h4><a href='/work-with-us/'>"
        "<img src='/work-with-us.png' alt=''></a></div></div>"
        "</article>"
    )
    source = config.source_by_id(item["source_id"])
    _apply_http_document(
        item, source, markup, item["url"], 200, config, tmp_path,
    )

    details = item["metadata"]["image_candidate_details"]
    assert [row["url"] for row in details] == [
        "https://theaviationist.com/story.jpg",
        "https://theaviationist.com/body-callout.jpg",
    ]
    assert details[0]["caption"] == "Aircraft in the story."


def test_main_page_keeps_post_media_figures_and_excludes_archive_recommendations():
    body_images = "".join(
        f'<figure class="post-body"><img src="/figures/body-{index}.jpg" '
        f'alt="Article image {index}"><figcaption>Article figure {index}.</figcaption></figure>'
        for index in range(6)
    )
    archive_cards = "".join(
        f'<article class="archive-post"><div class="archive-image"><a class="link">'
        f'<img src="/recommendations/recommend-{index}.jpg" alt="Related story">'
        f'</a></div></article>'
        for index in range(3)
    )
    markup = (
        "<html><body><main><article class='task-brief'><p>"
        + "A short task card can be selected ahead of this project page. " * 12
        + "</p></article><div class='post-main'><div class='post-media'>"
        + "<div class='post-body'><p>" + "The article body describes vending machines. " * 8
        + "</p>" + body_images + "</div></div></div><div class='wrapper'>"
        + archive_cards + "</div></main></body></html>"
    )
    document = extract_document(
        BeautifulSoup(markup, "html.parser"), [], expected_title="vending machines",
    )

    candidates = article_image_candidates(
        document, "vending machines", "https://news.example/story/",
    )

    assert {row["url"] for row in candidates} == {
        f"https://news.example/figures/body-{index}.jpg" for index in range(6)
    }


def test_yahoo_brand_card_in_header_is_excluded_without_dropping_story_images():
    markup = BeautifulSoup('''<html><body><article>
      <header><a href="https://profiles.yahoo.com/brands/bbc/">
        <img src="https://s.yimg.com/rz/p/yahoo_bbc_logo.png" width="487" height="100"
             alt="BBC"></a>
        <figure><a href="/hero.jpg"><img src="/hero.jpg" alt="Story hero"></a></figure>
      </header>
      <p>Story title and details. The body contains another relevant image.</p>
      <figure><img src="/body-small.jpg" width="40" height="40" alt="Story detail"></figure>
    </article></body></html>''', "html.parser")
    document = extract_document(markup, [], expected_title="Story title and details")

    candidates = article_image_candidates(
        document, "Story title and details", "https://news.example/story/",
    )

    assert {row["url"] for row in candidates} == {
        "https://news.example/hero.jpg", "https://news.example/body-small.jpg",
    }


def test_sina_visitor_page_is_classified_as_access_challenge():
    result = classify_access_text(200, "Sina Visitor System", "")

    assert result["required"] is True
    assert result["matched_text"] == "sina visitor system"


def test_github_blob_link_keeps_explicit_raw_image_src():
    markup = (
        "<article><p>Imp is a full port of DSPy to the BEAM. "
        "The library provides modules, optimizers, agent loops and retrieval.</p>"
        '<a href="/deepfates/imp/blob/main/assets/imp-with-cards.jpg">'
        '<img src="/deepfates/imp/raw/main/assets/imp-with-cards.jpg" width="300" '
        'alt="An imp studies a hand of cards through a lens."></a></article>'
    )
    document = extract_document(BeautifulSoup(markup, "html.parser"), [])

    candidates = article_image_candidates(
        document, "Imp DSPy port to BEAM", "https://github.com/deepfates/imp",
    )

    assert [candidate["url"] for candidate in candidates] == [
        "https://github.com/deepfates/imp/raw/main/assets/imp-with-cards.jpg",
    ]


@pytest.mark.parametrize(("region", "closing", "selector", "image", "expected_url"), [
    ('<div class="article">', "</div>", "div.article", "../../../notes/2026/09/27/moon.svg",
     "https://news.example/notes/2026/09/27/moon.svg"),
    ('<div id="blogpage"><div class="content">', "</div></div>", "#blogpage .content",
     "mads-talk.png", "https://news.example/story/mads-talk.png"),
])
def test_semantic_article_divs_are_specific_image_regions(region, closing, selector, image,
                                                          expected_url):
    markup = (region + "<p>The article explains its main technical argument. "
              "It includes details and a summary of the evidence presented on the page.</p>"
              f'<figure><img src="{image}" alt="Article illustration"></figure>{closing}')
    document = extract_document(BeautifulSoup(markup, "html.parser"), [])

    candidates = article_image_candidates(
        document, "article technical argument", "https://news.example/story/index.html",
    )

    assert document.selector == selector
    assert document.quality["region"] == "specific"
    assert [candidate["url"] for candidate in candidates] == [expected_url]


def test_article_images_exclude_explicit_rss_feed_controls():
    markup = (
        '<div class="article"><p>The article explains the technical change and its result. '
        "It includes the full story and what readers should expect next.</p>"
        '<img src="/images/story.jpg" alt="Project result">'
        '<a href="/rss"><img src="/blog/feed.svg" alt="RSS feed" height="35"></a>'
        '<a href="/atom"><img src="/blog/atom-feed.svg" alt="RSS feed" height="35"></a>'
        "</div>"
    )
    document = extract_document(BeautifulSoup(markup, "html.parser"), [])

    candidates = article_image_candidates(
        document, "technical change", "https://news.example/story",
    )

    assert [candidate["url"] for candidate in candidates] == [
        "https://news.example/images/story.jpg",
    ]


def test_article_image_scan_continues_past_early_promotions(tmp_path):
    config = load_config()
    item = _item()
    games = "".join(f"<img src='/game-{index}.png'>" for index in range(26))
    markup = (
        "<article><p>The report describes a security incident at a government portal.</p>"
        f"<div class='in-article-games'>{games}</div>"
        "<figure><img src='/late-article-photo.jpg' alt='Government portal'>"
        "<figcaption>Officials discuss the portal.</figcaption></figure></article>"
    )
    _apply_http_document(
        item, config.source_by_id(item["source_id"]), markup, item["url"], 200,
        config, tmp_path,
    )

    details = item["metadata"]["image_candidate_details"]
    assert [entry["url"] for entry in details] == [
        "https://www.bbc.com/late-article-photo.jpg",
    ]


def test_loaded_image_src_precedes_relative_lazy_path_and_figure_caption_is_kept(tmp_path):
    config = load_config()
    item = _item()
    markup = (
        "<article><p>A sufficiently detailed article body about a public announcement.</p>"
        "<p><img data-src='articles/example/en/resources/figure.jpg' "
        "src='https://imgopt.example/fit/figure.jpg'></p>"
        "<p><small><strong>Figure 1. Architecture overview (Source: author).</strong>"
        "</small></p>"
        "<p><img src='/image/transparent.png' data-src='/real-image.jpg'></p>"
        "<p>This nearby paragraph explains the article and is not a figure caption.</p>"
        "<p><img src='/first-unlabeled.jpg'></p>"
        "<p><img src='/second-figure.jpg'></p>"
        "<p>Figure 2. The second image only.</p>"
        "</article>"
    )
    _apply_http_document(
        item, config.source_by_id(item["source_id"]), markup, item["url"], 200,
        config, tmp_path,
    )

    details = item["metadata"]["image_candidate_details"]
    first = next(row for row in details if row.get("position") == 0)
    second = next(row for row in details if row.get("position") == 1)
    assert first["url"] == "https://imgopt.example/fit/figure.jpg"
    assert first["caption"] == "Figure 1. Architecture overview (Source: author)."
    assert second["url"] == "https://www.bbc.com/real-image.jpg"
    assert second["caption"] == ""
    later = [row for row in details if row.get("position") in (2, 3)]
    assert next(row for row in later if row["position"] == 2)["caption"] == ""
    assert next(row for row in later if row["position"] == 3)["caption"] == (
        "Figure 2. The second image only."
    )


@pytest.mark.parametrize("figure", [
    "<figure><img src='/photo.jpg'><figcaption>{caption}</figcaption></figure>",
    "<div class='wp-caption'><a><img src='/photo.jpg'></a>"
    "<p class='wp-caption-text'>{caption}</p></div>",
    "<div><picture><img data-src='/photo.jpg'></picture>"
    "<span class='image-caption'>{caption}</span></div>",
    "<div><img src='/photo.jpg'><span itemprop='caption'>{caption}</span></div>",
])
def test_article_image_captions_preserve_publisher_text(tmp_path, figure):
    config = load_config()
    item = _item()
    markup = (
        "<article><p>The publisher describes the commissioning of a new reactor.</p>"
        + figure.format(
            caption="  反应堆<strong>调试</strong>现场 &amp; control room.\n 摄影：李明。 "
        )
        + "</article>"
    )
    _apply_http_document(
        item, config.source_by_id(item["source_id"]), markup, item["url"], 200,
        config, tmp_path,
    )
    details = item["metadata"]["image_candidate_details"]
    assert details[0]["caption"] == "反应堆调试现场 & control room. 摄影：李明。"
    index = {"items": [item], "sources": [{"items": [{"item_id": item["item_id"]}]}]}
    synchronize_nested_items(index)
    assert index["sources"][0]["items"][0]["metadata"]["image_candidate_details"] == details


def test_missing_caption_never_uses_alt_title_or_a_neighboring_figure(tmp_path):
    config = load_config()
    item = _item()
    markup = (
        "<article><p>The publisher describes the commissioning of a new reactor.</p>"
        "<figure><img src='/first.jpg'><figcaption>First photo only.</figcaption></figure>"
        "<figure><img src='/second.jpg' alt='An accessible description' "
        "title='A tooltip'></figure><p>A nearby paragraph is not a caption.</p></article>"
    )
    _apply_http_document(
        item, config.source_by_id(item["source_id"]), markup, item["url"], 200,
        config, tmp_path,
    )
    captions = {
        row["url"]: row["caption"] for row in item["metadata"]["image_candidate_details"]
    }
    assert captions == {
        "https://www.bbc.com/first.jpg": "First photo only.",
        "https://www.bbc.com/second.jpg": "",
    }


def test_single_article_image_never_borrows_quote_attribution(tmp_path):
    config = load_config()
    item = _item()
    markup = (
        "<article><p>The publisher describes the new cache performance dashboard.</p>"
        "<div><div><img src='/dashboard.png'></div>"
        "<blockquote><p>Our costs have fallen significantly with prompt caching.</p>"
        "<span class='caption'>—Mario Rodriguez, Chief Product Officer</span>"
        "</blockquote></div></article>"
    )
    _apply_http_document(
        item, config.source_by_id(item['source_id']), markup, item['url'], 200,
        config, tmp_path,
    )
    assert item['metadata']['image_candidate_details'][0]['caption'] == ''


def test_article_images_prefer_explicit_full_size_link(tmp_path):
    config = load_config()
    item = _item()
    markup = (
        "<article><p>The official report shows the latest aircraft test flight.</p>"
        "<figure><a href='/full-aircraft.jpg'><img src='/aircraft-706x400.jpg'></a>"
        "<figcaption>Aircraft during its flight test.</figcaption></figure>"
        "<a href='/another-story'><img src='/second.jpg'></a></article>"
    )
    _apply_http_document(
        item, config.source_by_id(item['source_id']), markup, item['url'], 200,
        config, tmp_path,
    )
    details = item['metadata']['image_candidate_details']
    first = next(row for row in details if row.get('position') == 0)
    assert first['url'] == 'https://www.bbc.com/full-aircraft.jpg'
    assert first['caption'] == 'Aircraft during its flight test.'
    assert not any(row['url'].endswith('/another-story') for row in details)


def test_repeated_extraction_never_overwrites_prior_body_or_blocks(tmp_path):
    config = load_config()
    item = _item()
    source = config.source_by_id(item["source_id"])
    first = "<article><p>The official announcement takes effect on Monday.</p></article>"
    _apply_http_document(item, source, first, item["url"], 200, config, tmp_path)
    path = Path(item["content_path"])
    content = path.read_bytes()
    _apply_http_document(item, source, first.replace("Monday", "Tuesday"), item["url"], 200,
                         config, tmp_path)
    assert Path(item["content_path"]) != path
    assert path.read_bytes() == content
    assert path.with_suffix(".json").exists()


def test_unlabeled_article_image_does_not_displace_publisher_metadata(tmp_path):
    config = load_config()
    item = _item()
    markup = (
        "<head><meta property='og:image' content='/publisher.jpg'></head>"
        "<article><p>Official announcement about new reactor commissioning dates.</p>"
        "<img src='/unlabeled.jpg'></article>"
    )
    _apply_http_document(
        item, config.source_by_id(item["source_id"]), markup, item["url"], 200,
        config, tmp_path,
    )
    assert item["image_url"] == "https://www.bbc.com/publisher.jpg"


@pytest.mark.parametrize(("http_status", "expected"), [
    (403, ContentStatus.VERIFICATION_REQUIRED),
    (429, ContentStatus.VERIFICATION_REQUIRED),
    (500, ContentStatus.FAILED),
])
def test_non_html_error_response_keeps_access_failure(tmp_path, http_status, expected):
    item = _item()
    transport = httpx.MockTransport(lambda _: httpx.Response(http_status, json={"error": "failed"}))
    fallback = asyncio.run(
        _run_http_extraction([item], load_config(), tmp_path, transport=transport),
    )
    assert fallback == []
    assert item["content_status"] == expected


def _item(item_id: str = "bbc-static") -> dict:
    return {
        "item_id": item_id,
        "source_id": "bbc_world",
        "source_name": "BBC",
        "title": "Original public headline",
        "url": f"https://www.bbc.com/news/articles/{item_id}",
        "content_status": ContentStatus.NOT_FETCHED,
        "metadata": {},
    }


def test_http_first_content_extraction_avoids_browser_for_static_article(
    tmp_path: Path,
):
    config = load_config()
    item = _item()
    article_text = " ".join(["verified public article detail"] * 180)
    document = (
        "<html><head>"
        '<meta property="og:title" content="Updated public headline">'
        '<meta property="article:published_time" content="2026-07-24T08:00:00Z">'
        '<meta property="og:image" content="/image/grey-placeholder.png">'
        '<meta name="twitter:image" content="/image/story.png">'
        "</head><body><article>"
        f"{article_text}"
        "</article></body></html>"
    )
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            content=document.encode(),
            headers={"Content-Type": "text/html; charset=utf-8"},
        )
    )

    browser_targets = asyncio.run(
        _run_http_extraction(
            [item],
            config,
            tmp_path,
            transport=transport,
        )
    )

    assert browser_targets == []
    assert item["content_status"] == ContentStatus.FULL_TEXT
    assert item["metadata"]["content_acquisition"] == "http"
    assert item["published_at"] == "2026-07-24T08:00:00Z"
    assert item["image_url"] == "https://www.bbc.com/image/story.png"
    assert Path(item["content_path"]).is_file()


@pytest.mark.parametrize(("role", "expected_index_date"), [
    ("discovery", "2026-09-27T02:22:41+08:00"),
    (None, "2026-09-19T12:20:26Z"),
])
def test_original_page_date_does_not_replace_discovery_posted_date(
    tmp_path: Path, role: str | None, expected_index_date: str,
):
    config = load_config()
    item = _item("hacker-news-post")
    item["published_at"] = "2026-09-27T02:22:41+08:00"
    if role:
        item["metadata"]["role"] = role
    article_text = " ".join(["The paper describes its original systems research"] * 40)
    markup = (
        '<html><head><meta property="article:published_time" '
        'content="2026-09-19T12:20:26Z"></head><body><article>'
        f"<p>{article_text}</p></article></body></html>"
    )

    _apply_http_document(
        item, config.source_by_id(item["source_id"]), markup, item["url"], 200,
        config, tmp_path,
    )

    assert item["published_at"] == expected_index_date
    assert item["metadata"]["content_source"]["published_at"] == (
        "2026-09-19T12:20:26Z"
    )


def test_generic_page_time_does_not_replace_direct_source_publication_date(tmp_path: Path):
    config = load_config()
    item = _item("direct-source")
    item["published_at"] = "2026-09-27T08:00:00Z"
    article_text = " ".join(["The source article has useful public details"] * 40)
    markup = (
        "<html><body><time datetime='2026-09-28T08:00:00Z'>Updated</time>"
        f"<article><p>{article_text}</p></article></body></html>"
    )

    _apply_http_document(
        item, config.source_by_id(item["source_id"]), markup, item["url"], 200,
        config, tmp_path,
    )

    assert item["published_at"] == "2026-09-27T08:00:00Z"
    assert item["metadata"]["content_source"]["published_at"] is None


def test_http_first_content_extraction_uses_browser_only_for_javascript_shell(
    tmp_path: Path,
):
    config = load_config()
    item = _item("bbc-js-shell")
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            text="<html><body><main id='app'>Loading</main></body></html>",
            headers={"Content-Type": "text/html"},
        )
    )

    browser_targets = asyncio.run(
        _run_http_extraction(
            [item],
            config,
            tmp_path,
            transport=transport,
        )
    )

    assert browser_targets == [item]
    assert item["content_status"] == ContentStatus.METADATA_ONLY


def test_http_access_failure_stays_verification_required_without_browser_retry(
    tmp_path: Path,
):
    config = load_config()
    item = _item("bbc-forbidden")
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            403,
            text="<html><title>Access denied</title></html>",
            headers={"Content-Type": "text/html"},
        )
    )

    browser_targets = asyncio.run(
        _run_http_extraction(
            [item],
            config,
            tmp_path,
            transport=transport,
        )
    )

    assert browser_targets == []
    assert item["content_status"] == ContentStatus.VERIFICATION_REQUIRED
    assert item["metadata"]["content_challenge"]["required"] is True


def test_content_pipeline_reuses_existing_successful_content(monkeypatch, tmp_path: Path):
    config = load_config()
    content_path = tmp_path / "content" / "bbc_world" / "cached" / "body.md"
    content_path.parent.mkdir(parents=True)
    content_path.write_text("cached article", encoding="utf-8")
    item = _item("cached")
    item.update(
        {
            "content_status": ContentStatus.FULL_TEXT,
            "content_path": str(content_path),
        }
    )

    async def unexpected_http(*_args, **_kwargs):
        raise AssertionError("HTTP must not run for reusable content")

    async def unexpected_browser(*_args, **_kwargs):
        raise AssertionError("browser must not run for reusable content")

    monkeypatch.setattr(
        "signaltrail.content._run_http_extraction",
        unexpected_http,
    )
    monkeypatch.setattr(
        "signaltrail.content._extract_with_browser",
        unexpected_browser,
    )

    metrics = asyncio.run(
        _extract_pipeline(
            [item],
            config,
            tmp_path,
            False,
            tmp_path / "profile",
            None,
        )
    )

    assert metrics["cache_hits"] == 1
    assert metrics["http_attempted"] == 0
    assert metrics["browser_fallback"] == 0
    assert item["metadata"]["content_acquisition"] == "cache"


def test_enriched_root_items_are_mirrored_to_legacy_nested_items():
    payload = {
        "items": [
            {
                "item_id": "item-1",
                "content_status": "full_text",
                "content_path": "content/item-1.md",
            }
        ],
        "sources": [
            {
                "source_id": "source-1",
                "items": [{"item_id": "item-1", "content_status": "not_fetched"}],
            }
        ],
    }

    synchronize_nested_items(payload)

    nested = payload["sources"][0]["items"][0]
    assert nested == payload["items"][0]
    assert nested["content_status"] == "full_text"



def test_enrichment_targets_follow_importance_order_and_hard_limit():
    items = [
        {"item_id": "low"},
        {"item_id": "high"},
        {"item_id": "medium"},
    ]

    targets = _ordered_targets(
        items,
        ["high", "medium", "high", "missing", "low"],
        max_items=2,
    )

    assert [item["item_id"] for item in targets] == ["high", "medium"]



def test_enrichment_is_parallel_across_domains_and_serial_within_domain(
    monkeypatch, tmp_path: Path
):
    config = load_config()
    config.browser.global_concurrency = 2
    config.browser.per_domain_concurrency = 1
    active = 0
    maximum_active = 0
    active_by_domain: dict[str, int] = defaultdict(int)
    maximum_by_domain: dict[str, int] = defaultdict(int)

    async def fake_extract_one(_context, item, _config, _data_dir):
        nonlocal active, maximum_active
        domain = item["url"].split("/")[2]
        active += 1
        active_by_domain[domain] += 1
        maximum_active = max(maximum_active, active)
        maximum_by_domain[domain] = max(
            maximum_by_domain[domain], active_by_domain[domain]
        )
        await asyncio.sleep(0.02)
        active_by_domain[domain] -= 1
        active -= 1

    monkeypatch.setattr("signaltrail.content._extract_one", fake_extract_one)
    targets = [
        {"item_id": "a1", "url": "https://a.example/1"},
        {"item_id": "a2", "url": "https://a.example/2"},
        {"item_id": "b1", "url": "https://b.example/1"},
        {"item_id": "c1", "url": "https://c.example/1"},
    ]

    asyncio.run(_run_parallel_extraction(object(), targets, config, tmp_path))

    assert maximum_active == 2
    assert maximum_by_domain["a.example"] == 1
