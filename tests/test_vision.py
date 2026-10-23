import numpy as np
import pytest

from image_splitter import ModelError, split_image, split_many
from image_splitter.vision import parse_boxes, parse_rotation
from scenes import Item, scene, three_receipts, top_is_dark


def _vision(server, **extra):
    return dict(base_url=server.base_url, model="vm", **extra)


@pytest.mark.parametrize(
    "text",
    [
        '{"items": [[100, 200, 300, 400]]}',
        'Sure:\n```json\n{"items": [[100, 200, 300, 400]]}\n```',
        "[[100, 200, 300, 400]]",
        '[{"box_2d": [100, 200, 300, 400], "label": "receipt"}]',
        '{"boxes": [{"bbox": [0.1, 0.2, 0.3, 0.4]}]}',
        '{"items": [[300, 400, 100, 200]]}',
    ],
)
def test_parse_boxes_formats(text):
    assert parse_boxes(text, (1000, 1000)) == [pytest.approx((0.1, 0.2, 0.3, 0.4))]


def test_parse_boxes_pixels_of_sent_image():
    boxes = parse_boxes('{"items": [[160, 120, 1600, 600]]}', (1600, 1200))
    assert boxes == [pytest.approx((0.1, 0.1, 1.0, 0.5))]


@pytest.mark.parametrize("text", ["", "no items here", '{"items": "none"}', '{"items": [[1, 2]]}', '{"items": [[5, 5, 5, 5]]}'])
def test_parse_boxes_unusable_answers(text):
    assert parse_boxes(text, (1000, 1000)) == []


@pytest.mark.parametrize("text,degrees", [("180", 180), ("Rotate by 90 degrees.", 90), ("270", 270), ("upright", 0), ("45", 0)])
def test_parse_rotation(text, degrees):
    assert parse_rotation(text) == degrees


def test_equal_count_keeps_opencv_result(server):
    server.boxes = '{"items": [[100, 100, 300, 800], [400, 100, 600, 800], [700, 100, 900, 800]]}'
    parts = split_image(scene(three_receipts()), **_vision(server))
    assert [p.method for p in parts] == ["contour"] * 3
    # one request for the boxes, one per part for the orientation
    assert len(server.requests) == 4


def test_model_separates_touching_items(server):
    items = [Item((500, 600), (300, 800)), Item((800, 600), (300, 800))]
    page = scene(items, size=(1600, 1200))
    assert len(split_image(page)) == 1  # OpenCV alone sees one merged item
    server.boxes = '{"items": [[219, 167, 406, 833], [406, 167, 594, 833]]}'
    parts = split_image(page, **_vision(server, orient=False))
    assert len(parts) == 2
    for part in parts:
        assert abs(part.image.width - 300) <= 40
        assert abs(part.image.height - 800) <= 40


def test_model_finds_single_document_filling_the_frame(server):
    page = scene([Item((800, 600), (1700, 1300))])
    assert len(split_image(page)) > 1  # OpenCV takes details of the document for items
    server.boxes = '{"items": [[0, 0, 1000, 1000]]}'
    parts = split_image(page, **_vision(server, orient=False))
    assert len(parts) == 1
    assert parts[0].image.size == (1600, 1200)


def test_model_turns_item_upright(server):
    page = scene([Item((600, 600), (360, 700), angle=180 + 6)], size=(1200, 1200))
    assert not top_is_dark(np.asarray(split_image(page)[0].image))
    server.boxes = '{"items": [[300, 200, 700, 800]]}'
    server.rotation = "180"
    part = split_image(page, **_vision(server))[0]
    assert part.rotation == 180
    assert top_is_dark(np.asarray(part.image))


def test_unreadable_box_answer_falls_back_to_opencv(server):
    server.boxes = "I cannot help with that."
    parts = split_image(scene(three_receipts()), **_vision(server, orient=False))
    assert len(parts) == 3


def test_no_orient_sends_only_the_box_request(server):
    split_image(scene(three_receipts()), **_vision(server, orient=False))
    assert len(server.requests) == 1


def test_api_key_is_sent_or_placeholder(server):
    split_image(scene(three_receipts()), **_vision(server, orient=False, api_key="secret"))
    split_image(scene(three_receipts()), **_vision(server, orient=False))
    auth = [r["headers"]["authorization"] for r in server.requests]
    assert auth == ["Bearer secret", "Bearer not-needed"]


def test_server_error_is_reported(server, save):
    server.fail = True
    with pytest.raises(ModelError):
        split_image(scene(three_receipts()), **_vision(server, max_retries=0))
    path = save("a.png", scene(three_receipts()))
    result = split_many([path], **_vision(server, max_retries=0))[str(path)]
    assert not result.ok and "failed" in result.error
