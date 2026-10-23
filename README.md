# image-splitter

A lightweight Python utility that splits one scan or photo with several items, such as receipts, photos, ID cards or business cards, into one image per item. Each item is cut out along its edges, straightened and corrected for perspective. It works with classic image processing (OpenCV) and needs no AI model. A vision model is optional and helps with difficult cases. A web page lets you check and correct every frame by hand.

```
scan.jpg  ->  scan_1.jpg  scan_2.jpg  scan_3.jpg
```

The parts can be used directly as input for tools that expect one document per file, for example [invoice-extract](https://github.com/hamidmergan/invoice-extract) or [doc-extract](https://github.com/hamidmergan/doc-extract).

image-splitter currently supports:

- Images (PNG, JPG, WEBP, GIF, BMP, TIFF)
- PDF (every page is split on its own)

## Prerequisites

- Python 3.9 or newer
- Optional: a server with an OpenAI-compatible API and a **vision-capable model** (for example Ollama, vLLM, LM Studio, a university server or a cloud provider). A text-only model is not enough. Without a model, image-splitter works offline with OpenCV only.
- An API key is optional. Many self-hosted servers do not need one.

If you run your own model, your scans stay on your own network. Nothing leaves your machine or data center.

## Installation

```bash
pip install image-splitter-cv
```

With the web page and support for a vision model:

```bash
pip install "image-splitter-cv[ui,vision]"
```

Alternatively, you can install it from the source:

```bash
git clone https://github.com/hamidmergan/image-splitter.git
cd image-splitter
pip install ".[ui,vision]"
```

## Usage

### Web page

```bash
image-splitter serve
```

Use `--port` if 8765 is taken.

Open http://127.0.0.1:8765 and drop your scans onto the page, or click **Try samples** to load the sample images.

```
┌──────────────────────────────────────────┐
│  Files      Page with frames      Parts  │
│  scan.jpg   ┌───┐ ┌───┐ ┌────┐    ▢ 1    │
│  doc.pdf    │ 1 │ │ 2 │ │ 3  │    ▢ 2    │
│             └───┘ └───┘ └────┘    ▢ 3    │
└──────────────────────────────────────────┘
```

- **The page** shows every item found with a numbered frame. Drag a corner to move it, drag inside a frame to move the whole frame, and drag on an empty spot to draw a new one. "Add frame" does the same with a button.
- **Rotate** turns the selected part clockwise by 90 degrees (key `R`), **Delete** removes its frame (key `Delete`), **Reset page** brings back the frames that were found.
- **Parts** shows each cut-out part as it will be saved.
- **Download ZIP** saves all parts of all files, named as on the command line.

With `--base-url` and `--model`, the page also uses a vision model (see below). The detection settings (`--min-area`, `--padding`, `--pdf-dpi`) work here too.

The page has no login. It listens on 127.0.0.1 by default and only answers requests for localhost, so other websites cannot reach it. Only use `--host 0.0.0.0` on a trusted network, and name the host names it may answer to with `--allowed-hosts` (or `IMAGE_SPLITTER_ALLOWED_HOSTS`, `*` for any).

### Docker

Start the web page with one command, no Python needed:

```bash
docker run --rm -p 127.0.0.1:8765:8765 ghcr.io/hamidmergan/image-splitter
```

Then open http://localhost:8765. Stop it with `Ctrl+C`. If the port is taken, change the first number, e.g. `-p 127.0.0.1:9000:8765`, or use `IMAGE_SPLITTER_PORT=9000 docker compose up`.

Or build it from the source:

```bash
git clone https://github.com/hamidmergan/image-splitter.git
cd image-splitter
docker compose up
```

With a vision model, for example Ollama on the same machine:

```bash
docker run --rm -p 127.0.0.1:8765:8765 \
  --add-host=host.docker.internal:host-gateway \
  -e IMAGE_SPLITTER_BASE_URL=http://host.docker.internal:11434/v1 \
  -e IMAGE_SPLITTER_MODEL=your-vision-model \
  ghcr.io/hamidmergan/image-splitter
```

Inside the container, `localhost` is the container itself, so a model server on your machine is reached as `host.docker.internal`. All `IMAGE_SPLITTER_*` settings can be passed with `-e`.

The container only answers requests for localhost, and `-p 127.0.0.1:8765:8765` keeps the port on your own machine. To run it on a server for a trusted network, publish the port without `127.0.0.1:` and set `-e IMAGE_SPLITTER_ALLOWED_HOSTS=your-server-name`.

### Command-Line

Split a scan:

```bash
image-splitter scan.jpg
```

This writes `scan_1.jpg`, `scan_2.jpg`, ... next to `scan.jpg`, in reading order (rows from top to bottom, left to right). Several files and PDFs work the same way:

```bash
image-splitter scan.jpg receipts.pdf -o parts/
```

For a PDF with more than one page, the page number is part of the name (`receipts_p2_1.jpg`). Use `-o` to choose an output folder and `--format png` for lossless output. If two inputs share the same name without extension (for example `a.pdf` and `a.jpg`), the full name is used instead (`a_pdf_1.jpg`, `a_jpg_1.jpg`). Existing files are never overwritten, a number is added instead (`scan_1 (1).jpg`).

Check what was found:

```bash
image-splitter scan.jpg --debug
```

This also writes `scan_debug.jpg` with every item outlined and numbered. The dot marks the corner that becomes the top left.

If nothing is found on a page, the whole page is kept as one part and a note is printed. This way image-splitter can run in front of other tools without losing files. Errors appear on stderr. The exit code is 1 if at least one file failed.

With a vision model:

```bash
image-splitter scan.jpg --base-url http://localhost:11434/v1 --model your-vision-model
```

The model is used as soon as `--base-url` and `--model` are given (or set as environment variables). It does two things:

- **Finding items.** The model is asked for a rough box around each item. If its count differs from what OpenCV found, the model's boxes are used, and OpenCV looks for the exact outline inside each box. This helps when items touch each other, when white paper lies on a white background, or when a single document fills the whole picture. Vision models are often imprecise with coordinates, so their boxes are not used for cutting if an outline can be found.
- **Turning items upright.** Each cut-out item is checked for a rotation by 90, 180 or 270 degrees. Use `--no-orient` to skip this.

Use `--no-vision` to work without the model even if one is configured.

### Python API

```python
from image_splitter import split

parts = split("scan.jpg")
for part in parts:
    part.image.save(f"receipt_{part.index}.jpg")
```

Each part has `image` (a Pillow image), `page`, `index`, `corners` (the four corners on the page, top left first), `method` (`contour`, `vision`, `box` or `page`) and `rotation`.

An image that is already in memory (Pillow image or RGB NumPy array):

```python
from image_splitter import split_image

parts = split_image(image, base_url="http://localhost:11434/v1", model="your-vision-model")
```

Several files, each handled on its own:

```python
from image_splitter import split_many

results = split_many(["a.jpg", "b.pdf"])
for name, result in results.items():
    if result.ok:
        print(name, len(result.parts), "parts")
    else:
        print(name, "Error:", result.error)
```

`split_many` keeps the input order. If one file fails, the others continue and the error is stored in that file's result. `draw_parts(page, parts)` returns the page with the parts outlined, and `cut(page, corners, rotation)` cuts out an item along four corners you choose yourself.

### Settings

Order: argument, then environment variable, then default.

| Argument / flag | Environment variable | Default |
| --- | --- | --- |
| `min_area` / `--min-area` | `IMAGE_SPLITTER_MIN_AREA` | 0.01 (1% of the page) |
| `padding` / `--padding` | `IMAGE_SPLITTER_PADDING` | 0 pixels (negative values trim) |
| `pdf_dpi` / `--pdf-dpi` | `IMAGE_SPLITTER_PDF_DPI` | 200 |
| `base_url` / `--base-url` | `IMAGE_SPLITTER_BASE_URL` | none, needed for the model |
| `model` / `--model` | `IMAGE_SPLITTER_MODEL` | none, needed for the model |
| `api_key` / `--api-key` | `IMAGE_SPLITTER_API_KEY` (then `OPENAI_API_KEY`) | optional |
| `vision` / `--no-vision` | `IMAGE_SPLITTER_VISION` | on if base_url or model is set |
| `orient` / `--no-orient` | `IMAGE_SPLITTER_ORIENT` | on (with a model) |
| `max_image_side` / `--max-image-side` | `IMAGE_SPLITTER_MAX_IMAGE_SIDE` | 1600 pixels |
| `concurrency` / `--concurrency` | `IMAGE_SPLITTER_CONCURRENCY` | 4 |
| `timeout` / `--timeout` | `IMAGE_SPLITTER_TIMEOUT` | 120 seconds |
| `max_file_mb` / `--max-file-mb` | `IMAGE_SPLITTER_MAX_FILE_MB` | 50 |
| `max_pages` / `--max-pages` | `IMAGE_SPLITTER_MAX_PAGES` | 50 |
| `max_files` / `--max-files` | `IMAGE_SPLITTER_MAX_FILES` | 100 |

The command line also has `--format` (`jpg`, `png`, `webp`, `tif`) and `--quality` (default 95).

## How it works

1. The background colour is taken from the edge of the page.
2. Everything that differs clearly from it becomes a candidate. Shadows (darker, same tint) are ignored. If nothing differs, closed outlines are used instead.
3. Each candidate gets four corners: the real corners if it is a clean quadrilateral (keeps perspective), otherwise the smallest rotated rectangle around it.
4. The edges are measured again at full resolution, so the corners are accurate to about one pixel.
5. Each item is mapped onto an upright rectangle with the smallest possible rotation, and thin slivers of background along its edges are cut off.

## Limitations

- Best results come from items on a background that differs from them, for example receipts on a dark table. White on white works if there is at least a faint difference.
- Shadows next to items are ignored: areas that are only darker than the background but keep its tint count as background. A plain grey item that is a little darker than the background may be taken for a shadow.
- Without a model, items that touch or overlap are seen as one. A model separates touching items. Overlapping items are not supported.
- Without a model, items are straightened by at most 45 degrees. An item that lies upside down or on its side needs the model to be turned upright.
- Without a model, a photo that shows a single document filling the frame may be split into its larger blocks (logos, pictures). Skip image-splitter for such files or use a model.
- With a model, quality depends on the chosen model. Check `--debug` output or the web page for important files.

Every case not solved automatically can be fixed by hand on the web page.

## Samples

The [samples](src/image_splitter/samples/) folder holds generated test images, one per typical case, and the script that creates them (`python src/image_splitter/samples/generate.py`). They come with the package, and **Try samples** on the web page loads them with one click.

| File | Case | Without a model |
| --- | --- | --- |
| `01_receipts_wood_table.jpg` | 3 tilted receipts on a wooden table | 3 parts |
| `02_photos_on_scanner.jpg` | 4 photos on a flatbed scanner | 4 parts |
| `03_business_cards_desk.jpg` | 4 business cards with shadows | 4 parts |
| `04_phone_photo_perspective.jpg` | phone photo taken at an angle | 3 parts, perspective corrected |
| `05_white_receipts_on_white.jpg` | white receipts on a white scanner lid | 3 parts |
| `06_touching_receipts.jpg` | 2 receipts touching each other | 1 part (needs a model or the web page) |
| `07_upside_down_and_sideways.jpg` | receipt upside down, one on its side | 2 parts, not turned upright (needs a model or the web page) |
| `08_two_page_scan.pdf` | PDF with 2 pages | 3 parts |
| `09_single_invoice.png` | one document filling the frame | the whole page |

```bash
image-splitter src/image_splitter/samples/01_receipts_wood_table.jpg -o parts/ --debug
```

## Running Tests

```bash
pip install -e ".[test]"
pytest
```

The tests use generated images, the samples and a local fake server, and need no real model.

## License

MIT
