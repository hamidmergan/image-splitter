import pytest
from PIL import Image

from image_splitter.cli import LOOPBACK, allowed_hosts, main
from scenes import Item, scene, three_receipts


def _names(folder):
    return sorted(p.name for p in folder.iterdir())


def test_writes_parts_next_to_input(save, tmp_path):
    save("scan.jpg", scene(three_receipts()))
    assert main([str(tmp_path / "scan.jpg")]) == 0
    assert _names(tmp_path) == ["scan.jpg", "scan_1.jpg", "scan_2.jpg", "scan_3.jpg"]
    assert Image.open(tmp_path / "scan_1.jpg").format == "JPEG"


def test_output_folder_format_and_debug(save, tmp_path, capsys):
    path = save("scan.png", scene(three_receipts()))
    out = tmp_path / "out"
    assert main([str(path), "-o", str(out), "--format", "png", "--debug"]) == 0
    assert _names(out) == ["scan_1.png", "scan_2.png", "scan_3.png", "scan_debug.jpg"]
    assert "Wrote" in capsys.readouterr().err


def test_pdf_pages_get_page_numbers(save, tmp_path):
    path = save("doc.pdf", scene(three_receipts()), scene([Item((800, 600), (500, 700))]))
    out = tmp_path / "out"
    assert main([str(path), "-o", str(out), "--pdf-dpi", "72"]) == 0
    assert _names(out) == ["doc_p1_1.jpg", "doc_p1_2.jpg", "doc_p1_3.jpg", "doc_p2_1.jpg"]


def test_same_stem_uses_full_name_and_existing_files_are_kept(save, tmp_path):
    save("a.png", scene([Item((800, 600), (500, 700))]))
    save("a.jpg", scene([Item((800, 600), (500, 700))]))
    out = tmp_path / "out"
    out.mkdir()
    (out / "a_png_1.jpg").write_bytes(b"old")
    assert main([str(tmp_path / "a.png"), str(tmp_path / "a.jpg"), "-o", str(out)]) == 0
    assert _names(out) == ["a_jpg_1.jpg", "a_png_1 (1).jpg", "a_png_1.jpg"]
    assert (out / "a_png_1.jpg").read_bytes() == b"old"


def test_whole_page_kept_with_note(save, tmp_path, capsys):
    path = save("blank.png", scene([], size=(400, 300)))
    assert main([str(path)]) == 0
    assert "kept the whole page" in capsys.readouterr().err
    assert Image.open(tmp_path / "blank_1.jpg").size == (400, 300)


def test_failed_file_gives_exit_code_1(save, tmp_path, capsys):
    good = save("good.png", scene(three_receipts()))
    assert main([str(good), str(tmp_path / "missing.png")]) == 1
    assert "missing.png" in capsys.readouterr().err
    assert (tmp_path / "good_1.jpg").exists()


def test_incomplete_model_settings_give_exit_code_2(save, capsys):
    path = save("scan.png", scene(three_receipts()))
    assert main([str(path), "--base-url", "http://localhost:11434/v1"]) == 2
    assert "model" in capsys.readouterr().err


def test_no_vision_ignores_model_settings(save):
    path = save("scan.png", scene(three_receipts()))
    assert main([str(path), "--base-url", "http://localhost:11434/v1", "--no-vision"]) == 0


def test_vision_through_cli(server, save, tmp_path):
    server.rotation = "90"
    path = save("card.png", scene([Item((800, 600), (500, 300))]))
    assert main([str(path), "--base-url", server.base_url, "--model", "vm"]) == 0
    assert Image.open(tmp_path / "card_1.jpg").size[0] < Image.open(tmp_path / "card_1.jpg").size[1]
    assert {r["body"]["model"] for r in server.requests} == {"vm"}


def test_output_must_be_folder(save, tmp_path):
    path = save("scan.png", scene([]))
    target = tmp_path / "file.txt"
    target.write_text("x")
    assert main([str(path), "-o", str(target)]) == 2


@pytest.mark.parametrize(
    "host,raw,expected",
    [
        ("127.0.0.1", None, list(LOOPBACK)),
        ("0.0.0.0", None, None),
        ("0.0.0.0", "localhost, 127.0.0.1", ["localhost", "127.0.0.1"]),
        ("0.0.0.0", "*", None),
        ("127.0.0.1", "Scanner.Local", ["scanner.local"]),
    ],
)
def test_allowed_hosts(host, raw, expected):
    assert allowed_hosts(host, raw) == expected
