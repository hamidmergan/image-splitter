import argparse
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

from . import __version__
from .config import resolve
from .core import Result, draw_parts, split_many
from .errors import SplitError
from .loader import load_pages

FORMATS = {"jpg": "JPEG", "png": "PNG", "webp": "WEBP", "tif": "TIFF"}
LOOPBACK = ("127.0.0.1", "localhost", "::1")
UI_HINT = 'The web UI needs extra packages: pip install "image-splitter-cv[ui]"'
NO_LOGIN = "Warning: the UI has no login. Only expose it on a trusted network."


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="image-splitter",
        description="Split scans and photos with several items (receipts, photos, cards) "
        "into one straight image per item. Run 'image-splitter serve' for the web page.",
    )
    p.add_argument("files", nargs="+", help="Images or PDFs")
    p.add_argument("-o", "--output", help="Output folder. Default: next to each input")
    p.add_argument("--format", choices=sorted(FORMATS), default="jpg", help="Image format of the parts (default: jpg)")
    p.add_argument("--quality", type=int, default=95, help="JPEG/WEBP quality from 1 to 100 (default: 95)")
    p.add_argument("--debug", action="store_true", help="Also write each page with the found items outlined")
    _shared_flags(p)
    p.add_argument("--version", action="version", version=f"image-splitter {__version__}")
    return p


def _serve_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="image-splitter serve", description="Start the web page to check and correct the frames.")
    p.add_argument("--host", default="127.0.0.1", help="Address to listen on (default: 127.0.0.1)")
    p.add_argument("--port", type=int, default=8765, help="Port (default: 8765)")
    p.add_argument(
        "--allowed-hosts",
        help="Comma-separated host names the page answers to, or * for any "
        "(env IMAGE_SPLITTER_ALLOWED_HOSTS; default: localhost names when listening on 127.0.0.1, else any)",
    )
    _shared_flags(p)
    return p


def _shared_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--min-area", type=float, help="Smallest item as a share of the page, e.g. 0.01 = 1%%")
    p.add_argument("--padding", type=int, help="Pixels added around each item (negative values trim)")
    p.add_argument("--pdf-dpi", type=int, help="Resolution for PDF pages")
    vision = p.add_argument_group("vision model (optional)")
    vision.add_argument("--base-url", help="URL of the OpenAI-compatible server, e.g. http://localhost:11434/v1")
    vision.add_argument("--model", help="Name of the vision model")
    vision.add_argument("--api-key", help="API key, if the server requires one")
    vision.add_argument("--no-vision", action="store_true", help="Do not use the model even if one is configured")
    vision.add_argument("--no-orient", action="store_true", help="Do not ask the model to turn items upright")
    vision.add_argument("--max-image-side", type=int, help="Longest image side in pixels before sending")
    vision.add_argument("--concurrency", type=int, help="Parallel requests per page")
    vision.add_argument("--timeout", type=float, help="Seconds per request")
    limits = p.add_argument_group("limits")
    limits.add_argument("--max-file-mb", type=float)
    limits.add_argument("--max-pages", type=int)
    limits.add_argument("--max-files", type=int)


def _options(args: argparse.Namespace) -> dict:
    return dict(
        min_area=args.min_area,
        padding=args.padding,
        pdf_dpi=args.pdf_dpi,
        vision=False if args.no_vision else None,
        orient=False if args.no_orient else None,
        base_url=args.base_url,
        model=args.model,
        api_key=args.api_key,
        max_image_side=args.max_image_side,
        concurrency=args.concurrency,
        timeout=args.timeout,
        max_file_mb=args.max_file_mb,
        max_pages=args.max_pages,
        max_files=args.max_files,
    )


def _free(path: Path) -> Path:
    """Return path, or 'name (1).jpg', 'name (2).jpg', ... if it already exists."""
    candidate, n = path, 1
    while candidate.exists():
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        n += 1
    return candidate


def stems(keys: List[str]) -> Dict[str, str]:
    """Base name per input: the stem, or the full name if two stems would collide."""
    stems = [Path(k).stem for k in keys]
    unique = len(set(stems)) == len(stems)
    return {k: (Path(k).stem if unique else Path(k).name.replace(".", "_")) for k in keys}


def part_name(stem: str, page: int, index: int, pages: int, ext: str) -> str:
    """File name of a part: scan_2.jpg, or scan_p3_2.jpg for a file with several pages."""
    if pages > 1:
        return f"{stem}_p{page}_{index}.{ext}"
    return f"{stem}_{index}.{ext}"


def save_image(image, target, fmt: str, quality: int) -> None:
    options = {"quality": quality} if fmt in ("JPEG", "WEBP") else {}
    image.save(target, format=fmt, **options)


def _write_debug(key: str, result: Result, folder: Path, stem: str, settings) -> None:
    for number, page in enumerate(load_pages(key, settings), start=1):
        parts = [p for p in result.parts if p.page == number]
        suffix = f"_p{number}" if result.pages > 1 else ""
        target = _free(folder / f"{stem}{suffix}_debug.jpg")
        save_image(draw_parts(page, parts), target, "JPEG", 90)
        print(f"Wrote {target}", file=sys.stderr)


def allowed_hosts(host: str, raw: Optional[str]) -> Optional[List[str]]:
    """Host names the page answers to, None for any.

    Limiting them protects against DNS rebinding: another web page cannot reach the UI
    through a host name of its own that points to this machine.
    """
    if raw and raw.strip():
        names = [h.strip().lower() for h in raw.split(",") if h.strip()]
        return None if "*" in names else names
    return list(LOOPBACK) if host in LOOPBACK else None


def _run_serve(argv: List[str]) -> int:
    args = _serve_parser().parse_args(argv)
    try:
        import uvicorn

        from .web.app import create_app
    except ImportError:
        print(UI_HINT, file=sys.stderr)
        return 2
    try:
        settings = resolve(**_options(args))
    except SplitError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    allowed = allowed_hosts(args.host, args.allowed_hosts or os.environ.get("IMAGE_SPLITTER_ALLOWED_HOSTS"))
    if allowed is None:
        print(NO_LOGIN, file=sys.stderr)
    uvicorn.run(create_app(settings, allowed_hosts=allowed), host=args.host, port=args.port)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "serve":
        return _run_serve(argv[1:])
    args = _parser().parse_args(argv)
    out = Path(args.output) if args.output else None
    if out is not None and out.exists() and not out.is_dir():
        print("-o must be a folder.", file=sys.stderr)
        return 2
    if not 1 <= args.quality <= 100:
        print("--quality must be between 1 and 100.", file=sys.stderr)
        return 2

    options = _options(args)
    try:
        settings = resolve(**options)
        results = split_many(args.files, **options)
    except SplitError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    fmt, ext = FORMATS[args.format], args.format
    names = stems(list(results))
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)

    failed = 0
    for key, result in results.items():
        if not result.ok:
            failed += 1
            print(f"Error for {key}: {result.error}", file=sys.stderr)
            continue
        folder = out if out is not None else Path(key).parent
        for part in result.parts:
            if part.method == "page":
                where = f" page {part.page}" if result.pages > 1 else ""
                print(f"No separate items found in {key}{where}, kept the whole page.", file=sys.stderr)
            target = _free(folder / part_name(names[key], part.page, part.index, result.pages, ext))
            save_image(part.image, target, fmt, args.quality)
            print(f"Wrote {target}", file=sys.stderr)
        if args.debug:
            _write_debug(key, result, folder, names[key], settings)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
