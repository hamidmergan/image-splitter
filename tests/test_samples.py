"""The sample images in samples/ give the results the README promises."""

import pytest

from image_splitter import split
from image_splitter.loader import SAMPLES


def _shapes(parts):
    return ["portrait" if p.image.height > p.image.width else "landscape" for p in parts]


@pytest.mark.parametrize(
    "name,shapes",
    [
        ("01_receipts_wood_table.jpg", ["portrait"] * 3),
        ("02_photos_on_scanner.jpg", ["landscape"] * 4),
        ("03_business_cards_desk.jpg", ["landscape"] * 4),
        ("04_phone_photo_perspective.jpg", ["portrait", "portrait", "landscape"]),
        ("05_white_receipts_on_white.jpg", ["portrait"] * 3),
    ],
)
def test_sample_items_are_found(name, shapes):
    parts = split(SAMPLES / name)
    assert _shapes(parts) == shapes
    assert all(p.method == "contour" for p in parts)


def test_sample_pdf_pages():
    parts = split(SAMPLES / "08_two_page_scan.pdf")
    assert [(p.page, p.index) for p in parts] == [(1, 1), (1, 2), (2, 1)]


def test_sample_single_document_stays_whole():
    parts = split(SAMPLES / "09_single_invoice.png")
    assert len(parts) == 1 and parts[0].method == "page"


def test_sample_limits_without_a_model():
    # touching receipts are seen as one item
    assert len(split(SAMPLES / "06_touching_receipts.jpg")) == 1
    # a receipt on its side is only straightened, not turned upright
    assert sorted(_shapes(split(SAMPLES / "07_upside_down_and_sideways.jpg"))) == ["landscape", "portrait"]
