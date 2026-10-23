"""Optional help from a vision model on an OpenAI-compatible server.

The model is asked two things: where the items are (rough boxes) and how far an
item must be turned to be upright. Its boxes are never used directly for cutting,
because vision models are often imprecise with coordinates. OpenCV refines them.
"""

import base64
import io
import json
import re
from typing import List, Optional, Tuple

from .config import Settings
from .errors import ConfigError, ModelError

Box = Tuple[float, float, float, float]  # x0, y0, x1, y1 as shares of width and height

BOX_PROMPT = (
    "This image shows a scan or photo with one or more separate items on a background, "
    "for example receipts, photos, ID cards or business cards. Find every separate item. "
    'Answer only with JSON in this form: {"items": [[x_min, y_min, x_max, y_max], ...]}. '
    "Use integers from 0 to 1000, relative to the image width and height. "
    "Give one box per item, also for items that touch each other. "
    'If there is no item, answer {"items": []}.'
)

ORIENT_PROMPT = (
    "This image shows one item, for example a receipt, photo, ID card or business card. "
    "By how many degrees must it be rotated clockwise so that it is upright and its text "
    "reads normally? Answer with one number only: 0, 90, 180 or 270."
)


def make_client(settings: Settings):
    try:
        from openai import OpenAI
    except ImportError:
        raise ConfigError(
            "The vision model needs the openai package. "
            "Install it with: pip install 'image-splitter-cv[vision]'"
        )
    return OpenAI(
        base_url=settings.base_url,
        api_key=settings.api_key,
        timeout=settings.timeout,
        max_retries=settings.max_retries,
    )


def _data_url(image, max_side: int) -> str:
    from PIL import Image

    longest = max(image.size)
    if longest > max_side:
        factor = max_side / longest
        size = (max(1, round(image.width * factor)), max(1, round(image.height * factor)))
        image = image.resize(size, Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def ask(client, settings: Settings, image, prompt: str) -> str:
    """Send one image with an instruction and return the model's text answer."""
    try:
        response = client.chat.completions.create(
            model=settings.model,
            temperature=0,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": _data_url(image, settings.max_image_side)}},
                    ],
                }
            ],
        )
    except Exception as exc:
        raise ModelError(f"Request to {settings.base_url} failed: {exc}")
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError):
        raise ModelError("The server response has an unexpected format.")
    return (content or "").strip()


def _json(text: str):
    """The first JSON object or list in a text, also inside a Markdown code block."""
    pairs = [("{", "}"), ("[", "]")]
    # try the bracket that opens first, so a list of objects is not read as one object
    pairs.sort(key=lambda pair: text.find(pair[0]) if pair[0] in text else len(text))
    for opener, closer in pairs:
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except ValueError:
                continue
    return None


def _numbers(entry) -> Optional[List[float]]:
    if isinstance(entry, dict):
        for key in ("box", "bbox", "box_2d", "bbox_2d", "coordinates"):
            if key in entry:
                return _numbers(entry[key])
        return None
    if isinstance(entry, (list, tuple)) and len(entry) == 4:
        try:
            return [float(v) for v in entry]
        except (TypeError, ValueError):
            return None
    return None


def parse_boxes(text: str, sent_size: Tuple[int, int]) -> List[Box]:
    """Read boxes from the model's answer. Unreadable answers give an empty list.

    Values from 0 to 1 are taken as shares, up to 1000 as thousandths (as asked),
    larger values as pixels of the image that was sent.
    """
    data = _json(text)
    if isinstance(data, dict):
        data = data.get("items", data.get("boxes"))
    if not isinstance(data, list):
        return []
    rows = [n for n in (_numbers(e) for e in data) if n is not None]
    if not rows:
        return []
    largest = max(max(r) for r in rows)
    width, height = sent_size
    boxes = []
    for x0, y0, x1, y1 in rows:
        if largest <= 1:
            scale_x = scale_y = 1.0
        elif largest <= 1000:
            scale_x = scale_y = 1000.0
        else:
            scale_x, scale_y = float(width), float(height)
        x0, x1 = sorted((x0 / scale_x, x1 / scale_x))
        y0, y1 = sorted((y0 / scale_y, y1 / scale_y))
        x0, y0 = max(0.0, x0), max(0.0, y0)
        x1, y1 = min(1.0, x1), min(1.0, y1)
        if x1 - x0 > 0.01 and y1 - y0 > 0.01:
            boxes.append((x0, y0, x1, y1))
    return boxes


def find_boxes(client, settings: Settings, image) -> List[Box]:
    """Rough boxes of all items on a page, as shares of its width and height."""
    longest = max(image.size)
    factor = min(1.0, settings.max_image_side / longest)
    sent = (round(image.width * factor), round(image.height * factor))
    return parse_boxes(ask(client, settings, image, BOX_PROMPT), sent)


def parse_rotation(text: str) -> int:
    """Clockwise rotation in degrees from the model's answer, 0 if unclear."""
    match = re.search(r"\b(0|90|180|270)\b", text)
    return int(match.group(1)) if match else 0


def find_rotation(client, settings: Settings, image) -> int:
    return parse_rotation(ask(client, settings, image, ORIENT_PROMPT))
