"""Validate files and convert them into page images (RGB)."""

from pathlib import Path
from typing import List, Optional, Union

from .config import Settings
from .errors import LimitError, UnsupportedFileError

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
PDF_SUFFIX = ".pdf"
SAMPLES = Path(__file__).parent / "samples"


def supported_suffixes() -> List[str]:
    return sorted(IMAGE_SUFFIXES | {PDF_SUFFIX})


def sample_files() -> List[Path]:
    """The sample images that come with the package, one per typical case."""
    suffixes = set(supported_suffixes())
    return sorted(p for p in SAMPLES.iterdir() if p.suffix.lower() in suffixes)


def check_file(path: Path, settings: Settings) -> None:
    if not path.is_file():
        raise UnsupportedFileError(f"File not found: {path}")
    suffix = path.suffix.lower()
    if suffix != PDF_SUFFIX and suffix not in IMAGE_SUFFIXES:
        raise UnsupportedFileError(
            f"File type {suffix or '(no extension)'} is not supported. "
            f"Allowed: {', '.join(supported_suffixes())}"
        )
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > settings.max_file_mb:
        raise LimitError(
            f"{path.name} is {size_mb:.1f} MB. The limit is "
            f"{settings.max_file_mb:g} MB (max_file_mb)."
        )


def load_pages(path: Union[str, Path], settings: Settings) -> list:
    """Return one RGB PIL image per page. An image yields exactly one page."""
    path = Path(path)
    check_file(path, settings)
    if path.suffix.lower() == PDF_SUFFIX:
        return _pdf_pages(path, settings)
    return [_image_page(path)]


def load_page(path: Union[str, Path], settings: Settings, number: int):
    """Return page `number` (1-based) as an RGB PIL image, without rendering the other pages."""
    path = Path(path)
    check_file(path, settings)
    if path.suffix.lower() != PDF_SUFFIX:
        if number != 1:
            raise UnsupportedFileError(f"{path.name} has only one page.")
        return _image_page(path)
    return _pdf_pages(path, settings, only=number)[0]


def to_rgb(image):
    """Convert any PIL image to RGB, with transparent areas turned white."""
    from PIL import Image

    if image.mode == "RGB":
        return image
    if image.mode in ("RGBA", "LA", "P", "PA"):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[-1])
        return background
    return image.convert("RGB")


def _image_page(path: Path):
    from PIL import Image, ImageOps

    try:
        with Image.open(path) as image:
            image.load()
            return to_rgb(ImageOps.exif_transpose(image))
    except (OSError, ValueError) as exc:
        raise UnsupportedFileError(f"{path.name} cannot be read as an image: {exc}")


def _pdf_pages(path: Path, settings: Settings, only: Optional[int] = None) -> list:
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(str(path))
    except Exception as exc:
        raise UnsupportedFileError(f"{path.name} cannot be read as a PDF: {exc}")
    try:
        count = len(pdf)
        if count > settings.max_pages:
            raise LimitError(
                f"{path.name} has {count} pages. The limit is "
                f"{settings.max_pages} (max_pages)."
            )
        if only is not None and not 1 <= only <= count:
            raise UnsupportedFileError(f"{path.name} has no page {only}.")
        pages = []
        for index in range(count) if only is None else [only - 1]:
            page = pdf[index]
            try:
                bitmap = page.render(scale=settings.pdf_dpi / 72)
                pages.append(to_rgb(bitmap.to_pil()))
            finally:
                page.close()
        return pages
    finally:
        pdf.close()
