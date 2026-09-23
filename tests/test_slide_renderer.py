from bs4 import BeautifulSoup

import daily_intelligence.slide_renderer as renderer
from daily_intelligence.slide_renderer import render_slides_html


def _deck() -> dict:
    return {
        "title": "新闻图文流",
        "language": "zh-CN",
        "as_of": "2026-09-23",
        "report_id": "edition-1",
        "slides": [
            {
                "event_id": "event-1",
                "title": "第一条新闻",
                "summary": "摘要内容",
                "narration": "第一段讲解。\n\n第二段讲解。",
                "perspectives": ["只供审阅"],
                "sources": [
                    {
                        "name": "来源",
                        "title": "原始报道",
                        "url": "https://news.example/a",
                        "published_at": "今日",
                        "access": "full_text",
                    }
                ],
                "images": [
                    {
                        "url": "https://images.example/a.jpg",
                        "caption": None,
                        "alt": "不得代替图注",
                        "credit": "摄影者",
                        "source_url": "https://news.example/a",
                    },
                    {
                        "url": "javascript:alert(1)",
                        "caption": "现场原图注",
                        "alt": "alt",
                        "credit": "",
                        "source_url": "",
                    },
                ],
            },
            {
                "event_id": "event-2",
                "title": "第二条新闻",
                "summary": "<script>bad()</script>",
                "narration": "讲解",
                "sources": [],
                "images": [],
            },
        ],
    }


def test_slides_include_story_content_controls_and_safe_image_caption_semantics():
    rendered = render_slides_html(_deck())
    soup = BeautifulSoup(rendered, "html.parser")

    assert len(soup.select("article.slide")) == 2
    assert len(soup.select(".toc-item")) == 2
    assert soup.select_one("[data-next]") and soup.select_one("[data-prev]")
    assert soup.select_one("[data-fullscreen]")
    assert soup.select_one(".image-frame img")["src"] == "https://images.example/a.jpg"
    assert soup.select_one(".image-frame img.broken") is None
    assert soup.select_one(".gallery figure:first-of-type figcaption") is None
    assert soup.select_one(".gallery figure:first-of-type img")["alt"] == "不得代替图注"
    assert "现场原图注" in soup.select_one(".gallery").get_text()
    assert 'src="javascript:' not in rendered
    assert "<script>bad()</script>" not in rendered
    assert "&lt;script&gt;bad()&lt;/script&gt;" in rendered
    assert "只供审阅" not in rendered
    assert "正文" in rendered and "full_text" not in rendered
    assert 'aria-label="上一张图片"' in rendered
    assert 'aria-label="下一张图片"' in rendered
    assert "prefers-reduced-motion" in rendered
    assert "data-image-next" in rendered


def test_renderer_escapes_document_title_and_handles_empty_deck():
    deck = _deck()
    deck["title"] = "<script>alert(1)</script>"
    deck["slides"] = []
    rendered = render_slides_html(deck)
    soup = BeautifulSoup(rendered, "html.parser")

    assert "<script>alert(1)</script>" not in rendered
    assert soup.title.get_text() == "<script>alert(1)</script>"
    assert soup.select_one(".empty")
    assert "JavaScript" in rendered


def test_renderer_uses_package_assets_as_a_complete_document():
    rendered = render_slides_html(_deck())

    assert "<style>" in rendered and "@media print" in rendered
    assert "<script>(() =>" in rendered
    assert "https://" in rendered
    assert not any(asset in rendered for asset in ('src="slides.js', 'href="slides.css'))


def test_no_script_documents_keep_all_articles_and_images_accessible():
    soup = BeautifulSoup(render_slides_html(_deck()), "html.parser")

    assert all(not story.has_attr("aria-hidden") for story in soup.select("article.slide"))
    assert len(soup.select(".gallery figure")) == 2
    assert soup.select_one(".story-grid.no-gallery")


def test_one_image_has_no_navigation_controls():
    deck = _deck()
    deck["slides"][0]["images"] = deck["slides"][0]["images"][:1]
    soup = BeautifulSoup(render_slides_html(deck), "html.parser")

    assert not soup.select("[data-image-prev], [data-image-next]")


def test_local_image_is_loaded_once_per_render_and_refreshed_next_time(tmp_path, monkeypatch):
    image_path = tmp_path / "media/images/shared.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"first image")
    deck = _deck()
    for slide in deck["slides"]:
        slide["images"] = [{
            "local_path": "media/images/shared.png",
            "content_type": "image/png",
            "url": "https://images.example/shared.png",
            "caption": "原始图注",
        }]
    calls = 0
    embed = renderer._embedded_image_sources

    def count_embed(*args, **kwargs):
        nonlocal calls
        calls += 1
        return embed(*args, **kwargs)

    monkeypatch.setattr(renderer, "_embedded_image_sources", count_embed)
    first = render_slides_html(deck, tmp_path)

    assert calls == 1
    assert first.count("data:image/png;base64,") == 2
    assert "原始图注" in first
    assert "当前浏览器未启用 JavaScript" in first

    image_path.write_bytes(b"updated image")
    second = render_slides_html(deck, tmp_path)

    assert calls == 2
    assert first != second
