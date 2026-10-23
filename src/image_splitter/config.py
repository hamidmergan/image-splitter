"""Default values and resolution of settings.

Order: argument, then environment variable, then default.
"""

import os
from dataclasses import dataclass
from typing import Optional

from .errors import ConfigError

# Limits
MAX_FILE_MB = 50
MAX_PAGES = 50
MAX_FILES = 100

# Detection
MIN_AREA = 0.01  # smallest item as a share of the page area
PADDING = 0  # pixels added around each item (negative values trim)
PDF_DPI = 200

# Vision model (optional)
MAX_IMAGE_SIDE = 1600
CONCURRENCY = 4
TIMEOUT_SECONDS = 120
MAX_RETRIES = 2

# Placeholder, because the OpenAI library requires a value.
# Local servers ignore it.
PLACEHOLDER_API_KEY = "not-needed"

ENV_PREFIX = "IMAGE_SPLITTER_"

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


@dataclass(frozen=True)
class Settings:
    min_area: float
    padding: int
    pdf_dpi: int
    max_file_mb: float
    max_pages: int
    max_files: int
    vision: bool
    orient: bool
    base_url: Optional[str]
    model: Optional[str]
    api_key: str
    max_image_side: int
    concurrency: int
    timeout: float
    max_retries: int


def _env(name: str) -> Optional[str]:
    value = os.environ.get(ENV_PREFIX + name)
    if value is None or value.strip() == "":
        return None
    return value.strip()


def _bool(raw: str) -> bool:
    lowered = raw.lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise ValueError(raw)


def _pick(arg, env_name: str, default, cast):
    if arg is not None:
        return arg
    raw = _env(env_name)
    if raw is None:
        return default
    try:
        return cast(raw)
    except ValueError:
        raise ConfigError(
            f"Environment variable {ENV_PREFIX}{env_name} has an invalid value: {raw!r}"
        )


def resolve(
    *,
    min_area: Optional[float] = None,
    padding: Optional[int] = None,
    pdf_dpi: Optional[int] = None,
    max_file_mb: Optional[float] = None,
    max_pages: Optional[int] = None,
    max_files: Optional[int] = None,
    vision: Optional[bool] = None,
    orient: Optional[bool] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    max_image_side: Optional[int] = None,
    concurrency: Optional[int] = None,
    timeout: Optional[float] = None,
    max_retries: Optional[int] = None,
) -> Settings:
    base_url = _pick(base_url, "BASE_URL", None, str)
    model = _pick(model, "MODEL", None, str)
    # Without an explicit choice, the vision model is used as soon as one is configured.
    vision = _pick(vision, "VISION", bool(base_url or model), _bool)

    if vision:
        missing = []
        if not base_url:
            missing.append("base_url (--base-url or IMAGE_SPLITTER_BASE_URL)")
        if not model:
            missing.append("model (--model or IMAGE_SPLITTER_MODEL)")
        if missing:
            raise ConfigError(
                "The vision model needs " + " and ".join(missing) + ". "
                "Example for Ollama: base_url http://localhost:11434/v1 and a vision model. "
                "Without a model, leave out --base-url and --model (or pass --no-vision)."
            )

    key = _pick(api_key, "API_KEY", None, str)
    if not key:
        key = os.environ.get("OPENAI_API_KEY") or PLACEHOLDER_API_KEY

    settings = Settings(
        min_area=_pick(min_area, "MIN_AREA", MIN_AREA, float),
        padding=_pick(padding, "PADDING", PADDING, int),
        pdf_dpi=_pick(pdf_dpi, "PDF_DPI", PDF_DPI, int),
        max_file_mb=_pick(max_file_mb, "MAX_FILE_MB", MAX_FILE_MB, float),
        max_pages=_pick(max_pages, "MAX_PAGES", MAX_PAGES, int),
        max_files=_pick(max_files, "MAX_FILES", MAX_FILES, int),
        vision=vision,
        orient=_pick(orient, "ORIENT", True, _bool),
        base_url=base_url,
        model=model,
        api_key=key,
        max_image_side=_pick(max_image_side, "MAX_IMAGE_SIDE", MAX_IMAGE_SIDE, int),
        concurrency=_pick(concurrency, "CONCURRENCY", CONCURRENCY, int),
        timeout=_pick(timeout, "TIMEOUT", TIMEOUT_SECONDS, float),
        max_retries=_pick(max_retries, "MAX_RETRIES", MAX_RETRIES, int),
    )
    _validate(settings)
    return settings


def _validate(s: Settings) -> None:
    positive = {
        "pdf_dpi": s.pdf_dpi,
        "max_file_mb": s.max_file_mb,
        "max_pages": s.max_pages,
        "max_files": s.max_files,
        "max_image_side": s.max_image_side,
        "concurrency": s.concurrency,
        "timeout": s.timeout,
    }
    for name, value in positive.items():
        if value <= 0:
            raise ConfigError(f"{name} must be greater than 0, but is {value}.")
    if not 0 < s.min_area < 1:
        raise ConfigError(f"min_area must be between 0 and 1, but is {s.min_area}.")
    if s.max_retries < 0:
        raise ConfigError("max_retries must not be negative.")
