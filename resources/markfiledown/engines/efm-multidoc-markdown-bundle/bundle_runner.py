from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import unicodedata
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from pipeline_runner import compact_excerpt, ocr_image_text, relative_path, run_pdf_pipeline, slugify, summarize_text, utc_now, write_json, write_text

try:
    import win32com.client as win32
except Exception:  # pragma: no cover
    win32 = None

try:
    from openpyxl import load_workbook
except Exception:  # pragma: no cover
    load_workbook = None


SUPPORTED_INPUT_SUFFIXES = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx"}
OOXML_SUFFIXES = {".docx", ".pptx", ".xlsx"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
# V3.3 — 扩展：让 PRE 引擎支持全面的输入格式（不仅 Office / PDF）。
STANDALONE_IMAGE_SUFFIXES = IMAGE_SUFFIXES | {".svg", ".ico"}
HTML_SUFFIXES = {".html", ".htm"}
TEXT_PASSTHROUGH_SUFFIXES = {".md", ".mdx", ".markdown", ".txt", ".rst", ".log"}
DATA_SUFFIXES = {".csv", ".tsv", ".json", ".yaml", ".yml", ".xml", ".toml", ".ini"}
CODE_SUFFIXES = {
    ".py", ".java", ".kt", ".go", ".rs", ".c", ".cpp", ".h", ".hpp", ".cs",
    ".rb", ".php", ".sh", ".bat", ".ps1", ".sql", ".js", ".ts", ".tsx",
    ".jsx", ".vue", ".svelte", ".css",
}
# 代码 / 数据文件 fenced code 语言标注。
CODE_FENCE_LANG = {
    ".py": "python", ".java": "java", ".kt": "kotlin", ".go": "go", ".rs": "rust",
    ".c": "c", ".cpp": "cpp", ".h": "c", ".hpp": "cpp", ".cs": "csharp",
    ".rb": "ruby", ".php": "php", ".sh": "bash", ".bat": "bat", ".ps1": "powershell",
    ".sql": "sql", ".js": "javascript", ".ts": "typescript", ".tsx": "tsx",
    ".jsx": "jsx", ".vue": "vue", ".svelte": "svelte", ".css": "css",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".xml": "xml",
    ".toml": "toml", ".ini": "ini", ".csv": "csv", ".tsv": "tsv",
}
SUPPORTED_INPUT_SUFFIXES |= (
    STANDALONE_IMAGE_SUFFIXES
    | HTML_SUFFIXES
    | TEXT_PASSTHROUGH_SUFFIXES
    | DATA_SUFFIXES
    | CODE_SUFFIXES
)
PACKAGE_MEDIA_ROOTS = {
    ".docx": "word/media/",
    ".pptx": "ppt/media/",
    ".xlsx": "xl/media/",
}
WORD_DOCX_FORMAT = 12
WORD_PDF_FORMAT = 17
POWERPOINT_PPTX_FORMAT = 24
POWERPOINT_PDF_FORMAT = 32
EXCEL_XLSX_FORMAT = 51
WORD_NS_URI = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WORD_NS = {"w": WORD_NS_URI}
DRAWINGML_NS_URI = "http://schemas.openxmlformats.org/drawingml/2006/main"
WP_NS_URI = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
PICTURE_NS_URI = "http://schemas.openxmlformats.org/drawingml/2006/picture"
R_NS_URI = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
DRAWINGML_NS = {"a": DRAWINGML_NS_URI, "r": R_NS_URI}


def _word_rels_map(package_path: Path) -> dict[str, str]:
    """Parse word/_rels/document.xml.rels -> {rId: target_filename}."""
    with zipfile.ZipFile(package_path) as archive:
        try:
            payload = archive.read("word/_rels/document.xml.rels")
        except KeyError:
            return {}
    root = ET.fromstring(payload)
    # The rels file uses the default namespace http://schemas.openxmlformats.org/package/2006/relationships
    rels_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    mapping: dict[str, str] = {}
    for rel in root.findall(f"{{{rels_ns}}}Relationship"):
        rid = rel.attrib.get("Id", "")
        target = rel.attrib.get("Target", "")
        if rid and target:
            mapping[rid] = target
    return mapping


def _extract_images_from_element(element: ET.Element, rels_map: dict[str, str]) -> list[dict[str, Any]]:
    """Scan an OOXML element for <w:drawing> children and return image refs.

    Returns a list of dicts with keys: rId, filename, alt_text.
    """
    results: list[dict[str, Any]] = []
    for drawing in element.findall(f".//{{{WORD_NS_URI}}}drawing"):
        # Find wp:inline or wp:anchor in the correct namespace
        shape = drawing.find(f".//{{{WP_NS_URI}}}inline")
        if shape is None:
            shape = drawing.find(f".//{{{WP_NS_URI}}}anchor")
        if shape is None:
            continue
        doc_pr = shape.find(f".//{{{WP_NS_URI}}}docPr")
        alt_text = ""
        if doc_pr is not None:
            alt_text = (doc_pr.attrib.get("descr", "") or
                        doc_pr.attrib.get("title", "") or
                        doc_pr.attrib.get("name", ""))
        # Find a:blip anywhere in the drawing (under pic:blipFill)
        for blip in drawing.findall(f".//{{{DRAWINGML_NS_URI}}}blip"):
            rid = blip.attrib.get(f"{{{R_NS_URI}}}embed", "")
            filename = rels_map.get(rid, "")
            if rid and filename:
                # Map OOXML media path to extracted location
                media_name = Path(filename).name  # e.g. "image1.png" from "media/image1.png"
                md_path = f"artifacts/embedded-media/{media_name}"
                results.append({"rId": rid, "filename": md_path, "alt_text": alt_text})
                break
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="All-in-one multi-format document bundle runner.")
    parser.add_argument("--input-path")
    parser.add_argument("--input-file", action="append", default=[])
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--source-format", default="auto", choices=["auto", "pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx"])
    parser.add_argument("--markdown-style", default="technical", choices=["technical", "narrative", "audit-friendly"])
    parser.add_argument("--pdf-agent-validation", default="on", choices=["on", "off"])
    parser.add_argument("--asset-links", default="on", choices=["on", "off"])
    parser.add_argument("--ocr", default="on", choices=["on", "off"])
    parser.add_argument("--recurse", default="on", choices=["on", "off"])
    return parser.parse_args()


def short_file_hash(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()[:8]


def unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    ordered: list[Path] = []
    for path in paths:
        key = str(path.resolve())
        if key not in seen:
            seen.add(key)
            ordered.append(path.resolve())
    return ordered


def discover_input_files(input_path: str | None, input_files: list[str], recurse: bool, source_format: str) -> list[Path]:
    candidates: list[Path] = []
    if input_path:
        root = Path(input_path).resolve()
        if root.is_file():
            candidates.append(root)
        elif root.is_dir():
            pattern = "**/*" if recurse else "*"
            candidates.extend(path for path in root.glob(pattern) if path.is_file())
        else:
            raise FileNotFoundError(f"Input path not found: {root}")
    for item in input_files:
        path = Path(item).resolve()
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Input file not found: {path}")
        candidates.append(path)

    discovered = []
    allowed_suffixes = SUPPORTED_INPUT_SUFFIXES if source_format == "auto" else {f".{source_format}"}
    for path in unique_paths(candidates):
        if path.name.startswith("~$"):
            continue
        if path.suffix.lower() in allowed_suffixes:
            discovered.append(path)
    if not discovered:
        raise FileNotFoundError("No supported input files were found for the requested source format.")
    return discovered


def ensure_win32com() -> None:
    if win32 is None:
        raise RuntimeError("pywin32 is required for Office conversion in this bundle.")


def sanitize_output_name(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).replace("\u00a0", " ").strip()
    normalized = normalized.replace(" ", "_")
    safe = []
    for char in normalized:
        if char in '<>:"/\\|?*' or ord(char) < 32:
            safe.append("_")
        elif char.isalnum() or char in {"-", "_", ".", "(", ")"} or ("\u4e00" <= char <= "\u9fff"):
            safe.append(char)
        else:
            safe.append("_")
    collapsed = re.sub(r"_+", "_", "".join(safe)).strip("_.-")
    return collapsed[:80] or "document"


def create_output_dir(output_root: Path, source_file: Path) -> Path:
    safe_name = sanitize_output_name(source_file.stem)
    return output_root / f"{safe_name}-{short_file_hash(source_file)}"


def copy_if_needed(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != destination.resolve():
        shutil.copy2(source, destination)
    return destination


def convert_word_to_docx(source_file: Path, work_dir: Path) -> Path:
    normalized_docx = work_dir / f"{source_file.stem}.docx"
    if source_file.suffix.lower() == ".docx":
        return copy_if_needed(source_file, normalized_docx)

    ensure_win32com()
    app = win32.DispatchEx("Word.Application")
    app.Visible = False
    app.DisplayAlerts = 0
    document = None
    try:
        document = app.Documents.Open(str(source_file), ReadOnly=True)
        document.SaveAs(str(normalized_docx), FileFormat=WORD_DOCX_FORMAT)
    finally:
        if document is not None:
            document.Close(False)
        app.Quit()
    return normalized_docx


def convert_word_to_pdf(source_file: Path, work_dir: Path) -> tuple[Path, Path]:
    ensure_win32com()
    app = win32.DispatchEx("Word.Application")
    app.Visible = False
    app.DisplayAlerts = 0
    document = None
    normalized_docx = work_dir / f"{source_file.stem}.docx"
    pdf_path = work_dir / f"{source_file.stem}.pdf"
    try:
        document = app.Documents.Open(str(source_file), ReadOnly=True)
        if source_file.suffix.lower() == ".docx":
            normalized_docx = copy_if_needed(source_file, normalized_docx)
        else:
            document.SaveAs(str(normalized_docx), FileFormat=WORD_DOCX_FORMAT)
        document.ExportAsFixedFormat(str(pdf_path), WORD_PDF_FORMAT)
    finally:
        if document is not None:
            document.Close(False)
        app.Quit()
    return normalized_docx, pdf_path


def convert_powerpoint_to_pdf(source_file: Path, work_dir: Path) -> tuple[Path, Path]:
    ensure_win32com()
    app = win32.DispatchEx("PowerPoint.Application")
    presentation = None
    normalized_pptx = work_dir / f"{source_file.stem}.pptx"
    pdf_path = work_dir / f"{source_file.stem}.pdf"
    try:
        presentation = app.Presentations.Open(str(source_file), WithWindow=False)
        if source_file.suffix.lower() == ".pptx":
            normalized_pptx = copy_if_needed(source_file, normalized_pptx)
        else:
            presentation.SaveAs(str(normalized_pptx), POWERPOINT_PPTX_FORMAT)
        presentation.SaveAs(str(pdf_path), POWERPOINT_PDF_FORMAT)
    finally:
        if presentation is not None:
            presentation.Close()
        app.Quit()
    return normalized_pptx, pdf_path


def convert_excel_to_xlsx(source_file: Path, work_dir: Path) -> Path:
    if source_file.suffix.lower() == ".xlsx":
        return copy_if_needed(source_file, work_dir / f"{source_file.stem}.xlsx")
    ensure_win32com()
    app = win32.DispatchEx("Excel.Application")
    app.Visible = False
    app.DisplayAlerts = False
    workbook = None
    normalized_xlsx = work_dir / f"{source_file.stem}.xlsx"
    try:
        workbook = app.Workbooks.Open(str(source_file))
        workbook.SaveAs(str(normalized_xlsx), FileFormat=EXCEL_XLSX_FORMAT)
    finally:
        if workbook is not None:
            workbook.Close(False)
        app.Quit()
    return normalized_xlsx


def extract_ooxml_media(package_path: Path, output_dir: Path) -> list[dict[str, str]]:
    suffix = package_path.suffix.lower()
    media_root = PACKAGE_MEDIA_ROOTS.get(suffix)
    if not media_root or not package_path.exists():
        return []

    items: list[dict[str, str]] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package_path) as archive:
        for member in archive.namelist():
            if not member.startswith(media_root):
                continue
            member_path = Path(member)
            if member_path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            target_path = output_dir / member_path.name
            with archive.open(member) as src, target_path.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            items.append({
                "source_member": member,
                "asset_path": str(target_path),
            })
    return items


def read_package_xml(package_path: Path, member: str) -> ET.Element:
    with zipfile.ZipFile(package_path) as archive:
        try:
            payload = archive.read(member)
        except KeyError as exc:
            raise RuntimeError(f"Missing OOXML member: {member}") from exc
    return ET.fromstring(payload)


def word_text(element: ET.Element) -> str:
    fragments: list[str] = []
    for node in element.iter():
        if node.tag == f"{{{WORD_NS_URI}}}t" and node.text:
            fragments.append(node.text)
        elif node.tag == f"{{{WORD_NS_URI}}}tab":
            fragments.append(" ")
        elif node.tag in {f"{{{WORD_NS_URI}}}br", f"{{{WORD_NS_URI}}}cr"}:
            fragments.append(" ")
    return " ".join("".join(fragments).split())


def word_paragraph_style(paragraph: ET.Element) -> str:
    style = paragraph.find("./w:pPr/w:pStyle", WORD_NS)
    if style is None:
        return ""
    return style.attrib.get(f"{{{WORD_NS_URI}}}val", "")


def extract_docx_blocks(package_path: Path) -> tuple[list[dict[str, Any]], dict[str, str]]:
    root = read_package_xml(package_path, "word/document.xml")
    rels_map = _word_rels_map(package_path)
    body = root.find("w:body", WORD_NS)
    if body is None:
        return [], rels_map

    paragraph_tag = f"{{{WORD_NS_URI}}}p"
    table_tag = f"{{{WORD_NS_URI}}}tbl"
    blocks: list[dict[str, Any]] = []
    for child in body:
        if child.tag == paragraph_tag:
            text = word_text(child)
            images = _extract_images_from_element(child, rels_map)
            if text:
                if images:
                    blocks.append({
                        "type": "paragraph",
                        "style": word_paragraph_style(child),
                        "text": text,
                        "images": images,
                    })
                else:
                    blocks.append({
                        "type": "paragraph",
                        "style": word_paragraph_style(child),
                        "text": text,
                    })
            elif images:
                # Image-only paragraph (icons in tables etc.)
                for img in images:
                    blocks.append({
                        "type": "image",
                        "filename": img["filename"],
                        "alt_text": img["alt_text"],
                    })
        elif child.tag == table_tag:
            rows: list[list[str]] = []
            for row in child.findall("w:tr", WORD_NS):
                values: list[str] = []
                for cell in row.findall("w:tc", WORD_NS):
                    paragraphs = [word_text(paragraph) for paragraph in cell.findall("w:p", WORD_NS)]
                    cell_text = " / ".join(t for t in paragraphs if t)
                    cell_images = []
                    for paragraph in cell.findall("w:p", WORD_NS):
                        cell_images.extend(_extract_images_from_element(paragraph, rels_map))
                    if cell_images:
                        parts = []
                        for img in cell_images:
                            parts.append(f"![{img.get('alt_text', img['filename'])}]({img['filename']})")
                        cell_text = " ".join(parts) if not cell_text else cell_text + " " + " ".join(parts)
                    values.append(cell_text)
                if any(value for value in values):
                    rows.append(values)
            if rows:
                blocks.append({
                    "type": "table",
                    "rows": rows,
                })

    if blocks:
        return blocks, rels_map

    fallback_parts = [node.text for node in root.findall(".//w:t", WORD_NS) if node.text]
    fallback_text = " ".join(" ".join(fallback_parts).split())
    if fallback_text:
        return [{"type": "paragraph", "style": "", "text": fallback_text}], rels_map
    return [], rels_map


def render_markdown_table(rows: list[list[str]]) -> list[str]:
    column_count = max(len(row) for row in rows)
    normalized_rows: list[list[str]] = []
    for row in rows:
        normalized = row + [""] * (column_count - len(row))
        normalized_rows.append([cell.replace("\n", "<br>") or " " for cell in normalized])

    lines = [
        "| " + " | ".join(normalized_rows[0]) + " |",
        "| " + " | ".join(["---"] * column_count) + " |",
    ]
    for row in normalized_rows[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return lines


def heading_level_from_style(style: str) -> int:
    normalized = style.lower()
    if not normalized.startswith("heading"):
        return 0
    digits = "".join(character for character in normalized if character.isdigit())
    if digits:
        return max(2, min(6, int(digits) + 1))
    return 2


def export_word_document(package_path: Path, document_root: Path, source_file: Path) -> dict[str, Any]:
    blocks, rels_map = extract_docx_blocks(package_path)
    paragraph_count = sum(1 for block in blocks if block["type"] == "paragraph")
    table_count = sum(1 for block in blocks if block["type"] == "table")
    image_count = sum(1 for block in blocks if block["type"] == "image")
    manifest_blocks: list[dict[str, Any]] = []
    for index, block in enumerate(blocks, start=1):
        if block["type"] == "paragraph":
            manifest_blocks.append(
                {
                    "block_index": index,
                    "type": "paragraph",
                    "style": block.get("style", ""),
                    "excerpt": compact_excerpt(block["text"]),
                }
            )
        elif block["type"] == "table":
            manifest_blocks.append(
                {
                    "block_index": index,
                    "type": "table",
                    "row_count": len(block["rows"]),
                    "column_count": max(len(row) for row in block["rows"]),
                    "excerpt": compact_excerpt(" | ".join(block["rows"][0])),
                }
            )
        else:
            manifest_blocks.append(
                {
                    "block_index": index,
                    "type": "image",
                    "filename": block["filename"],
                }
            )

    manifest = {
        "source_file": source_file.name,
        "normalized_package": package_path.name,
        "generated_at": utc_now(),
        "block_count": len(blocks),
        "paragraph_count": paragraph_count,
        "table_count": table_count,
        "image_count": image_count,
        "blocks": manifest_blocks,
    }
    write_json(document_root / "evidence" / "word-manifest.json", manifest)
    write_json(document_root / ".pipeline-state.json", {"pipeline": "efm-multidoc-markdown-bundle", "updated_at": utc_now(), "current_phase": "docx", "status": "completed"})
    write_text(
        document_root / "intake-validation-report.md",
        "# Intake Validation Report\n\n"
        f"- Input document: `{source_file.name}`\n"
        f"- Normalized package: `{package_path.name}`\n"
        f"- Extracted blocks: `{len(blocks)}`\n"
        "- Route: `word-text-first`\n"
        "- Result: `pass`\n",
    )

    source_lines = [
        f"# {source_file.stem} Baseline Source",
        "",
        "> This file preserves direct OOXML text extraction from the Word package without page-level visual repair.",
        "",
        "## Document Overview",
        "",
        f"- Source file: `{source_file.name}`",
        f"- Normalized package: `{package_path.name}`",
        f"- Paragraph blocks: `{paragraph_count}`",
        f"- Table blocks: `{table_count}`",
        f"- Image blocks: `{image_count}`",
        "",
    ]
    final_lines = [
        f"# {source_file.stem} Text Export",
        "",
        "> Word documents are rendered from direct OOXML text and table extraction. Embedded images are inlined at their original positions.",
        "",
        "## Document Overview",
        "",
        f"- Source file: `{source_file.name}`",
        f"- Normalized package: `{package_path.name}`",
        f"- Text blocks: `{paragraph_count}`",
        f"- Tables: `{table_count}`",
        f"- Images: `{image_count}`",
        "",
    ]

    table_index = 0
    for index, block in enumerate(blocks, start=1):
        if block["type"] == "paragraph":
            text = block["text"]
            level = heading_level_from_style(block.get("style", ""))
            if level:
                final_lines.extend([f"{'#' * level} {text}", ""])
            else:
                final_lines.extend([text, ""])
            source_lines.extend([f"### Paragraph {index}", "", text, ""])
            # Inline images for this paragraph
            for img in block.get("images", []):
                md_img = f"![{img['alt_text'] or img['filename']}]({img['filename']})"
                final_lines.extend([md_img, ""])
                source_lines.extend([md_img, ""])
        elif block["type"] == "table":
            table_index += 1
            table_lines = render_markdown_table(block["rows"])
            source_lines.extend([f"### Table {table_index}", "", *table_lines, ""])
            final_lines.extend([f"### Table {table_index}", "", *table_lines, ""])
        else:
            # Standalone image block
            alt = block.get("alt_text", "") or block["filename"]
            md_img = f"![{alt}]({block['filename']})"
            final_lines.extend([md_img, ""])
            source_lines.extend([f"### Image {image_count - sum(1 for b in blocks[index:] if b['type'] != 'image')}", "", md_img, ""])

    if not blocks:
        source_lines.extend(["No textual content was extracted.", ""])
        final_lines.extend(["No textual content was extracted.", ""])

    write_text(document_root / "source.md", "\n".join(source_lines).rstrip() + "\n")
    write_text(document_root / "final.md", "\n".join(final_lines).rstrip() + "\n")
    return manifest


def infer_mermaid_from_ocr(ocr_text: str) -> str:
    normalized = [line for line in clean_lines(ocr_text) if len(line) <= 60]
    if not normalized:
        return ""
    lower = " ".join(normalized).lower()
    if any(token in lower for token in ["flow", "流程", "步骤", "开始", "结束", "判断", "success", "failure"]):
        nodes = normalized[:5]
        lines = ["flowchart TD"]
        for index, label in enumerate(nodes, start=1):
            node = f"N{index}"
            safe = label.replace('"', "'")
            lines.append(f'  {node}["{safe}"]')
            if index > 1:
                lines.append(f"  N{index - 1} --> {node}")
        return "\n".join(lines)
    if any(token in lower for token in ["architecture", "架构", "模块", "系统", "服务", "平台", "接口"]):
        nodes = normalized[:6]
        if len(nodes) < 2:
            return ""
        lines = ["flowchart LR"]
        hub = nodes[0].replace('"', "'")
        lines.append(f'  HUB["{hub}"]')
        for index, label in enumerate(nodes[1:], start=1):
            safe = label.replace('"', "'")
            node = f"M{index}"
            lines.append(f'  HUB --> {node}["{safe}"]')
        return "\n".join(lines)
    return ""


def clean_lines(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        line = " ".join(raw.split()).strip()
        if line:
            lines.append(line)
    return lines


def build_embedded_media_review(document_root: Path, package_path: Path) -> None:
    media_dir = document_root / "artifacts" / "embedded-media"
    extracted = extract_ooxml_media(package_path, media_dir)
    if not extracted:
        return

    report_items: list[dict[str, Any]] = []
    lines = ["# Embedded Media Review", "", "This report captures OCR-driven media interpretation for inserted images extracted from the original Office package.", ""]
    for index, item in enumerate(extracted, start=1):
        asset_path = Path(item["asset_path"])
        ocr_text = ocr_image_text(asset_path)
        mermaid = infer_mermaid_from_ocr(ocr_text)
        relative_asset = relative_path(asset_path, document_root)
        record = {
            "media_id": f"media-{index:03d}",
            "source_member": item["source_member"],
            "asset_path": relative_asset,
            "ocr_excerpt": summarize_text(ocr_text, 280),
            "has_mermaid": bool(mermaid),
        }
        report_items.append(record)
        lines.extend(
            [
                f"## {record['media_id']}",
                "",
                f"- Source member: `{record['source_member']}`",
                f"- Asset: ![{record['media_id']}]({relative_asset})",
                f"- OCR excerpt: {record['ocr_excerpt'] or 'No OCR text recovered.'}",
            ]
        )
        if mermaid:
            lines.extend(["", "```mermaid", mermaid, "```"])
        lines.append("")

    write_json(document_root / "artifacts" / "embedded-media" / "embedded-media.json", report_items)
    write_text(document_root / "artifacts" / "embedded-media" / "embedded-media-report.md", "\n".join(lines).rstrip() + "\n")
    # Note: images are already inlined in final.md via export_word_document(),
    # so we no longer append an "Embedded Media Review" section to final.md.


def export_workbook_csvs(workbook_path: Path, document_root: Path, source_file: Path) -> dict[str, Any]:
    if load_workbook is None:
        raise RuntimeError("openpyxl is required for workbook CSV export.")

    workbook = load_workbook(workbook_path, data_only=True)
    csv_dir = document_root / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)
    sheet_manifest: list[dict[str, Any]] = []

    for index, worksheet in enumerate(workbook.worksheets, start=1):
        sheet_slug = slugify(worksheet.title) or f"sheet-{index:02d}"
        csv_path = csv_dir / f"{sheet_slug}.csv"
        rows_written = 0
        max_columns = 0
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            for row in worksheet.iter_rows(values_only=True):
                values = ["" if value is None else str(value) for value in row]
                if any(value != "" for value in values):
                    writer.writerow(values)
                    rows_written += 1
                    max_columns = max(max_columns, len(values))
        sheet_manifest.append(
            {
                "sheet_name": worksheet.title,
                "sheet_index": index,
                "csv_path": relative_path(csv_path, document_root),
                "rows_written": rows_written,
                "column_count": max_columns,
                "embedded_image_count": len(getattr(worksheet, "_images", []) or []),
            }
        )

    manifest = {
        "source_file": source_file.name,
        "normalized_workbook": workbook_path.name,
        "generated_at": utc_now(),
        "sheet_count": len(sheet_manifest),
        "sheets": sheet_manifest,
    }
    write_json(document_root / "evidence" / "workbook-manifest.json", manifest)
    write_json(document_root / ".pipeline-state.json", {"pipeline": "efm-multidoc-markdown-bundle", "updated_at": utc_now(), "current_phase": "xlsx", "status": "completed"})
    write_text(
        document_root / "intake-validation-report.md",
        "# Intake Validation Report\n\n"
        f"- Input workbook: `{source_file.name}`\n"
        f"- Normalized workbook: `{workbook_path.name}`\n"
        f"- Generated at: `{utc_now()}`\n"
        "- Result: `pass`\n",
    )

    source_lines = [f"# {source_file.stem} Baseline Source", "", "> This file preserves the workbook sheet structure before CSV-focused rendering.", ""]
    final_lines = [f"# {source_file.stem} Workbook Export", "", "> Excel inputs are normalized to per-sheet CSV files and summarized here for batch processing consistency.", ""]
    final_lines.extend(["## Workbook Overview", "", f"- Source file: `{source_file.name}`", f"- Normalized workbook: `{workbook_path.name}`", f"- Sheet count: `{len(sheet_manifest)}`", ""])

    for sheet in sheet_manifest:
        source_lines.extend(
            [
                f"## {sheet['sheet_name']}",
                "",
                f"- CSV path: [{Path(sheet['csv_path']).name}]({sheet['csv_path']})",
                f"- Rows written: `{sheet['rows_written']}`",
                f"- Column count: `{sheet['column_count']}`",
                "",
            ]
        )
        final_lines.extend(
            [
                f"## {sheet['sheet_name']}",
                "",
                f"- CSV export: [{Path(sheet['csv_path']).name}]({sheet['csv_path']})",
                f"- Rows: `{sheet['rows_written']}`",
                f"- Columns: `{sheet['column_count']}`",
                f"- Embedded images: `{sheet['embedded_image_count']}`",
                "",
            ]
        )
        csv_path = document_root / sheet["csv_path"]
        preview_lines = csv_path.read_text(encoding="utf-8-sig").splitlines()[:8] if csv_path.exists() else []
        if preview_lines:
            source_lines.extend(["```csv", *preview_lines, "```", ""])
            final_lines.extend(["Preview:", "", "```csv", *preview_lines, "```", ""])

    write_text(document_root / "source.md", "\n".join(source_lines).rstrip() + "\n")
    write_text(document_root / "final.md", "\n".join(final_lines).rstrip() + "\n")
    return manifest


def process_visual_document(source_file: Path, document_root: Path, markdown_style: str, pdf_agent_validation: bool, include_asset_links: bool, enable_ocr: bool) -> dict[str, Any]:
    normalized_dir = document_root / "normalized"
    normalized_dir.mkdir(parents=True, exist_ok=True)
    suffix = source_file.suffix.lower()
    package_path = source_file
    if suffix == ".pdf":
        pdf_path = copy_if_needed(source_file, normalized_dir / source_file.name)
    elif suffix in {".doc", ".docx"}:
        package_path, pdf_path = convert_word_to_pdf(source_file, normalized_dir)
    elif suffix in {".ppt", ".pptx"}:
        package_path, pdf_path = convert_powerpoint_to_pdf(source_file, normalized_dir)
    else:
        raise ValueError(f"Unsupported visual document format: {suffix}")

    summary = run_pdf_pipeline(
        pdf_path=pdf_path,
        output_root=document_root,
        source_format=suffix.lstrip("."),
        markdown_style=markdown_style,
        pdf_agent_validation=pdf_agent_validation,
        include_asset_links=include_asset_links,
        enable_ocr=enable_ocr,
    )
    if package_path.suffix.lower() in OOXML_SUFFIXES:
        build_embedded_media_review(document_root, package_path)
    return summary


def process_word_document(source_file: Path, document_root: Path) -> dict[str, Any]:
    normalized_dir = document_root / "normalized"
    normalized_dir.mkdir(parents=True, exist_ok=True)
    package_path = convert_word_to_docx(source_file, normalized_dir)
    manifest = export_word_document(package_path, document_root, source_file)
    build_embedded_media_review(document_root, package_path)
    return {
        "output_root": str(document_root),
        "raw_block_total": manifest["block_count"],
        "visual_review_required_pages": [],
        "pdf_agent_review_status": "pass",
    }


def process_workbook_document(source_file: Path, document_root: Path) -> dict[str, Any]:
    normalized_dir = document_root / "normalized"
    normalized_dir.mkdir(parents=True, exist_ok=True)
    workbook_path = convert_excel_to_xlsx(source_file, normalized_dir)
    manifest = export_workbook_csvs(workbook_path, document_root, source_file)
    build_embedded_media_review(document_root, workbook_path)
    return {
        "output_root": str(document_root),
        "raw_block_total": manifest["sheet_count"],
        "visual_review_required_pages": [],
        "pdf_agent_review_status": "pass",
    }


def convert_html_to_markdown(html: str) -> str:
    """HTML -> Markdown，优先 markitdown / markdownify，最后回退到朴素去标签。"""
    # 1) markitdown（与本 bundle 生态一致，若已安装）
    try:
        from markitdown import MarkItDown  # type: ignore

        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as tmp:
            tmp.write(html)
            tmp_path = tmp.name
        try:
            result = MarkItDown().convert(tmp_path)
            text = getattr(result, "text_content", None) or getattr(result, "markdown", None)
            if text and text.strip():
                return text.strip()
        finally:
            try:
                Path(tmp_path).unlink()
            except OSError:
                pass
    except Exception:
        pass

    # 2) markdownify
    try:
        from markdownify import markdownify as _md  # type: ignore

        text = _md(html)
        if text and text.strip():
            return text.strip()
    except Exception:
        pass

    # 3) 朴素回退：剥离 script/style，转标签为换行，反转义实体。
    import html as _htmllib

    cleaned = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", html)
    cleaned = re.sub(r"(?i)<\s*br\s*/?>", "\n", cleaned)
    cleaned = re.sub(r"(?i)</\s*(p|div|li|tr|h[1-6])\s*>", "\n", cleaned)
    cleaned = re.sub(r"(?s)<[^>]+>", "", cleaned)
    cleaned = _htmllib.unescape(cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def process_text_document(source_file: Path, document_root: Path) -> dict[str, Any]:
    """Markdown / 纯文本 / HTML 直接转 Markdown（无需 Office / PDF 管线）。"""
    document_root.mkdir(parents=True, exist_ok=True)
    suffix = source_file.suffix.lower()
    raw = source_file.read_text(encoding="utf-8-sig", errors="replace")

    if suffix in HTML_SUFFIXES:
        body = convert_html_to_markdown(raw)
    else:
        # md / mdx / markdown / txt / rst / log：直接作为正文，保留原始内容。
        body = raw.strip()

    header = f"# {source_file.stem}\n\n_Source: `{source_file.name}` ({suffix.lstrip('.')})_\n"
    content = f"{header}\n{body}\n".rstrip() + "\n"
    write_text(document_root / "source.md", content)
    write_text(document_root / "final.md", content)
    return {
        "output_root": str(document_root),
        "raw_block_total": body.count("\n\n") + 1,
        "visual_review_required_pages": [],
        "pdf_agent_review_status": "pass",
    }


def process_data_document(source_file: Path, document_root: Path) -> dict[str, Any]:
    """csv/tsv/json/yaml/xml/toml/ini 及代码文件 -> Markdown 代码块（csv/tsv 额外渲染为表格预览）。"""
    document_root.mkdir(parents=True, exist_ok=True)
    suffix = source_file.suffix.lower()
    raw = source_file.read_text(encoding="utf-8-sig", errors="replace")
    lang = CODE_FENCE_LANG.get(suffix, "")

    lines = [f"# {source_file.stem}", "", f"_Source: `{source_file.name}` ({suffix.lstrip('.')})_", ""]

    if suffix in {".csv", ".tsv"}:
        delimiter = "\t" if suffix == ".tsv" else ","
        try:
            rows = list(csv.reader(raw.splitlines(), delimiter=delimiter))
        except Exception:
            rows = []
        preview = [r for r in rows if any(cell.strip() for cell in r)][:50]
        if preview:
            width = max(len(r) for r in preview)
            header_cells = preview[0] + [""] * (width - len(preview[0]))
            lines.append("| " + " | ".join(c.strip() or " " for c in header_cells) + " |")
            lines.append("| " + " | ".join(["---"] * width) + " |")
            for r in preview[1:]:
                cells = r + [""] * (width - len(r))
                lines.append("| " + " | ".join(c.strip().replace("|", "\\|") or " " for c in cells) + " |")
            lines.append("")
            if len(rows) > len(preview):
                lines.append(f"_（仅预览前 {len(preview)} 行，共 {len(rows)} 行）_")
                lines.append("")

    body = raw.strip()
    lines.extend([f"```{lang}", body, "```", ""])
    content = "\n".join(lines).rstrip() + "\n"
    write_text(document_root / "source.md", content)
    write_text(document_root / "final.md", content)
    return {
        "output_root": str(document_root),
        "raw_block_total": 1,
        "visual_review_required_pages": [],
        "pdf_agent_review_status": "pass",
    }


def process_image_document(source_file: Path, document_root: Path, enable_ocr: bool) -> dict[str, Any]:
    """独立图片 -> Markdown：拷贝图片到 assets/，嵌入引用，并尝试 OCR 提取文字。"""
    document_root.mkdir(parents=True, exist_ok=True)
    assets_dir = document_root / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    asset_path = copy_if_needed(source_file, assets_dir / source_file.name)
    rel = relative_path(asset_path, document_root)

    lines = [
        f"# {source_file.stem}",
        "",
        f"_Source: `{source_file.name}` ({source_file.suffix.lstrip('.')})_",
        "",
        f"![{source_file.stem}]({rel})",
        "",
    ]

    ocr_text = ""
    if enable_ocr and source_file.suffix.lower() in IMAGE_SUFFIXES:
        try:
            ocr_text = (ocr_image_text(source_file) or "").strip()
        except Exception:
            ocr_text = ""
    if ocr_text:
        lines.extend(["## OCR 提取文本", "", ocr_text, ""])
    else:
        lines.extend([
            "> 该图片未提取到文字（或未启用 OCR）。如需理解图片语义，请在后续多模态修复阶段补充描述。",
            "",
        ])

    content = "\n".join(lines).rstrip() + "\n"
    write_text(document_root / "source.md", content)
    write_text(document_root / "final.md", content)
    return {
        "output_root": str(document_root),
        "raw_block_total": 1,
        "visual_review_required_pages": [],
        "pdf_agent_review_status": "pass" if ocr_text else "needs-multimodal-repair",
    }


def build_batch_index(output_root: Path, batch_items: list[dict[str, Any]]) -> None:
    manifest = {
        "generated_at": utc_now(),
        "document_count": len(batch_items),
        "documents": batch_items,
    }
    write_json(output_root / "batch-manifest.json", manifest)

    lines = ["# Batch Document Index", "", f"- Document count: `{len(batch_items)}`", f"- Generated at: `{manifest['generated_at']}`", "", "| Source file | Format | Output | Final | Status |", "| --- | --- | --- | --- | --- |"]
    for item in batch_items:
        lines.append(
            f"| {item['source_name']} | {item['source_format']} | [{Path(item['output_root']).name}]({relative_path(Path(item['output_root']), output_root)}) | [{Path(item['final_path']).name}]({relative_path(Path(item['final_path']), output_root)}) | {item['status']} |"
        )
    write_text(output_root / "index.md", "\n".join(lines).rstrip() + "\n")


def main() -> None:
    args = parse_args()
    input_files = discover_input_files(args.input_path, args.input_file, recurse=args.recurse == "on", source_format=args.source_format)
    output_root = Path(args.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    batch_items: list[dict[str, Any]] = []
    for source_file in input_files:
        document_root = create_output_dir(output_root, source_file)
        suffix = source_file.suffix.lower()
        if suffix in {".pdf", ".ppt", ".pptx"}:
            summary = process_visual_document(
                source_file=source_file,
                document_root=document_root,
                markdown_style=args.markdown_style,
                pdf_agent_validation=args.pdf_agent_validation == "on",
                include_asset_links=args.asset_links == "on",
                enable_ocr=args.ocr == "on",
            )
            status = summary["pdf_agent_review_status"]
        elif suffix in {".doc", ".docx"}:
            summary = process_word_document(source_file=source_file, document_root=document_root)
            status = summary["pdf_agent_review_status"]
        elif suffix in {".xls", ".xlsx"}:
            summary = process_workbook_document(source_file=source_file, document_root=document_root)
            status = summary["pdf_agent_review_status"]
        elif suffix in HTML_SUFFIXES or suffix in TEXT_PASSTHROUGH_SUFFIXES:
            summary = process_text_document(source_file=source_file, document_root=document_root)
            status = summary["pdf_agent_review_status"]
        elif suffix in DATA_SUFFIXES or suffix in CODE_SUFFIXES:
            summary = process_data_document(source_file=source_file, document_root=document_root)
            status = summary["pdf_agent_review_status"]
        elif suffix in STANDALONE_IMAGE_SUFFIXES:
            summary = process_image_document(
                source_file=source_file,
                document_root=document_root,
                enable_ocr=args.ocr == "on",
            )
            status = summary["pdf_agent_review_status"]
        else:
            raise ValueError(f"Unsupported input format: {suffix}")

        final_path = document_root / "final.md"
        batch_items.append(
            {
                "source_name": source_file.name,
                "source_path": str(source_file),
                "source_format": suffix.lstrip("."),
                "output_root": str(document_root),
                "final_path": str(final_path),
                "status": status,
            }
        )

    build_batch_index(output_root, batch_items)
    print(json.dumps({"output_root": str(output_root), "document_count": len(batch_items), "documents": batch_items}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
