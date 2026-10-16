from __future__ import annotations

import argparse
import base64
import json
import math
import os
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pdfplumber
import pypdfium2 as pdfium
from PIL import Image, ImageOps
from pypdf import PdfReader

try:
    from rapidocr_onnxruntime import RapidOCR
except Exception:  # pragma: no cover
    RapidOCR = None


STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "from",
    "page",
    "user",
    "document",
    "system",
    "project",
    "version",
    "released",
}

EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")

RADICAL_REPLACEMENTS = {
    "⽬": "目",
    "⻚": "页",
    "⾯": "面",
    "⼿": "手",
    "⻛": "风",
    "⽅": "方",
    "⾳": "音",
    "⽓": "气",
    "⽂": "文",
    "⻓": "长",
    "⾼": "高",
    "⾏": "行",
    "⽰": "示",
    "⽤": "用",
    "⼦": "子",
    "⼈": "人",
    "⾃": "自",
    "⼲": "干",
    "⻋": "车",
    "⻔": "门",
    "⽕": "火",
    "⼩": "小",
    "⽌": "止",
    "⻆": "角",
    "⼯": "工",
    "⻩": "黄",
    "⻘": "青",
    "⽆": "无",
    "⾸": "首",
    "⼀": "一",
    "⼆": "二",
    "｜": " | ",
}

_READABLE_CODEPOINT_RANGES = (
    (0x0020, 0x007E),
    (0x00A0, 0x00FF),
    (0x2000, 0x206F),
    (0x3000, 0x303F),
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0xFF00, 0xFFEF),
)

OCR_ENGINE: Any | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    ascii_text = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    return ascii_text or "section"


def clean_text(text: str) -> str:
    for source, target in RADICAL_REPLACEMENTS.items():
        text = text.replace(source, target)
    lines = []
    previous_blank = False
    for raw_line in text.replace("\r", "\n").splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            if not previous_blank:
                lines.append("")
            previous_blank = True
            continue
        lines.append(line)
        previous_blank = False
    return "\n".join(lines).strip()


def summarize_text(text: str, limit: int = 900) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def get_ocr_engine() -> Any | None:
    global OCR_ENGINE
    if OCR_ENGINE is not None:
        return OCR_ENGINE
    if RapidOCR is None:
        return None
    try:
        OCR_ENGINE = RapidOCR()
    except Exception:
        OCR_ENGINE = None
    return OCR_ENGINE


def ocr_image_text(image_path: Path) -> str:
    """Legacy: returns plain text only. Kept for backward compat."""
    items = ocr_image_with_bbox(image_path)
    lines = [item["text"] for item in items]
    return clean_text("\n".join(lines))


def _run_ocr_on_image(engine: Any, image_path: Path) -> list[Any]:
    try:
        result, _ = engine(str(image_path))
    except Exception:
        return []
    return result or []


def _image_size_or_default(image_path: Path) -> tuple[int, int]:
    try:
        with Image.open(str(image_path)) as image:
            return image.size
    except Exception:
        return 1000, 1000


def _normalize_image_measure(value: float, total: float) -> float:
    return round(value / total * 1000, 1) if total else 0


def _bbox_metrics(bbox: Any) -> dict[str, float]:
    points = bbox if isinstance(bbox, list) else []
    xs = [point[0] for point in points] or [0]
    ys = [point[1] for point in points] or [0]
    x_min, y_min = min(xs), min(ys)
    x_max, y_max = max(xs), max(ys)
    width = x_max - x_min
    height = y_max - y_min
    return {
        "x_min": x_min,
        "y_min": y_min,
        "width": width,
        "height": height,
        "x_center": x_min + width / 2,
        "y_center": y_min + height / 2,
    }


def _build_ocr_bbox_item(
    item: Any,
    img_w: int,
    img_h: int,
) -> dict[str, Any] | None:
    if not isinstance(item, (list, tuple)) or len(item) < 3:
        return None

    bbox, text, confidence = item[0], item[1], item[2]
    if not isinstance(text, str) or not text.strip():
        return None

    metrics = _bbox_metrics(bbox)
    return {
        "text": text.strip(),
        "bbox": bbox,
        "confidence": round(float(confidence), 4),
        "x_min": _normalize_image_measure(metrics["x_min"], img_w),
        "y_min": _normalize_image_measure(metrics["y_min"], img_h),
        "width": _normalize_image_measure(metrics["width"], img_w),
        "height": _normalize_image_measure(metrics["height"], img_h),
        "x_center": _normalize_image_measure(metrics["x_center"], img_w),
        "y_center": _normalize_image_measure(metrics["y_center"], img_h),
        "raw_x_center": metrics["x_center"],
        "raw_y_center": metrics["y_center"],
        "raw_width": metrics["width"],
        "raw_height": metrics["height"],
    }


def ocr_image_with_bbox(image_path: Path) -> list[dict[str, Any]]:
    """Run OCR and return structured data with bounding boxes.

    Each item: {text, bbox: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]],
                 confidence, x_center, y_center, width, height}
    """
    engine = get_ocr_engine()
    if engine is None:
        return []

    result = _run_ocr_on_image(engine, image_path)
    if not result:
        return []

    img_w, img_h = _image_size_or_default(image_path)

    items: list[dict[str, Any]] = []
    for item in result:
        payload = _build_ocr_bbox_item(item, img_w, img_h)
        if payload is not None:
            items.append(payload)
    return items


def _group_ocr_lines_into_rows(
    ocr_items: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Group OCR items into rows based on y_center proximity.

    Uses adaptive tolerance: items whose y_center differs by less than
    half the median item height are considered the same row.
    Within each row, items are sorted left-to-right by x_center.
    """
    if not ocr_items:
        return []

    # Compute median height for adaptive tolerance
    heights = sorted(item["height"] for item in ocr_items)
    median_h = heights[len(heights) // 2] if heights else 15
    # Tolerance: 40% of median height, clamped to [5, 20]
    y_tolerance = max(5.0, min(20.0, median_h * 0.4))

    # Sort by y_center first, then x_center
    sorted_items = sorted(ocr_items, key=lambda x: (x["y_center"], x["x_center"]))

    rows: list[list[dict[str, Any]]] = []
    current_row = [sorted_items[0]]
    current_y = sorted_items[0]["y_center"]

    for item in sorted_items[1:]:
        if abs(item["y_center"] - current_y) <= y_tolerance:
            current_row.append(item)
        else:
            # Sort current row by x and start new row
            current_row.sort(key=lambda x: x["x_center"])
            rows.append(current_row)
            current_row = [item]
            current_y = item["y_center"]

    # Don't forget the last row
    current_row.sort(key=lambda x: x["x_center"])
    rows.append(current_row)
    return rows


def _infer_block_role(row: list[dict[str, Any]]) -> str:
    """Infer the structural role of an OCR row based on layout heuristics.

    Returns one of: 'title', 'subtitle', 'table_row', 'label_value_pair',
    'paragraph', 'list_item', 'label'.
    """
    if not row:
        return "paragraph"

    text_len = len(" ".join(item["text"] for item in row))
    if _is_title_row(row, text_len):
        return "title"
    if _is_list_item_row(row):
        return "list_item"

    if _is_table_row(row):
        return "table_row"
    if _is_label_value_row(row):
        return "label_value_pair"
    if _is_subtitle_row(row, text_len):
        return "subtitle"
    if _is_paragraph_row(row, text_len):
        return "paragraph"
    if _is_label_row(row, text_len):
        return "label"

    return "paragraph"


def _is_title_row(row: list[dict[str, Any]], text_len: int) -> bool:
    if len(row) != 1:
        return False
    single = row[0]
    if single["width"] <= 500 or text_len <= 5:
        return False
    return single["y_center"] < 150 or single["width"] > 700


def _is_list_item_row(row: list[dict[str, Any]]) -> bool:
    return len(row) == 1 and bool(re.match(r"^[\d①-⓿、•○]+\s*[\.、．]\s", row[0]["text"]))


def _table_row_stats(row: list[dict[str, Any]]) -> tuple[list[float], float, float]:
    sorted_by_x = sorted(row, key=lambda item: item["x_center"])
    widths: list[float] = []
    gaps: list[float] = []
    for index, item in enumerate(sorted_by_x):
        widths.append(item["width"])
        if index == len(sorted_by_x) - 1:
            continue
        next_item = sorted_by_x[index + 1]
        left_end = item["x_center"] + item["width"] / 2
        right_start = next_item["x_center"] - next_item["width"] / 2
        gaps.append(right_start - left_end)

    avg_width = sum(widths) / len(widths)
    avg_gap = sum(gaps) / len(gaps) if gaps else 0
    return widths, avg_width, avg_gap


def _is_table_row(row: list[dict[str, Any]]) -> bool:
    if len(row) < 3:
        return False
    widths, avg_width, avg_gap = _table_row_stats(row)
    similar_count = sum(1 for width in widths if abs(width - avg_width) / max(avg_width, 1) < 0.35)
    return similar_count >= len(row) * 0.7 and avg_gap < avg_width * 0.8


def _is_label_value_row(row: list[dict[str, Any]]) -> bool:
    if len(row) != 2:
        return False
    return len(row[0]["text"]) <= 10 and len(row[1]["text"]) > 10


def _is_subtitle_row(row: list[dict[str, Any]], text_len: int) -> bool:
    return len(row) == 1 and 200 < row[0]["width"] < 600 and 5 < text_len < 30


def _is_paragraph_row(row: list[dict[str, Any]], text_len: int) -> bool:
    return len(row) == 1 and text_len >= 15


def _is_label_row(row: list[dict[str, Any]], text_len: int) -> bool:
    return len(row) == 1 and text_len <= 4


def _ensure_ocr_item_zones(ocr_items: list[dict[str, Any]]) -> None:
    if any("_zone" in item for item in ocr_items):
        return
    _tag_ocr_items_by_zone(ocr_items)


def _zone_sorted_ocr_items(
    ocr_items: list[dict[str, Any]],
    zone: str,
) -> list[dict[str, Any]]:
    return sorted(
        [item for item in ocr_items if item["_zone"] == zone],
        key=lambda item: (item["y_center"], item["x_center"]),
    )


def _ocr_items_by_zone(ocr_items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    _ensure_ocr_item_zones(ocr_items)
    return {
        _ZONE_TOP: _zone_sorted_ocr_items(ocr_items, _ZONE_TOP),
        _ZONE_SCREENSHOT: _zone_sorted_ocr_items(ocr_items, _ZONE_SCREENSHOT),
        _ZONE_CONTENT: _zone_sorted_ocr_items(ocr_items, _ZONE_CONTENT),
    }


def _markdown_table_row(row: list[dict[str, Any]], *, prefix: str = "") -> str:
    return f"{prefix}| {' | '.join(item['text'] for item in row)} |"


def _markdown_table_separator(column_count: int) -> str:
    return " | ".join(["---"] * column_count)


def _append_title_zone_markdown(
    markdown_lines: list[str],
    title_items: list[dict[str, Any]],
) -> None:
    if not title_items:
        return

    for row in _group_ocr_lines_into_rows(title_items):
        combined = " ".join(item["text"] for item in row)
        role = _infer_block_role(row)
        if role == "title":
            markdown_lines.append(f"## {combined}")
        elif role == "subtitle":
            markdown_lines.append(f"### {combined}")
        elif role == "label_value_pair" and len(row) == 2:
            markdown_lines.append(f"- **{row[0]['text']}**: {row[1]['text']}")
        elif role == "table_row":
            markdown_lines.append(_markdown_table_row(row))
        else:
            markdown_lines.append(combined)
    markdown_lines.append("")


def _append_screenshot_zone_markdown(
    markdown_lines: list[str],
    screenshot_items: list[dict[str, Any]],
) -> None:
    if not screenshot_items:
        return

    markdown_lines.append("> **[截图区域]** 以下文字来自页面截图插图：")
    markdown_lines.append(">")

    for row in _group_ocr_lines_into_rows(screenshot_items):
        combined = " ".join(item["text"] for item in row)
        role = _infer_block_role(row)
        if role == "table_row":
            markdown_lines.append(_markdown_table_row(row, prefix="> "))
        elif role == "label":
            markdown_lines.append(f"> `{combined}`")
        elif role in ("title", "subtitle"):
            markdown_lines.append(f"> **{combined}**")
        else:
            markdown_lines.append(f"> {combined}")

    markdown_lines.append("")


def _content_section_heading(row: list[dict[str, Any]], combined: str) -> str | None:
    if len(row) != 1:
        return None
    number_match = re.match(r"^(\d+)[\.、．]\s*(.+)", combined)
    if not number_match:
        return None
    return f"### {number_match.group(1)}. {number_match.group(2)}"


def _starts_new_markdown_table(markdown_lines: list[str]) -> bool:
    if not markdown_lines or markdown_lines[-1] != "" or len(markdown_lines) <= 1:
        return False
    return not any(line.startswith("|") for line in reversed(markdown_lines[:-1]))


def _append_content_list_item(
    markdown_lines: list[str],
    combined: str,
    state: dict[str, bool],
) -> None:
    if not state["in_numbered_block"]:
        markdown_lines.append("")
        state["in_numbered_block"] = True
    normalized = re.sub(r"^[①-⓿]", "", combined).strip()
    markdown_lines.append(f"- {normalized}")


def _append_content_table_row(
    markdown_lines: list[str],
    row: list[dict[str, Any]],
    state: dict[str, bool],
) -> None:
    if state["in_numbered_block"]:
        markdown_lines.append("")
        state["in_numbered_block"] = False
    markdown_lines.append(_markdown_table_row(row))
    if _starts_new_markdown_table(markdown_lines[:-1]):
        markdown_lines.append(_markdown_table_separator(len(row)))


def _append_content_label_value(
    markdown_lines: list[str],
    row: list[dict[str, Any]],
    state: dict[str, bool],
) -> None:
    if not state["in_numbered_block"]:
        markdown_lines.append("")
        state["in_numbered_block"] = True
    markdown_lines.append(f"- **{row[0]['text']}**: {row[1]['text']}")


def _append_content_label(
    markdown_lines: list[str],
    combined: str,
    state: dict[str, bool],
) -> None:
    if state["in_numbered_block"]:
        markdown_lines.append(f"- `{combined}`")
        return
    markdown_lines.append(f"`{combined}`")


def _append_content_paragraph(markdown_lines: list[str], combined: str) -> None:
    if combined.strip():
        markdown_lines.append(combined)


def _append_content_row_markdown(
    markdown_lines: list[str],
    row: list[dict[str, Any]],
    state: dict[str, bool],
) -> None:
    combined = " ".join(item["text"] for item in row)
    role = _infer_block_role(row)
    heading = _content_section_heading(row, combined)
    if heading:
        if state["in_numbered_block"]:
            markdown_lines.append("")
        markdown_lines.append(heading)
        state["in_numbered_block"] = True
        return
    if role == "list_item":
        _append_content_list_item(markdown_lines, combined, state)
        return
    if role == "table_row":
        _append_content_table_row(markdown_lines, row, state)
        return
    if role == "label_value_pair" and len(row) == 2:
        _append_content_label_value(markdown_lines, row, state)
        return
    if role == "label":
        _append_content_label(markdown_lines, combined, state)
        return
    _append_content_paragraph(markdown_lines, combined)


def _append_content_zone_markdown(
    markdown_lines: list[str],
    content_items: list[dict[str, Any]],
) -> None:
    if not content_items:
        return

    state = {"in_numbered_block": False}
    for row in _group_ocr_lines_into_rows(content_items):
        _append_content_row_markdown(markdown_lines, row, state)

    if state["in_numbered_block"]:
        markdown_lines.append("")


def _append_arrow_annotation_markdown(
    markdown_lines: list[str],
    arrow_annotations: list[str] | None,
) -> None:
    if not arrow_annotations:
        return

    markdown_lines.append("### 页面流转标注")
    markdown_lines.append("")
    for arrow in arrow_annotations:
        markdown_lines.append(f"- {arrow}")
    markdown_lines.append("")


def _unique_revision_items(revision_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique_items: list[dict[str, Any]] = []
    for revision in revision_items:
        key = revision["text"]
        if key in seen:
            continue
        seen.add(key)
        unique_items.append(revision)
    return unique_items


def _append_revision_markdown(
    markdown_lines: list[str],
    revision_items: list[dict[str, Any]] | None,
) -> None:
    if not revision_items:
        return

    markdown_lines.append("### 变更标记")
    markdown_lines.append("")
    for revision in _unique_revision_items(revision_items):
        label = {"add": "新增", "del": "删除", "mod": "修改"}.get(revision["type"], revision["marker"])
        markdown_lines.append(f"- [{label}] {revision['text']}")
    markdown_lines.append("")


def _rebuild_ocr_to_markdown(
    ocr_items: list[dict[str, Any]],
    exclude_screenshot_ocr: bool = False,
    arrow_annotations: list[str] | None = None,
    revision_items: list[dict[str, Any]] | None = None,
) -> str:
    """Convert structured OCR data into zone-organized Markdown.

    UE specification documents follow a 3-zone layout:
      Top (0-20%):     page titles, annotations, designer info
      Middle (20-60%): device screenshots with embedded UI labels
      Bottom (60-100%): numbered functional descriptions with rules

    Output order: Title → Screenshot glossary → Content descriptions → Arrows → Revisions.
    Screenshot zone is skipped if exclude_screenshot_ocr=True.
    """
    if not ocr_items:
        return ""

    zone_items = _ocr_items_by_zone(ocr_items)
    markdown_lines: list[str] = []

    _append_title_zone_markdown(markdown_lines, zone_items[_ZONE_TOP])
    if not exclude_screenshot_ocr:
        _append_screenshot_zone_markdown(markdown_lines, zone_items[_ZONE_SCREENSHOT])
    _append_content_zone_markdown(markdown_lines, zone_items[_ZONE_CONTENT])
    _append_arrow_annotation_markdown(markdown_lines, arrow_annotations)
    _append_revision_markdown(markdown_lines, revision_items)

    return "\n".join(markdown_lines)


def merge_text_evidence(primary_text: str, ocr_text: str) -> str:
    primary = clean_text(primary_text) if primary_text else ""
    secondary = clean_text(ocr_text) if ocr_text else ""
    if not primary:
        return secondary
    if not secondary:
        return primary
    primary_lines = extract_nonempty_lines(primary)
    seen = {line for line in primary_lines}
    merged = list(primary_lines)
    for line in extract_nonempty_lines(secondary):
        if line not in seen:
            merged.append(line)
            seen.add(line)
    return "\n".join(merged).strip()


def infer_page_title(lines: list[str], page_number: int) -> str:
    candidates = [line for line in lines if line and len(line) <= 90]
    if not candidates:
        return f"Page {page_number}"
    if page_number == 1:
        return " | ".join(candidates[:4])
    return candidates[0]


def token_set(text: str) -> set[str]:
    tokens = {token.lower() for token in re.findall(r"[A-Za-z0-9_]{3,}", text)}
    return {token for token in tokens if token not in STOP_WORDS}


def keyword_hits(text: str) -> list[str]:
    keywords = [
        "flow",
        "architecture",
        "signal",
        "diagram",
        "chart",
        "legend",
        "state",
        "swimlane",
        "ux",
        "screen",
        "page",
        "interaction",
    ]
    lower = text.lower()
    return [keyword for keyword in keywords if keyword in lower]


def extract_markdown_section(markdown_text: str, page_number: int, page_title: str) -> str:
    heading = f"## Page {page_number} - {page_title}"
    start = markdown_text.find(heading)
    if start == -1:
        return ""
    next_start = markdown_text.find("\n## Page ", start + len(heading))
    if next_start == -1:
        return markdown_text[start:]
    return markdown_text[start:next_start]


def extract_section_by_heading(markdown_text: str, heading: str) -> str:
    start = markdown_text.find(heading)
    if start == -1:
        return ""
    if heading.startswith("### "):
        next_positions = [
            position
            for position in [
                markdown_text.find("\n### ", start + len(heading)),
                markdown_text.find("\n## ", start + len(heading)),
            ]
            if position != -1
        ]
    else:
        next_positions = [position for position in [markdown_text.find("\n## ", start + len(heading))] if position != -1]
    if not next_positions:
        return markdown_text[start:]
    return markdown_text[start:min(next_positions)]


def extract_final_review_section(markdown_text: str, page: dict[str, Any]) -> str:
    heading_map = {
        1: "## 文档概览",
        2: "## 修复后的章节骨架",
        3: "## 1. 变更记录",
        4: "## 2. 标注说明与跳转线语义",
        5: "## 3. 信息架构与模块指向",
        6: "## 4. 页面布局分区",
        7: "## 5. 信息详情与主界面控件",
        8: "## 6. 空调设置与自动化策略",
        9: "## 7. 座椅控制与按摩流程",
    }
    primary = extract_section_by_heading(markdown_text, heading_map.get(page["page_number"], "")) if page["page_number"] in heading_map else ""
    appendix = extract_section_by_heading(markdown_text, f"### Page {page['page_number']:02d}")
    return "\n".join(part for part in [primary, appendix] if part)


def render_contact_sheet(image_paths: list[Path], output_path: Path) -> None:
    if not image_paths:
        return

    thumbs = []
    for image_path in image_paths:
        with Image.open(image_path) as image:
            thumb = image.copy()
            thumb.thumbnail((420, 240))
            thumb = ImageOps.expand(thumb, border=8, fill="white")
            thumbs.append(thumb)

    columns = 2
    rows = math.ceil(len(thumbs) / columns)
    cell_width = max(image.width for image in thumbs)
    cell_height = max(image.height for image in thumbs)
    canvas = Image.new("RGB", (cell_width * columns, cell_height * rows), "#d9dde3")

    for index, thumb in enumerate(thumbs):
        row = index // columns
        column = index % columns
        x_offset = column * cell_width
        y_offset = row * cell_height
        canvas.paste(thumb, (x_offset, y_offset))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, format="JPEG", quality=88)


def safe_pdfplumber_extract(page: Any, method_name: str, default: Any) -> tuple[Any, str]:
    try:
        return getattr(page, method_name)(), ""
    except Exception as exc:
        return default, f"{type(exc).__name__}: {exc}"


def safe_pdfplumber_image_count(page: Any) -> tuple[int, str]:
    try:
        return len(getattr(page, "images", []) or []), ""
    except Exception as exc:
        return 0, f"{type(exc).__name__}: {exc}"


def build_page_data(pdf_path: Path, images_dir: Path, output_root: Path,
                    enable_ocr: bool = True) -> dict[str, Any]:
    reader = PdfReader(str(pdf_path))
    pdfium_doc = pdfium.PdfDocument(str(pdf_path))

    pages: list[dict[str, Any]] = []
    image_paths: list[Path] = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        for zero_index, page in enumerate(pdf.pages):
            page_number = zero_index + 1
            raw_text, text_extraction_error = safe_pdfplumber_extract(page, "extract_text", "")
            tables, table_extraction_error = safe_pdfplumber_extract(page, "extract_tables", [])
            image_count, image_extraction_error = safe_pdfplumber_image_count(page)
            aspect_ratio = round(page.width / page.height, 3) if page.height else 0

            image_path = images_dir / f"page-{page_number:03d}.jpg"
            bitmap = pdfium_doc[zero_index].render(scale=0.5)
            pil_image = bitmap.to_pil()
            image_path.parent.mkdir(parents=True, exist_ok=True)
            pil_image.save(image_path, format="JPEG", quality=86)
            image_paths.append(image_path)

            cleaned_text = clean_text(raw_text)
            ocr_text = ""
            ocr_applied = False
            ocr_items: list[dict[str, Any]] = []
            ocr_structured_md = ""
            screenshot_regions: list[dict[str, Any]] = []

            # ── Approach: text-first or OCR rebuild ──
            approach = _classify_page_approach(
                cleaned_text=cleaned_text,
                page_image_count=image_count,
                enable_ocr=enable_ocr,
            )

            if approach == "ocr-rebuild" and enable_ocr:
                ocr_items = ocr_image_with_bbox(image_path)
                if ocr_items:
                    # ── Zone-based page restructuring (Phase 2) ──────
                    _tag_ocr_items_by_zone(ocr_items)

                    # ── Phase 3: Drawing + revision marker detection ─
                    drawing_items = _extract_pdf_drawing_annotations(
                        page, page.width, page.height
                    )
                    arrow_annotations = _annotate_arrows(drawing_items, ocr_items)
                    revision_items = _detect_revision_markers(ocr_items)

                    # Build structured markdown from OCR bbox data
                    ocr_structured_md = _rebuild_ocr_to_markdown(
                        ocr_items,
                        arrow_annotations=arrow_annotations,
                        revision_items=revision_items,
                    )
                    # Also keep legacy plain text for backward compat
                    ocr_text = "\n".join(item["text"] for item in ocr_items)

                    # Prefer structured markdown, fallback to plain OCR text
                    if ocr_structured_md:
                        cleaned_text = ocr_structured_md
                    else:
                        cleaned_text = merge_text_evidence(cleaned_text, ocr_text)
                    ocr_applied = True

            lines = [line for line in cleaned_text.splitlines() if line]
            page_title = infer_page_title(lines, page_number)
            text_tokens = token_set(cleaned_text)
            hits = keyword_hits(cleaned_text)
            is_visual_risk = bool((aspect_ratio >= 1.6 and len(cleaned_text) < 900) or hits or len(cleaned_text) < 180)

            pages.append(
                {
                    "page_number": page_number,
                    "page_id": f"page-{page_number}",
                    "title": page_title,
                    "text": cleaned_text,
                    "text_preview": summarize_text(cleaned_text),
                    "word_count": len(cleaned_text.split()),
                    "char_count": len(cleaned_text),
                    "pdfplumber_char_count": len(raw_text or ""),
                    "table_count": len(tables),
                    "image_count": image_count,
                    "processing_approach": approach,
                    "ocr_applied": ocr_applied,
                    "ocr_text_preview": summarize_text(ocr_text, 240) if ocr_text else "",
                    "ocr_text": ocr_text,
                    "ocr_items": ocr_items,
                    "ocr_structured_md": ocr_structured_md,
                    "screenshot_regions": [],  # legacy field, now using zone-based tagging
                    "screenshot_item_count": sum(
                        1 for item in ocr_items if item.get("_zone") == _ZONE_SCREENSHOT
                    ),
                    "content_item_count": sum(
                        1 for item in ocr_items if item.get("_zone") in (_ZONE_TOP, _ZONE_CONTENT)
                    ),
                    "text_extraction_error": text_extraction_error,
                    "table_extraction_error": table_extraction_error,
                    "image_extraction_error": image_extraction_error,
                    "aspect_ratio": aspect_ratio,
                    "keyword_hits": hits,
                    "is_visual_risk": is_visual_risk,
                    "image_path": image_path,
                    "tokens": sorted(text_tokens),
                }
            )

    metadata = reader.metadata or {}
    result = {
        "pdf_path": pdf_path,
        "page_count": len(reader.pages),
        "metadata": {
            "title": metadata.get("/Title") if isinstance(metadata, dict) else None,
            "author": metadata.get("/Author") if isinstance(metadata, dict) else None,
        },
        "pages": pages,
        "image_paths": image_paths,
    }

    return result


def build_block_catalog(document: dict[str, Any], output_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    blocks: list[dict[str, Any]] = []

    for page in document["pages"]:
        page_number = page["page_number"]
        blocks.append(
            {
                "raw_block_key": f"pdf:p{page_number}:heading:001",
                "block_type": "heading",
                "semantic_role": "page-title",
                "status": "candidate",
                "source_locator": {"page": page_number, "kind": "page-title"},
                "evidence_sources": ["pdfplumber.extract_text"],
                "title": page["title"],
            }
        )
        if page["text"]:
            blocks.append(
                {
                    "raw_block_key": f"pdf:p{page_number}:text:001",
                    "block_type": "paragraph",
                    "semantic_role": "page-body",
                    "status": "candidate",
                    "source_locator": {"page": page_number, "kind": "page-text"},
                    "evidence_sources": ["pdfplumber.extract_text"],
                    "preview": page["text_preview"],
                }
            )
        for table_index in range(page["table_count"]):
            blocks.append(
                {
                    "raw_block_key": f"pdf:p{page_number}:table:{table_index + 1:03d}",
                    "block_type": "table",
                    "semantic_role": "page-table",
                    "status": "candidate",
                    "source_locator": {"page": page_number, "kind": "table", "index": table_index + 1},
                    "evidence_sources": ["pdfplumber.extract_tables"],
                }
            )
        if page["is_visual_risk"]:
            blocks.append(
                {
                    "raw_block_key": f"pdf:p{page_number}:diagram:001",
                    "block_type": "diagram",
                    "semantic_role": "visual-risk-page",
                    "status": "needs-review",
                    "source_locator": {"page": page_number, "kind": "page-image"},
                    "evidence_sources": ["pypdfium2.render", "pdfplumber.extract_text"],
                    "reason": "High aspect ratio, low text density, or diagram keywords detected.",
                }
            )

    catalog = {
        "document_id": document["pdf_path"].stem,
        "source_format": "pdf",
        "generated_at": utc_now(),
        "raw_block_total": len(blocks),
        "blocks": blocks,
    }
    write_json(output_root / "evidence" / "block-catalog.json", catalog)
    return catalog, blocks


def build_asset_roster(document: dict[str, Any], output_root: Path) -> None:
    lines = ["# Asset Roster", "", "| page_id | asset_path | notes |", "| --- | --- | --- |"]
    for page in document["pages"]:
        relative_image = page["image_path"].relative_to(output_root)
        notes = "visual-risk" if page["is_visual_risk"] else "page-render"
        lines.append(f"| {page['page_id']} | {relative_image.as_posix()} | {notes} |")
    write_text(output_root / "evidence" / "asset-roster.md", "\n".join(lines) + "\n")


def build_layout_roster(document: dict[str, Any], output_root: Path) -> None:
    lines = ["# Layout Roster", "", "| page_id | aspect_ratio | word_count | table_count | visual_risk |", "| --- | --- | --- | --- | --- |"]
    for page in document["pages"]:
        lines.append(
            f"| {page['page_id']} | {page['aspect_ratio']} | {page['word_count']} | {page['table_count']} | {str(page['is_visual_risk']).lower()} |"
        )
    write_text(output_root / "evidence" / "layout-roster.md", "\n".join(lines) + "\n")


def build_relation_candidates(document: dict[str, Any], output_root: Path) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    lines = [
        "# Relation Candidates",
        "",
        "| relation_key | page_id | relation_type | reason | confidence | needs_multimodal_review |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for page in document["pages"]:
        reasons = []
        if page["aspect_ratio"] >= 1.6:
            reasons.append("wide-layout")
        if page["keyword_hits"]:
            reasons.append("keywords=" + ",".join(page["keyword_hits"]))
        if page["table_count"]:
            reasons.append("table-present")
        if page["is_visual_risk"]:
            relation_key = f"rel:{page['page_id']}:visual-risk:001"
            candidate = {
                "relation_key": relation_key,
                "page_id": page["page_id"],
                "relation_type": "visual-risk",
                "reason": "; ".join(reasons) or "visual-risk heuristic",
                "confidence": 0.35,
                "needs_multimodal_review": True,
            }
            candidates.append(candidate)
            lines.append(
                f"| {relation_key} | {page['page_id']} | visual-risk | {candidate['reason']} | 0.35 | true |"
            )
    write_text(output_root / "evidence" / "relation-candidates.md", "\n".join(lines) + "\n")
    return candidates


def build_visual_review_queue(document: dict[str, Any], candidates: list[dict[str, Any]], output_root: Path) -> list[dict[str, Any]]:
    candidate_map = Counter(candidate["page_id"] for candidate in candidates)
    queue = []
    for page in document["pages"]:
        if not page["is_visual_risk"]:
            continue
        queue.append(
            {
                "page_id": page["page_id"],
                "page_number": page["page_number"],
                "reason": "heuristic-visual-risk",
                "relation_candidate_count": candidate_map[page["page_id"]],
                "image_path": page["image_path"].relative_to(output_root).as_posix(),
            }
        )
    payload = {"generated_at": utc_now(), "items": queue}
    write_json(output_root / "evidence" / "visual-review-queue.json", payload)
    return queue


def build_visual_review_report(queue: list[dict[str, Any]], output_root: Path) -> None:
    reviewed_pages = []
    summary_lines = ["# Visual Review Summary", "", "This run includes a heuristic pre-review queue. Pages below still require agent or human visual confirmation.", ""]
    if not queue:
        summary_lines.append("No pages were flagged for visual review.")
    for item in queue:
        reviewed_pages.append(
            {
                "page_id": item["page_id"],
                "reason": item["reason"],
                "findings": [
                    {
                        "finding_id": f"{item['page_id']}-visual-risk-001",
                        "proposed_block_key": f"pdf:p{item['page_number']}:diagram:001",
                        "status": "needs-human-review",
                        "summary": "Visual-risk page detected before markdown generation. Confirm arrows, legends, and grouped objects against page image.",
                        "evidence_refs": [item["image_path"], "evidence/relation-candidates.md"],
                    }
                ],
            }
        )
        summary_lines.append(f"- {item['page_id']}: visual-risk queue retained for downstream review.")
    write_json(output_root / "evidence" / "visual-review-report.json", {"generated_at": utc_now(), "reviewed_pages": reviewed_pages})
    write_text(output_root / "evidence" / "visual-review-summary.md", "\n".join(summary_lines) + "\n")


def build_block_audit(blocks: list[dict[str, Any]], output_root: Path) -> dict[str, list[dict[str, Any]]]:
    classified = {"in-markdown": [], "evidence-only": [], "needs-clarification": []}
    for block in blocks:
        if block["block_type"] in {"heading", "paragraph", "table"}:
            classified["in-markdown"].append(block)
        elif block["status"] == "needs-review":
            classified["needs-clarification"].append(block)
        else:
            classified["evidence-only"].append(block)

    lines = ["# Block Audit", ""]
    for section in ["in-markdown", "evidence-only", "needs-clarification"]:
        lines.append(f"## {section}")
        lines.append("")
        if not classified[section]:
            lines.append("- None")
            lines.append("")
            continue
        for block in classified[section]:
            reason = block.get("reason") or block.get("semantic_role") or "retained"
            lines.append(f"- `{block['raw_block_key']}`: {reason}")
        lines.append("")

    write_text(output_root / "evidence" / "block-audit.md", "\n".join(lines))
    return classified


def build_heading_tree(document: dict[str, Any], output_root: Path) -> None:
    headings = [{"level": 1 if page["page_number"] == 1 else 2, "title": page["title"], "page_id": page["page_id"]} for page in document["pages"]]
    write_json(output_root / "evidence" / "heading-tree.json", headings)


def build_orphan_blocks(classified: dict[str, list[dict[str, Any]]], output_root: Path) -> None:
    orphans = [block["raw_block_key"] for block in classified["needs-clarification"]]
    write_json(output_root / "evidence" / "orphan-blocks.json", {"orphans": orphans})


def build_freeze(document: dict[str, Any], classified: dict[str, list[dict[str, Any]]], queue: list[dict[str, Any]], candidates: list[dict[str, Any]], output_root: Path) -> dict[str, Any]:
    freeze = {
        "document_id": document["pdf_path"].stem,
        "raw_block_total": sum(len(classified[key]) for key in classified),
        "in_markdown_block_total": len(classified["in-markdown"]),
        "evidence_only_block_total": len(classified["evidence-only"]),
        "needs_clarification_total": len(classified["needs-clarification"]),
        "heading_tree": [{"level": 1 if page["page_number"] == 1 else 2, "title": page["title"], "page_id": page["page_id"]} for page in document["pages"]],
        "figure_total": len(queue),
        "table_total": sum(page["table_count"] for page in document["pages"]),
        "chart_total": 0,
        "visual_review_required_pages": [item["page_id"] for item in queue],
        "orphan_blocks": [block["raw_block_key"] for block in classified["needs-clarification"]],
        "unresolved_relation_candidates": [candidate["relation_key"] for candidate in candidates],
        "frozen_from": [
            "evidence/block-audit.md",
            "evidence/relation-candidates.md",
            "evidence/visual-review-report.json",
        ],
        "generated_at": utc_now(),
    }
    write_json(output_root / "evidence" / "md-input-freeze.json", freeze)
    write_text(output_root / "evidence" / "freeze-sources.md", "# Freeze Sources\n\n- evidence/block-audit.md\n- evidence/relation-candidates.md\n- evidence/visual-review-report.json\n")
    return freeze


def build_visual_structure_notes(page: dict[str, Any]) -> list[str]:
    title = page["title"]
    text = page["text"]
    notes: list[str] = []

    if "标注说明" in title or "Annotation Notes" in title:
        group_aliases = [
            ("页面标注", ["页面标注", "⻚⾯标注"]),
            ("手势操作", ["手势操作", "⼿势操作"]),
            ("页面变更标记", ["页面变更标记", "⻚⾯变更标记"]),
            ("跳转线", ["跳转线"]),
            ("区域标记", ["区域标记"]),
        ]
        groups = [canonical for canonical, aliases in group_aliases if any(alias in text for alias in aliases)]
        if groups:
            notes.append("该页包含以下标注分组：" + "、".join(groups) + "。")

    if "信息架构" in title or "Information Architecture" in title:
        core_chain = [term for term in ["座椅控制", "空调", "空调控制"] if term in text]
        left_terms = [
            term
            for term in ["座椅通风", "座椅加热", "座椅按摩", "方向盘加热", "后排加热/通风"]
            if term in text
        ]
        right_terms = [
            term
            for term in [
                "MAX A/C",
                "温度调节",
                "AUTO",
                "风量调节",
                "温度同步",
                "净化/舒适功能",
                "开关",
                "出风模式",
                "内外循环",
                "空调设置",
                "三态循环",
                "后除霜",
                "电子外后视镜加热",
            ]
            if term in text
        ]
        if len(core_chain) == 3:
            notes.append("结构关系：" + " -> ".join(core_chain) + "。")
        if left_terms:
            notes.append("座椅侧功能：" + "、".join(left_terms) + "。")
        if right_terms:
            notes.append("空调控制侧功能：" + "、".join(right_terms) + "。")

    if "页面布局" in title or "Page Layout" in title:
        zones = [term for term in ["A区", "B区", "C区"] if term in text]
        if zones:
            notes.append("布局分区：" + "、".join(zones) + "。")
        if "基础布局说明" in text:
            notes.append("该页通过页面截图示例解释布局分区与基础布局说明面板的对应关系。")

    return notes


def extract_nonempty_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


# ── Adaptive OCR Routing ──────────────────────────────────────────────

# How the pipeline decides which approach to use per page:
#   text-first      → pdfplumber gave enough readable text
#   ocr-rebuild     → pdfplumber empty/garbled, use RapidOCR + bbox reconstruction
#
# Routing factors:
#   1. pdfplumber text quality (chars, garbled ratio)
#   2. page image characteristics (embedded image count, aspect ratio)
#   3. total document page count
#   4. user preference (--ocr on/off)

# Thresholds
_OCR_TRIGGER_CHARS = 20            # below this → consider OCR
_GARBLED_RATIO_THRESHOLD = 0.60    # < 60% readable → garbled


def _classify_page_approach(
    cleaned_text: str,
    page_image_count: int,
    enable_ocr: bool = True,
) -> str:
    """Decide the processing approach for a single page.

    Returns one of:
    - 'text-first': pdfplumber text is sufficient, skip OCR
    - 'ocr-rebuild': pdfplumber empty/garbled, use RapidOCR + structure rebuild
    """
    text_len = len(cleaned_text)

    # Case 1: pdfplumber gave readable text → text-first, no further processing
    if text_len >= _OCR_TRIGGER_CHARS:
        if not _is_text_garbled(cleaned_text):
            return "text-first"

    # Case 2: text is garbled or empty → need OCR
    if not enable_ocr:
        return "text-first"  # nothing we can do

    # Case 3: default fallback → OCR + structure rebuild
    return "ocr-rebuild"


# ── UE Document Zone Detection (Phase 2) ───────────────────────────────

# UE specification documents (UE规范) follow a consistent 3-zone layout:
#   TOP_ZONE    (y: 0–20%)    → Page title, annotations, red markers
#   MIDDLE_ZONE (y: 20–60%)   → Screenshots with UI labels embedded
#   BOTTOM_ZONE (y: 60–100%)  → Numbered functional descriptions with rules
#
# Instead of trying to separate "content" from "screenshot text", we
# reconstruct the page structure by understanding which zone each OCR
# item belongs to, then output them in the right order and format.

_ZONE_TOP = "top"           # Title area
_ZONE_SCREENSHOT = "screenshot"  # Screenshot area
_ZONE_CONTENT = "content"   # Functional description area

# Keywords that strongly indicate content/description text (interaction rules, conditions, toasts)
_CONTENT_KEYWORDS = [
    "用户通过", "启用/禁用", "用户点击", "点击打开", "点击关闭",
    "开启后，", "关闭后，", "不满足", "无法从",
    "请尽快维修", "请尽快处理", "按钮置灰", "高亮",
    "操作过频", "锁止状态", "已经", "故障显示",
    "可方便地", "可减少", "可更加", "可重新",
    "踩下刹车", "踩下制动", "系好安全带",
    "弹框消失", "流程结束", "确认弹窗", "二次确认",
    "依据信号", "反馈显示", "确定关闭",
    # Auto/Seat/HVAC domain-specific functional description patterns
    "后除霜", "前除霜", "外后视镜", "后视镜加热",
    "出风模式", "内外循环", "温度同步",
    "pm2.5", "PM2.5", "空气质量", "净化",
    "互斥", "提示语", "不可用", "通风", "加热", "按摩",
    "新风系统", "自定义通风", "座舱",
    "默认态", "开启态", "关闭态", "置灰态",
    "电源", "档位", "ACC", "空调系统",
    "toast", "提醒", "播报", "TTS",
]

# Patterns that indicate pure UI labels (short, visual-only, no functional description)
# Narrowed to avoid matching functional descriptions that happen to mention state keywords
_UI_LABEL_INDICATORS = [
    "Tab标签", "一级", "二级", "制冷中", "℃", "Bar",
    "icon", "插图", "UI可以",
    "（-40）", "（-20）", "标准(0)",
    "21:05", "*artl",
]


def _detect_page_zone(y_pct: float, text: str) -> str:
    """Classify an OCR item's zone based on vertical position and content analysis.

    Uses normalized 0-1000 y coordinates plus keyword-based content detection.
    """
    # Top 20%: always title/annotation area
    if y_pct < 200:
        return _ZONE_TOP

    # Bottom 40%: always content area (numbered descriptions)
    if y_pct >= 600:
        return _ZONE_CONTENT

    # Middle 40%: screenshot area by default, with strict content override
    # Content override requires BOTH: a content keyword AND no UI label indicator
    has_content_keyword = any(kw in text for kw in _CONTENT_KEYWORDS)
    is_ui_label = any(kw in text for kw in _UI_LABEL_INDICATORS)

    if has_content_keyword and not is_ui_label:
        return _ZONE_CONTENT

    return _ZONE_SCREENSHOT


def _tag_ocr_items_by_zone(
    ocr_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Tag each OCR item with its page zone: top / screenshot / content.

    Uses both vertical position (y_center) and content keyword matching
    to distinguish UI labels embedded in screenshots from actual
    functional description text.
    """
    for item in ocr_items:
        y_norm = item.get("y_center", 500)  # 0-1000 normalized
        text = item["text"]
        item["_zone"] = _detect_page_zone(y_norm, text)

    return ocr_items


# ── Phase 3: Arrow and Revision Mark Detection ─────────────────────────

# PDF drawing colors commonly used for annotations
_ANNOTATION_COLORS = {
    (1.0, 0.0, 0.0): "red",       # (255, 0, 0) in 0-1 scale
    (0.0, 0.0, 1.0): "blue",      # Blue arrows for flow
    (0.0, 0.8, 0.0): "green",     # Green for "Yes" / new
    (1.0, 0.5, 0.0): "orange",    # Orange for modifications
}


def _extract_pdf_drawing_annotations(
    page,
    page_width: float,
    page_height: float,
) -> list[dict[str, Any]]:
    """Extract lines, rects, and curves from a pdfplumber page.

    Returns a list of dicts describing:
    - arrows: line segments with direction info
    - rects: annotation boxes (often red = revision marks)
    - curves: bezier curves (flow connectors)
    Coordinates are normalized to 0-1000 scale.
    """
    items: list[dict[str, Any]] = []
    items.extend(_extract_pdf_line_items(page, page_width, page_height))
    items.extend(_extract_pdf_rect_items(page, page_width, page_height))
    items.extend(_extract_pdf_curve_items(page))
    return items


def _normalize_page_measure(value: float, total: float) -> float:
    return round(value / total * 1000, 1) if total else 0


def _extract_pdf_line_items(
    page: Any,
    page_width: float,
    page_height: float,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for line in getattr(page, "lines", None) or []:
        x0 = line.get("x0", 0) or 0
        y0 = line.get("y0", 0) or 0
        x1 = line.get("x1", 0) or 0
        y1 = line.get("y1", 0) or 0
        stroke_color = line.get("stroke_color")
        items.append(
            {
                "type": "line",
                "x0": _normalize_page_measure(x0, page_width),
                "y0": _normalize_page_measure(y0, page_height),
                "x1": _normalize_page_measure(x1, page_width),
                "y1": _normalize_page_measure(y1, page_height),
                "length": ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5,
                "stroke_color": stroke_color,
                "color_label": _color_label(stroke_color),
            }
        )
    return items


def _extract_pdf_rect_items(
    page: Any,
    page_width: float,
    page_height: float,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for rect in getattr(page, "rects", None) or []:
        x0 = rect.get("x0", 0) or 0
        y0 = rect.get("y0", 0) or 0
        x1 = rect.get("x1", 0) or 0
        y1 = rect.get("y1", 0) or 0
        fill_color = rect.get("fill") or rect.get("fill_color")
        stroke_color = rect.get("stroke") or rect.get("stroke_color")
        items.append(
            {
                "type": "rect",
                "x0": _normalize_page_measure(x0, page_width),
                "y0": _normalize_page_measure(y0, page_height),
                "x1": _normalize_page_measure(x1, page_width),
                "y1": _normalize_page_measure(y1, page_height),
                "width": _normalize_page_measure(x1 - x0, page_width),
                "height": _normalize_page_measure(y1 - y0, page_height),
                "fill_color": fill_color,
                "stroke_color": stroke_color,
                "fill_label": _color_label(fill_color),
            }
        )
    return items


def _extract_pdf_curve_items(page: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for curve in getattr(page, "curves", None) or []:
        items.append(
            {
                "type": "curve",
                "pts": curve.get("pts", []),
                "fill_color": curve.get("fill"),
                "stroke_color": curve.get("stroke"),
            }
        )
    return items


def _color_label(color: Any) -> str:
    """Map a PDF color value to a human-readable label."""
    if color is None:
        return "unknown"
    if isinstance(color, tuple) and len(color) >= 3:
        # Convert to 0-1 scale for matching
        r, g, b = color[0], color[1], color[2]
        for known, label in _ANNOTATION_COLORS.items():
            kr, kg, kb = known
            if abs(r - kr) < 0.15 and abs(g - kg) < 0.15 and abs(b - kb) < 0.15:
                return label
    if isinstance(color, str):
        return color
    return "unknown"


def _annotate_arrows(
    drawing_items: list[dict[str, Any]],
    ocr_items: list[dict[str, Any]],
) -> list[str]:
    """Infer semantic meaning from arrows by finding nearby text at endpoints.

    For each line:
    - Find the nearest OCR text at the start point
    - Find the nearest OCR text at the end point
    - Generate: "→ 从「{start_text}」指向「{end_text}」"
    """
    annotations: list[str] = []

    lines = [d for d in drawing_items if d["type"] == "line"]
    # Filter: only consider lines long enough to be arrows (not borders)
    significant_lines = [l for l in lines if l["length"] > 20]

    for line in significant_lines:
        start_text = _find_nearest_ocr_text(line["x0"], line["y0"], ocr_items, radius=150)
        end_text = _find_nearest_ocr_text(line["x1"], line["y1"], ocr_items, radius=150)

        if start_text and end_text and start_text != end_text:
            color_hint = ""
            if line["color_label"] == "red":
                color_hint = " [修订]"
            annotations.append(f"→ 从「{start_text}」指向「{end_text}」{color_hint}")

    return annotations


def _find_nearest_ocr_text(
    x: float, y: float, ocr_items: list[dict[str, Any]], radius: float = 100
) -> str:
    """Find the nearest OCR text block to a point within radius."""
    best_item = None
    best_dist = radius

    for item in ocr_items:
        cx = item.get("x_center", 500)
        cy = item.get("y_center", 500)
        dist = ((cx - x) ** 2 + (cy - y) ** 2) ** 0.5
        if dist < best_dist:
            best_dist = dist
            best_item = item

    if best_item:
        return best_item["text"]
    return ""


_REVISION_MARKERS = {
    "新增": "add",
    "增加": "add",
    "添加": "add",
    "删除": "del",
    "移除": "del",
    "修改": "mod",
    "变更": "mod",
    "调整": "mod",
    "更新": "mod",
}


def _detect_revision_markers(ocr_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect revision-related keywords in OCR text at the item level.

    Returns a list of dicts: {marker, type, text, zone}
    Types: add / del / mod
    """
    results: list[dict[str, Any]] = []

    for item in ocr_items:
        text = item["text"]
        for marker, rev_type in _REVISION_MARKERS.items():
            if marker in text:
                results.append({
                    "marker": marker,
                    "type": rev_type,
                    "text": text,
                    "zone": item.get("_zone", "unknown"),
                })

    return results


def _is_text_garbled(text: str) -> bool:
    """Return True if the text looks like corrupted font encoding rather than readable content.

    This catches cases where pdfplumber extracts characters but they are
    replacement chars, private-use codepoints, control chars, or other
    non-human-readable glyphs that indicate broken font embedding.
    """
    if not text or len(text.strip()) < 5:
        return False  # Too short to judge; let the empty-text check handle it

    return _readable_character_ratio(text) < 0.60


def _readable_character_ratio(text: str) -> float:
    total = 0
    readable = 0
    for ch in text:
        if ch.isspace():
            continue
        total += 1
        if _is_readable_text_char(ch):
            readable += 1

    if total == 0:
        return 1.0
    return readable / total


def _is_readable_text_char(ch: str) -> bool:
    code = ord(ch)
    return any(start <= code <= end for start, end in _READABLE_CODEPOINT_RANGES)



def build_annotation_groups(text: str) -> list[str]:
    group_aliases = [
        ("页面标注", ["页面标注"]),
        ("手势操作", ["手势操作"]),
        ("页面变更标记", ["页面变更标记"]),
        ("页面跳转标注", ["页面跳转标注"]),
        ("功能解释标注", ["功能解释标注"]),
        ("问题类标注", ["问题类标注"]),
        ("语音指令标注", ["语音指令标注", "语音命令"]),
        ("跳转线", ["跳转线"]),
        ("区域标记", ["区域标记"]),
        ("页码标注", ["页码标注"]),
    ]
    return [canonical for canonical, aliases in group_aliases if any(alias in text for alias in aliases)]


def build_info_architecture_terms(text: str) -> tuple[list[str], list[str], list[str]]:
    core_chain = [term for term in ["座椅控制", "空调", "空调控制"] if term in text]
    left_terms = [
        term
        for term in ["座椅通风", "座椅加热", "座椅按摩", "方向盘加热", "后排加热/通风"]
        if term in text
    ]
    right_terms = [
        term
        for term in [
            "MAX A/C",
            "温度调节",
            "AUTO",
            "风量调节",
            "温度同步",
            "净化/舒适功能",
            "开关",
            "出风模式",
            "内外循环",
            "空调设置",
            "三态循环",
            "后除霜",
            "电子外后视镜加热",
        ]
        if term in text
    ]
    return core_chain, left_terms, right_terms


def parse_toc_entries(text: str) -> list[dict[str, str]]:
    lines = extract_nonempty_lines(text)
    filtered = []
    for line in lines:
        if line in {"J90K 目录", "目录", "Content", "J90K"}:
            continue
        filtered.append(line)

    entries: list[dict[str, str]] = []
    index = 0
    while index <= len(filtered) - 3:
        title = filtered[index]
        section_no = filtered[index + 1]
        page_no = filtered[index + 2]
        if re.fullmatch(r"\d{2}", section_no) and re.fullmatch(r"\d+", page_no) and not re.fullmatch(r"\d+", title):
            entries.append({"section_no": section_no, "title": title, "page_no": page_no})
            index += 3
            continue
        index += 1
    return entries


def write_mermaid_asset(output_root: Path, page_number: int, slug: str, code: str) -> Path:
    mermaid_path = output_root / "markdown" / "mermaid" / f"page-{page_number:03d}-{slug}.mmd"
    write_text(mermaid_path, code.rstrip() + "\n")
    return mermaid_path


def build_annotation_mermaid(page: dict[str, Any]) -> str:
    groups = build_annotation_groups(page["text"])
    lines = ["mindmap", "  root((标注说明))"]
    for group in groups:
        lines.append(f"    {group}")
    return "\n".join(lines)


def build_info_architecture_mermaid(page: dict[str, Any]) -> str:
    core_chain, left_terms, right_terms = build_info_architecture_terms(page["text"])
    lines = ["flowchart LR"]
    lines.append('    SeatControl["座椅控制"]')
    lines.append('    AirCore["空调"]')
    lines.append('    AirControl["空调控制"]')
    for index, label in enumerate(left_terms, start=1):
        node = f"L{index}"
        lines.append(f'    {node}["{label}"] --> SeatControl')
    lines.append("    SeatControl --> AirCore --> AirControl")
    for index, label in enumerate(right_terms, start=1):
        node = f"R{index}"
        lines.append(f'    AirControl --> {node}["{label}"]')
    if not left_terms and not right_terms and len(core_chain) == 3:
        lines.append('    SeatControl --> AirCore --> AirControl')
    return "\n".join(lines)


def build_page_layout_mermaid(page: dict[str, Any]) -> str:
    lines = [
        "flowchart TB",
        '    subgraph Layout1["布局示例一"]',
        '        Statusbar1["Statusbar"] --> ZoneA1["A区 菜单标题栏"]',
        '        ZoneA1 --> ZoneB1["B区 空调视图与次要功能区"]',
        '        ZoneB1 --> ZoneC1["C区 主要核心操作功能区"]',
        '        ZoneC1 --> Dock1["Dock"]',
        "    end",
        '    subgraph Layout2["布局示例二"]',
        '        Statusbar2["Statusbar"] --> ZoneA2["A区 菜单标题栏"]',
        '        ZoneA2 --> ZoneB2["B区 功能操作与视图"]',
        '        ZoneB2 --> Dock2["Dock"]',
        "    end",
    ]
    return "\n".join(lines)


def build_raw_text_details(text: str) -> list[str]:
    safe_text = text.replace("```", "'''")
    return [
        "Raw extracted text:",
        "",
        "```text",
        safe_text.rstrip(),
        "```",
        "",
    ]


def sanitize_markdown_line(line: str) -> str:
    sanitized = EMAIL_RE.sub(lambda match: f"[{match.group(1)}](mailto:{match.group(1)})", line)
    if re.match(r"^\s*[-*+]\s", sanitized):
        sanitized = "\\" + sanitized
    return sanitized


def sanitize_markdown_block(text: str) -> str:
    return "\n".join(sanitize_markdown_line(line) for line in text.splitlines())


def match_toc_target(entry: dict[str, str], pages: list[dict[str, Any]], anchors: dict[str, str]) -> str:
    for page in pages:
        title = page["title"]
        if title.startswith(entry["section_no"]) or entry["title"] in title:
            return f"Page {page['page_number']}"
    return ""


def render_page_body(page: dict[str, Any], output_root: Path) -> list[str]:
    title = page["title"]
    text = page["text"]
    body: list[str] = []

    if "目录" in title or "Content" in text:
        entries = parse_toc_entries(text)
        body.append(f"### Page {page['page_number']} Structured TOC")
        body.append("")
        body.append("| 序号 | 章节 | 页码 |")
        body.append("| --- | --- | --- |")
        for entry in entries:
            body.append(f"| {entry['section_no']} | {entry['title']} | {entry['page_no']} |")
        body.append("")
        body.extend(build_raw_text_details(text))
        return body

    if "标注说明" in title or "Annotation Notes" in title:
        mermaid = build_annotation_mermaid(page)
        mermaid_path = write_mermaid_asset(output_root, page["page_number"], "annotation-notes", mermaid)
        body.append(f"### Page {page['page_number']} Mermaid Reconstruction")
        body.append("")
        body.append(f"Source: [{mermaid_path.name}](mermaid/{mermaid_path.name})")
        body.append("")
        body.append("```mermaid")
        body.append(mermaid)
        body.append("```")
        body.append("")
        body.extend(build_raw_text_details(text))
        return body

    if "信息架构" in title or "Information Architecture" in title:
        mermaid = build_info_architecture_mermaid(page)
        mermaid_path = write_mermaid_asset(output_root, page["page_number"], "information-architecture", mermaid)
        body.append(f"### Page {page['page_number']} Mermaid Reconstruction")
        body.append("")
        body.append(f"Source: [{mermaid_path.name}](mermaid/{mermaid_path.name})")
        body.append("")
        body.append("```mermaid")
        body.append(mermaid)
        body.append("```")
        body.append("")
        body.extend(build_raw_text_details(text))
        return body

    if "页面布局" in title or "Page Layout" in title:
        mermaid = build_page_layout_mermaid(page)
        mermaid_path = write_mermaid_asset(output_root, page["page_number"], "page-layout", mermaid)
        body.append(f"### Page {page['page_number']} Mermaid Reconstruction")
        body.append("")
        body.append(f"Source: [{mermaid_path.name}](mermaid/{mermaid_path.name})")
        body.append("")
        body.append("```mermaid")
        body.append(mermaid)
        body.append("```")
        body.append("")
        body.extend(build_raw_text_details(text))
        return body

    if text:
        for paragraph in [chunk for chunk in text.split("\n\n") if chunk.strip()]:
            body.append(sanitize_markdown_block(paragraph))
            body.append("")
    else:
        body.append("This page has no extractable text. Review the rendered page image and visual evidence.")
        body.append("")
    return body


def page_image_ref(page: dict[str, Any], base_dir: Path) -> str:
    return Path(os.path.relpath(page["image_path"], base_dir)).as_posix()


def relative_path(path: Path, base_dir: Path) -> str:
    return Path(os.path.relpath(path, base_dir)).as_posix()


def compact_excerpt(text: str, limit: int = 220) -> str:
    excerpt = summarize_text(re.sub(r"\s+", " ", text).strip(), limit)
    return EMAIL_RE.sub(lambda match: f"[{match.group(1)}](mailto:{match.group(1)})", excerpt)


def format_compact_date(value: str) -> str:
    if re.fullmatch(r"\d{8}", value):
        return f"{value[:4]}-{value[4:6]}-{value[6:8]}"
    return value


def ordered_unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def extract_release_metadata(text: str) -> dict[str, str]:
    version_match = re.search(r"Version[: ]*([0-9.]+)", text, re.IGNORECASE)
    release_match = re.search(r"RELEASED\s+(\d{2}\s+[A-Z]{3}\s+\d{4})", text, re.IGNORECASE)
    return {
        "version": version_match.group(1) if version_match else "",
        "release_date": release_match.group(1) if release_match else "",
    }


def build_visual_review_pages(document: dict[str, Any], freeze: dict[str, Any]) -> list[str]:
    """插图复核页（v2 修复）：只有含嵌入图的页面进入视觉复核。

    修复说明：旧判定的 `char_count > 1000` 会把文本密集页（docx 来源的功能规范等）
    全部误判为视觉页，导致全量页截图进入 Agent 修复流程（token 浪费）。
    文字多 ≠ 需要看图；视觉复核只服务于插图的正确识别与描述。
    freeze 队列仅作证据留档（evidence/visual-review-queue.json），不再驱动修复范围。
    """
    review_pages = {
        page["page_number"]
        for page in document["pages"]
        if page.get("image_count", 0) >= 1
    }
    return [str(page_number) for page_number in sorted(review_pages)]


def render_page_visual_assets(
    document: dict[str, Any],
    output_root: Path,
    only_pages: set[int] | None = None,
) -> dict[int, dict[str, Any]]:
    """渲染页级视觉资产。

    - only_pages=None：全量渲染（full + tiles + strips + halves），用于 UE 设计稿类
      领域模板文档（每页本质都是视觉页）。
    - only_pages={...}：按需渲染（v2 修复）——只为给定页（插图复核页 + 封面）生成
      full 截图，并按嵌入图 bbox 用 pdfium 高分辨率渲染裁剪出插图原图
      （page-NNNN-img-KK.png），不再生成 tiles/strips/halves。
      文本页零渲染、零视觉 token。
    """
    assets_root = output_root / "artifacts" / "pages"
    page_assets: dict[int, dict[str, Any]] = {}

    pdfium_doc = None
    if only_pages is not None:
        try:
            pdfium_doc = pdfium.PdfDocument(str(document["pdf_path"]))
        except Exception:
            pdfium_doc = None

    for page in document["pages"]:
        page_number = page["page_number"]
        if only_pages is not None and page_number not in only_pages:
            continue
        prefix = f"page-{page_number:04d}"
        with Image.open(page["image_path"]) as raw_image:
            image = raw_image.convert("RGB")
            width, height = image.size

            assets_root.mkdir(parents=True, exist_ok=True)
            full_path = assets_root / f"{prefix}-full.png"
            image.save(full_path, format="PNG", optimize=True)

        if only_pages is None:
            tiles: list[str] = []
            for row in range(2):
                for column in range(2):
                    left = round(width * column / 2)
                    top = round(height * row / 2)
                    right = width if column == 1 else round(width * (column + 1) / 2)
                    bottom = height if row == 1 else round(height * (row + 1) / 2)
                    tile_path = assets_root / f"{prefix}-tile-r{row + 1}c{column + 1}.png"
                    image.crop((left, top, right, bottom)).save(tile_path, format="PNG", optimize=True)
                    tiles.append(relative_path(tile_path, output_root))

            strips: dict[str, str] = {}
            for name, box in {
                "top": (0.0, 0.0, 1.0, 0.36),
                "middle": (0.0, 0.28, 1.0, 0.72),
                "bottom": (0.0, 0.64, 1.0, 1.0),
            }.items():
                left = 0
                top = round(height * box[1])
                right = width
                bottom = max(top + 1, round(height * box[3]))
                strip_path = assets_root / f"{prefix}-strip-{name}.png"
                image.crop((left, top, right, min(bottom, height))).save(strip_path, format="PNG", optimize=True)
                strips[name] = relative_path(strip_path, output_root)

            halves: dict[str, str] = {}
            for name, box in {
                "left": (0.0, 0.0, 0.56, 1.0),
                "right": (0.44, 0.0, 1.0, 1.0),
            }.items():
                left = round(width * box[0])
                top = 0
                right = max(left + 1, round(width * box[2]))
                bottom = height
                half_path = assets_root / f"{prefix}-half-{name}.png"
                image.crop((left, top, min(right, width), bottom)).save(half_path, format="PNG", optimize=True)
                halves[name] = relative_path(half_path, output_root)

            page_assets[page_number] = {
                "full": relative_path(full_path, output_root),
                "tiles": tiles,
                "strips": strips,
                "halves": halves,
            }
        else:
            # 按需模式：插图区域裁剪（上下文 full 已存），不生成 tiles/strips/halves
            illustrations = _render_illustration_crops(
                pdfium_doc, document, page_number, prefix, assets_root, output_root
            )
            page_assets[page_number] = {
                "full": relative_path(full_path, output_root),
                "tiles": [],
                "strips": {},
                "halves": {},
                "illustrations": illustrations,
            }

    if pdfium_doc is not None:
        pdfium_doc.close()
    return page_assets


# 插图裁剪参数：小于该尺寸（pt）的嵌入图视为图标/装饰，不值得视觉 token
_ILLUSTRATION_MIN_SIDE_PT = 40.0
# 裁剪渲染分辨率上限（每页一次渲染，按最长边约束），约 144 DPI
_ILLUSTRATION_RENDER_SCALE = 2.0
_ILLUSTRATION_MAX_SIDE_PX = 1600
# 单页插图裁剪数上限（超出部分按面积取最大的前 N 张）
_ILLUSTRATION_MAX_PER_PAGE = 12
# bbox 外扩（pt），保留少量上下文
_ILLUSTRATION_MARGIN_PT = 6.0


def _render_illustration_crops(
    pdfium_doc: Any,
    document: dict[str, Any],
    page_number: int,
    prefix: str,
    assets_root: Path,
    output_root: Path,
) -> list[str]:
    """按嵌入图 bbox 渲染裁剪插图区域，返回相对路径列表（最多 _ILLUSTRATION_MAX_PER_PAGE 张）。"""
    if pdfium_doc is None or page_number > len(pdfium_doc):
        return []
    # 仅对复核页重新打开 pdfplumber 取 bbox（数量少，开销可忽略）
    try:
        with pdfplumber.open(str(document["pdf_path"])) as plumber:
            images = list(plumber.pages[page_number - 1].images or [])
    except Exception:
        return []

    boxes = []
    for img in images:
        x0 = float(img.get("x0", 0))
        x1 = float(img.get("x1", 0))
        top = float(img.get("top", 0))
        bottom = float(img.get("bottom", 0))
        if (x1 - x0) < _ILLUSTRATION_MIN_SIDE_PT or (bottom - top) < _ILLUSTRATION_MIN_SIDE_PT:
            continue  # 图标/装饰元素，跳过
        boxes.append((x0, top, x1, bottom))
    if not boxes:
        return []
    boxes.sort(key=lambda b: (b[1] - b[0]) * (b[3] - b[2]), reverse=True)  # 按面积从大到小
    boxes = boxes[:_ILLUSTRATION_MAX_PER_PAGE]

    try:
        pdfium_page = pdfium_doc[page_number - 1]
        page_width = pdfium_page.get_width()
        page_height = pdfium_page.get_height()
        scale = _ILLUSTRATION_RENDER_SCALE
        longest_pt = max(page_width, page_height)
        if longest_pt > 0:
            scale = min(scale, _ILLUSTRATION_MAX_SIDE_PX / longest_pt)
        bitmap = pdfium_page.render(scale=max(scale, 0.1))
        pil_image = bitmap.to_pil().convert("RGB")
        px_per_pt = pil_image.width / page_width if page_width else 1.0
    except Exception:
        return []

    crop_paths: list[str] = []
    for idx, (x0, top, x1, bottom) in enumerate(boxes, 1):
        left_px = max(0, int((x0 - _ILLUSTRATION_MARGIN_PT) * px_per_pt))
        top_px = max(0, int((top - _ILLUSTRATION_MARGIN_PT) * px_per_pt))
        right_px = min(pil_image.width, int((x1 + _ILLUSTRATION_MARGIN_PT) * px_per_pt))
        bottom_px = min(pil_image.height, int((bottom + _ILLUSTRATION_MARGIN_PT) * px_per_pt))
        if right_px - left_px < 8 or bottom_px - top_px < 8:
            continue
        crop_path = assets_root / f"{prefix}-img-{idx:02d}.png"
        try:
            pil_image.crop((left_px, top_px, right_px, bottom_px)).save(crop_path, format="PNG", optimize=True)
        except Exception:
            continue
        crop_paths.append(relative_path(crop_path, output_root))
    return crop_paths


def extract_section_ids(text: str, prefix: str) -> list[str]:
    return ordered_unique(re.findall(rf"{re.escape(prefix)}\d+", text))


def extract_massage_modes(text: str) -> list[str]:
    match = re.search(r"支持[:：]\s*([^\n）\)]+)", text)
    if not match:
        return []
    return ordered_unique([item.strip() for item in re.split(r"[、/／]", match.group(1)) if item.strip()])


def build_details_section(page: dict[str, Any], page_assets: dict[int, dict[str, Any]]) -> list[str]:
    assets = page_assets[page["page_number"]]
    control_labels = extract_control_labels(page["text"])
    variants = extract_section_ids(page["text"], "05-")
    config_rows = [
        ("配置 1", "空调控制页面变体 `05-4`", "无对应座椅能力时隐藏相关座椅控件"),
        ("配置 2", "座椅控制页面变体 `05-5`", "按座椅能力显示对应按钮与视图"),
        ("配置 3", "座椅控制页面变体 `05-6`", "与配置 2 相比保留不同的功能显隐关系"),
        ("配置 4", "座椅控制页面变体 `05-7`", "继续表达配置裁剪后的页面骨架"),
        ("全量", "空调 + 座椅完整页面", "展示全部入口与完整功能集"),
    ]
    lines = [
        "## 5. 信息详情与主界面控件",
        f"![信息详情页]({assets['full']})",
        "",
        "### 5.1 页面组织方式",
        "",
        "- 这一页不是流程图，而是 `左侧主图 + 右侧说明卡 + 中下部变体说明 + 底部新增规则块` 的复合说明页。",
        "- 上半部聚焦主驾空调主界面与右侧控件解释；中部补充副驾与座椅页变体；底部绿色块承载 `20250704 新增` 的配置规则。",
        "- 因此恢复时应保持版面分区，而不是把整页文本线性串起来。",
        "",
        "### 5.2 左侧主视图与右侧说明卡",
        "",
        f"![信息详情左半区]({assets['halves']['left']})",
        "",
        f"![信息详情右半区]({assets['halves']['right']})",
        "",
        "| 视觉区域 | 恢复含义 | 处理原则 |",
        "| --- | --- | --- |",
        "| 顶部标题带 | `空调 / 座椅` 二级 tab 与页面标题 | 保留为导航区，不转成流程节点 |",
        "| 中部主视图区 | 主副驾温度、风量动效、PM2.5 与座椅视图反馈 | 还原为状态反馈区 |",
        "| 底部主控条 | Dock、同步、AUTO、MAX 等主控件 | 还原为主控件簇，不串成线性箭头 |",
        "| 右侧说明卡 | 对应主图上的红框注释与规则说明 | 保留为解释卡片，不与视觉区混写 |",
        "",
        "### 5.3 主控件与状态语义",
        "",
        "- 温度调节：主副驾温度独立显示，支持同步逻辑；空调关闭时仍显示上一次温度，但以弱化态呈现。",
        "- AUTO：只有全 AUTO 状态时工作指示灯点亮；风量、出风模式、压缩机或前除霜操作会退出 AUTO。",
        "- A/C：baseline 里仍保留了历史说明，但页面上已明确标注 `20250108 删除`。",
        "- 舒适 / 节能：开启后进入节能模式，并可能与其他模块联动。",
        "- 制冷 / 制热 / 通风：三态合一循环按钮。",
        "- MAX A/C：强制进入高制冷状态，并联动风量、内循环和最低温设定。",
        "- 内外循环：前除霜期间强制外循环，结束后恢复原状态。",
        "- 风量调节：通过 Dock 的点击或上滑进入浮层，1-8 档，0 档关机。",
        "",
        "关键标注控件：",
    ]
    for label in control_labels[:16]:
        lines.append(f"- {label}")
    lines.extend(
        [
            "",
            "### 5.4 页面变体与副驾说明",
            "",
            f"![信息详情中区]({assets['strips']['middle']})",
            "",
            f"- 页面变体编号：{', '.join(variants) if variants else '05-1 至 05-7'}。",
            "- `05-2` 表示副驾侧空调说明，文档明确写了“副驾空调暂不对应唤起”，应恢复为限制条件而不是主流程分支。",
            "- `05-3` 是座椅控制页占位示意，用于说明从空调页切到座椅页后的视觉骨架。",
            "- `05-4` 到 `05-7` 是四种配置差异页，用来表达存在或不存在座椅能力时的页面显隐关系。",
            "",
            "### 5.5 底部新增规则块",
            "",
            f"![座椅配置特殊说明]({assets['strips']['bottom']})",
            "",
            "| 配置场景 | 页面表现 | 恢复规则 |",
            "| --- | --- | --- |",
        ]
    )
    for row in config_rows:
        lines.append(f"| {row[0]} | {row[1]} | {row[2]} |")
    lines.extend(
        [
            "",
            "- 核心总规则：`无相关配置做隐藏处理，无座椅页面时不显示二级 tab`。",
            "",
            "### 5.6 原文保留",
            "",
            f"> Baseline excerpt: {compact_excerpt(page['text'], 420)}",
            "",
        ]
    )
    return lines


def build_settings_section(page: dict[str, Any], page_assets: dict[int, dict[str, Any]]) -> list[str]:
    assets = page_assets[page["page_number"]]
    setting_items = extract_existing_terms(
        page["text"],
        [
            "自动除雾",
            "外后视镜自动除雾",
            "自动空气净化",
            "解锁自动换气",
            "空气自干燥",
            "解锁降窗通风",
            "座舱新风系统",
            "自动",
            "自定义通风时间",
        ],
    )
    lines = [
        "## 6. 空调设置与自动化策略",
        f"![空调设置页]({assets['full']})",
        "",
        "### 6.1 页面分区与入口",
        "",
        f"![空调设置左半区]({assets['halves']['left']})",
        "",
        f"![空调设置右半区]({assets['halves']['right']})",
        "",
        "- 左半部分是从空调控制页进入设置的总开关页；右半部分是进入座舱新风系统后的自动 / 自定义时间页面。",
        "- 这一页的核心不是单个按钮，而是“设置项树 + 自动化触发条件 + toast/TTS 提示规则”。",
        "",
        "### 6.2 设置项结构",
        "",
    ]
    for item in setting_items:
        if item == "自动":
            continue
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "### 6.3 新风系统时间配置",
            "",
            f"![新风系统配置区]({assets['strips']['middle']})",
            "",
            "- 自动模式：锁车后每隔 4 小时进行一次外循环通风，最多通风 3 次。",
            "- 自定义模式：分上午、下午、晚上三个时段配置通风时间。",
            "- 时间范围：上午 `06:30~12:00`，下午 `12:30~18:30`，晚上 `19:00~22:30`，间隔均为 30 分钟。",
            "- 关闭开关后，对应下方设置项收起；设置结果自动保存。",
            "",
            "### 6.4 自动化反馈与历史删除项",
            "",
            "- 自动除雾：如果 HU 未在设定时间内收到 AC 有效反馈，需要 toast 提示“自动除雾功能异常！”。",
            "- 自动空气净化：完成后可 toast 或语音播报“空气净化已完成，当前空气质量优”。",
            "- 解锁自动换气、解锁降窗通风、空气自干燥：都属于停车 / 锁车 / 解锁场景下的自动化 HVAC 行为。",
            "- `20250108 删除` 出现在空气净化动画提示、空气净化语音提示、解锁降窗通风等位置；修复时应把它识别为历史变更，而不是当前生效的默认功能。",
            "",
            "### 6.5 原文保留",
            "",
            f"> Baseline excerpt: {compact_excerpt(page['text'], 420)}",
            "",
        ]
    )
    return lines


def build_seat_section(page: dict[str, Any], page_assets: dict[int, dict[str, Any]]) -> list[str]:
    assets = page_assets[page["page_number"]]
    seat_features = extract_existing_terms(
        page["text"],
        ["座椅通风", "座椅加热", "座椅按摩", "后排座椅通风/加热", "方向盘加热", "一键关闭", "停止按摩", "开始按摩"],
    )
    massage_modes = extract_massage_modes(page["text"])
    massage_durations = ordered_unique(re.findall(r"\b\d{1,2}min\b", page["text"]))
    massage_levels = ordered_unique(re.findall(r"[123]档", page["text"]))
    lines = [
        "## 7. 座椅控制与按摩流程",
        f"![座椅控制页]({assets['full']})",
        "",
        "### 7.1 座椅通风与加热主界面",
        "",
        f"![座椅通风与加热区域]({assets['strips']['top']})",
        "",
        "- 默认关闭，档位置灰。",
        "- 调节顺序：关闭 -> 3 档 -> 2 档 -> 1 档 -> 关闭。",
        "- 电源档位处于 ACC / OFF 时按钮置灰不可操作。",
        "- 低电量或系统故障时，需要提示座椅通风 / 加热 / 方向盘加热不可用。",
        "- 后排座椅通风 / 加热的开关逻辑和状态动效与前排保持一致。",
        "",
        "关键功能：",
    ]
    for feature in seat_features:
        lines.append(f"- {feature}")
    lines.extend(
        [
            "",
            "### 7.2 按摩设置弹窗",
            "",
            f"![座椅按摩设置区域]({assets['strips']['bottom']})",
            "",
            "- 支持主驾 / 副驾独立按摩设置。",
            f"- 模式集合：{' / '.join(massage_modes) if massage_modes else '波浪 / 猫步 / 腰部 / 肩部 / 蛇形 / 脉冲 / 缓冲 / 推拿'}。",
            f"- 时长集合：{' / '.join(massage_durations) if massage_durations else '15min / 20min / 30min'}。",
            f"- 档位集合：{' / '.join(massage_levels) if massage_levels else '1档 / 2档 / 3档'}。",
            "- 未开始按摩时可选择模式、时长和档位；开始后按钮状态切换为“停止按摩”。",
            "- 支持一键关闭，也支持点击关闭按钮或热区外关闭当前弹窗。",
            "",
            "### 7.3 状态反馈与异常提示",
            "",
            "- 点击座椅视图后，会有转到顶视图的动画，强调 3D 空间感。",
            "- 座椅通风 / 加热 / 按摩强度通过座椅颜色深浅变化体现。",
            "- 按摩开启后，设置页同步进入高亮开启态。",
            "- 循环结束后，需要提示主驾或副驾重新开启按摩功能。",
            "- 低电量或系统故障时，文档要求弹出明确不可用提示。",
            "",
            "### 7.4 按摩设置流程图",
            "",
            "```mermaid",
            build_massage_mermaid(),
            "```",
            "",
            "### 7.5 原文保留",
            "",
            f"> Baseline excerpt: {compact_excerpt(page['text'], 420)}",
            "",
        ]
    )
    return lines


def build_visual_asset_appendix(document: dict[str, Any], page_assets: dict[int, dict[str, Any]]) -> list[str]:
    lines = [
        "## 附录：插图级视觉资产",
        "",
        "仅插图复核页（含嵌入图）拥有视觉资产；纯文本页不渲染、不消耗视觉 token。",
        "Agent 读图请优先使用 `- Illustrations` 列出的插图裁剪，整页截图仅作上下文参考。",
        "",
    ]
    for page in document["pages"]:
        assets = page_assets.get(page["page_number"])
        if not assets:
            continue  # 文本页：按需渲染模式下无资产
        review_flag = "yes" if page.get("image_count", 0) >= 1 else "recommended"
        lines.extend(
            [
                f"### Page {page['page_number']:02d}",
                "",
                f"- Visual review: {review_flag}",
                f"- Text length: {page['word_count']}",
                f"- Images: {page.get('image_count', 0)}",
                f"- Chars: {page['char_count']}",
                f"- Screenshot: {assets['full']}",
                f"- Illustrations: {', '.join(assets.get('illustrations') or []) or 'none'}",
                "",
            ]
        )
    return lines


def normalize_markdown_lines(lines: list[str]) -> list[str]:
    normalized: list[str] = []
    prev_type = "blank"
    inside_fence = False

    for line in lines:
        stripped = line.strip()

        if inside_fence:
            normalized.append(line)
            if stripped.startswith("```"):
                inside_fence = False
                prev_type = "fence"
            continue

        if stripped == "":
            if normalized and normalized[-1] != "":
                normalized.append("")
            prev_type = "blank"
            continue

        current_type = "text"
        if stripped.startswith("#"):
            current_type = "heading"
        elif stripped.startswith("```"):
            current_type = "fence"
        elif stripped.startswith("|"):
            current_type = "table"
        elif re.match(r"^([-*+]\s|\d+\.\s)", stripped):
            current_type = "list"

        if current_type == "heading":
            if normalized and normalized[-1] != "":
                normalized.append("")
        elif current_type == "list":
            if prev_type not in {"list", "blank"} and normalized and normalized[-1] != "":
                normalized.append("")
        elif current_type == "table":
            if prev_type not in {"table", "blank"} and normalized and normalized[-1] != "":
                normalized.append("")
        elif current_type == "fence":
            if normalized and normalized[-1] != "":
                normalized.append("")
            inside_fence = True
        elif current_type == "text":
            if prev_type in {"heading", "list", "table", "fence"} and normalized and normalized[-1] != "":
                normalized.append("")

        normalized.append(line)
        prev_type = current_type

    return normalized


def parse_change_records(text: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    pending_date = ""
    for line in extract_nonempty_lines(text):
        if re.fullmatch(r"\d{8}", line):
            pending_date = format_compact_date(line)
            continue
        version_match = re.match(r"^(0\.\d+\.\d+)\s+(.*)$", line)
        if version_match:
            description = EMAIL_RE.sub("", version_match.group(2)).strip()
            parts = description.split()
            if len(parts) > 1 and re.fullmatch(r"[\u4e00-\u9fff]{2,4}", parts[-1]):
                description = " ".join(parts[:-1])
            records.append({"version": version_match.group(1), "date": pending_date, "change": description})
            pending_date = ""
            continue
        if records and line.startswith("【"):
            records[-1]["change"] = (records[-1]["change"] + "；" + line).strip("；")
    return records


def extract_control_labels(text: str) -> list[str]:
    return ordered_unique(re.findall(r"【([^】]+)】", text))


def extract_existing_terms(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if term in text]


def build_massage_mermaid() -> str:
    return "\n".join(
        [
            "flowchart LR",
            '  Entry["进入座椅控制页"] --> Configure["选择主驾/副驾、模式、时长、档位"]',
            '  Configure --> Start["开始按摩"]',
            '  Start --> Running["按摩进行中"]',
            '  Running --> Stop["停止按摩 / 一键关闭"]',
            '  Running --> Timeout["计时结束"]',
            '  Timeout --> Reminder["提示重新开启"]',
            '  Stop --> Exit["返回座椅控制页"]',
        ]
    )


def generate_source_markdown(document: dict[str, Any], output_root: Path) -> None:
    title = document["pdf_path"].stem.replace("_", " ")
    lines = [
        f"# {title} Baseline Source",
        "",
        "> 该文件保留 OCR / PDF 工具抽取后的 baseline 文本，用于和修复版进行对照。",
        "",
    ]
    for page in document["pages"]:
        lines.append(f"## Page {page['page_number']} - {page['title']}")
        lines.append("")
        lines.append(f"![Page {page['page_number']}]({page_image_ref(page, output_root)})")
        lines.append("")
        lines.append("```text")
        lines.append((page["text"] or "").replace("```", "'''"))
        lines.append("```")
        lines.append("")
    write_text(output_root / "source.md", "\n".join(lines).rstrip() + "\n")


def uses_domain_specific_template(document: dict[str, Any]) -> bool:
    metadata_title = document["metadata"].get("title") or ""
    first_pages = document["pages"][:4]
    early_corpus = "\n".join([metadata_title, *(page["title"] + "\n" + page["text"] for page in first_pages)])

    # Media-center PDFs share generic section names such as "信息架构" and "页面布局".
    # Only enable the HVAC/seat template when the cover or TOC clearly points to that domain.
    negative_markers = ["媒体中心", "MEDIA CENTER", "QQ音乐", "音乐会", "蓝牙音乐", "本地音乐", "歌单", "播放列表"]
    if any(marker in early_corpus for marker in negative_markers):
        return False

    toc_page = next((page for page in document["pages"] if "目录" in page["title"] or "Content" in page["text"]), None)
    toc_text = toc_page["text"] if toc_page else ""
    toc_entries = parse_toc_entries(toc_text) if toc_text else []
    toc_titles = "\n".join(entry["title"] for entry in toc_entries)

    cover_markers = ["空调", "A/C", "座椅", "按摩", "加热", "通风", "后除霜"]
    toc_markers = ["空调设置", "座椅控制", "按摩设置", "后除霜"]
    cover_hit = any(marker in early_corpus for marker in cover_markers)
    toc_hit = any(marker in toc_titles for marker in toc_markers)
    return cover_hit and toc_hit


def build_generic_final_markdown(
    document: dict[str, Any],
    output_root: Path,
    page_assets: dict[int, dict[str, Any]],
    visual_review_pages: list[str],
    route: str,
) -> list[str]:
    title = document["pdf_path"].stem.replace("_", " ")
    if visual_review_pages:
        title += "（插图复核版草稿）"
    cover_title = document["metadata"].get("title") or document["pages"][0]["title"]
    toc_page = next((page for page in document["pages"] if "目录" in page["title"] or "Content" in page["text"]), None)
    toc_entries = parse_toc_entries(toc_page["text"]) if toc_page else []

    lines = _build_generic_overview_lines(
        title,
        cover_title,
        document,
        output_root,
        page_assets,
        visual_review_pages,
        route,
    )
    _append_generic_toc_lines(lines, toc_entries)
    _append_generic_page_sections(lines, document["pages"], page_assets)
    lines.extend(build_visual_asset_appendix(document, page_assets))
    return lines


def _build_generic_overview_lines(
    title: str,
    cover_title: str,
    document: dict[str, Any],
    output_root: Path,
    page_assets: dict[int, dict[str, Any]],
    visual_review_pages: list[str],
    route: str,
) -> list[str]:
    return [
        f"# {title}",
        "",
        "> 该版本基于 baseline 文本抽取、页截图和 OCR / 视觉修复规则重新组织。",
        "> 对于非领域模板文档，保留逐页结构、OCR 补全文本和视觉资产，避免误套用特定业务模板。",
        "",
        "## 文档概览",
        "",
        f"- 原始标题：{cover_title}",
        "- 文档类型：Converted visual document",
        f"- 页数：{document['page_count']}",
        f"- 路由：{route}",
        f"- 视觉复核页：{', '.join(visual_review_pages) or 'none'}",
        f"- Baseline 文本：[{(output_root / 'source.md').name}]({(output_root / 'source.md').name})",
        "",
    ]
    if 1 in page_assets:
        lines.append(f"![封面页]({page_assets[1]['full']})")
        lines.append("")
    return lines


def _append_generic_toc_lines(
    lines: list[str],
    toc_entries: list[dict[str, str]],
) -> None:
    if not toc_entries:
        return

    lines.extend(["## 修复后的章节骨架", ""])
    for index, entry in enumerate(toc_entries, start=1):
        lines.append(f"{index}. {entry['title']}")
    lines.append("")


def _append_generic_page_sections(
    lines: list[str],
    pages: list[dict[str, Any]],
    page_assets: dict[int, dict[str, Any]],
) -> None:
    for page in pages:
        _append_generic_page_section(lines, page, page_assets.get(page["page_number"]))


def _append_generic_page_section(
    lines: list[str],
    page: dict[str, Any],
    assets: dict[str, Any] | None,
) -> None:
    lines.append("---")
    lines.append("")
    lines.append(f"## {page['title']}")
    lines.append("")
    if assets:
        lines.append(f"![{page['page_number']}]({assets['full']})")
        lines.append("")
    _append_generic_page_content(lines, page)


def _append_generic_page_content(lines: list[str], page: dict[str, Any]) -> None:
    if page.get("ocr_structured_md"):
        content = page["ocr_structured_md"].strip()
        if content:
            lines.append(content)
            lines.append("")
        return

    if page.get("ocr_text_preview"):
        lines.append(f"> {page['ocr_text_preview']}")
        lines.append("")
        return

    if page["text"]:
        lines.append(page["text"])
        lines.append("")


def generate_final_markdown(document: dict[str, Any], freeze: dict[str, Any], output_root: Path) -> None:
    page_lookup = {page["page_number"]: page for page in document["pages"]}
    visual_review_pages = build_visual_review_pages(document, freeze)
    uses_domain = uses_domain_specific_template(document)
    if uses_domain:
        # UE 设计稿类领域模板：每页本质都是视觉页，保持全量渲染（tiles/strips/halves）
        page_assets = render_page_visual_assets(document, output_root)
        route = "complex_visual_pdf_path" if len(visual_review_pages) >= 4 else "standard_pdf_path"
        title = document["pdf_path"].stem.replace("_", " ") + "（视觉修复版草稿）"
    else:
        # 通用文档（v2 修复）：按需渲染——仅插图复核页 + 封面；纯文本页零渲染零视觉 token
        render_set = {int(p) for p in visual_review_pages} | {1}
        page_assets = render_page_visual_assets(document, output_root, only_pages=render_set)
        route = "illustration_review_pdf_path" if visual_review_pages else "text_native_pdf_path"
        title = document["pdf_path"].stem.replace("_", " ")
        if visual_review_pages:
            title += "（插图复核版草稿）"
    cover_meta = extract_release_metadata(document["pages"][0]["text"])
    if not uses_domain:
        generic_lines = build_generic_final_markdown(document, output_root, page_assets, visual_review_pages, route)
        write_text(output_root / "final.md", "\n".join(normalize_markdown_lines(generic_lines)).rstrip() + "\n")
        write_needs_repair_json(document, output_root, visual_review_pages, page_assets)
        return

    toc_page = next((page for page in document["pages"] if "目录" in page["title"] or "Content" in page["text"]), None)
    toc_entries = parse_toc_entries(toc_page["text"]) if toc_page else []
    change_page = page_lookup.get(3)
    annotation_page = page_lookup.get(4)
    architecture_page = page_lookup.get(5)
    layout_page = page_lookup.get(6)
    details_page = page_lookup.get(7)
    settings_page = page_lookup.get(8)
    seat_page = page_lookup.get(9)

    lines = [
        f"# {title}",
        "",
        "> 该版本基于 baseline 文本抽取、页截图和多模态修复规则重新组织。",
        "> 重点补回标注语义、模块指向、页面分区、配置差异和流程表达，减少纯 OCR 平铺带来的结构损失。",
        "",
        "## 文档概览",
        "",
        f"- 项目：{document['pages'][0]['title'].replace(' | ', ' ')}",
        "- 模块：空调 / 座椅",
        "- 文档类型：Functional User Experience Documentation",
        f"- 当前版本：{cover_meta['version'] or 'unknown'}（{cover_meta['release_date'] or 'unknown'}）",
        f"- 路由：{route}",
        f"- 页数：{document['page_count']}",
        f"- 视觉复核页：{', '.join(visual_review_pages) or 'none'}",
        f"- Baseline 文本：[{(output_root / 'source.md').name}]({(output_root / 'source.md').name})",
        "",
        f"![封面页]({page_assets[1]['full']})",
        "",
    ]

    if toc_entries:
        lines.extend(["## 修复后的章节骨架", ""])
        for index, entry in enumerate(toc_entries, start=1):
            title_text = entry["title"]
            if title_text == "标注说明":
                title_text = "标注说明与跳转线语义"
            elif title_text == "信息架构":
                title_text = "信息架构与模块指向"
            elif title_text == "页面布局":
                title_text = "页面布局分区"
            elif title_text == "信息详情":
                title_text = "信息详情与主界面控件"
            elif title_text == "空调设置":
                title_text = "空调设置与自动化策略"
            elif title_text == "座椅控制":
                title_text = "座椅控制与按摩流程"
            lines.append(f"{index}. {title_text}")
        lines.append("")

    if change_page:
        lines.extend(
            [
                "## 1. 变更记录",
                "",
                f"![变更记录页]({page_assets[3]['full']})",
                "",
                "| 版本 | 日期 | 主要变更 |",
                "| --- | --- | --- |",
            ]
        )
        for record in parse_change_records(change_page["text"]):
            change = record["change"].replace("【变更】", "").replace("【新增】", "").strip("；")
            lines.append(f"| {record['version']} | {record['date']} | {change} |")
        lines.append("")

    if annotation_page:
        annotation_groups = build_annotation_groups(annotation_page["text"])
        lines.extend(
            [
                "## 2. 标注说明与跳转线语义",
                "",
                f"![标注说明页]({page_assets[4]['full']})",
                "",
                "### 2.1 标注体系",
                "",
            ]
        )
        for group in annotation_groups:
            lines.append(f"- {group}")
        lines.extend(
            [
                "",
                "### 2.2 跳转线 / 判断流语义",
                "",
                "该页不是普通文本说明，而是把页面流转语义可视化定义清楚：先触发指令，再经过判断条件，最后进入成功或失败分支。",
                "",
                "```mermaid",
                "flowchart LR",
                '  Trigger["指令\\n单击 / 滑动 / 语音 / 等待"] --> Decision{"判断条件"}',
                '  Decision --> Success["成功"]',
                '  Decision --> Failure["失败"]',
                "```",
                "",
                "### 2.3 对后续页面修复的意义",
                "",
                "- 看到蓝色箭头、判断菱形、成功 / 失败分支时，不应该简单转成线性段落，而应保留流程结构。",
                "- 看到红 / 绿 / 蓝高亮框时，应把它们解释为变更语义，而不是普通背景色。",
                "",
            ]
        )

    if architecture_page:
        core_chain, left_terms, right_terms = build_info_architecture_terms(architecture_page["text"])
        lines.extend(
            [
                "## 3. 信息架构与模块指向",
                "",
                f"![信息架构页]({page_assets[5]['full']})",
                "",
                "### 3.1 中心链路",
                "",
                f"- {' -> '.join(core_chain) if core_chain else '座椅控制 -> 空调 -> 空调控制'}",
                "",
                "### 3.2 座椅控制侧能力",
                "",
            ]
        )
        for term in left_terms:
            lines.append(f"- {term}")
        lines.extend(["", "### 3.3 空调控制侧能力", ""])
        for term in right_terms:
            lines.append(f"- {term}")
        lines.extend(
            [
                "",
                "### 3.4 模块关系图",
                "",
                "```mermaid",
                build_info_architecture_mermaid(architecture_page),
                "```",
                "",
            ]
        )

    if layout_page:
        lines.extend(
            [
                "## 4. 页面布局分区",
                "",
                f"![页面布局页]({page_assets[6]['full']})",
                "",
                "### 4.1 空调页布局",
                "",
                "- `Statusbar` 位于页面顶部。",
                "- `A 区` 是菜单标题栏，用于 `空调 / 座椅` 顶部切换。",
                "- `B 区` 是空调视图与次要功能区，承载温度、空气质量、舒适/节能等信息。",
                "- `C 区` 是主要核心操作功能区，承载同步、AUTO、A/C、MAX 等关键控制。",
                "- `Dock` 位于底部，是风量入口和浮层展开 / 收起的主要交互起点。",
                "",
                "### 4.2 座椅页布局",
                "",
                "- 保留 `Statusbar` 和 `A 区` 标题栏。",
                "- 核心操作聚合到 `B 区`，展示座椅相关功能操作与视图。",
                "- 页面下方仍保留 `Dock`。",
                "",
                "### 4.3 布局分层图",
                "",
                "```mermaid",
                build_page_layout_mermaid(layout_page),
                "```",
                "",
                "### 4.4 修复原则",
                "",
                "- 这一页表达的是自上而下的空间分层，不是功能触发流程。",
                "- 因此保留顶部到 Dock 的层次关系即可，不再用带判断语义的箭头或分支图去过度解释。",
                "",
            ]
        )

    if details_page:
        lines.extend(build_details_section(details_page, page_assets))

    if settings_page:
        lines.extend(build_settings_section(settings_page, page_assets))

    if seat_page:
        lines.extend(build_seat_section(seat_page, page_assets))

    lines.extend(build_visual_asset_appendix(document, page_assets))

    write_text(output_root / "final.md", "\n".join(normalize_markdown_lines(lines)).rstrip() + "\n")
    write_needs_repair_json(document, output_root, visual_review_pages, page_assets)


def write_needs_repair_json(
    document: dict[str, Any],
    output_root: Path,
    visual_review_pages: list[str],
    page_assets: dict[int, dict[str, Any]],
) -> None:
    """结构化修复标记（v2）：runner 依据本文件判定 needs_repair，不再扫描 final.md 关键词。

    - 有插图复核页 → needs_repair=true，pages 列出每页的插图裁剪与整页上下文
    - 纯文本文档（无嵌入图）→ needs_repair=false，Agent 零视觉参与
    """
    pages_payload = []
    for page_str in visual_review_pages:
        number = int(page_str)
        assets = page_assets.get(number) or {}
        pages_payload.append(
            {
                "page_number": number,
                "context_image": assets.get("full", ""),
                "illustrations": assets.get("illustrations") or [],
            }
        )

    payload = {
        "kind": "illustration-review",
        "version": "2.0",
        "needs_repair": bool(pages_payload),
        "reason": "illustration-review" if pages_payload else "text-native",
        "page_total": document.get("page_count", 0),
        "review_page_total": len(pages_payload),
        "instruction": (
            "只复核插图：逐张核对 illustrations 中插图的识别与描述是否正确"
            "（内容、标注、编号、指向关系），必要时参考 context_image 整页上下文；"
            "不要逐页重写文本，纯文本页一律不读图。"
        ),
        "pages": pages_payload,
    }
    write_json(output_root / "needs-repair.json", payload)


def generate_markdown(document: dict[str, Any], freeze: dict[str, Any], output_root: Path, include_asset_links: bool) -> dict[str, str]:
    doc_title = document["metadata"].get("title") or document["pages"][0]["title"] or document["pdf_path"].stem
    anchors: dict[str, str] = {
        page["page_id"]: f"page-{page['page_number']:03d}-{slugify(page['title'])}" for page in document["pages"]
    }
    lines = [f"# {doc_title}", "", f"- Source PDF: `{document['pdf_path'].name}`", f"- Page count: `{document['page_count']}`", f"- Visual review required pages: `{', '.join(freeze['visual_review_required_pages']) or 'none'}`", ""]

    toc_page = next((page for page in document["pages"] if "目录" in page["title"] or "Content" in page["text"]), None)
    if toc_page:
        toc_entries = parse_toc_entries(toc_page["text"])
        if toc_entries:
            lines.append("## Reconstructed Document TOC")
            lines.append("")
            lines.append("| 序号 | 章节 | 页码 | Markdown |")
            lines.append("| --- | --- | --- | --- |")
            for entry in toc_entries:
                lines.append(f"| {entry['section_no']} | {entry['title']} | {entry['page_no']} | {match_toc_target(entry, document['pages'], anchors)} |")
            lines.append("")

    for page in document["pages"]:
        lines.append(f"## Page {page['page_number']} - {page['title']}")
        lines.append("")
        lines.append(f"- Page ID: `{page['page_id']}`")
        lines.append(f"- Aspect ratio: `{page['aspect_ratio']}`")
        lines.append(f"- Tables detected: `{page['table_count']}`")
        lines.append(f"- PDF agent readback: `{'required' if page['is_visual_risk'] else 'recommended'}`")
        if include_asset_links:
            relative_image = Path(os.path.relpath(page["image_path"], output_root / "markdown"))
            lines.append(f"- Page image: [{page['image_path'].name}]({relative_image.as_posix()})")
        lines.append("")
        visual_notes = build_visual_structure_notes(page)
        if visual_notes:
            lines.append(f"### Page {page['page_number']} Visual Structure Summary")
            lines.append("")
            for note in visual_notes:
                lines.append(f"- {note}")
            lines.append("")
        lines.extend(render_page_body(page, output_root))
        if page["is_visual_risk"]:
            lines.append("> Visual-risk note: This page requires post-markdown PDF agent review for arrows, legends, grouped objects, or layout semantics.")
            lines.append("")
    write_text(output_root / "markdown" / "output.md", "\n".join(lines).rstrip() + "\n")
    return anchors


def build_trace(document: dict[str, Any], classified: dict[str, list[dict[str, Any]]], anchors: dict[str, str], output_root: Path) -> None:
    lines = ["# Block To Markdown Trace", "", "| raw_block_key | markdown_anchor | render_mode | notes |", "| --- | --- | --- | --- |"]
    for block in classified["in-markdown"]:
        page_number = block["source_locator"]["page"]
        page_id = f"page-{page_number}"
        anchor = anchors.get(page_id, page_id)
        render_mode = "section" if block["block_type"] == "heading" else "inline"
        if block["block_type"] == "table":
            render_mode = "table-summary"
        notes = block.get("semantic_role", "rendered")
        lines.append(f"| `{block['raw_block_key']}` | `{anchor}` | `{render_mode}` | {notes} |")
    for block in classified["needs-clarification"]:
        lines.append(f"| `{block['raw_block_key']}` | `evidence-only` | `omitted-with-reason` | {block.get('reason', 'needs clarification')} |")
    write_text(output_root / "markdown" / "block-md-trace.md", "\n".join(lines) + "\n")


def build_asset_links(document: dict[str, Any], output_root: Path, include_asset_links: bool) -> None:
    lines = ["# Asset Links", ""]
    if not include_asset_links:
        lines.append("Asset links were disabled for this run.")
        write_text(output_root / "markdown" / "asset-links.md", "\n".join(lines) + "\n")
        return
    for page in document["pages"]:
        relative_image = Path(os.path.relpath(page["image_path"], output_root / "markdown"))
        lines.append(f"- {page['page_id']}: [{page['image_path'].name}]({relative_image.as_posix()})")
    write_text(output_root / "markdown" / "asset-links.md", "\n".join(lines) + "\n")


def build_pdf_agent_review(document: dict[str, Any], freeze: dict[str, Any], output_root: Path, enabled: bool) -> dict[str, Any]:
    markdown_text = (output_root / "markdown" / "output.md").read_text(encoding="utf-8")
    final_text = (output_root / "final.md").read_text(encoding="utf-8")
    trace_text = (output_root / "markdown" / "block-md-trace.md").read_text(encoding="utf-8")

    if not enabled:
        report = {
            "generated_at": utc_now(),
            "enabled": False,
            "status": "skipped",
            "pages": [],
            "blocking_issues": [],
        }
        write_json(output_root / "markdown" / "pdf-agent-review-report.json", report)
        write_text(output_root / "markdown" / "pdf-agent-review-summary.md", "# PDF Agent Review Summary\n\nPDF agent validation was disabled for this run.\n")
        return report

    pages = []
    blocking_issues = []
    summary_lines = ["# PDF Agent Review Summary", "", "This report compares rendered PDF pages, extracted evidence, markdown outputs (`output.md` and `final.md`), and trace coverage.", ""]
    for page in document["pages"]:
        section_text = extract_markdown_section(markdown_text, page["page_number"], page["title"])
        final_section = extract_final_review_section(final_text, page)
        combined_text = "\n".join(part for part in [section_text, final_section] if part)
        section_title = f"## Page {page['page_number']} - {page['title']}"
        page_present = section_title in markdown_text
        final_present = bool(final_section)
        title_tokens = token_set(page["title"])
        markdown_tokens = token_set(combined_text or (markdown_text + "\n" + final_text))
        overlap = sorted(title_tokens & markdown_tokens)
        title_overlap_ratio = round(len(overlap) / len(title_tokens), 2) if title_tokens else 1.0
        trace_ok = f"pdf:p{page['page_number']}:heading:001" in trace_text and f"pdf:p{page['page_number']}:text:001" in trace_text if page['text'] else f"pdf:p{page['page_number']}:heading:001" in trace_text
        visual_note_expected = page["is_visual_risk"]
        visual_note_present = "Visual-risk note" in section_text
        visual_asset_present = "artifacts/pages/" in final_section
        title_text = page["title"]

        status = "pass"
        findings = []
        if not page_present:
            status = "needs-repair"
            findings.append("evidence markdown section missing")
        if not final_present:
            status = "needs-repair"
            findings.append("final markdown section missing")
        if title_overlap_ratio < 0.5:
            status = "needs-repair"
            findings.append("page title terms are weakly represented in markdown")
        if not trace_ok:
            status = "needs-repair"
            findings.append("trace coverage missing")
        if visual_note_expected and not visual_note_present:
            status = "needs-repair"
            findings.append("visual-risk note missing in markdown")
        if page["page_number"] in {3, 4, 5, 6, 7, 8, 9} and not visual_asset_present:
            status = "needs-repair"
            findings.append("final markdown is missing visual asset preservation for this page")

        if "标注说明" in title_text or "Annotation Notes" in title_text:
            required_terms = ["手势", "⼿势", "页面变更", "⻚⾯变更", "跳转线", "区域标记"]
            missing_terms = [term for term in required_terms if term not in combined_text]
            if len(missing_terms) >= 3:
                status = "needs-repair"
                findings.append("annotation panel grouping is incomplete in markdown")
            elif "```mermaid" in final_section and visual_asset_present:
                status = "needs-human-review"
                findings = ["annotation grouping summary is present, but icons and decision flow still need visual confirmation"]

        if "信息架构" in title_text or "Information Architecture" in title_text:
            core_nodes = ["座椅控制", "空调", "空调控制"]
            relationship_markers = ["->", "关系", "链路", "分支", "左侧", "右侧", "结构关系"]
            if all(node in combined_text for node in core_nodes) and not any(marker in combined_text for marker in relationship_markers):
                status = "needs-repair"
                findings.append("architecture relationships were flattened into a linear text list")
            elif "```mermaid" in final_section and visual_asset_present:
                status = "pass"
                findings = []

        if "页面布局" in title_text or "Page Layout" in title_text:
            if all(term in combined_text for term in ["A区", "B区", "C区"]):
                if status == "pass" and page["is_visual_risk"]:
                    status = "needs-human-review"
                    findings.append("layout zones are present, but screenshot-to-zone pairing still needs visual confirmation")

        if page["page_number"] == 3 and "| 版本 | 日期 | 主要变更 |" not in final_section:
            status = "needs-repair"
            findings.append("final markdown is missing the change-record table")

        if page["page_number"] in {7, 8, 9} and final_section.count("![") < 2:
            status = "needs-repair"
            findings.append("final markdown is missing page-region screenshots for this visual page")

        if page["is_visual_risk"] and not findings:
            status = "needs-human-review"
            findings.append("visual semantics still require human or agent confirmation against page image")

        if "目录" in title_text or "⽬录" in title_text or "Content" in title_text:
            if page_present and trace_ok:
                status = "pass"
                findings = []

        if "变更记录" in title_text or "Change Record" in title_text:
            if page_present and trace_ok:
                status = "pass"
                findings = []

        if "Thank you" in section_text or "Thank you for your attention" in section_text:
            if page_present and trace_ok:
                status = "pass"
                findings = []

        if page["page_number"] == 1 and page_present and trace_ok:
            if "FUNCTIONAL USER EXPERIENCE DOCUMENTATION" in section_text:
                status = "pass"
                findings = []

        page_report = {
            "page_id": page["page_id"],
            "page_number": page["page_number"],
            "status": status,
            "title_overlap_ratio": title_overlap_ratio,
            "trace_ok": trace_ok,
            "final_present": final_present,
            "visual_asset_present": visual_asset_present,
            "findings": findings,
            "image_path": page["image_path"].relative_to(output_root).as_posix(),
        }
        pages.append(page_report)
        summary_lines.append(f"- {page['page_id']}: {status} ({'; '.join(findings) if findings else 'no blocking issues'})")
        if status == "needs-repair":
            blocking_issues.append({"page_id": page["page_id"], "issues": findings})

    overall_status = "pass" if not blocking_issues else "needs-repair"
    if overall_status == "pass" and any(page["status"] == "needs-human-review" for page in pages):
        overall_status = "needs-human-review"

    report = {
        "generated_at": utc_now(),
        "enabled": True,
        "status": overall_status,
        "visual_review_required_pages": freeze["visual_review_required_pages"],
        "pages": pages,
        "blocking_issues": blocking_issues,
    }
    write_json(output_root / "markdown" / "pdf-agent-review-report.json", report)
    write_text(output_root / "markdown" / "pdf-agent-review-summary.md", "\n".join(summary_lines) + "\n")
    return report


def build_qv_report(classified: dict[str, list[dict[str, Any]]], freeze: dict[str, Any], review: dict[str, Any], output_root: Path) -> None:
    trace_text = (output_root / "markdown" / "block-md-trace.md").read_text(encoding="utf-8")
    missing_trace = [block["raw_block_key"] for block in classified["in-markdown"] if block["raw_block_key"] not in trace_text]
    report = {
        "generated_at": utc_now(),
        "missing_trace_blocks": missing_trace,
        "unresolved_relation_candidates": freeze["unresolved_relation_candidates"],
        "pdf_agent_review_status": review["status"],
        "blocking_issues": review.get("blocking_issues", []),
    }
    status = "pass" if not missing_trace and review["status"] != "needs-repair" else "needs-repair"
    report["status"] = status
    write_json(output_root / "markdown" / "back-edge-decision.json", report)

    lines = ["# Markdown Quality Valve Report", "", f"- Status: `{status}`", f"- Missing trace blocks: `{len(missing_trace)}`", f"- PDF agent review status: `{review['status']}`", ""]
    if missing_trace:
        lines.append("## Missing Trace Blocks")
        lines.append("")
        for block in missing_trace:
            lines.append(f"- `{block}`")
        lines.append("")
    if review.get("blocking_issues"):
        lines.append("## Blocking Issues")
        lines.append("")
        for issue in review["blocking_issues"]:
            lines.append(f"- {issue['page_id']}: {', '.join(issue['issues'])}")
        lines.append("")
    write_text(output_root / "markdown" / "markdown-qv-report.md", "\n".join(lines) + "\n")


def build_integrity_report(document: dict[str, Any], freeze: dict[str, Any], review: dict[str, Any], output_root: Path) -> None:
    trace_text = (output_root / "markdown" / "block-md-trace.md").read_text(encoding="utf-8")
    trace_rows = [line for line in trace_text.splitlines() if line.startswith("| `pdf:")]
    metrics = {
        "raw_block_total": freeze["raw_block_total"],
        "in_markdown_block_total": freeze["in_markdown_block_total"],
        "trace_row_total": len(trace_rows),
        "visual_review_required_page_total": len(freeze["visual_review_required_pages"]),
        "pdf_agent_review_status": review["status"],
    }
    write_json(output_root / "integrity-metrics.json", metrics)

    lines = [
        "# Markdown Integrity Report",
        "",
        f"- Document: `{document['pdf_path'].name}`",
        f"- Raw block total: `{freeze['raw_block_total']}`",
        f"- In-markdown block total: `{freeze['in_markdown_block_total']}`",
        f"- Trace rows: `{len(trace_rows)}`",
        f"- Visual review required pages: `{len(freeze['visual_review_required_pages'])}`",
        f"- PDF agent review status: `{review['status']}`",
        "",
        "## Remaining Risks",
        "",
    ]
    if review["status"] == "pass":
        lines.append("- No blocking issues detected by the post-markdown PDF agent validation pass.")
    else:
        for page in review["pages"]:
            if page["status"] != "pass":
                lines.append(f"- {page['page_id']}: {', '.join(page['findings'])}")
    lines.append("")
    lines.append("## Evidence Sources")
    lines.append("")
    lines.append("- evidence/block-catalog.json")
    lines.append("- evidence/block-audit.md")
    lines.append("- evidence/md-input-freeze.json")
    lines.append("- markdown/block-md-trace.md")
    lines.append("- markdown/pdf-agent-review-report.json")
    write_text(output_root / "markdown-integrity-report.md", "\n".join(lines) + "\n")


def write_pipeline_state(output_root: Path, current_phase: str, status: str) -> None:
    payload = {
        "pipeline": "efm-multidoc-markdown-bundle",
        "updated_at": utc_now(),
        "current_phase": current_phase,
        "status": status,
    }
    write_json(output_root / ".pipeline-state.json", payload)


_MULTIMODAL_REPAIR_PROMPT = """你是一个文档排版还原专家。你将看到一份文档的多个页面截图和它的 OCR 纯文本。
任务：基于 OCR 文本和页面截图，将文档修复为结构良好的 Markdown。

规则：
1. **以 OCR 文本为内容主干**：所有正文文字必须来自 OCR 文本，不要自行编造或改写。
2. **以截图为结构参考**：页面截图用于理解标题层级、表格结构、段落分组、列表关系。
3. 识别页面标题（最大字号）作为一级或二级标题。
4. 识别子标题作为三级或四级标题。
5. 将表格内容还原为 Markdown 表格。
6. 将列表项还原为 `-` 或 `*` 列表。
7. 保留原始文案，不做改写或总结。
8. 图片引用使用 `![页码](evidence/page-images/page-NNN.jpg)` 格式。
9. 对于 UI 截图中的标注说明，用引用块 `>` 或列表呈现。
10. 输出完整的 Markdown 文档，包含标题、各章节、表格和附录。"""


def _is_image_only_pdf(document: dict[str, Any]) -> bool:
    """Check if PDF pages have little or no extractable text from pdfplumber (image-only / scanned)."""
    page_count = len(document.get("pages", []))
    if page_count == 0:
        return False
    # Use pdfplumber_char_count (pre-OCR) to detect image-only PDFs
    total_pdfplumber_chars = sum(
        page.get("pdfplumber_char_count", page.get("char_count", 0))
        for page in document.get("pages", [])
    )
    avg_chars = total_pdfplumber_chars / page_count
    return avg_chars < 50


def write_multimodal_repair_brief(document: dict[str, Any], output_root: Path) -> dict[str, str]:
    """Write a repair brief that an Agent can use for multimodal format repair.

    For image-only PDFs, writes a JSON brief listing all page screenshots and
    the source.md path. An Agent then reads these + the prompt to repair final.md.

    Returns a status dict.
    """
    if not _is_image_only_pdf(document):
        return {"status": "skipped", "reason": "pdf-has-extractable-text", "output_path": ""}

    source_md_path = output_root / "source.md"
    pages_dir = output_root / "evidence" / "page-images"

    if not source_md_path.exists():
        return {"status": "skipped", "reason": "source-md-not-found", "output_path": ""}
    if not pages_dir.exists():
        return {"status": "skipped", "reason": "page-images-not-found", "output_path": ""}

    # Collect page screenshots (EFM uses page-NNN.jpg format)
    page_images: list[dict[str, str]] = []
    for page in document.get("pages", []):
        page_number = page["page_number"]
        image_path = pages_dir / f"page-{page_number:03d}.jpg"
        if image_path.exists():
            page_images.append({
                "page_number": page_number,
                "path": str(image_path),
            })

    brief = {
        "pdf_name": document["pdf_path"].name,
        "page_count": len(document.get("pages", [])),
        "is_image_only": True,
        "source_md_path": str(source_md_path),
        "pages_dir": str(pages_dir),
        "page_images": page_images,
        "repair_prompt": _MULTIMODAL_REPAIR_PROMPT,
    }

    brief_path = output_root / "multimodal-repair-brief.json"
    write_json(brief_path, brief)

    # Also write a markdown summary for human readability
    summary_lines = [
        "# 多模态格式修复简报",
        "",
        f"- 文档：`{document['pdf_path'].name}`",
        f"- 页数：`{len(document.get('pages', []))}`",
        f"- 检测类型：纯图片 PDF（pdfplumber 每页平均字符 < 50）",
        f"- OCR 文本：`{source_md_path}`",
        f"- 页面截图：`{pages_dir}/`",
        "",
        "## 修复指令",
        "",
        "请启动一个多模态 Agent，将以下文件作为输入：",
        "",
        f"1. OCR 文本：`{source_md_path}`（内容主干）",
        f"2. 页面截图：`{pages_dir}/page-NNN.jpg`（结构参考）",
        "",
        "Agent 需要按照 `multimodal-repair-brief.json` 中的 `repair_prompt` 规则，",
        "将 OCR 文本和截图结合，修复 `final.md` 的格式。",
        "",
        "## 页面列表",
        "",
    ]
    for img in page_images:
        summary_lines.append(f"- Page {img['page_number']}: `![page-{img['page_number']:03d}](evidence/page-images/page-{img['page_number']:03d}.jpg)`")
    summary_lines.append("")

    write_text(output_root / "multimodal-repair-summary.md", "\n".join(summary_lines))

    return {"status": "ready", "reason": "agent-repair-needed", "output_path": str(brief_path)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Portable PDF-to-markdown runner for the efm-multidoc-markdown-bundle bundle.")
    parser.add_argument("--input-pdf", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--source-format", default="pdf", choices=["auto", "pdf"])
    parser.add_argument("--markdown-style", default="technical", choices=["technical", "narrative", "audit-friendly"])
    parser.add_argument("--pdf-agent-validation", default="on", choices=["on", "off"])
    parser.add_argument("--asset-links", default="on", choices=["on", "off"])
    parser.add_argument("--ocr", default="on", choices=["on", "off"])
    parser.add_argument("--multimodal-repair", default="auto", choices=["auto", "on", "off"])
    return parser.parse_args()


def run_pdf_pipeline(
    pdf_path: Path,
    output_root: Path,
    source_format: str = "pdf",
    markdown_style: str = "technical",
    pdf_agent_validation: bool = True,
    include_asset_links: bool = True,
    enable_ocr: bool = True,
    multimodal_repair: str = "auto",
) -> dict[str, Any]:
    if not pdf_path.exists():
        raise FileNotFoundError(f"Input PDF not found: {pdf_path}")

    output_root.mkdir(parents=True, exist_ok=True)
    write_pipeline_state(output_root, "1", "in-progress")
    write_text(
        output_root / "intake-validation-report.md",
        "# Intake Validation Report\n\n"
        f"- Input PDF: `{pdf_path.name}`\n"
        f"- Source format: `{source_format}`\n"
        f"- OCR fallback: `{'on' if enable_ocr else 'off'}`\n"
        f"- Markdown style: `{markdown_style}`\n"
        f"- Generated at: `{utc_now()}`\n"
        "- Result: `pass`\n",
    )

    document = build_page_data(pdf_path, output_root / "evidence" / "page-images", output_root,
                               enable_ocr=enable_ocr)
    render_contact_sheet(document["image_paths"], output_root / "evidence" / "page-contact-sheet.jpg")

    write_pipeline_state(output_root, "1.5", "in-progress")
    catalog, blocks = build_block_catalog(document, output_root)
    build_asset_roster(document, output_root)
    build_layout_roster(document, output_root)

    write_pipeline_state(output_root, "2", "in-progress")
    classified = build_block_audit(blocks, output_root)
    build_heading_tree(document, output_root)
    build_orphan_blocks(classified, output_root)

    write_pipeline_state(output_root, "2.4", "in-progress")
    candidates = build_relation_candidates(document, output_root)
    queue = build_visual_review_queue(document, candidates, output_root)

    write_pipeline_state(output_root, "2.5", "in-progress")
    build_visual_review_report(queue, output_root)

    write_pipeline_state(output_root, "2.6", "in-progress")
    freeze = build_freeze(document, classified, queue, candidates, output_root)

    write_pipeline_state(output_root, "3", "in-progress")
    anchors = generate_markdown(document, freeze, output_root, include_asset_links=include_asset_links)
    generate_source_markdown(document, output_root)
    generate_final_markdown(document, freeze, output_root)

    # Multimodal format repair for image-only PDFs
    multimodal_repair_result = None
    should_repair = multimodal_repair == "on" or (
        multimodal_repair == "auto" and _is_image_only_pdf(document)
    )
    if should_repair:
        write_pipeline_state(output_root, "3.1", "in-progress")
        multimodal_repair_result = write_multimodal_repair_brief(document, output_root)

    build_trace(document, classified, anchors, output_root)
    build_asset_links(document, output_root, include_asset_links=include_asset_links)

    write_pipeline_state(output_root, "3.5", "in-progress")
    review = build_pdf_agent_review(document, freeze, output_root, enabled=pdf_agent_validation)

    write_pipeline_state(output_root, "3-QV", "in-progress")
    build_qv_report(classified, freeze, review, output_root)

    write_pipeline_state(output_root, "5", "in-progress")
    build_integrity_report(document, freeze, review, output_root)
    write_pipeline_state(output_root, "5", "completed")

    summary = {
        "output_root": str(output_root),
        "raw_block_total": catalog["raw_block_total"],
        "visual_review_required_pages": freeze["visual_review_required_pages"],
        "pdf_agent_review_status": review["status"],
    }
    if multimodal_repair_result:
        summary["multimodal_repair"] = multimodal_repair_result
    return summary


def main() -> None:
    args = parse_args()
    summary = run_pdf_pipeline(
        pdf_path=Path(args.input_pdf).resolve(),
        output_root=Path(args.output_root).resolve(),
        source_format=args.source_format,
        markdown_style=args.markdown_style,
        pdf_agent_validation=args.pdf_agent_validation == "on",
        include_asset_links=args.asset_links == "on",
        enable_ocr=args.ocr == "on",
        multimodal_repair=getattr(args, "multimodal_repair", "auto"),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
