"""通过固定的 50 条材料评估图文准备、提交、渲染与复用。"""

from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from bs4 import BeautifulSoup
from PIL import Image, ImageDraw

from signaltrail.config import MediaConfig
from signaltrail.image_policy import image_variant_groups, normalize_image_candidates
from signaltrail.narrative_store import ArtifactReader, digest, load_artifact, save_artifact
from signaltrail.news_slides import (
    _source_image_candidates,
    prepare_slides,
    render_slides,
    review_candidates,
    review_model_input,
    submit_slides,
)
from signaltrail.slide_images import _read_page, enrich_slide_images
from signaltrail.slide_renderer import render_slides_html
from signaltrail.utils import write_json

DATE = "2026-01-15"
PAGE_COUNT = 50
TOPICS = (
    "公共建筑节能改造", "公交站台照明", "社区雨水收集", "河道水质监测", "街区无障碍设施",
    "图书馆自助借阅", "社区食品冷链", "公园树木养护", "乡村道路维修", "学校屋顶光伏",
)


def _responsive_gallery_candidates() -> bool:
    """同构图的下载候选按清晰度排序，独立裁切和签名原址继续可用。"""
    path = "https://i.guim.co.uk/img/uploads/photo.jpg"
    small = f"{path}?width=120&dpr=1&crop=5%3A4&s=none"
    large = f"{path}?width=220&dpr=2&crop=5%3A4&s=none"
    alternate_crop = f"{path}?width=220&dpr=2&crop=16%3A9&s=none"
    signed = f"{path}?width=440&dpr=1&crop=5%3A4&s=signed"
    groups = image_variant_groups([
        {"url": url} for url in (small, large, alternate_crop, signed)
    ])
    article = "https://www.theguardian.com/fixture"
    initial = _source_image_candidates(
        {"url": article, "image_candidates": [small, large, alternate_crop, signed]},
        {}, article, preserve_variants=False,
    )
    return (
        [[image["url"] for image in group] for group in groups]
        == [[large, small], [alternate_crop], [signed]]
        and {image["url"] for image in initial} == {large, alternate_crop, signed}
    )


def _bbc_newsletter_banner_excluded() -> bool:
    """保留气候大会现场图，排除同篇报道中订阅横幅的多个转码版本。"""
    cdn = "https://ichef.bbci.co.uk/news"
    photo = f"{cdn}/1536/cpsprodpb/afca/live/39aa8840-e69c-11f1-936e-1fd1d31671db.jpg.webp"
    banner = "8c6c/live/f9295fc0-0fde-11f0-ba12-8d27eb561761.png"
    return normalize_image_candidates([
        photo, f"{cdn}/1536/cpsprodpb/{banner}.webp", f"{cdn}/640/branded_news/{banner}",
    ]) == [photo]


def _shared_photo_keeps_article_caption(data_dir: Path, photo: dict) -> bool:
    """两份报道复用同一张照片文件时，各自保留发布方署名和图注。"""
    stories = []
    for number in (1, 2):
        url = f"https://bulletin-{number}.example/article"
        image = dict(photo, caption=f"图注 {number}", credit=f"媒体 {number}")
        stories.append({
            "sources": [{"url": url, "name": f"媒体 {number}"}], "images": [],
            "image_source_pages": {url: [image]},
        })
    enriched, metrics = enrich_slide_images(stories, data_dir, MediaConfig())
    return (
        metrics["source_pages_reused"] == 2
        and [(story["images"][0]["credit"], story["images"][0]["caption"],
              story["images"][0]["local_path"]) for story in enriched]
        == [(f"媒体 {number}", f"图注 {number}", photo["local_path"]) for number in (1, 2)]
    )


def _make_fixture(data_dir: Path) -> tuple[dict, dict, dict]:
    """将虚构项目的正文、来源和本地示意图写入隔离数据根，返回索引与预期产物。"""
    items, drafts, evidence = [], {}, {}
    content_dir, media_dir = data_dir / "content", data_dir / "media" / "images"
    content_dir.mkdir(parents=True)
    media_dir.mkdir(parents=True)
    for number in range(1, PAGE_COUNT + 1):
        topic = TOPICS[(number - 1) % len(TOPICS)]
        area, count = f"第{number:02}区", 12 + number
        item_id = f"fixture-{number:02}"
        source_number = (number - 1) % 4 + 1
        source = f"评估用公报{source_number}"
        url = f"https://bulletin-{source_number}.example/notice/{number:02}"
        image_url = f"https://bulletin-{source_number}.example/media/{number:02}.png"
        title = f"{area}公示{topic}试点"
        summary = f"{source}公布{area}{topic}试点，首阶段核查{count}处设施，结果将在复核后公开。"
        narration = (
            f"{source}在一月十五日发布通知。{area}将开展{topic}试点，首阶段安排核查{count}处设施。"
            "通知将首次核查与整改验收列为两个阶段。工作人员先记录现场情况、设施状态和实际使用人数，"
            "并把原始台账交给复核人员比对。负责单位随后根据记录确认需要处理的设施，并安排第二次核查。"
            "通知要求在复核结束后公开结果。居民可以按公报中的项目编号查阅设施清单、核查日期和公开说明。"
            "公报公布的是工作安排和首阶段范围，试点后的使用情况将在后续公开材料中说明。"
        )
        video_tldr = (
            f"{area}公布{topic}试点安排。首阶段将核查{count}处设施，逐项记录现场情况，"
            "再由负责单位比对台账并确定后续整改事项。复核结束后，居民可按项目编号查阅公开结果。"
        )
        body = f"{title}\n\n{narration}\n\n公报编号：评估-{number:02}。"
        body_path = content_dir / f"{item_id}.md"
        body_path.write_text(body, encoding="utf-8")
        image_path = media_dir / f"{item_id}.png"
        chart = Image.new("RGB", (640, 360), (240, 244, 249))
        draw = ImageDraw.Draw(chart)
        draw.rectangle((60, 130, 60 + count * 8, 210), fill=(30, 107, 143))
        draw.text((60, 76), f"Fixture {number:02} / sites scheduled: {count}", fill=(30, 40, 53))
        chart.save(image_path)
        caption = f"{area}首阶段计划核查{count}处设施。"
        items.append({
            "item_id": item_id,
            "source_id": f"bulletin-{source_number}",
            "source_name": source,
            "title": title,
            "url": url,
            "canonical_url": url,
            "published_at": f"{DATE}T08:{number:02}:00+08:00",
            "description": summary,
            "content_status": "partial" if number == 1 else "full_text",
            "content_path": str(body_path),
            "metadata": {"content_quality": {
                "extraction_status": "partial" if number == 1 else "complete",
                "response_truncated": number == 1,
                "numeric_tables_without_headers": ["table-1"] if number == 1 else [],
                "fact_verification": "not_performed",
                "candidates": [{"selector": "article", "characters": len(body)}],
                "baseline_quality": {"region": "broad", "extraction_status": "insufficient"},
            }, "content_completion": {
                "status": "with_gaps" if number == 1 else "complete",
                "unresolved": ["truncated"] if number == 1 else [],
            }, "image_candidate_details": [{
                "url": image_url, "local_path": image_path.relative_to(data_dir).as_posix(),
                "width": 640, "height": 360, "content_type": "image/png",
                "caption": caption, "credit": source,
            }]},
        })
        event_id = f"index-{item_id}"
        if number == 1:
            items[-1]["metadata"].update(publication_time_kind="platform",
                                         content_source={"published_at": DATE})
        drafts[event_id] = {
            "event_id": event_id, "title": title, "summary": summary, "narration": narration,
            "video_tldr": video_tldr, "perspectives": [],
        }
        evidence[event_id] = {"body": body, "url": url, "image_url": image_url, "caption": caption}
    index = {
        "schema_version": "1.1", "index_id": "slides-evaluation", "revision": 1,
        "date": DATE, "edition": "daily", "timezone": "Asia/Shanghai",
        "generated_at": f"{DATE}T12:00:00+08:00", "sources": [], "items": items,
    }
    return index, drafts, evidence


def _rendered_pages(
    deck: dict, html_path: Path, selected: list[str], drafts: dict, evidence: dict,
) -> dict:
    """核对实际页面、完整讲解、短稿以及原文和图片出处。"""
    slides = deck["slides"]
    html = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")
    pages = html.select("article.slide")
    ordered = [slide["event_id"] for slide in slides] == selected and len(pages) == len(selected)
    matching_text, matching_sources = 0, 0
    for slide, page in zip(slides, pages, strict=False):
        expected, source = drafts[slide["event_id"]], evidence[slide["event_id"]]
        heading = page.select_one("h2")
        narration = page.select_one(".narration")
        matching_text += (
            heading is not None and heading.get_text(strip=True) == expected["title"]
            and page.select_one(".summary") is None and slide["summary"] == expected["summary"]
            and narration is not None and narration.get_text(strip=True) == expected["narration"]
            and slide["video_tldr"] == expected["video_tldr"]
        )
        image, caption = page.select_one("figure img"), page.select_one("figcaption")
        matching_sources += (
            any(item["url"] == source["url"] for item in slide["sources"])
            and any(item["source_url"] == source["url"] and item["url"] == source["image_url"]
                    for item in slide["images"])
            and any(link.get("href") == source["url"] for link in page.select(".source-chips a"))
            and any(link.get("href") == source["image_url"]
                    for link in page.select(".image-credit a"))
            and image is not None and str(image.get("src", "")).startswith("data:image/png;base64,")
            and caption is not None and caption.get_text(strip=True) == source["caption"]
        )
    return {"ordered": ordered, "text_pages": matching_text, "source_pages": matching_sources}


def _xinhua_captioned_photo() -> bool:
    """检查新华社正文图及对应原文图注进入真实图片提取入口。"""
    url = "https://english.news.cn/article/c.html"
    body = "<p>Shenzhen hosts the summit and both delegations attended the meeting.</p>" * 12
    soup = BeautifulSoup(
        '<body><img src="/site-logo.png"><div id="detailContent">'
        '<p><img src="meeting.jpeg"></p>'
        '<p><span>The delegations meet in Shenzhen. (Xinhua/Wang Ye)</span></p>'
        f"{body}</div></body>", "html.parser",
    )
    with patch("signaltrail.slide_images.fetch_article_page", return_value=(soup, url)):
        images, _ = _read_page(url, "Shenzhen summit", MediaConfig())
    return [(image["url"], image["caption"]) for image in images] == [
        ("https://english.news.cn/article/meeting.jpeg",
         "The delegations meet in Shenzhen. (Xinhua/Wang Ye)"),
    ]


def evaluate(work_dir: Path) -> dict:
    """以固定索引和讲稿运行实际图文链路，返回质量门禁、阶段耗时和产物路径。"""
    data_dir = work_dir.resolve()
    index, drafts, evidence = _make_fixture(data_dir)
    index_path = write_json(data_dir / "indexes" / "fixture-r1.json", index)
    selected = list(reversed(drafts))
    decision = {"selected_event_ids": selected}

    start = perf_counter()
    candidates = review_candidates(None, index, max_news=PAGE_COUNT, data_dir=data_dir)
    reviewed = perf_counter()
    prepared = prepare_slides(None, index_path, data_dir, review=decision)
    prepared_at = perf_counter()
    plan_path = Path(prepared["plan_path"])
    reader = ArtifactReader(data_dir)
    frozen_news = {
        row["event_id"]: row for row in reader.load(plan_path)["payload"]["news"]
    }
    quality_preserved = True
    exact_evidence = set()
    for path in map(Path, prepared["packet_paths"]):
        packet = reader.load(path)["payload"]["model_input"]
        batch = []
        for news in packet["news"]:
            event_id = news["event_id"]
            source = evidence[event_id]
            frozen = frozen_news[event_id]["evidence"][0]
            expected_quality = frozen["content_quality"].copy()
            quality_preserved &= bool(expected_quality.pop("candidates"))
            quality_preserved &= bool(expected_quality.pop("baseline_quality"))
            quality_preserved &= news["evidence"] == [
                {**frozen, "content_quality": expected_quality}
            ]
            if event_id == "index-fixture-01":
                quality_preserved &= news["sources"][0]["published_at"] == DATE
            if (any(row["body"].strip() == source["body"] for row in news["evidence"])
                    and any(row["url"] == source["url"] for row in news["sources"])):
                exact_evidence.add(event_id)
            batch.append(drafts[event_id])
        result = {"slides": batch}
        if "video_title" in packet["output_schema"]["properties"]:
            result["video_title"] = "社区公共服务试点公报"
        submit_slides(path, result, data_dir)
    submitted = perf_counter()
    rendered = render_slides(plan_path, data_dir, refresh_images=False)
    rendered_at = perf_counter()

    revision_path = write_json(data_dir / "indexes" / "fixture-r2.json", index | {"revision": 2})
    reuse_start = perf_counter()
    reused = prepare_slides(None, revision_path, data_dir, review=decision, reuse_plan=plan_path)
    reused_at = perf_counter()
    rerendered = render_slides(Path(reused["plan_path"]), data_dir, refresh_images=False)
    reuse_end = perf_counter()

    first_record = reader.load(Path(rendered["json_path"]), kind="slides-deck")
    first_deck = first_record["payload"]
    next_deck = reader.load(Path(rerendered["json_path"]), kind="slides-deck")["payload"]
    first_html, next_html = Path(rendered["html_path"]), Path(rerendered["html_path"])
    pages = _rendered_pages(first_deck, first_html, selected, drafts, evidence)
    replay = _rendered_pages(next_deck, next_html, selected, drafts, evidence)
    original_index = index_path.read_bytes()
    changed_parent_rejected = False
    try:
        # 新渲染操作必须重新核对先前已经读取过的索引父文件。
        index_path.write_bytes(original_index + b"\n")
        render_slides(plan_path, data_dir, refresh_images=False)
    except ValueError as exc:
        changed_parent_rejected = "Explainer parent changed" in str(exc)
    finally:
        index_path.write_bytes(original_index)
    parents = {name: data_dir / ref["path"] for name, ref in first_record["parents"].items()}
    batch = parents["batch-1"]
    original_batch = batch.read_bytes()
    updated_batch = json.loads(original_batch)
    updated_batch["created_at"] = f"{DATE}T12:00:00+00:00"
    updated_batch.pop("content_hash")
    updated_batch["content_hash"] = digest(updated_batch)
    changed_batch_rejected = False
    try:
        # 模拟读取完成后，提交前某个父结果被另一份合法产物替换。
        batch.write_text(json.dumps(updated_batch, ensure_ascii=False), encoding="utf-8")
        load_artifact(batch, data_dir, kind="slides-result-1")
        save_artifact(data_dir, first_record["session"], "slides-deck", first_deck, parents,
                      Path(rendered["markdown_path"]).read_bytes().decode("utf-8"),
                      expected_parents=first_record["parents"])
    except ValueError as exc:
        changed_batch_rejected = "Explainer parent changed before artifact commit" in str(exc)
    finally:
        batch.write_bytes(original_batch)
    first, second = first_deck["slides"][:2]
    cover = first["images"][0]
    source = first["sources"][0]
    caption = second["images"][0]["caption"]
    cited_title = "City council publishes the final community infrastructure review"
    related = {
        **second["images"][0], "source_url": source["url"], "alt": cited_title,
        "provenance": "article_body",
    }
    gallery_case = {
        **first_deck, "slides": [
            {**first, "images": [cover, related],
             "sources": [{**source, "title": cited_title + " | Local News"}]},
            {**first, "images": [cover, {**related, "source_url": second["sources"][0]["url"]}],
             "sources": [{**source, "title": cited_title}]},
        ],
    }
    gallery_pages = BeautifulSoup(
        render_slides_html(gallery_case, data_dir), "html.parser"
    ).select(".slide")
    return {
        "workload": {"candidate_articles": len(index["items"]), "sources": 4,
                     "target_pages": PAGE_COUNT, "drafts": "fixed", "images": "local"},
        "checks": {
            "xinhua_body_image_preserves_source_caption": _xinhua_captioned_photo(),
            "bbc_newsletter_banner_excluded": _bbc_newsletter_banner_excluded(),
            "shared_photo_keeps_article_caption": _shared_photo_keeps_article_caption(
                data_dir, cover,
            ),
            "responsive_gallery_groups_sizes_and_preserves_crops": _responsive_gallery_candidates(),
            "full_candidate_pool_reviewed": {row["event_id"] for row in candidates["candidates"]}
            == set(selected) and candidates["eligible_count"] == PAGE_COUNT,
            "review_preserves_source_image_hints": all(
                evidence_row[-1].get("image_candidate") is True
                for candidate in review_model_input(candidates)["candidates"]
                for evidence_row in candidate[1]
            ),
            "author_packets_preserve_all_evidence": exact_evidence == set(selected),
            "packets_keep_quality_and_plan_keeps_extractor_comparisons": quality_preserved,
            "all_pages_render_in_selected_order": pages["ordered"],
            "all_pages_preserve_approved_text": pages["text_pages"] == PAGE_COUNT,
            "all_pages_preserve_sources_and_images": pages["source_pages"] == PAGE_COUNT,
            "lead_image_requires_matching_article_and_keeps_original_caption": (
                [[image["data-original"] for image in page.select("figure")]
                 for page in gallery_pages] == [
                    [related["url"], cover["url"]], [cover["url"], related["url"]],
                ]
                and gallery_pages[0].select_one("figcaption").get_text(strip=True) == caption
            ),
            "revision_reuses_all_narration": reused["reused_count"] == PAGE_COUNT
            and not reused["packet_paths"] and reused["pending_news_count"] == 0,
            "revision_rerenders_same_deliverable": replay == pages
            and first_deck["slides"] == next_deck["slides"],
            "new_render_rejects_changed_parent": changed_parent_rejected,
            "deck_commit_rejects_replaced_batch": changed_batch_rejected,
        },
        "metrics": {
            "review_seconds": reviewed - start, "prepare_seconds": prepared_at - reviewed,
            "submit_seconds": submitted - prepared_at, "render_seconds": rendered_at - submitted,
            "elapsed_seconds": rendered_at - start,
            "pages_per_second": len(first_deck["slides"]) / (rendered_at - start),
            "reuse_prepare_seconds": reused_at - reuse_start,
            "reuse_render_seconds": reuse_end - reused_at,
            "reused_pages": reused["reused_count"], "author_batches": len(prepared["packet_paths"]),
            "estimated_input_tokens": prepared["estimated_input_tokens"],
            "html_bytes": first_html.stat().st_size,
        },
        "artifacts": {
            "plan": str(plan_path), "deck": rendered["json_path"], "html": str(first_html),
            "reused_plan": reused["plan_path"], "reused_html": str(next_html),
            "reused_deck": rerendered["json_path"],
        },
        "limitations": ["固定讲稿与本地图像用于测量程序阶段，模型写作和浏览器视口另行评估。"],
    }
