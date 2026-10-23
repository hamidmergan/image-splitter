import cv2
import numpy as np
import pytest

from image_splitter import detect
from scenes import Item, corners, scene, three_receipts, top_is_dark


def _cut(page, min_area=0.01):
    colour, threshold = detect.background(page)
    quads = detect.find_quads(page, min_area)
    quads = [detect.refine_quad(page, quads[i], colour, threshold) for i in detect.reading_order(quads)]
    parts = [detect.trim_edges(detect.warp(page, q), colour, threshold) for q in quads]
    return quads, parts


def _closest(quad, items):
    return min(float(np.abs(quad - corners(it)).max()) for it in items)


@pytest.mark.parametrize(
    "background,noise",
    [
        ((55, 60, 70), 4),  # dark table
        ((150, 110, 70), 12),  # brown, noisy
        ((225, 225, 228), 4),  # light grey
        ((238, 238, 236), 3),  # white receipts on a white scanner lid
    ],
)
def test_finds_rotated_receipts_on_different_backgrounds(background, noise):
    items = three_receipts()
    page = scene(items, background=background, noise=noise)
    quads, parts = _cut(page)
    assert len(quads) == 3
    for quad in quads:
        assert _closest(quad, items) < 2.5
    for part, item in zip(parts, items):
        w, h = item.size
        assert abs(part.shape[1] - w) <= 4 and abs(part.shape[0] - h) <= 4
        assert top_is_dark(part)


@pytest.mark.parametrize("angle", [-44, -30, -10, 0, 10, 30, 44])
def test_turns_back_any_tilt_up_to_45_degrees(angle):
    item = Item((600, 600), (360, 600), angle=angle)
    quads, parts = _cut(scene([item], size=(1200, 1200)))
    assert len(parts) == 1
    assert parts[0].shape[0] > parts[0].shape[1]  # stays portrait
    assert top_is_dark(parts[0])


def test_no_dark_background_left_at_the_edges():
    _, parts = _cut(scene(three_receipts()))
    for part in parts:
        gray = cv2.cvtColor(part, cv2.COLOR_RGB2GRAY)
        edges = np.concatenate([gray[0], gray[-1], gray[:, 0], gray[:, -1]])
        assert np.median(edges) > 200


def test_corrects_perspective():
    page = scene([Item((500, 450), (500, 700))], size=(1000, 900), noise=2)
    src = np.float32([[0, 0], [1000, 0], [1000, 900], [0, 900]])
    dst = np.float32([[40, 30], [960, 90], [990, 860], [10, 880]])
    tilted = cv2.warpPerspective(page, cv2.getPerspectiveTransform(src, dst), (1000, 900),
                                 borderMode=cv2.BORDER_REPLICATE)
    quads, parts = _cut(tilted)
    assert len(parts) == 1
    part = parts[0]
    gray = cv2.cvtColor(part, cv2.COLOR_RGB2GRAY)
    # the cut-out is the white item only, without background at any corner
    corner_size = 10
    for patch in (gray[:corner_size, :corner_size], gray[:corner_size, -corner_size:],
                  gray[-corner_size:, :corner_size], gray[-corner_size:, -corner_size:]):
        assert patch.mean() > 200
    assert top_is_dark(part)


@pytest.mark.parametrize("background", [(48, 52, 60), (150, 110, 70), (200, 200, 200)])
def test_shadow_is_not_cut_out(background):
    item = Item((600, 500), (500, 300), angle=8, color=(235, 240, 250))
    page = scene([item], size=(1200, 1000), background=background).astype(np.float32)
    inside = np.zeros(page.shape[:2], np.uint8)
    cv2.fillConvexPoly(inside, np.round(corners(item)).astype(np.int32), 1)
    shadow = np.zeros(page.shape[:2], np.float32)
    cv2.fillConvexPoly(shadow, np.round(corners(item) + [14, 18]).astype(np.int32), 1.0)
    shadow = cv2.GaussianBlur(shadow, (41, 41), 0) * (inside == 0)
    page = (page * (1 - 0.4 * shadow[..., None])).astype(np.uint8)
    quads, _ = _cut(page)
    assert len(quads) == 1
    assert _closest(quads[0], [item]) < 2.5


def test_blank_page_has_no_items():
    assert detect.find_quads(scene([]), 0.01) == []


def test_small_items_below_min_area_are_ignored():
    items = [Item((400, 400), (300, 500)), Item((1200, 600), (40, 40))]
    page = scene(items)
    assert len(detect.find_quads(page, 0.01)) == 1
    assert len(detect.find_quads(page, 0.0005)) == 2


def test_reading_order_rows_then_left_to_right():
    items = [
        Item((1200, 300), (300, 300)),
        Item((300, 320), (300, 300)),
        Item((750, 280), (300, 300)),
        Item((400, 900), (300, 300)),
        Item((1100, 880), (300, 300)),
    ]
    quads = detect.find_quads(scene(items), 0.01)
    ordered = [quads[i] for i in detect.reading_order(quads)]
    centres = [tuple(np.round(q.mean(axis=0), -2)) for q in ordered]
    assert centres == [(300, 300), (800, 300), (1200, 300), (400, 900), (1100, 900)]


@pytest.mark.parametrize("angle", [-40, -5, 0, 5, 40])
def test_order_quad_starts_top_left(angle):
    item = Item((500, 500), (200, 400), angle=angle)
    expected = corners(item)
    shuffled = expected[[2, 0, 3, 1]]
    assert np.allclose(detect.order_quad(shuffled), expected, atol=1e-3)


def test_refine_box_finds_item_in_rough_box():
    item = Item((600, 500), (300, 500), angle=12)
    page = scene([item], size=(1200, 1000))
    xs, ys = corners(item)[:, 0], corners(item)[:, 1]
    rough = (xs.min() - 30, ys.min() + 10, xs.max() + 20, ys.max() - 15)
    quad = detect.refine_box(page, rough)
    assert quad is not None
    assert _closest(quad, [item]) < 4


def test_refine_box_returns_none_for_empty_box():
    page = scene([Item((300, 300), (200, 200))], size=(1200, 1000))
    assert detect.refine_box(page, (700, 500, 1000, 900)) is None


def test_padding_adds_and_trims():
    page = scene([Item((500, 500), (300, 400))], size=(1000, 1000))
    quad = detect.find_quads(page, 0.01)[0]
    base = detect.warp(page, quad)
    assert detect.warp(page, quad, 10).shape[:2] == (base.shape[0] + 20, base.shape[1] + 20)
    assert detect.warp(page, quad, -5).shape[:2] == (base.shape[0] - 10, base.shape[1] - 10)


def test_draw_quads_keeps_size():
    page = scene(three_receipts())
    out = detect.draw_quads(page, detect.find_quads(page, 0.01))
    assert out.shape == page.shape and not np.array_equal(out, page)
