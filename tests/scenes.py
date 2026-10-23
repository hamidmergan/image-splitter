"""Synthetic test pages: rotated items with a dark bar at their top edge on a background."""

from dataclasses import dataclass
from typing import List, Sequence, Tuple

import cv2
import numpy as np


@dataclass
class Item:
    center: Tuple[float, float]
    size: Tuple[float, float]  # width, height before rotation
    angle: float = 0.0  # degrees, clockwise on screen
    color: Tuple[int, int, int] = (248, 248, 245)


def _place(item: Item, x0: float, y0: float, x1: float, y1: float) -> np.ndarray:
    """Corners of the sub-rectangle (relative -0.5..0.5 coordinates) of a rotated item."""
    w, h = item.size
    a = np.deg2rad(item.angle)
    rot = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    local = np.array([[x0 * w, y0 * h], [x1 * w, y0 * h], [x1 * w, y1 * h], [x0 * w, y1 * h]])
    return (local @ rot.T + np.array(item.center)).astype(np.float32)


def corners(item: Item) -> np.ndarray:
    """Item corners in page pixels: top-left, top-right, bottom-right, bottom-left."""
    return _place(item, -0.5, -0.5, 0.5, 0.5)


def _fill(canvas: np.ndarray, quad: np.ndarray, color) -> None:
    # draw with sub-pixel precision so edges stay straight
    cv2.fillConvexPoly(canvas, np.round(quad * 16).astype(np.int32), color, cv2.LINE_AA, shift=4)


def scene(
    items: Sequence[Item],
    size: Tuple[int, int] = (1600, 1200),
    background: Tuple[int, int, int] = (55, 60, 70),
    noise: float = 4.0,
    seed: int = 0,
) -> np.ndarray:
    """RGB page with the items drawn on it. Each item gets a dark bar near its top
    edge and a few grey text lines, so orientation and holes can be checked."""
    rng = np.random.default_rng(seed)
    w, h = size
    canvas = np.empty((h, w, 3), np.uint8)
    canvas[:] = background
    for item in items:
        _fill(canvas, corners(item), item.color)
        _fill(canvas, _place(item, -0.4, -0.45, 0.4, -0.35), (20, 20, 20))
        for top in np.arange(-0.2, 0.4, 0.1):
            _fill(canvas, _place(item, -0.35, top, 0.2, top + 0.03), (90, 90, 90))
    if noise:
        noisy = canvas.astype(np.float32) + rng.normal(0, noise, canvas.shape)
        canvas = np.clip(noisy, 0, 255).astype(np.uint8)
    return canvas


def three_receipts() -> List[Item]:
    return [
        Item((300, 520), (300, 760), angle=-8),
        Item((800, 560), (320, 820), angle=5),
        Item((1290, 500), (290, 700), angle=-22),
    ]


def top_is_dark(part: np.ndarray) -> bool:
    """True if the dark bar is at the top of the cut-out part, not at the bottom."""
    gray = cv2.cvtColor(np.asarray(part), cv2.COLOR_RGB2GRAY).astype(np.float32)
    h, w = gray.shape
    rows = gray[:, w // 10 : w - w // 10].mean(axis=1)
    return rows[: h // 5].min() < rows[-h // 5 :].min() - 60
