import json
import wave
from pathlib import Path
from threading import Event

import pytest
from PIL import Image

from signaltrail import slide_video, video_runtime


def test_page_cache_reuses_pages_after_reorder_and_invalidates_changed_image(monkeypatch, tmp_path):
    import playwright.sync_api

    spoken = []
    inferences = []
    second_speech_started = Event()
    first_page_rendered = Event()
    check_overlap = True
    fail_speech = fail_encoding = False
    closed_browsers = []

    class Voice:
        execution_mode = "oneshot"
        runtime = {}
        provider = "cpu"
        fallback_reason = None
        profile = {"name": "test"}
        reference = None
        engine = "test"
        generated = hits = page_hits = 0

        def __init__(self, *args, **kwargs):
            pass

        def close(self):
            pass

        def page(self, title, brief, destination, **kwargs):
            if fail_speech:
                raise RuntimeError("speech failed")
            spoken.append((title, brief))
            if destination.is_file():
                self.page_hits += 1
                return {"duration": 1, "provider": "cpu", "page_cache_hit": True}
            inferences.append(title)
            if check_overlap and title == "b":
                second_speech_started.set()
                assert first_page_rendered.wait(5), "Rendering did not overlap the next speech page"
            with wave.open(str(destination), "wb") as audio:
                audio.setparams((1, 2, 1000, 0, "NONE", "not compressed"))
                audio.writeframes(b"\0\0" * 1000)
            return {"duration": 1, "provider": "cpu"}

    evaluations = []
    navigations = []
    viewports = []

    class Page:
        def route(self, *args):
            pass

        def goto(self, *args, **kwargs):
            navigations.append((args, kwargs))

        def evaluate(self, *args):
            evaluations.append(args)
            return len(evaluations) == 1

        def screenshot(self, *, path, animations):
            nonlocal check_overlap
            if check_overlap:
                try:
                    assert second_speech_started.wait(5), "Speech did not prefetch the next page"
                finally:
                    first_page_rendered.set()
                    check_overlap = False
            assert animations == "disabled"
            Path(path).write_bytes(b"frame")

    class Browser:
        def new_page(self, **kwargs):
            viewports.append(kwargs)
            return Page()

        def close(self):
            closed_browsers.append(True)

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
    commands = []

    def run_command(command):
        commands.append(command)
        if fail_encoding and Path(command[-1]).parent.name == "page-cache":
            raise RuntimeError("encoding failed")
        Path(command[-1]).write_bytes(b"video")

    monkeypatch.setattr(slide_video, "_run", run_command)
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

    def run(title="AI and energy"):
        from signaltrail.slide_renderer import render_slides_html

        deck = {"language": "en", "slides": slides, "video_title": "Model chosen video title"}
        deck_path.write_text(json.dumps(deck), encoding="utf-8")
        deck_path.with_suffix(".html").write_text(
            render_slides_html(deck, tmp_path), encoding="utf-8"
        )
        return slide_video.render_video(deck_path, output, None, tmp_path, title=title)

    first = run()
    assert first["source_slides_html"] == str(deck_path.with_suffix(".html"))
    assert first["video_zoom"] == 1.4
    assert first["title"] == "AI and energy"
    assert navigations == [(
        (deck_path.with_suffix(".html").resolve().as_uri(),),
        {"wait_until": "domcontentloaded", "timeout": 120_000},
    )]
    assert evaluations[0][1] == [0, 0]
    assert "window.signaltrailPlayback.seek(s, i)" in evaluations[0][0]
    assert "30000" in evaluations[0][0]
    assert "clearTimeout(timer)" in evaluations[0][0]
    assert commands[-1][-3:-1] == ["-metadata", "title=AI and energy"]
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
    diagnostics = json.loads(Path(first["diagnostics_path"]).read_text(encoding="utf-8"))
    assert any(
        row["stage"] == "render_image" and row["result"] == "timed_out"
        and row["event_id"] == "a" and row["image"] == 1
        for row in diagnostics
    )
    inference_count, browser_count = len(inferences), len(viewports)
    second = run()
    assert (second["pages_rendered"], second["page_clips_reused"]) == (0, 2)
    assert second["tts_page_cache_hits"] == 2
    assert (len(inferences), len(viewports)) == (inference_count, browser_count)
    Image.new("RGB", (20, 10), "green").save(tmp_path / "media/images/a.png")
    changed = run()
    assert (
        changed["pages_rendered"],
        changed["page_clips_generated"],
        changed["page_clips_reused"],
    ) == (1, 1, 1)
    slides.reverse()
    reordered = run()
    assert (reordered["pages_rendered"], reordered["page_clips_reused"]) == (2, 0)
    timeline = json.loads(Path(reordered["timeline_path"]).read_text(encoding="utf-8"))
    assert [(x["event_id"], x["start"]) for x in timeline] == [("b", 0), ("a", 1)]
    assert run(title=None)["title"] == "Model chosen video title"

    slides[0]["title"] += " changed"
    fail_encoding = True
    closes = len(closed_browsers)
    with pytest.raises(RuntimeError, match="encoding failed"):
        run()
    assert len(closed_browsers) == closes + 1
    fail_encoding = False
    assert run()["page_clips_generated"] == 2

    fail_speech = True
    with pytest.raises(RuntimeError, match="speech failed"):
        run()
    fail_speech = False
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
