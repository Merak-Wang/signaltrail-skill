import pytest

from daily_intelligence.image_policy import normalize_image_candidates, srcset_candidates


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
