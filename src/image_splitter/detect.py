"""Find items on a page with classic image processing (OpenCV) and cut them out straight.

All functions take and return RGB arrays. A quad is a float32 array of shape (4, 2)
with the corners in page pixels, ordered top-left, top-right, bottom-right, bottom-left.
"""

from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

WORK_SIDE = 1000  # detection runs on a copy with this longest side
BORDER = 0.03  # share of the page edge used to estimate the background colour
MAX_AREA = 0.97  # a contour this large is the page itself, not an item
NOISE_MARGIN = 6.0  # colour distance above the background noise that counts as an item
SHADOW = 0.55  # darker than the background down to this share of its lightness, same tint: a shadow


def _shrink(image: np.ndarray) -> Tuple[np.ndarray, float]:
    h, w = image.shape[:2]
    scale = min(1.0, WORK_SIDE / max(h, w))
    if scale < 1.0:
        size = (max(1, round(w * scale)), max(1, round(h * scale)))
        image = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
    return image, scale


def _kernel(shape: Tuple[int, int], share: float) -> np.ndarray:
    k = max(3, round(min(shape) * share)) | 1
    return cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))


def _fill_holes(mask: np.ndarray) -> np.ndarray:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(mask)
    cv2.drawContours(filled, contours, -1, 255, thickness=cv2.FILLED)
    return filled


def _lab(image: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(image, cv2.COLOR_RGB2LAB).astype(np.float32)
    return cv2.GaussianBlur(lab, (3, 3), 0)


def _background(lab: np.ndarray) -> Tuple[np.ndarray, float]:
    """Background colour (Lab) from the page edge, and the colour distance above which
    a pixel counts as part of an item."""
    h, w = lab.shape[:2]
    b = max(2, round(min(h, w) * BORDER))
    border = np.concatenate(
        [lab[:b].reshape(-1, 3), lab[-b:].reshape(-1, 3), lab[:, :b].reshape(-1, 3), lab[:, -b:].reshape(-1, 3)]
    )
    colour = np.median(border, axis=0)
    # the median is robust against items that touch the page edge
    noise = 2.5 * float(np.median(np.linalg.norm(border - colour, axis=1)))
    return colour, noise + NOISE_MARGIN


def background(image: np.ndarray) -> Tuple[np.ndarray, float]:
    """Background colour and threshold of a page, see trim_edges."""
    return _background(_lab(_shrink(image)[0]))


def _distance(lab: np.ndarray, colour: np.ndarray, threshold: float) -> np.ndarray:
    """Colour distance of each pixel to the background.

    Shadows are only darker than the background but keep its tint, so for them only
    the tint counts. Otherwise the shadow next to an item would be cut out with it.
    Less light shrinks a* and b* together with L* + 16, so the tint is compared after
    scaling the background's a* and b* by the same factor.
    """
    dist = np.linalg.norm(lab - colour, axis=-1)
    lightness = lab[..., 0]
    # OpenCV stores L* as 0..255 and a*, b* shifted by 128
    scale = (lightness * 100 / 255 + 16) / (colour[0] * 100 / 255 + 16)
    expected = (colour[1:] - 128) * scale[..., None]
    tint = np.linalg.norm(lab[..., 1:] - 128 - expected, axis=-1)
    shadow = (lightness < colour[0]) & (lightness >= SHADOW * colour[0]) & (tint <= threshold)
    return np.where(shadow, tint, dist)


def _colour_mask(small: np.ndarray) -> np.ndarray:
    """Pixels whose colour differs clearly from the background at the page edge."""
    lab = _lab(small)
    colour, threshold = _background(lab)
    dist = _distance(lab, colour, threshold)
    return np.where(dist > threshold, 255, 0).astype(np.uint8)


def _edge_mask(small: np.ndarray) -> np.ndarray:
    """Closed outlines, for items whose colour is close to the background."""
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 10, 30)
    return cv2.dilate(edges, _kernel(gray.shape, 0.004))


def _blobs(mask: np.ndarray, min_area: float) -> List[np.ndarray]:
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, _kernel(mask.shape, 0.006))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, _kernel(mask.shape, 0.006))
    mask = _fill_holes(mask)
    # remove thin bridges and dust that survived the closing
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, _kernel(mask.shape, 0.012))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    page = mask.shape[0] * mask.shape[1]
    return [c for c in contours if min_area * page <= cv2.contourArea(c) <= MAX_AREA * page]


def order_quad(points) -> np.ndarray:
    """Order four corners so that the top edge needs the smallest rotation to be level."""
    pts = np.asarray(points, dtype=np.float32).reshape(4, 2)
    centre = pts.mean(axis=0)
    # with y pointing down, ascending angles run clockwise on screen
    pts = pts[np.argsort(np.arctan2(pts[:, 1] - centre[1], pts[:, 0] - centre[0]))]

    def tilt(start: int) -> float:
        dx, dy = pts[(start + 1) % 4] - pts[start]
        return abs(np.arctan2(dy, dx))

    best = min(range(4), key=tilt)
    return np.roll(pts, -best, axis=0)


def quad_from_contour(contour: np.ndarray) -> np.ndarray:
    """Four corners: the real corners if the outline is a clean quadrilateral
    (keeps perspective), otherwise the smallest rotated rectangle around it."""
    hull = cv2.convexHull(contour)
    hull_area = cv2.contourArea(hull)
    perimeter = cv2.arcLength(hull, True)
    for eps in (0.02, 0.03, 0.04):
        approx = cv2.approxPolyDP(hull, eps * perimeter, True)
        if len(approx) == 4 and cv2.isContourConvex(approx) and cv2.contourArea(approx) >= 0.95 * hull_area:
            return order_quad(approx)
    return order_quad(cv2.boxPoints(cv2.minAreaRect(hull)))


def find_quads(image: np.ndarray, min_area: float) -> List[np.ndarray]:
    """Return one quad per item found, in page pixels, in no particular order."""
    small, scale = _shrink(image)
    blobs = _blobs(_colour_mask(small), min_area)
    if not blobs:
        blobs = _blobs(_edge_mask(small), min_area)
    return [quad_from_contour(c) / scale for c in blobs]


def quad_area(quad: np.ndarray) -> float:
    return float(cv2.contourArea(np.asarray(quad, dtype=np.float32)))


def refine_box(image: np.ndarray, box: Sequence[float]) -> Optional[np.ndarray]:
    """Find the exact outline of the one item inside a rough box (x0, y0, x1, y1).

    Returns None if nothing in the box looks like that item.
    """
    h, w = image.shape[:2]
    x0, y0, x1, y1 = box
    mx, my = (x1 - x0) * 0.1, (y1 - y0) * 0.1
    cx0, cy0 = max(0, int(x0 - mx)), max(0, int(y0 - my))
    cx1, cy1 = min(w, int(x1 + mx) + 1), min(h, int(y1 + my) + 1)
    if cx1 - cx0 < 8 or cy1 - cy0 < 8:
        return None
    quads = find_quads(image[cy0:cy1, cx0:cx1], min_area=0.2)
    if not quads:
        return None
    best = max(quads, key=quad_area)
    box_area = (x1 - x0) * (y1 - y0)
    if not 0.5 * box_area <= quad_area(best) <= 1.3 * box_area:
        return None
    return best + np.float32([cx0, cy0])


def box_quad(box: Sequence[float]) -> np.ndarray:
    x0, y0, x1, y1 = box
    return np.float32([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])


def reading_order(quads: Sequence[np.ndarray]) -> List[int]:
    """Indexes of the quads in reading order: rows from top to bottom, left to right in a row."""
    spans = [(q[:, 1].min(), q[:, 1].max(), q[:, 0].mean(), q[:, 1].mean()) for q in quads]
    rows: List[List[int]] = []
    row_top = row_bottom = 0.0
    for i in sorted(range(len(quads)), key=lambda i: spans[i][0]):
        top, bottom, _, middle = spans[i]
        if rows and middle <= row_bottom and top < (row_top + row_bottom) / 2:
            rows[-1].append(i)
            row_bottom = max(row_bottom, bottom)
        else:
            rows.append([i])
            row_top, row_bottom = top, bottom
    return [i for row in rows for i in sorted(row, key=lambda i: spans[i][2])]


def warp(image: np.ndarray, quad: np.ndarray, padding: int = 0) -> np.ndarray:
    """Cut out the quad and map it onto an upright rectangle."""
    tl, tr, br, bl = np.asarray(quad, dtype=np.float32)
    width = round((np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2)
    height = round((np.linalg.norm(bl - tl) + np.linalg.norm(br - tr)) / 2)
    out_w, out_h = max(1, width + 2 * padding), max(1, height + 2 * padding)
    p = float(padding)
    target = np.float32([[p, p], [p + width, p], [p + width, p + height], [p, p + height]])
    matrix = cv2.getPerspectiveTransform(np.float32([tl, tr, br, bl]), target)
    return cv2.warpPerspective(
        image, matrix, (out_w, out_h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )


def _intersect(a: Tuple[np.ndarray, np.ndarray], b: Tuple[np.ndarray, np.ndarray]) -> Optional[np.ndarray]:
    (p, r), (q, s) = a, b
    cross = r[0] * s[1] - r[1] * s[0]
    if abs(cross) < 1e-6:
        return None
    t = ((q[0] - p[0]) * s[1] - (q[1] - p[1]) * s[0]) / cross
    return p + t * r


def refine_quad(image: np.ndarray, quad: np.ndarray, colour: np.ndarray, threshold: float) -> np.ndarray:
    """Move each edge of a quad onto the real item edge, measured at full resolution.

    Detection runs on a smaller copy, so its corners are off by a few pixels. Here
    short profiles across every edge are sampled, the colour change in each profile
    is located, and a line is fitted through those points. Edges without a clear
    colour change keep their position.
    """
    quad = np.asarray(quad, dtype=np.float32)
    reach = max(4.0, 0.006 * max(image.shape[:2]))
    steps = np.arange(-reach, reach + 0.25, 0.5, dtype=np.float32)
    samples = np.linspace(0.1, 0.9, 40, dtype=np.float32)
    centre = quad.mean(axis=0)

    lines = []
    for i in range(4):
        p0, p1 = quad[i], quad[(i + 1) % 4]
        direction = (p1 - p0) / max(float(np.linalg.norm(p1 - p0)), 1e-6)
        normal = np.float32([direction[1], -direction[0]])
        if np.dot(normal, (p0 + p1) / 2 - centre) < 0:
            normal = -normal  # point outwards
        base = p0 + np.outer(samples, p1 - p0)
        coords = base[:, None, :] + steps[None, :, None] * normal
        profile = cv2.remap(
            image, coords[..., 0], coords[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE
        )
        lab = cv2.cvtColor(profile, cv2.COLOR_RGB2LAB).astype(np.float32)
        dist = cv2.blur(_distance(lab, colour, threshold), (3, 1))
        half = len(steps) // 2
        points = []
        for k in range(len(samples)):
            inner, outer = np.median(dist[k, :half]), np.median(dist[k, half:])
            if inner - outer < 0.5 * threshold:
                continue
            middle = (inner + outer) / 2
            # walk inwards from outside and stop at the first pixel that belongs to the item
            above = np.nonzero(dist[k, ::-1] >= middle)[0]
            if not len(above):
                continue
            j = len(steps) - 1 - above[0]
            points.append(base[k] + steps[j] * normal)
        if len(points) < 8:
            lines.append((p0, direction))
            continue
        vx, vy, x, y = cv2.fitLine(np.float32(points), cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
        lines.append((np.float32([x, y]), np.float32([vx, vy])))

    refined = []
    for i in range(4):
        corner = _intersect(lines[i - 1], lines[i])
        if corner is None or np.linalg.norm(corner - quad[i]) > 2 * reach:
            corner = quad[i]
        refined.append(corner)
    return np.float32(refined)


def trim_edges(part: np.ndarray, colour: np.ndarray, threshold: float, limit: float = 0.03) -> np.ndarray:
    """Cut off thin slivers of background along the edges of a cut-out part.

    A line is a sliver if its colour is clearly closer to the background than the
    lines just inside it (edges are blurred, so a plain threshold would miss them).
    At most `limit` of the width or height is removed per side.
    """
    dist = _distance(_lab(part), colour, threshold)
    h, w = dist.shape

    def count(lines: np.ndarray, most: int) -> int:
        if most < 1:
            return 0
        medians = np.median(lines[: 2 * most], axis=1)
        inside = float(np.median(medians[most:]))
        if inside < 2 * threshold:
            return 0  # the part looks like the background, nothing to compare with
        n = 0
        while n < most and medians[n] < 0.8 * inside:
            n += 1
        return n

    my, mx = int(h * limit), int(w * limit)
    top, bottom = count(dist, my), count(dist[::-1], my)
    left, right = count(dist.T, mx), count(dist.T[::-1], mx)
    return part[top : h - bottom, left : w - right]


def draw_quads(image: np.ndarray, quads: Sequence[np.ndarray]) -> np.ndarray:
    """Copy of the image with each quad outlined and numbered, for checking results."""
    out = image.copy()
    thickness = max(2, round(max(image.shape[:2]) / 400))
    for number, quad in enumerate(quads, start=1):
        pts = np.round(quad).astype(np.int32)
        cv2.polylines(out, [pts], True, (255, 0, 0), thickness)
        cv2.circle(out, tuple(int(v) for v in pts[0]), thickness * 3, (0, 160, 255), -1)
        x, y = pts.mean(axis=0).astype(int)
        cv2.putText(out, str(number), (int(x), int(y)), cv2.FONT_HERSHEY_SIMPLEX,
                    thickness * 0.8, (255, 0, 0), thickness * 2, cv2.LINE_AA)
    return out
