from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from ..models import WorkingBundle
from ..utils import read_text_file, resolution_for_max_width, scale_image_for_ocr

# OCR dependencies (optional, imported at runtime)
_pdfplumber_available = True
try:
    import pdfplumber
except ImportError:
    _pdfplumber_available = False

_numpy_available = True
try:
    import numpy as np
except ImportError:
    _numpy_available = False

_rapidocr_available = True
try:
    from rapidocr_onnxruntime import RapidOCR
except ImportError:
    _rapidocr_available = False


TEXT_FALLBACK_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".json",
    ".xml",
    ".html",
    ".htm",
    ".yml",
    ".yaml",
}

DOCX_EXTENSION = ".docx"
WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WORD_NAMESPACES = {"w": WORD_NAMESPACE}


class MarkItDownBaselineAdapter:
    def __init__(self, *, enable_plugins: bool = False):
        self.enable_plugins = enable_plugins

    def extract(self, bundle: WorkingBundle) -> str:
        source_path = bundle.source_document.source_path
        if source_path is None:
            bundle.add_diagnostic("No source path is attached to the working bundle.")
            bundle.metadata["baseline_adapter"] = "fallback"
            return self._placeholder_markdown(bundle, None)

        file_path = Path(source_path)
        markitdown_class = self._resolve_markitdown_class()
        if markitdown_class is not None:
            try:
                instance = markitdown_class(enable_plugins=self.enable_plugins)
                result = instance.convert(str(file_path))
                bundle.metadata["baseline_adapter"] = "markitdown"
                markdown = (getattr(result, "markdown", "") or "").strip()
                if markdown:
                    if file_path.suffix.lower() == DOCX_EXTENSION:
                        markdown = self._restore_docx_table_line_breaks(file_path, markdown, bundle)
                    return markdown
                bundle.add_diagnostic("MarkItDown returned empty markdown; fallback extraction will be used.")
            except Exception as exc:
                bundle.add_diagnostic(f"MarkItDown baseline extraction failed: {exc}")

        # Fallback: try OCR-based extraction for PDFs
        bundle.metadata["baseline_adapter"] = "fallback"
        if file_path.suffix.lower() == ".pdf":
            ocr_markdown = self._pdf_ocr_extraction(file_path, bundle)
            if ocr_markdown:
                bundle.metadata["baseline_adapter"] = "pdf-ocr-fallback"
                return ocr_markdown

        return self._fallback_markdown(file_path, bundle)

    def _pdf_ocr_extraction(self, file_path: Path, bundle: WorkingBundle) -> str:
        """Extract text from PDF using pdfplumber + rapidocr fallback."""
        if not _pdfplumber_available:
            bundle.add_diagnostic("pdfplumber not available for OCR extraction.")
            return ""

        lines: list[str] = []
        ocr_page_count = 0

        try:
            ocr_engine = None
            if _rapidocr_available:
                try:
                    ocr_engine = RapidOCR()
                except Exception:
                    ocr_engine = None

            with pdfplumber.open(str(file_path)) as pdf:
                lines.append(f"# {file_path.stem}")
                lines.append("")

                for index, page in enumerate(pdf.pages):
                    page_number = index + 1
                    text = page.extract_text() or ""

                    # If no text extracted, try OCR
                    if (not text.strip()) and ocr_engine is not None:
                        ocr_text = self._ocr_page_with_rapidocr(page, ocr_engine)
                        if ocr_text.strip():
                            text = ocr_text
                            ocr_page_count += 1
                            bundle.add_diagnostic(f"Page {page_number}: OCR applied, extracted {len(text)} chars.")

                    if text.strip():
                        lines.append(f"## Page {page_number}")
                        lines.append("")
                        # Detect structure and format as markdown
                        structured = self._format_page_text(text)
                        lines.extend(structured)
                        lines.append("")
                    else:
                        lines.append(f"## Page {page_number}")
                        lines.append("")
                        lines.append("> 该页无可用文本")
                        lines.append("")

                if ocr_page_count > 0:
                    lines.append("")
                    lines.append(f"> OCR 回退：共 {ocr_page_count} 页使用了 OCR 文字提取。")

        except Exception as exc:
            bundle.add_diagnostic(f"PDF OCR extraction failed: {exc}")
            return ""

        bundle.metadata["pdf_ocr_extraction"] = {
            "page_count": len(lines),
            "ocr_page_count": ocr_page_count,
        }

        return "\n".join(lines).rstrip() + "\n"

    def _ocr_page_with_rapidocr(self, plumber_page: Any, ocr_engine: Any) -> str:
        """Run RapidOCR on a single page."""
        if not _numpy_available:
            return ""
        try:
            resolution = resolution_for_max_width(float(getattr(plumber_page, "width", 0) or 0))
            pil_image = plumber_page.to_image(resolution=resolution).original
            pil_image = scale_image_for_ocr(pil_image)
            arr = np.array(pil_image)
            result, _ = ocr_engine(arr)
            if not result:
                return ""
            # result is list of [bbox, text, confidence]
            texts = []
            for item in result:
                t = item[1]
                if isinstance(t, str) and t.strip():
                    texts.append(t.strip())
            return "\n".join(texts)
        except Exception:
            return ""

    def _format_page_text(self, text: str) -> list[str]:
        """Format extracted page text into structured markdown."""
        result: list[str] = []
        for raw_line in text.splitlines():
            line = raw_line.replace(" ", " ").replace("\t", " ").strip()
            if not line:
                continue

            # Classify line type
            if len(line) <= 30 and not line.endswith(("。", "！", "？", ".", "!", "?", "，", ",")):
                if not re.match(r"^[-*•\d]", line):
                    result.append(f"### {line}")
                    continue

            if re.match(r"^[\d]+[\.、)]\s", line):
                result.append(f"- {re.sub(r'^[\d]+[\.、)]\s*', '', line)}")
                continue

            if re.match(r"^[-*•]\s", line):
                result.append(line)
                continue

            result.append(line)

        return result

    def _resolve_markitdown_class(self) -> Any | None:
        installed = self._import_installed_markitdown()
        if installed is not None:
            return installed

        return self._import_workspace_markitdown()

    def _import_installed_markitdown(self) -> Any | None:
        try:
            from markitdown import MarkItDown

            return MarkItDown
        except Exception:
            return None

    def _import_workspace_markitdown(self) -> Any | None:
        workspace_root = Path(__file__).resolve().parents[4]
        candidate = (
            workspace_root
            / "markitdown-main"
            / "markitdown-main"
            / "packages"
            / "markitdown"
            / "src"
        )
        if not candidate.exists():
            return None

        candidate_str = str(candidate)
        if candidate_str not in sys.path:
            sys.path.insert(0, candidate_str)

        try:
            from markitdown import MarkItDown

            return MarkItDown
        except Exception:
            return None

    def _fallback_markdown(self, file_path: Path, bundle: WorkingBundle) -> str:
        extension = file_path.suffix.lower()
        if extension in TEXT_FALLBACK_EXTENSIONS:
            text = read_text_file(file_path).strip()
            if extension in {".md", ".markdown"}:
                return text
            if extension == ".csv":
                return f"# {file_path.name}\n\n```csv\n{text}\n```"
            return f"# {file_path.name}\n\n{text}" if text else f"# {file_path.name}\n\n> File is empty."

        return self._placeholder_markdown(bundle, file_path)

    def _placeholder_markdown(
        self, bundle: WorkingBundle, file_path: Path | None
    ) -> str:
        filename = bundle.source_document.filename if file_path is None else file_path.name
        return "\n".join(
            [
                f"# {filename}",
                "",
                "> Baseline extraction is not available in standalone mode for this file yet.",
                f"> Selected route: {bundle.route_decision.route}",
                "",
                "## Next Steps",
                "- Plug in a deterministic worker for this route.",
                "- Or enable the MarkItDown adapter in an environment with its dependencies installed.",
            ]
        )

    def _restore_docx_table_line_breaks(
        self,
        file_path: Path,
        markdown: str,
        bundle: WorkingBundle,
    ) -> str:
        if "|" not in markdown:
            return markdown

        try:
            replacement_tables = self._extract_docx_markdown_tables(file_path)
        except Exception as exc:
            bundle.add_diagnostic(f"DOCX table line-break restoration failed: {exc}")
            return markdown

        if not replacement_tables:
            return markdown

        restored_markdown, replaced_count = self._replace_markdown_tables(
            markdown,
            replacement_tables,
        )
        if replaced_count == 0:
            bundle.add_diagnostic("DOCX table line-break restoration found no markdown tables to replace.")
            return markdown

        if replaced_count != len(replacement_tables):
            bundle.add_diagnostic(
                "DOCX table line-break restoration replaced "
                f"{replaced_count} markdown tables from {len(replacement_tables)} DOCX tables."
            )
        return restored_markdown

    def _extract_docx_markdown_tables(self, file_path: Path) -> list[str]:
        with zipfile.ZipFile(file_path) as archive:
            document_xml = archive.read("word/document.xml")

        root = ElementTree.fromstring(document_xml)
        markdown_tables: list[str] = []
        for table in root.findall(".//w:tbl", WORD_NAMESPACES):
            rows = self._extract_docx_table_rows(table)
            if rows:
                markdown_tables.append(self._render_markdown_table(rows))
        return markdown_tables

    def _extract_docx_table_rows(self, table: ElementTree.Element) -> list[list[str]]:
        rows: list[list[str]] = []
        for row in table.findall("./w:tr", WORD_NAMESPACES):
            cells: list[str] = []
            for cell in row.findall("./w:tc", WORD_NAMESPACES):
                cells.append(self._extract_docx_cell_text(cell))
                for _ in range(self._docx_grid_span(cell) - 1):
                    cells.append("")
            if cells:
                rows.append(cells)
        return rows

    def _extract_docx_cell_text(self, cell: ElementTree.Element) -> str:
        paragraphs: list[str] = []
        for paragraph in cell.findall("./w:p", WORD_NAMESPACES):
            paragraph_text = self._extract_docx_paragraph_text(paragraph)
            if paragraph_text:
                paragraphs.append(paragraph_text)
            elif paragraphs:
                paragraphs.append("")
        return "\n".join(paragraphs).strip()

    def _extract_docx_paragraph_text(self, paragraph: ElementTree.Element) -> str:
        fragments: list[str] = []
        for node in paragraph.iter():
            if node.tag == f"{{{WORD_NAMESPACE}}}t":
                fragments.append(node.text or "")
            elif node.tag in {f"{{{WORD_NAMESPACE}}}br", f"{{{WORD_NAMESPACE}}}cr"}:
                fragments.append("\n")
            elif node.tag == f"{{{WORD_NAMESPACE}}}tab":
                fragments.append(" ")

        joined = "".join(fragments).replace("\r", "")
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in joined.split("\n")]
        while lines and not lines[0]:
            lines.pop(0)
        while lines and not lines[-1]:
            lines.pop()
        return "\n".join(lines)

    def _docx_grid_span(self, cell: ElementTree.Element) -> int:
        grid_span = cell.find("./w:tcPr/w:gridSpan", WORD_NAMESPACES)
        if grid_span is None:
            return 1

        value = grid_span.get(f"{{{WORD_NAMESPACE}}}val")
        if value and value.isdigit():
            return max(1, int(value))
        return 1

    def _render_markdown_table(self, rows: list[list[str]]) -> str:
        column_count = max(len(row) for row in rows)
        normalized_rows = [row + [""] * (column_count - len(row)) for row in rows]
        header = normalized_rows[0]
        body = normalized_rows[1:]

        lines = [self._markdown_table_row(header)]
        lines.append("| " + " | ".join("---" for _ in range(column_count)) + " |")
        lines.extend(self._markdown_table_row(row) for row in body)
        return "\n".join(lines)

    def _markdown_table_row(self, cells: list[str]) -> str:
        rendered_cells = [self._escape_markdown_table_cell(cell) for cell in cells]
        return "| " + " | ".join(rendered_cells) + " |"

    def _escape_markdown_table_cell(self, text: str) -> str:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = [line.strip() for line in normalized.split("\n")]
        return "<br>".join(line.replace("|", r"\|") for line in lines)

    def _replace_markdown_tables(self, markdown: str, replacements: list[str]) -> tuple[str, int]:
        lines = markdown.splitlines()
        replaced_count = 0
        output_lines: list[str] = []
        index = 0

        while index < len(lines):
            if self._is_markdown_table_start(lines, index):
                table_start = index
                index += 2
                while index < len(lines) and self._looks_like_markdown_table_row(lines[index]):
                    index += 1

                if replaced_count < len(replacements):
                    output_lines.extend(replacements[replaced_count].splitlines())
                    replaced_count += 1
                else:
                    output_lines.extend(lines[table_start:index])
                continue

            output_lines.append(lines[index])
            index += 1

        return "\n".join(output_lines), replaced_count

    def _is_markdown_table_start(self, lines: list[str], index: int) -> bool:
        if index + 1 >= len(lines):
            return False

        header = lines[index].strip()
        separator = lines[index + 1].strip()
        return (
            self._looks_like_markdown_table_row(header)
            and "|" in header
            and re.fullmatch(r"\|?[ :\-\|]+\|?", separator) is not None
        )

    def _looks_like_markdown_table_row(self, line: str) -> bool:
        stripped = line.strip()
        return stripped.startswith("|") and stripped.endswith("|")
