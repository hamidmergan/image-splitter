"""Web API for the editor page: upload scans, find items in the background,
correct the frames by hand and download the parts as a ZIP."""

import io
import math
import re
import tempfile
import threading
import uuid
import zipfile
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlsplit

import numpy as np
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import detect
from ..cli import FORMATS, part_name, save_image, stems
from ..config import Settings
from ..core import _client, _split_page, cut
from ..loader import load_page, load_pages, sample_files

STATIC = Path(__file__).parent / "static"
PREVIEW_SIDE = 2000  # longest side of the page shown in the editor
THUMB_SIDE = 480  # longest side of a part preview
CACHED_PAGES = 6
MAX_PARTS = 200
ROTATIONS = (0, 90, 180, 270)
METHODS = ("contour", "vision", "box", "page", "manual")
_SUFFIX = re.compile(r"\.[a-z0-9]{1,10}")


@dataclass
class Frame:
    corners: List[List[float]]  # top-left, top-right, bottom-right, bottom-left in page pixels
    rotation: int = 0
    method: str = "manual"

    def to_dict(self) -> Dict[str, Any]:
        return {"corners": self.corners, "rotation": self.rotation, "method": self.method}


@dataclass
class PageEntry:
    width: int
    height: int
    frames: List[Frame]
    detected: List[Frame]  # what the detection found, for "reset"


@dataclass
class FileEntry:
    id: str
    name: str
    path: Path
    state: str = "pending"  # pending, running or done
    error: Optional[str] = None
    pages: List[PageEntry] = field(default_factory=list)


class FrameIn(BaseModel):
    corners: List[List[float]]
    rotation: int = 0
    method: str = "manual"


class FramesIn(BaseModel):
    frames: List[FrameIn]


def _entry_dict(entry: FileEntry) -> Dict[str, Any]:
    pages = [{"width": p.width, "height": p.height, "frames": [f.to_dict() for f in p.frames]} for p in entry.pages]
    return {"id": entry.id, "name": entry.name, "state": entry.state, "error": entry.error, "pages": pages}


def _hostname(host: str) -> str:
    if host.startswith("["):
        return host[1:host.find("]")].lower()
    return host.rsplit(":", 1)[0].lower() if host.count(":") == 1 else host.lower()


def _suffix(name: str) -> str:
    suffix = Path(name).suffix.lower()
    return suffix if _SUFFIX.fullmatch(suffix) else ""


def _jpeg(image, side: int, quality: int = 85) -> bytes:
    from PIL import Image

    longest = max(image.size)
    if longest > side:
        factor = side / longest
        image = image.resize((max(1, round(image.width * factor)), max(1, round(image.height * factor))),
                             Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


def _frame(data: FrameIn, width: int, height: int) -> Frame:
    """Check a frame from the page and bring its corners into the usual order."""
    if len(data.corners) != 4 or any(len(c) != 2 for c in data.corners):
        raise HTTPException(400, "A frame needs four corners with x and y.")
    if any(not math.isfinite(v) for c in data.corners for v in c):
        raise HTTPException(400, "Corners must be numbers.")
    if data.rotation not in ROTATIONS:
        raise HTTPException(400, f"Rotation must be one of {ROTATIONS}.")
    if data.method not in METHODS:
        raise HTTPException(400, f"Unknown method {data.method!r}.")
    points = np.clip(np.float32(data.corners), [0, 0], [width, height])
    quad = detect.order_quad(points)
    if detect.quad_area(quad) < 16:
        raise HTTPException(400, "A frame is too small.")
    return Frame([[float(x), float(y)] for x, y in quad], data.rotation, data.method)


def create_app(settings: Settings, workdir: Optional[Path] = None,
               allowed_hosts: Optional[Sequence[str]] = None) -> FastAPI:
    """The editor page and its JSON API, with one in-memory workspace.

    `allowed_hosts` limits the Host header (against DNS rebinding);
    requests from another origin are always refused.
    """
    tmp = None if workdir is not None else tempfile.TemporaryDirectory(prefix="image-splitter-")
    uploads = Path(workdir) if workdir is not None else Path(tmp.name)
    uploads.mkdir(parents=True, exist_ok=True)
    files: Dict[str, FileEntry] = {}
    cache: "OrderedDict[tuple, Any]" = OrderedDict()
    lock = threading.Lock()
    pool = ThreadPoolExecutor(2)
    client_holder: Dict[str, Any] = {}

    def client():
        with lock:
            if "client" not in client_holder:
                client_holder["client"] = _client(settings, None)
            return client_holder["client"]

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        pool.shutdown(wait=False, cancel_futures=True)
        if tmp is not None:
            tmp.cleanup()

    app = FastAPI(title="image-splitter", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    hosts = {h.lower() for h in allowed_hosts} if allowed_hosts is not None else None

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = request.headers.get("host", "")
        if hosts is not None and _hostname(host) not in hosts:
            return PlainTextResponse("Unknown host", status_code=400)
        origin = request.headers.get("origin")
        own = {host.lower(), request.headers.get("x-forwarded-host", "").lower()}  # also behind a reverse proxy
        if origin is not None and urlsplit(origin).netloc.lower() not in own:
            return PlainTextResponse("Cross-origin requests are not allowed", status_code=403)
        return await call_next(request)

    def entry_or_404(file_id: str) -> FileEntry:
        with lock:
            entry = files.get(file_id)
        if entry is None:
            raise HTTPException(404, f"Unknown file id {file_id!r}")
        return entry

    def page_or_404(entry: FileEntry, n: int) -> PageEntry:
        if entry.state != "done" or not 1 <= n <= len(entry.pages):
            raise HTTPException(404, f"No page {n} in {entry.name}")
        return entry.pages[n - 1]

    def page_image(entry: FileEntry, n: int):
        """Full-size page, from a small cache because rendering a PDF page takes a while."""
        key = (entry.id, n)
        with lock:
            if key in cache:
                cache.move_to_end(key)
                return cache[key]
        image = load_page(entry.path, settings, n)
        with lock:
            cache[key] = image
            while len(cache) > CACHED_PAGES:
                cache.popitem(last=False)
        return image

    def split_job(entry: FileEntry) -> None:
        with lock:
            entry.state = "running"
        try:
            pages = []
            for number, image in enumerate(load_pages(entry.path, settings), start=1):
                parts = _split_page(image, number, settings, client())
                found = [Frame([list(c) for c in p.corners], p.rotation, p.method) for p in parts]
                pages.append(PageEntry(image.width, image.height, found, [Frame(**f.to_dict()) for f in found]))
            error = None
        except Exception as e:  # one broken file must not stop the others
            pages, error = [], f"{type(e).__name__}: {e}"
        with lock:
            entry.pages, entry.error, entry.state = pages, error, "done"

    def render(entry: FileEntry, n: int, frame: Frame):
        # only an untouched outline found by OpenCV is trimmed, as on the command line
        trim = frame.method in ("contour", "vision") and settings.padding == 0
        return cut(page_image(entry, n), frame.corners, frame.rotation, settings.padding, trim)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html", media_type="text/html")

    def check_count(adding: int) -> None:
        with lock:
            total = len(files) + adding
        if total > settings.max_files:
            raise HTTPException(413, f"{total} files in total, the limit is {settings.max_files} "
                                     "(raise it with --max-files)")

    def add(name: str, data: bytes) -> FileEntry:
        file_id = uuid.uuid4().hex
        path = uploads / f"{file_id}{_suffix(name)}"
        path.write_bytes(data)
        return FileEntry(id=file_id, name=name, path=path)

    def start(entries: List[FileEntry]) -> Dict[str, Any]:
        with lock:
            for entry in entries:
                files[entry.id] = entry
                pool.submit(split_job, entry)
            return {"files": [_entry_dict(e) for e in entries]}

    @app.post("/api/files")
    async def upload(uploaded: List[UploadFile] = File(..., alias="files")) -> Dict[str, Any]:
        check_count(len(uploaded))
        entries = []
        for upload_file in uploaded:
            name = Path(upload_file.filename or "file").name or "file"
            entries.append(add(name, await upload_file.read()))
        return start(entries)

    @app.post("/api/samples")
    def samples() -> Dict[str, Any]:
        """Add the sample images that come with the package, to try the page without own files."""
        paths = sample_files()
        check_count(len(paths))
        return start([add(p.name, p.read_bytes()) for p in paths])

    @app.get("/api/state")
    def state() -> Dict[str, Any]:
        with lock:
            return {"files": [_entry_dict(e) for e in files.values()], "vision": settings.vision}

    @app.delete("/api/files")
    def clear() -> Dict[str, Any]:
        with lock:
            entries = list(files.values())
            files.clear()
            cache.clear()
        for entry in entries:
            entry.path.unlink(missing_ok=True)
        return {"files": []}

    @app.delete("/api/files/{file_id}")
    def remove(file_id: str) -> Dict[str, Any]:
        entry = entry_or_404(file_id)
        with lock:
            files.pop(file_id, None)
            for key in [k for k in cache if k[0] == file_id]:
                del cache[key]
        entry.path.unlink(missing_ok=True)
        return {"removed": file_id}

    @app.get("/api/files/{file_id}/pages/{n}.jpg")
    def page_jpeg(file_id: str, n: int) -> Response:
        entry = entry_or_404(file_id)
        page_or_404(entry, n)
        return Response(_jpeg(page_image(entry, n), PREVIEW_SIDE), media_type="image/jpeg",
                        headers={"Cache-Control": "private, max-age=3600"})

    @app.put("/api/files/{file_id}/pages/{n}/frames")
    def set_frames(file_id: str, n: int, body: FramesIn) -> Dict[str, Any]:
        entry = entry_or_404(file_id)
        page = page_or_404(entry, n)
        if len(body.frames) > MAX_PARTS:
            raise HTTPException(400, f"At most {MAX_PARTS} frames per page.")
        frames = [_frame(f, page.width, page.height) for f in body.frames]
        with lock:
            page.frames = frames
            return _entry_dict(entry)

    @app.post("/api/files/{file_id}/pages/{n}/reset")
    def reset(file_id: str, n: int) -> Dict[str, Any]:
        entry = entry_or_404(file_id)
        page = page_or_404(entry, n)
        with lock:
            page.frames = [Frame(**f.to_dict()) for f in page.detected]
            return _entry_dict(entry)

    @app.get("/api/files/{file_id}/pages/{n}/frames/{i}.jpg")
    def part_jpeg(file_id: str, n: int, i: int) -> Response:
        entry = entry_or_404(file_id)
        page = page_or_404(entry, n)
        with lock:
            frame = page.frames[i - 1] if 1 <= i <= len(page.frames) else None
        if frame is None:
            raise HTTPException(404, f"No frame {i} on page {n}")
        return Response(_jpeg(render(entry, n, frame), THUMB_SIDE), media_type="image/jpeg")

    @app.get("/api/download")
    def download(format: str = "jpg", quality: int = 95) -> Response:
        if format not in FORMATS:
            raise HTTPException(400, f"Unknown format {format!r}; use one of: {', '.join(FORMATS)}")
        if not 1 <= quality <= 100:
            raise HTTPException(400, "quality must be between 1 and 100")
        with lock:
            done = [e for e in files.values() if e.state == "done" and e.pages]
            # file names: the stem, or the full name if two uploads share a stem
            names = stems([e.name for e in done]) if len({e.name for e in done}) == len(done) else {}
            jobs = [(e, n, list(p.frames), len(e.pages)) for e in done for n, p in enumerate(e.pages, start=1)]
        if not any(frames for _, _, frames, _ in jobs):
            raise HTTPException(409, "There are no parts to download yet.")
        buffer = io.BytesIO()
        used = set()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
            for entry, n, frames, pages in jobs:
                stem = names.get(entry.name) or Path(entry.name).stem or "file"
                for i, frame in enumerate(frames, start=1):
                    name = part_name(stem, n, i, pages, format)
                    base, k = name, 1
                    while name in used:  # two uploads with the same name
                        name = f"{Path(base).stem} ({k}){Path(base).suffix}"
                        k += 1
                    used.add(name)
                    data = io.BytesIO()
                    save_image(render(entry, n, frame), data, FORMATS[format], quality)
                    archive.writestr(name, data.getvalue())
        return Response(buffer.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": 'attachment; filename="parts.zip"'})

    return app
