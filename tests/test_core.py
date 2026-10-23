import numpy as np
import pytest
from PIL import Image

from image_splitter import LimitError, UnsupportedFileError, draw_parts, split, split_image, split_many
from scenes import Item, scene, three_receipts, top_is_dark


def test_split_image_returns_parts_in_reading_order():
    parts = split_image(scene(three_receipts()))
    assert [p.index for p in parts] == [1, 2, 3]
    assert [p.page for p in parts] == [1, 1, 1]
    assert all(p.method == "contour" and p.rotation == 0 for p in parts)
    xs = [np.mean([c[0] for c in p.corners]) for p in parts]
    assert xs == sorted(xs)
    for part in parts:
        assert part.image.mode == "RGB"
        assert top_is_dark(np.asarray(part.image))


def test_split_image_accepts_pil_and_other_modes():
    page = Image.fromarray(scene(three_receipts())).convert("RGBA")
    assert len(split_image(page)) == 3


def test_nothing_found_keeps_whole_page():
    parts = split_image(scene([], size=(800, 600)))
    assert len(parts) == 1
    assert parts[0].method == "page"
    assert parts[0].image.size == (800, 600)


def test_padding_option():
    plain = split_image(scene(three_receipts()))[0].image
    padded = split_image(scene(three_receipts()), padding=20)[0].image
    assert padded.width >= plain.width + 38


def test_split_image_file(save):
    path = save("scan.jpg", scene(three_receipts()))
    assert len(split(path)) == 3


def test_split_pdf_pages(save):
    path = save("scan.pdf", scene(three_receipts()), scene([Item((800, 600), (500, 700), angle=8)]))
    parts = split(path, pdf_dpi=72)
    assert [(p.page, p.index) for p in parts] == [(1, 1), (1, 2), (1, 3), (2, 1)]


def test_max_pages(save):
    path = save("scan.pdf", scene([]), scene([]))
    with pytest.raises(LimitError):
        split(path, max_pages=1)


def test_unsupported_and_missing_files(tmp_path):
    other = tmp_path / "notes.txt"
    other.write_text("x")
    with pytest.raises(UnsupportedFileError):
        split(other)
    with pytest.raises(UnsupportedFileError):
        split(tmp_path / "missing.png")


def test_broken_image(tmp_path):
    path = tmp_path / "broken.png"
    path.write_bytes(b"not an image")
    with pytest.raises(UnsupportedFileError):
        split(path)


def test_split_many_keeps_order_and_isolates_errors(save, tmp_path):
    a = save("a.png", scene(three_receipts()))
    b = tmp_path / "missing.jpg"
    c = save("c.png", scene([Item((800, 600), (500, 700))]))
    results = split_many([a, b, c])
    assert list(results) == [str(a), str(b), str(c)]
    assert [len(r.parts) for r in results.values()] == [3, 0, 1]
    assert [r.ok for r in results.values()] == [True, False, True]
    assert results[str(a)].pages == 1


def test_split_many_limits(save):
    a = save("a.png", scene([]))
    with pytest.raises(LimitError):
        split_many([a, a])
    with pytest.raises(LimitError):
        split_many([a, save("b.png", scene([]))], max_files=1)


def test_draw_parts():
    page = scene(three_receipts())
    out = draw_parts(Image.fromarray(page), split_image(page))
    assert out.size == (page.shape[1], page.shape[0])
