import pytest

from signaltrail.image_policy import (
    image_resolution_candidates,
    image_variant_groups,
    normalize_image_candidates,
    select_image_variants,
    srcset_candidates,
)


@pytest.mark.parametrize(("value", "expected"), [
    ("small.jpg 400w, large.jpg 1600w", ["large.jpg", "small.jpg"]),
    ("large.jpg 1600w, small.jpg 400w", ["large.jpg", "small.jpg"]),
    ("regular.jpg 1x, retina.jpg 2x", ["retina.jpg", "regular.jpg"]),
    ("retina.jpg 2x, regular.jpg 1x", ["retina.jpg", "regular.jpg"]),
    ("a.jpg 1.5x, b.jpg 2x, c.jpg .5x", ["b.jpg", "a.jpg", "c.jpg"]),
    ("a.jpg, b.jpg 2x", ["b.jpg", "a.jpg"]),
    ("a.jpg, b.jpg, c.jpg", ["a.jpg", "b.jpg", "c.jpg"]),
    ("a.jpg 2x, b.jpg 2x, a.jpg 1x", ["a.jpg", "b.jpg"]),
    ("a.jpg 2x, b.jpg 800w, c.jpg 3x, d.jpg 1200w", ["c.jpg", "a.jpg", "d.jpg", "b.jpg"]),
    ("bad.jpg -2x, zero.jpg 0w, fraction.jpg 1.5w, ok.jpg 400w", ["ok.jpg"]),
    ("bad.jpg 1x 2x, inf.jpg 1e999x, ok.jpg 2e0x", ["ok.jpg"]),
    ("https://cdn.example/img?w=400,h=300 400w, high.jpg 800w",
     ["high.jpg", "https://cdn.example/img?w=400,h=300"]),
    (None, []),
    ("", []),
])
def test_srcset_orders_valid_descriptors_without_reversing_declaration_order(value, expected):
    assert srcset_candidates(value) == expected


def test_data_url_is_not_split_into_an_apparent_relative_image():
    candidates = srcset_candidates("data:image/png;base64,AAAA 1x, /photo.png 2x")
    assert normalize_image_candidates(candidates, "https://example.com/") == [
        "https://example.com/photo.png",
    ]


def test_known_photo_derivatives_choose_actual_high_resolution_and_keep_caption(tmp_path):
    from PIL import Image

    root = "https://global.unitednations.entermediadb.net/assets/photo.jpg/"
    un = [{"url": root + f"image{width}x{height}cropped.jpg", "width": width, "height": height}
          for width, height in ((350, 235), (1170, 531), (770, 420))]
    defense = "https://cdn.defenseone.com/media/img/cd/2026/11/04/photo/"
    versions = [{"url": defense + name, "width": width, "height": height}
                for name, width, height in (("large.jpg", 618, 284),
                                            ("860x394.jpg", 860, 394),
                                            ("open-graph.jpg", 400, 400))]
    assert select_image_variants(un)[0]["width"] == 1170
    assert select_image_variants(versions)[0]["width"] == 860
    dw = [{"url": "https://static.dw.com/image/79850193_803.webp", "width": 575, "height": 575},
          {"url": "https://static.dw.com/image/79850193_6.jpg", "width": 940, "height": 529}]
    assert select_image_variants(dw)[0]["width"] == 940
    base = "https://cdn.arstechnica.net/wp-content/uploads/2026/11/switchcarts"
    for size in (500, 2048):
        Image.new("RGB", (size, size * 3 // 4)).save(tmp_path / f"{size}.png")
    wordpress = [{"url": base + ".jpg"},
                 {"url": base + "-500x500.jpg", "width": 500, "height": 375,
                  "local_path": "500.png", "caption": "Original source caption."},
                 {"url": base + "-2048x1536.jpg", "width": 2048, "height": 1536,
                  "local_path": "2048.png"}]
    assert image_variant_groups(wordpress)[0][0]["url"] == base + ".jpg"
    selected = select_image_variants(wordpress, data_dir=tmp_path)
    assert len(selected) == 1
    assert selected[0]["local_path"] == "2048.png"
    assert selected[0]["caption"] == "Original source caption."


def test_unrelated_queries_and_explicit_crops_remain_distinct():
    guardian = [{"url": f"https://i.guim.co.uk/abc/photo.jpg?width={width}&quality={quality}"}
                for width, quality in ((140, 80), (1400, 90))]
    assert len(select_image_variants(guardian)) == 1
    assert "width=1400" in select_image_variants(guardian)[0]["url"]
    urls = ["https://cdn.example/photo.jpg?signature=first",
            "https://cdn.example/photo.jpg?signature=second",
            "https://images.ctfassets.net/photo.jpg?w=400&h=300&rect=0,0,400,300",
            "https://images.ctfassets.net/photo.jpg?w=800&h=600&rect=0,0,800,600",
            "https://cdn.arstechnica.net/wp-content/uploads/2026/11/other-photo-500x500.jpg"]
    assert [row["url"] for row in select_image_variants([{"url": url} for url in urls])] == urls


def test_cloudflare_proxy_keeps_one_highest_version_of_the_explicit_original():
    original = "https://blog.cloudflare.com/_emdash/api/media/file/photo.png"
    proxy = "https://blog.cloudflare.com/_image?href=" + original
    images = [{"url": proxy + "&w=640&h=400&fit=cover&position=center",
               "width": 640, "height": 400},
              {"url": proxy + "&w=1280&h=800&q=100&f=webp",
               "width": 1280, "height": 800},
              {"url": original, "width": 1200, "height": 750},
              {"url": proxy + "&w=640&h=400&position=top", "width": 640, "height": 400}]
    selected = select_image_variants(images)
    assert len(selected) == 2
    assert selected[0]["width"] == 1280
    assert selected[1]["url"].endswith("position=top")
    source = "https://layer3intel.com/eop_proxy_activity.png"
    next_proxy = "https://layer3intel.com/_next/image?url=%2Feop_proxy_activity.png&w=3840&q=75"
    next_images = [{"url": source, "width": 1801, "height": 493},
                   {"url": next_proxy, "width": 1801, "height": 493},
                   {"url": next_proxy.replace("eop_proxy_activity", "different-edited-table"),
                    "width": 1801, "height": 493}]
    assert len(select_image_variants(next_images)) == 2


def test_local_photo_pixels_merge_renamed_sizes_and_preserve_edited_charts(tmp_path):
    from PIL import Image, ImageDraw

    photo = Image.new("RGB", (256, 256))
    photo.putdata([(x, y, (x * 7 + y * 11) % 256) for y in range(256) for x in range(256)])
    photo.save(tmp_path / "photo.png")
    photo.resize((128, 128), Image.Resampling.LANCZOS).save(tmp_path / "renamed.png")
    images = [{"url": "https://example.com/old-header.png", "local_path": "renamed.png",
               "width": 128, "height": 128},
              {"url": "https://example.com/new-header.png", "local_path": "photo.png",
               "width": 256, "height": 256}]
    assert len(select_image_variants(images, data_dir=tmp_path)) == 1
    assert select_image_variants(images, data_dir=tmp_path)[0]["width"] == 256
    for number in (1, 2):
        chart = Image.new("RGB", (256, 256), "white")
        ImageDraw.Draw(chart).text((10, 10), f"Revenue {number}", fill="black")
        chart.save(tmp_path / f"chart-{number}.png")
        images.append({"url": f"https://example.com/chart-{number}.png",
                       "local_path": f"chart-{number}.png", "width": 256, "height": 256})
    assert len(select_image_variants(images, data_dir=tmp_path)) == 3


def test_guardian_crop_none_groups_sizes_and_keeps_highest_available_variant(tmp_path):
    from PIL import Image

    base = ("https://i.guim.co.uk/img/media/d6ebd9b4d868a9da787c0f6b207548c78ad7ab28/"
            "897_48_4916_3935/master/4916.jpg")
    images = [{"url": base + f"?width={width}&dpr=2&s=none&crop=none"}
              for width in (140, 300, 360, 465, 620, 645, 1200, 1400)]
    for number in (4, 5):
        path = tmp_path / f"{number}.png"
        Image.new("RGB", (160 * number, 100 * number), "blue").save(path)
        images[number]["local_path"] = path.name
    assert len(image_variant_groups(images)) == 1
    selected = select_image_variants(images, data_dir=tmp_path)
    assert len(selected) == 1 and selected[0]["url"] == images[5]["url"]
    independent = [
        {"url": base + "?width=645&dpr=2&s=none&crop=faces"},
        {"url": base + "?width=645&dpr=2&s=none&crop=none&rect=0,0,10,10"},
        {"url": base + "?width=645&dpr=2&s=signature&crop=none"},
        {"url": base.replace("master/4916.jpg", "master/other.jpg")
         + "?width=645&dpr=2&s=none&crop=none"},
    ]
    assert len(image_variant_groups(images + independent)) == 5


def test_bbc_feed_thumbnail_prefers_hd_and_preserves_signed_urls():
    thumbnail = "https://ichef.bbci.co.uk/ace/standard/240/cpsprodpb/live/photo.jpg"
    high, fallback = image_resolution_candidates(thumbnail)
    assert "/1920/" in high and fallback == thumbnail
    images = [{"url": thumbnail, "width": 240, "height": 135},
              {"url": high}, {"url": high + ".webp"}]
    assert len(image_variant_groups(images)) == 1
    assert select_image_variants(images)[0]["url"] == high
    assert image_resolution_candidates(thumbnail + "?signature=abc") == [
        thumbnail + "?signature=abc",
    ]


def test_wordpress_query_sizes_keep_only_largest_with_same_crop():
    base = "https://platform.theverge.com/wp-content/uploads/2026/photo.jpg"
    images = [{"url": base + f"?quality=90&crop=0%2C0%2C100%2C100&w={width}"}
              for width in (376, 640, 1920)]
    selected = select_image_variants(images)
    assert len(selected) == 1 and "w=1920" in selected[0]["url"]
    different_crop = {"url": base + "?crop=20%2C20%2C80%2C80&w=2400"}
    assert len(select_image_variants([*images, different_crop])) == 2
    assert select_image_variants([{"url": base + "?resize=300,200"},
                                  {"url": base + "?resize=1200,800"}])[0]["url"].endswith(
                                      "resize=1200,800")
