from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

try:
    import pdfplumber
    import pypdfium2 as pdfium
except Exception:  # pragma: no cover - graceful degradation
    pdfplumber = None  # type: ignore[assignment]
    pdfium = None  # type: ignore[assignment]

from .models import RouteDecision, SourceDocument
from .utils import (
    PURE_IMAGE_AVG_CHAR_THRESHOLD,
    PURE_IMAGE_PREVIEW_PAGE_COUNT,
    OCR_MAX_WIDTH,
    OCR_MAX_PIXELS,
    scale_for_render_bounds,
)

logger = logging.getLogger(__name__)

SPREADSHEET_EXTENSIONS = {".xlsx", ".xls", ".csv"}
OFFICE_DOCUMENT_EXTENSIONS = {".docx"}
PRESENTATION_EXTENSIONS = {".pptx"}
PDF_EXTENSIONS = {".pdf"}


def route_source_document(source_document: SourceDocument) -> RouteDecision:
    extension = source_document.extension.lower()
    size_bytes = int(source_document.metadata.get("size_bytes", 0))

    if extension in SPREADSHEET_EXTENSIONS:
        return RouteDecision(
            route="spreadsheet_pipeline",
            confidence=0.98,
            rationale="Spreadsheet-like files are treated as structured table sources.",
        )

    if extension in OFFICE_DOCUMENT_EXTENSIONS:
        return RouteDecision(
            route="office_document_pipeline",
            confidence=0.95,
            rationale="DOCX files are treated as structured office documents with assets.",
        )

    if extension in PRESENTATION_EXTENSIONS:
        return RouteDecision(
            route="presentation_pipeline",
            confidence=0.95,
            rationale="PPTX files are routed to slide-oriented extraction.",
        )

    if extension in PDF_EXTENSIONS:
        # Attempt pure-image detection before falling back to file-size routing.
        pure_image_decision = _try_detect_pure_image_pdf(source_document)
        if pure_image_decision is not None:
            return pure_image_decision

        # Fallback: file-size-based routing (original behavior).
        if size_bytes >= 15_000_000:
            return RouteDecision(
                route="complex_visual_pdf_path",
                confidence=0.60,
                rationale="Large PDFs default to the complex visual path until page-level analysis is implemented.",
            )

        if size_bytes >= 5_000_000:
            return RouteDecision(
                route="mixed_pdf_path",
                confidence=0.70,
                rationale="Mid-size PDFs default to the mixed path until page-level analysis is implemented.",
            )

        return RouteDecision(
            route="simple_text_pdf_path",
            confidence=0.65,
            rationale="PDF files default to the simple text path until a dedicated complexity analyzer is available.",
        )

    return RouteDecision(
        route="generic_file_pipeline",
        confidence=0.50,
        rationale="Unknown file types fall back to a generic baseline pipeline.",
    )


def _try_detect_pure_image_pdf(source_document: SourceDocument) -> RouteDecision | None:
    """Attempt to detect a pure-image PDF using pdfplumber + pypdfium2.

    Returns a RouteDecision if detection succeeds, or None to fall back
    to the file-size-based routing.
    """
    if pdfplumber is None or pdfium is None:
        return None

    source_path = source_document.source_path
    if source_path is None:
        return None

    pdf_path = Path(source_path)
    if not pdf_path.exists():
        return None

    try:
        # Step 1: Quick heuristic — check average pdfplumber character count.
        total_chars = 0
        page_count = 0

        with pdfplumber.open(str(pdf_path)) as plumber_pdf:
            page_count = len(plumber_pdf.pages)
            if page_count == 0:
                return None

            for page in plumber_pdf.pages:
                total_chars += len(page.chars) if page.chars else 0

        avg_chars = total_chars / page_count
        if avg_chars >= PURE_IMAGE_AVG_CHAR_THRESHOLD:
            logger.debug(
                "PDF %s: avg %.1f chars/page (threshold %d), not pure-image",
                pdf_path.name,
                avg_chars,
                PURE_IMAGE_AVG_CHAR_THRESHOLD,
            )
            return None

        logger.debug(
            "PDF %s: avg %.1f chars/page — suspected pure-image, checking page dimensions",
            pdf_path.name,
            avg_chars,
        )

        # Step 2: Render preview pages to check dimensions.
        preview_count = min(page_count, PURE_IMAGE_PREVIEW_PAGE_COUNT)
        has_oversized_page = False

        pdf = pdfium.PdfDocument(str(pdf_path))
        try:
            for i in range(preview_count):
                page = pdf[i]
                width = page.get_width()
                height = page.get_height()

                # Estimate rendered pixel dimensions at 1x scale.
                # 1 point = 1/72 inch, at 96 DPI that's 1.333px per point.
                render_width_px = int(width * 96 / 72)
                render_height_px = int(height * 96 / 72)

                if render_width_px > OCR_MAX_WIDTH or render_width_px * render_height_px > OCR_MAX_PIXELS:
                    has_oversized_page = True
                    break
        finally:
            pdf.close()

        if has_oversized_page:
            return RouteDecision(
                route="pure_image_pdf_path",
                confidence=0.75,
                rationale=(
                    "PDF contains no extractable text and has oversized pages; "
                    "routed to pure-image multimodal path with tile-based processing."
                ),
            )

        return RouteDecision(
            route="pure_image_pdf_path",
            confidence=0.80,
            rationale="PDF contains no extractable text; routed to pure-image multimodal path.",
        )

    except Exception as exc:
        logger.warning(
            "Pure-image detection failed for %s: %s — falling back to size-based routing",
            pdf_path.name,
            exc,
        )
        return None
