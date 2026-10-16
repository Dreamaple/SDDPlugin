from __future__ import annotations

import hashlib
import re
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None


OCR_RENDER_DPI = 96
OCR_MIN_RENDER_DPI = 24
OCR_MAX_WIDTH = 2200
OCR_MAX_PIXELS = 20000000

# Pure-image PDF detection
PURE_IMAGE_AVG_CHAR_THRESHOLD = 50
PURE_IMAGE_PREVIEW_PAGE_COUNT = 3

# Tile processing for oversized pages
TILE_MAX_WIDTH = 2200
TILE_MAX_HEIGHT = 3000
TILE_MAX_PIXELS = 6000000
TILE_MIN_COLS = 1
TILE_MAX_COLS = 5
TILE_MIN_ROWS = 1
TILE_MAX_ROWS = 5


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower())
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return normalized


def build_document_id(path: Path) -> str:
    stem = slugify(path.stem) or "document"
    digest = hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:8]
    return f"{stem}-{digest}"


def relative_to_root(path: Path, root: Path) -> str:
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    try:
        return resolved_path.relative_to(resolved_root).as_posix()
    except ValueError:
        return resolved_path.as_posix()


def read_text_file(path: Path) -> str:
    encodings = ("utf-8", "utf-8-sig", "gb18030", "latin-1")
    for encoding in encodings:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue

    return path.read_text(encoding="utf-8", errors="replace")


def resolution_for_max_width(
    page_width_points: float,
    *,
    preferred_resolution: int = OCR_RENDER_DPI,
    max_width: int = OCR_MAX_WIDTH,
    min_resolution: int = OCR_MIN_RENDER_DPI,
) -> int:
    if not page_width_points or page_width_points <= 0:
        return preferred_resolution

    width_inches = page_width_points / 72.0
    if width_inches <= 0:
        return preferred_resolution

    capped_resolution = int(max_width / width_inches)
    if capped_resolution <= 0:
        return min_resolution

    return max(min_resolution, min(preferred_resolution, capped_resolution))


def scale_for_render_bounds(
    page_width: float,
    page_height: float,
    *,
    preferred_scale: float,
    max_width: int = OCR_MAX_WIDTH,
    max_pixels: int = OCR_MAX_PIXELS,
) -> float:
    scale = preferred_scale
    if page_width and page_width > 0:
        scale = min(scale, max_width / page_width)

    if page_width and page_width > 0 and page_height and page_height > 0:
        pixel_scale = (max_pixels / (page_width * page_height)) ** 0.5
        scale = min(scale, pixel_scale)

    return max(scale, 0.05)


def scale_image_for_ocr(image, *, max_pixels: int = OCR_MAX_PIXELS):
    if Image is None:
        return image

    pixel_count = image.width * image.height
    if pixel_count <= max_pixels:
        return image

    scale = (max_pixels / pixel_count) ** 0.5
    new_size = (
        max(1, int(image.width * scale)),
        max(1, int(image.height * scale)),
    )
    if new_size == image.size:
        return image

    resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
    return image.resize(new_size, resample=resampling)


def is_j90k_hvac_document(filename: str, text: str = "") -> bool:
    normalized_filename = filename.casefold()
    if "j90k" in normalized_filename and "空调" in filename:
        return True

    required_markers = [
        "J90K PROJECT",
        "标注说明",
        "信息架构",
        "空调设置",
        "座椅",
    ]
    return all(marker in text for marker in required_markers)


def is_j90k_media_center_document(filename: str, text: str = "") -> bool:
    normalized_filename = filename.casefold()
    if "j90k" in normalized_filename and "媒体中心" in filename:
        return True

    required_markers = [
        "J90K PROJECT",
        "媒体中心",
        "QQ音乐首页",
        "信息架构",
        "页面布局",
    ]
    return all(marker in text for marker in required_markers)


def calculate_tile_grid(
    width: int,
    height: int,
    *,
    max_width: int = TILE_MAX_WIDTH,
    max_height: int = TILE_MAX_HEIGHT,
    max_pixels: int = TILE_MAX_PIXELS,
    min_cols: int = TILE_MIN_COLS,
    max_cols: int = TILE_MAX_COLS,
    min_rows: int = TILE_MIN_ROWS,
    max_rows: int = TILE_MAX_ROWS,
) -> tuple[int, int]:
    """Calculate optimal tile grid (rows, cols) so each tile fits within limits."""
    if width <= max_width and height <= max_height and width * height <= max_pixels:
        return (1, 1)

    # Determine minimum columns needed to satisfy width constraint
    cols_needed = max(min_cols, (width + max_width - 1) // max_width)
    cols_needed = min(cols_needed, max_cols)

    # Determine minimum rows needed to satisfy height constraint
    rows_needed = max(min_rows, (height + max_height - 1) // max_height)
    rows_needed = min(rows_needed, max_rows)

    # Check pixel constraint: may need more rows/cols
    tile_width = width / cols_needed
    tile_height = height / rows_needed
    tile_pixels = tile_width * tile_height

    while tile_pixels > max_pixels and (rows_needed < max_rows or cols_needed < max_cols):
        # Add to the dimension that gives the biggest reduction
        if rows_needed < max_rows and (rows_needed + 1) * cols_needed <= max_rows * max_cols:
            rows_needed += 1
        elif cols_needed < max_cols:
            cols_needed += 1
        else:
            break
        tile_width = width / cols_needed
        tile_height = height / rows_needed
        tile_pixels = tile_width * tile_height

    return (rows_needed, cols_needed)
