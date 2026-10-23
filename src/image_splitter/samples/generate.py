"""Create the sample images: receipts, photos and cards on different backgrounds.

Run `python src/image_splitter/samples/generate.py` to rebuild them. 09_single_invoice.png is a real
scan and the source of the invoice in 04; it is not generated. Pages are drawn
large and saved at half size to keep the repository small.
"""

from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent
SAMPLE = OUT / "09_single_invoice.png"
SCALE = 0.5
rng = np.random.default_rng(7)


def font(size):
    for name in ("/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Supplemental/Courier New.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def receipt(shop, lines, width=420):
    rows = [shop.upper(), "Hauptstr. 12, 23552 Luebeck", "-" * 30]
    total = 0.0
    for name, price in lines:
        rows.append(f"{name:<20}{price:>8.2f}")
        total += price
    rows += ["-" * 30, f"{'TOTAL EUR':<20}{total:>8.2f}", f"{'VAT 19%':<20}{total * 0.19 / 1.19:>8.2f}", "",
             "2026-10-23  14:32", "Thank you!"]
    f = font(22)
    height = 60 + 34 * len(rows)
    img = Image.new("RGB", (width, height), (250, 249, 244))
    d = ImageDraw.Draw(img)
    for i, row in enumerate(rows):
        d.text((24, 30 + 34 * i), row, fill=(35, 35, 40), font=f if i else font(28))
    return np.asarray(img)


def photo(w, h, seed):
    r = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w]
    sky = np.stack([90 + 80 * yy / h, 140 + 60 * yy / h, 220 - 40 * yy / h], -1)
    img = sky.copy()
    hill = h * (0.6 + 0.08 * np.sin(xx / w * 6 + seed))
    img[yy > hill] = [60, 130 + seed * 10, 60]
    img = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)
    cx, cy = r.integers(w // 4, 3 * w // 4), r.integers(h // 8, h // 3)
    d.ellipse([cx - 40, cy - 40, cx + 40, cy + 40], fill=(250, 220, 80))
    framed = Image.new("RGB", (w + 30, h + 30), (245, 245, 245))
    framed.paste(img, (15, 15))
    return np.asarray(framed)


def card(name, title):
    img = Image.new("RGB", (510, 300), (235, 240, 250))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 510, 70], fill=(30, 70, 140))
    d.text((24, 18), "ACME Consulting", fill="white", font=font(30))
    d.text((24, 120), name, fill=(20, 20, 30), font=font(30))
    d.text((24, 165), title, fill=(70, 70, 80), font=font(20))
    d.text((24, 230), "mail@example.com  +49 451 000000", fill=(70, 70, 80), font=font(18))
    return np.asarray(img)


def background(w, h, kind):
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    if kind == "wood":
        grain = np.sin(xx / 23.0 + 2.5 * np.sin(yy / 140.0)) * 0.5 + 0.5
        bg = np.stack([95 + 45 * grain, 62 + 30 * grain, 38 + 15 * grain], -1)
    elif kind == "dark":
        bg = np.full((h, w, 3), (48, 52, 60), np.float32)
    else:  # scanner lid
        bg = np.full((h, w, 3), (236, 236, 233), np.float32)
    light = 0.82 + 0.18 * (1 - ((xx - w * 0.4) ** 2 + (yy - h * 0.4) ** 2) / (w * w * 0.6))
    if kind != "lid":
        bg *= light[..., None]
    return np.clip(bg + rng.normal(0, 4, bg.shape), 0, 255).astype(np.float32)


def place(page, item, corners, shadow=0.35):
    h, w = item.shape[:2]
    H, W = page.shape[:2]
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    M = cv2.getPerspectiveTransform(src, np.float32(corners))
    warped = cv2.warpPerspective(item, M, (W, H), flags=cv2.INTER_CUBIC)
    mask = cv2.warpPerspective(np.full((h, w), 255, np.uint8), M, (W, H)).astype(np.float32) / 255
    if shadow:
        s = cv2.GaussianBlur(np.roll(mask, (10, 14), (0, 1)), (51, 51), 0)
        page *= (1 - shadow * s)[..., None]
    page[:] = page * (1 - mask[..., None]) + warped * mask[..., None]


def rotated(cx, cy, w, h, angle):
    a = np.deg2rad(angle)
    rot = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    pts = np.array([[-w / 2, -h / 2], [w / 2, -h / 2], [w / 2, h / 2], [-w / 2, h / 2]])
    return pts @ rot.T + [cx, cy]


def small(page):
    image = Image.fromarray(np.clip(page, 0, 255).astype(np.uint8))
    return image.resize((round(image.width * SCALE), round(image.height * SCALE)), Image.LANCZOS)


def save(page, name, **kw):
    small(page).save(OUT / name, **kw)


r1 = receipt("Edeka", [("Milk 1.5%", 1.19), ("Bread", 2.49), ("Apples 1kg", 2.99), ("Coffee", 6.99)])
r2 = receipt("Rewe", [("Pasta", 1.29), ("Tomatoes", 1.99), ("Cheese", 3.49), ("Olive oil", 7.99), ("Water 6x", 2.94)])
r3 = receipt("Pharmacy", [("Plasters", 3.95), ("Tea", 2.50)])

# 1 three receipts on a wooden table, tilted
page = background(2600, 1900, "wood")
for item, (cx, cy, angle) in zip((r1, r2, r3), ((520, 900, -9), (1300, 950, 6), (2080, 820, -18))):
    h, w = item.shape[:2]
    place(page, item, rotated(cx, cy, w * 1.4, h * 1.4, angle))
save(page, "01_receipts_wood_table.jpg", quality=90)

# 2 four photos on a flatbed scanner (white lid)
page = background(2480, 3500, "lid")
for i, (cx, cy, angle) in enumerate(((650, 800, 3), (1800, 760, -4), (640, 2300, -2), (1820, 2350, 5))):
    item = photo(900, 640, i)
    place(page, item, rotated(cx, cy, 930, 670, angle), shadow=0.08)
save(page, "02_photos_on_scanner.jpg", quality=92)

# 3 business cards on a dark desk
page = background(2400, 1600, "dark")
for (name, title), (cx, cy, angle) in zip(
    (("Jane Doe", "Managing Director"), ("John Smith", "Sales"), ("Erika Muster", "Engineering"), ("Max Muster", "Support")),
    ((600, 430, -12), (1700, 420, 8), (620, 1180, 25), (1750, 1170, -4)),
):
    item = card(name, title)
    place(page, item, rotated(cx, cy, 765, 450, angle))
save(page, "03_business_cards_desk.jpg", quality=90)

# 4 phone photo from an angle (perspective), two receipts and an invoice
page = background(3000, 2250, "wood")
place(page, r1, [[300, 330], [860, 300], [900, 1900], [250, 1950]])
place(page, r2, [[1050, 260], [1650, 280], [1690, 2000], [1000, 1990]])
invoice = np.asarray(Image.open(SAMPLE).convert("RGB"))
place(page, invoice, [[1850, 420], [2850, 520], [2900, 1450], [1800, 1380]])
save(page, "04_phone_photo_perspective.jpg", quality=88)

# 5 white receipts on a white scanner lid (hard case)
page = background(2480, 3500, "lid")
for item, (cx, cy, angle) in zip((r1, r2, r3), ((560, 1100, 2), (1500, 1150, -3), (1000, 2600, 4))):
    h, w = item.shape[:2]
    place(page, item, rotated(cx, cy, w * 1.5, h * 1.5, angle), shadow=0.05)
save(page, "05_white_receipts_on_white.jpg", quality=92)

# 6 two touching receipts (needs a vision model to separate)
page = background(2000, 1700, "dark")
h, w = r1.shape[:2]
place(page, r1, rotated(700, 850, w * 1.4, h * 1.4, 0), shadow=0)
place(page, r2, rotated(700 + w * 1.4, 850, w * 1.4, r2.shape[0] * 1.4, 0), shadow=0)
save(page, "06_touching_receipts.jpg", quality=90)

# 7 receipt upside down plus one on its side (needs a vision model to turn upright)
page = background(2400, 1800, "wood")
place(page, r1, rotated(700, 900, w * 1.4, h * 1.4, 183))
place(page, r3, rotated(1700, 900, r3.shape[1] * 1.4, r3.shape[0] * 1.4, 88))
save(page, "07_upside_down_and_sideways.jpg", quality=90)

# 8 two-page PDF scan
p1 = background(1700, 2200, "lid")
place(p1, r1, rotated(500, 900, w * 1.3, h * 1.3, -2), shadow=0.1)
place(p1, r3, rotated(1250, 800, r3.shape[1] * 1.3, r3.shape[0] * 1.3, 3), shadow=0.1)
p2 = background(1700, 2200, "dark")
place(p2, r2, rotated(850, 1100, r2.shape[1] * 1.5, r2.shape[0] * 1.5, 7))
pages = [small(p) for p in (p1, p2)]
pages[0].save(OUT / "08_two_page_scan.pdf", save_all=True, append_images=pages[1:], resolution=100)
