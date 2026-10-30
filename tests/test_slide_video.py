import json
import wave
from pathlib import Path

import pytest
from PIL import Image

from signaltrail import slide_video, video_runtime


def test_page_cache_reuses_pages_after_reorder_and_invalidates_changed_image(monkeypatch, tmp_path):
    import playwright.sync_api

    spoken = []

    class Voice:
        provider = "cpu"
        fallback_reason = None
        profile = {"name": "test"}
        reference = None
        engine = "test"
        generated = hits = page_hits = 0

        def __init__(self, *args, **kwargs):
            pass

        def page(self, title, brief, destination, **kwargs):
            spoken.append((title, brief))
            with wave.open(str(destination), "wb") as audio:
                audio.setparams((1, 2, 1000, 0, "NONE", "not compressed"))
                audio.writeframes(b"\0\0" * 1000)
            return {"duration": 1, "provider": "cpu"}

    evaluations = []
    viewports = []

    class Page:
        def route(self, *args):
            pass

        def goto(self, *args, **kwargs):
            pass

        def evaluate(self, *args):
            evaluations.append(args)

        def wait_for_timeout(self, _milliseconds):
            pass

        def screenshot(self, *, path):
            Path(path).write_bytes(b"frame")

    class Browser:
        def new_page(self, **kwargs):
            viewports.append(kwargs)
            return Page()

        def close(self):
            pass

    class Chromium:
        executable_path = "browser"

        def launch(self, **kwargs):
            return Browser()

    class Playwright:
        chromium = Chromium()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(slide_video, "VoiceSynthesizer", Voice)
    monkeypatch.setattr(
        video_runtime,
        "ensure_video_runtime",
        lambda *a, **k: {"ffmpeg": "ffmpeg", "model_dir": tmp_path},
    )
    monkeypatch.setattr(video_runtime, "_ensure_browser", lambda *a, **k: None)
    monkeypatch.setattr(playwright.sync_api, "sync_playwright", Playwright)
    monkeypatch.setattr(slide_video, "_run", lambda cmd: Path(cmd[-1]).write_bytes(b"video"))
    (tmp_path / "media/images").mkdir(parents=True)
    for name, color in (("a", "red"), ("b", "blue")):
        Image.new("RGB", (20, 10), color).save(tmp_path / f"media/images/{name}.png")
    slides = [
        {
            "event_id": name,
            "title": name,
            "video_tldr": f"Short model script {name}",
            "summary": f"Original summary {name}",
            "narration": f"Original explanation {name}",
            "images": [{"local_path": f"media/images/{name}.png"}],
        }
        for name in ("a", "b")
    ]
    deck_path = tmp_path / "deck.json"
    output = tmp_path / "result.mp4"

    def run():
        from signaltrail.slide_renderer import render_slides_html

        deck = {"language": "en", "slides": slides}
        deck_path.write_text(json.dumps(deck), encoding="utf-8")
        deck_path.with_suffix(".html").write_text(
            render_slides_html(deck, tmp_path), encoding="utf-8"
        )
        return slide_video.render_video(deck_path, output, None, tmp_path)

    first = run()
    assert first["source_slides_html"] == str(deck_path.with_suffix(".html"))
    assert first["video_zoom"] == 1.4
    assert viewports[0] == {
        "viewport": {"width": 1371, "height": 771},
        "device_scale_factor": 1.4005,
    }
    assert spoken[:2] == [
        ("a", "Short model script a"),
        ("b", "Short model script b"),
    ]
    original_html = deck_path.with_suffix(".html").read_text(encoding="utf-8")
    assert "Original summary a" in original_html and "Original explanation a" in original_html
    assert (first["pages_rendered"], first["page_clips_generated"]) == (2, 2)
    second = run()
    assert (second["pages_rendered"], second["page_clips_reused"]) == (0, 2)
    Image.new("RGB", (20, 10), "green").save(tmp_path / "media/images/a.png")
    changed = run()
    assert (
        changed["pages_rendered"],
        changed["page_clips_generated"],
        changed["page_clips_reused"],
    ) == (2, 2, 0)
    slides.reverse()
    reordered = run()
    assert (reordered["pages_rendered"], reordered["page_clips_reused"]) == (2, 0)
    timeline = json.loads(Path(reordered["timeline_path"]).read_text(encoding="utf-8"))
    assert [(x["event_id"], x["start"]) for x in timeline] == [("b", 0), ("a", 1)]
    slides[0].pop("video_tldr")
    count = len(spoken)
    with pytest.raises(ValueError, match="model read the full narration"):
        run()
    assert len(spoken) == count


def test_template_filter_preserves_standalone_chart_and_old_illustration():
    from signaltrail.image_policy import filter_editorial_templates

    base = "https://imgcdn.yicai.com/uppics/images/2019/10/"
    images = [
        {"url": base + "banner1.png", "width": 500, "height": 87},
        {"url": base + "banner2.png", "width": 500, "height": 87},
        {"url": base + "chart.png", "width": 500, "height": 87, "caption": "Figure 1"},
        {"url": base + "photo.png", "width": 800, "height": 600},
        {"url": "https://www.yicai.com/img/article_lock_left.123.png"},
    ]
    assert [x["url"] for x in filter_editorial_templates(images)] == [
        base + "chart.png",
        base + "photo.png",
    ]
