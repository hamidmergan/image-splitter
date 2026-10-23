import io
import time
import zipfile

import pytest
from PIL import Image

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from image_splitter.config import resolve  # noqa: E402
from image_splitter.web.app import create_app  # noqa: E402
from scenes import Item, scene, three_receipts  # noqa: E402


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(resolve(), workdir=tmp_path / "uploads")) as c:
        yield c


def upload(client, *paths):
    files = [("files", (p.name, p.read_bytes(), "application/octet-stream")) for p in paths]
    return client.post("/api/files", files=files)


def wait_done(client, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = client.get("/api/state").json()
        if state["files"] and all(f["state"] == "done" for f in state["files"]):
            return state
        time.sleep(0.05)
    raise AssertionError("files did not finish in time")


def zip_names(response):
    return sorted(zipfile.ZipFile(io.BytesIO(response.content)).namelist())


def test_index_page(client):
    response = client.get("/")
    assert response.status_code == 200 and "image-splitter" in response.text
    assert client.get("/static/app.js").status_code == 200


def test_upload_detect_and_state(client, save):
    path = save("scan.jpg", scene(three_receipts()))
    assert upload(client, path).status_code == 200
    state = wait_done(client)
    assert state["vision"] is False
    entry = state["files"][0]
    assert entry["name"] == "scan.jpg" and entry["error"] is None
    page = entry["pages"][0]
    assert (page["width"], page["height"]) == (1600, 1200)
    assert [f["method"] for f in page["frames"]] == ["contour"] * 3
    assert "path" not in entry  # the server-side path is never shown


def test_page_and_part_previews(client, save):
    upload(client, save("scan.png", scene(three_receipts())))
    file_id = wait_done(client)["files"][0]["id"]
    page = client.get(f"/api/files/{file_id}/pages/1.jpg")
    assert page.status_code == 200 and page.headers["content-type"] == "image/jpeg"
    part = Image.open(io.BytesIO(client.get(f"/api/files/{file_id}/pages/1/frames/2.jpg").content))
    assert part.height > part.width  # a receipt, upright
    assert client.get(f"/api/files/{file_id}/pages/1/frames/9.jpg").status_code == 404
    assert client.get(f"/api/files/{file_id}/pages/2.jpg").status_code == 404


def test_edit_frames_rotate_and_reset(client, save):
    upload(client, save("scan.png", scene(three_receipts())))
    entry = wait_done(client)["files"][0]
    file_id, frames = entry["id"], entry["pages"][0]["frames"]
    # delete the last frame, turn the first one, draw a new one in shuffled corner order
    edited = [dict(frames[0], rotation=90), frames[1],
              {"corners": [[1500, 1100], [1300, 900], [1500, 900], [1300, 1100]], "method": "manual"}]
    response = client.put(f"/api/files/{file_id}/pages/1/frames", json={"frames": edited})
    assert response.status_code == 200
    saved = response.json()["pages"][0]["frames"]
    assert [f["rotation"] for f in saved] == [90, 0, 0]
    assert saved[2]["corners"] == [[1300, 900], [1500, 900], [1500, 1100], [1300, 1100]]
    turned = Image.open(io.BytesIO(client.get(f"/api/files/{file_id}/pages/1/frames/1.jpg").content))
    assert turned.width > turned.height
    reset = client.post(f"/api/files/{file_id}/pages/1/reset").json()
    assert reset["pages"][0]["frames"] == frames


@pytest.mark.parametrize(
    "frame",
    [
        {"corners": [[0, 0], [10, 0], [10, 10]]},
        {"corners": [[0, 0], [100, 0], [100, 100], [0, 100]], "rotation": 45},
        {"corners": [[0, 0], [100, 0], [100, 100], [0, 100]], "method": "magic"},
        {"corners": [[0, 0], [2, 0], [2, 2], [0, 2]]},
    ],
)
def test_invalid_frames_are_rejected(client, save, frame):
    upload(client, save("scan.png", scene(three_receipts())))
    file_id = wait_done(client)["files"][0]["id"]
    response = client.put(f"/api/files/{file_id}/pages/1/frames", json={"frames": [frame]})
    assert response.status_code == 400


def test_corners_outside_the_page_are_clipped(client, save):
    upload(client, save("scan.png", scene([], size=(400, 300))))
    file_id = wait_done(client)["files"][0]["id"]
    frame = {"corners": [[-50, -50], [500, -10], [500, 400], [-20, 400]]}
    saved = client.put(f"/api/files/{file_id}/pages/1/frames", json={"frames": [frame]}).json()
    assert saved["pages"][0]["frames"][0]["corners"] == [[0, 0], [400, 0], [400, 300], [0, 300]]


def test_download_zip_names(client, save):
    upload(client, save("scan.jpg", scene(three_receipts())),
           save("doc.pdf", scene(three_receipts()), scene([Item((800, 600), (500, 700))])))
    wait_done(client)
    response = client.get("/api/download")
    assert response.status_code == 200 and response.headers["content-type"] == "application/zip"
    assert zip_names(response) == ["doc_p1_1.jpg", "doc_p1_2.jpg", "doc_p1_3.jpg", "doc_p2_1.jpg",
                                   "scan_1.jpg", "scan_2.jpg", "scan_3.jpg"]
    assert zip_names(client.get("/api/download?format=png"))[0] == "doc_p1_1.png"
    assert client.get("/api/download?format=gif").status_code == 400


def test_download_same_name_twice(client, save, tmp_path):
    path = save("scan.png", scene([Item((800, 600), (500, 700))]))
    upload(client, path, path)
    wait_done(client)
    assert zip_names(client.get("/api/download")) == ["scan_1 (1).jpg", "scan_1.jpg"]


def test_samples_can_be_loaded(client):
    names = [f["name"] for f in client.post("/api/samples").json()["files"]]
    assert names[0] == "01_receipts_wood_table.jpg" and "08_two_page_scan.pdf" in names
    assert "generate.py" not in names
    state = wait_done(client)
    parts = {f["name"]: sum(len(p["frames"]) for p in f["pages"]) for f in state["files"]}
    assert parts["01_receipts_wood_table.jpg"] == 3 and parts["08_two_page_scan.pdf"] == 3


def test_samples_respect_max_files(tmp_path):
    with TestClient(create_app(resolve(max_files=2), workdir=tmp_path / "u")) as c:
        assert c.post("/api/samples").status_code == 413


def test_download_without_parts(client):
    assert client.get("/api/download").status_code == 409


def test_broken_file_reports_error(client, tmp_path):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image")
    upload(client, bad)
    entry = wait_done(client)["files"][0]
    assert entry["error"] and entry["pages"] == []


def test_remove_and_clear(client, save):
    upload(client, save("a.png", scene([])), save("b.png", scene([])))
    ids = [f["id"] for f in wait_done(client)["files"]]
    assert client.delete(f"/api/files/{ids[0]}").status_code == 200
    assert [f["id"] for f in client.get("/api/state").json()["files"]] == ids[1:]
    assert client.delete("/api/files/unknown").status_code == 404
    client.delete("/api/files")
    assert client.get("/api/state").json()["files"] == []


def test_max_files(tmp_path, save):
    with TestClient(create_app(resolve(max_files=1), workdir=tmp_path / "u")) as c:
        path = save("a.png", scene([]))
        assert upload(c, path, path).status_code == 413


def test_host_and_origin_guard(tmp_path):
    app = create_app(resolve(), workdir=tmp_path / "u", allowed_hosts=["127.0.0.1", "localhost"])
    with TestClient(app, base_url="http://localhost:8000") as c:
        assert c.get("/api/state").status_code == 200
        assert c.get("/api/state", headers={"host": "evil.example"}).status_code == 400
        assert c.get("/api/state", headers={"origin": "http://evil.example"}).status_code == 403
        assert c.get("/api/state", headers={"origin": "http://localhost:8000"}).status_code == 200
