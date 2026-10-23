# PLAN

Split one scan or photo with several items (receipts, photos, ID cards, business cards) into one straight image per item.

## Design

```
scan.jpg / PDF page
   │
   ▼
[OpenCV] background distance + edges → contours → quads
   │            │
   │            │ --base-url/--model given: model boxes
   │            ▼
   │          more boxes than OpenCV found? → refine each box with OpenCV
   ▼            ▼
perspective warp (smallest rotation) → optional upright check by model (0/90/180/270)
   ▼
scan_1.jpg scan_2.jpg …   (PDF with several pages: scan_p2_1.jpg)
```

- Classic detection is the default, no model needed
- Vision model is optional: finds items OpenCV misses (white on white, touching items) and turns items upright
- Model boxes are never used as is: OpenCV refines them, the box is only the fallback
- Nothing found: the whole page is kept as one part, so the tool can always run before invoice-extract
- v1 scope: no overlapping items, no naming by model
- PyPI name `image-splitter-cv` (`image-splitter` is taken), command and repo `image-splitter`

## Progress

- [x] 1 Scaffold (pyproject, errors, config, LICENSE, CI)
- [x] 2 Loader (images, PDF pages)
- [x] 3 Classic detection and warp
- [x] 4 Vision (boxes, orientation)
- [x] 5 Core API (`split`, `split_image`, `split_many`)
- [x] 6 CLI (output names, `-o`, `--debug`)
- [x] 7 Tests with synthetic images and fake server
- [x] 8 README, CHANGELOG

## Web UI (v0.1.0, same pattern as invoice-extract)

```
image-splitter serve  →  http://127.0.0.1:8000
drop files → OpenCV (+ model) proposes frames → drag corners / move / add / delete / rotate → ZIP
```

- `image-splitter serve`, extra `[ui]` (fastapi, uvicorn, python-multipart)
- Backend `web/app.py`: upload, background detection, state, page preview, part preview, PUT parts, ZIP
- Pages are loaded on demand with a small cache, not kept in memory
- Same guard as invoice-extract: localhost only by default, no cross-origin requests
- Frontend `web/static/`: SVG editor over the page, previews of the cut parts
- Generated sample images in `samples/` (with `generate.py`), checked by `tests/test_samples.py`

- [x] 9 Core helper `cut()` for edited frames
- [x] 10 Web API + tests
- [x] 11 Web page (editor)
- [x] 12 `serve` command
- [x] 13 Samples + sample tests
- [x] 14 README, CHANGELOG

## Docker

- [x] 15 Dockerfile, .dockerignore, compose.yaml (port only on 127.0.0.1)
- [x] 16 `--allowed-hosts` / `IMAGE_SPLITTER_ALLOWED_HOSTS`, container answers only localhost
- [x] 17 Workflow `docker.yml`: image to ghcr.io/hamidmergan/image-splitter (amd64, arm64) on push to main and tags
- [x] 18 After the first push: check that the ghcr.io package is public
