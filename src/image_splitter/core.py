from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

import numpy as np

from . import config, detect, vision
from .errors import LimitError, SplitError
from .loader import load_pages, to_rgb

PathLike = Union[str, Path]


@dataclass
class Part:
    """One item cut out of a page."""

    image: "object"  # PIL.Image.Image, RGB
    page: int  # 1-based page number
    index: int  # 1-based position on the page, in reading order
    corners: List[Tuple[float, float]]  # top-left, top-right, bottom-right, bottom-left in page pixels
    method: str  # "contour", "vision", "box" or "page"
    rotation: int = 0  # clockwise degrees applied after cutting out


@dataclass
class Result:
    path: str
    parts: List[Part] = field(default_factory=list)
    pages: int = 0
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _locate(page: np.ndarray, pil_page, settings: config.Settings, client) -> List[Tuple[np.ndarray, str]]:
    """Quads with the method that found them."""
    found = [(q, "contour") for q in detect.find_quads(page, settings.min_area)]
    if not settings.vision:
        return found
    boxes = vision.find_boxes(client, settings, pil_page)
    # OpenCV is more precise, so the model only decides when the counts differ:
    # items merged or missed by OpenCV, or details of a single document taken for items
    if not boxes or len(boxes) == len(found):
        return found
    h, w = page.shape[:2]
    located = []
    for x0, y0, x1, y1 in boxes:
        box = (x0 * w, y0 * h, x1 * w, y1 * h)
        quad = detect.refine_box(page, box)
        located.append((quad, "vision") if quad is not None else (detect.box_quad(box), "box"))
    return located


def _rotate(image, degrees: int):
    """Turn clockwise. PIL's ROTATE_* constants turn counter-clockwise."""
    from PIL import Image

    clockwise = {
        90: Image.Transpose.ROTATE_270,
        180: Image.Transpose.ROTATE_180,
        270: Image.Transpose.ROTATE_90,
    }
    return image.transpose(clockwise[degrees]) if degrees in clockwise else image


def cut(page, corners: Sequence[Sequence[float]], rotation: int = 0, padding: int = 0, trim: bool = False):
    """Cut one item out of a page (PIL image or RGB array) along four corners
    (top-left first) and turn it clockwise by `rotation` degrees.

    `trim` removes thin slivers of background along the edges.
    """
    from PIL import Image

    page = np.asarray(to_rgb(page) if isinstance(page, Image.Image) else page)
    image = detect.warp(page, np.float32(corners), padding)
    if trim:
        colour, threshold = detect.background(page)
        image = detect.trim_edges(image, colour, threshold)
    return _rotate(Image.fromarray(image), rotation)


def _split_page(pil_page, number: int, settings: config.Settings, client) -> List[Part]:
    pil_page = to_rgb(pil_page)
    page = np.asarray(pil_page)
    located = _locate(page, pil_page, settings, client)
    if not located:
        h, w = page.shape[:2]
        located = [(detect.box_quad((0, 0, w, h)), "page")]

    order = detect.reading_order([q for q, _ in located])
    colour, threshold = detect.background(page)
    parts = []
    for index, i in enumerate(order, start=1):
        quad, method = located[i]
        # a model box or the whole page has no measured outline to sharpen
        outlined = method in ("contour", "vision")
        if outlined:
            quad = detect.refine_quad(page, quad, colour, threshold)
        image = cut(page, quad, padding=settings.padding, trim=outlined and settings.padding == 0)
        corners = [(float(x), float(y)) for x, y in quad]
        parts.append(Part(image, number, index, corners, method))

    if settings.vision and settings.orient:
        workers = max(1, min(settings.concurrency, len(parts)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            # map returns the results in input order
            turns = list(pool.map(lambda p: vision.find_rotation(client, settings, p.image), parts))
        for part, degrees in zip(parts, turns):
            part.image = _rotate(part.image, degrees)
            part.rotation = degrees
    return parts


def _client(settings: config.Settings, client):
    if not settings.vision:
        return None
    return client or vision.make_client(settings)


def split_image(image, *, client=None, **options) -> List[Part]:
    """Split one page (PIL image or RGB numpy array) into its items.

    If no item is found, the whole page is returned as one part (method "page").
    Settings (min_area, padding, base_url, model, ...) are keyword arguments.
    """
    from PIL import Image

    settings = config.resolve(**options)
    if isinstance(image, np.ndarray):
        image = Image.fromarray(image)
    return _split_page(image, 1, settings, _client(settings, client))


def _split_file(path: Path, settings: config.Settings, client) -> Tuple[List[Part], int]:
    pages = load_pages(path, settings)
    parts: List[Part] = []
    for number, page in enumerate(pages, start=1):
        parts.extend(_split_page(page, number, settings, client))
    return parts, len(pages)


def split(path: PathLike, *, client=None, **options) -> List[Part]:
    """Split an image or every page of a PDF into its items.

    Errors are raised as exceptions (subclasses of SplitError).
    """
    settings = config.resolve(**options)
    parts, _ = _split_file(Path(path), settings, _client(settings, client))
    return parts


def split_many(paths: Iterable[PathLike], *, client=None, **options) -> Dict[str, Result]:
    """Process several files one by one and return a Result per file.

    The input order is preserved. If one file fails,
    the rest continues and the error is stored in that file's Result.
    """
    settings = config.resolve(**options)
    path_list = [Path(p) for p in paths]
    if len(path_list) > settings.max_files:
        raise LimitError(
            f"{len(path_list)} files given. The limit is "
            f"{settings.max_files} (max_files)."
        )
    keys = [str(p) for p in path_list]
    if len(set(keys)) != len(keys):
        raise LimitError("The same file was given more than once.")

    client = _client(settings, client)
    results: Dict[str, Result] = {}
    for path in path_list:
        key = str(path)
        try:
            parts, pages = _split_file(path, settings, client)
            results[key] = Result(key, parts=parts, pages=pages)
        except SplitError as exc:
            results[key] = Result(key, error=str(exc))
    return results


def draw_parts(page, parts: Sequence[Part]):
    """Copy of a page with the outline and number of each part, for checking results."""
    from PIL import Image

    quads = [np.float32(p.corners) for p in parts]
    return Image.fromarray(detect.draw_quads(np.asarray(to_rgb(page)), quads))
