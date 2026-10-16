from __future__ import annotations

from pathlib import Path
import re
from typing import Any

import numpy as np

from ..models import PageRecord, WorkingBundle
from ..utils import (
    TILE_MAX_HEIGHT,
    TILE_MAX_PIXELS,
    TILE_MAX_WIDTH,
    calculate_tile_grid,
    is_j90k_hvac_document,
    is_j90k_media_center_document,
    relative_to_root,
    scale_for_render_bounds,
    scale_image_for_ocr,
)

_dependency_error: Exception | None = None
try:
    import pdfplumber
    import pypdfium2 as pdfium
except Exception as exc:  # pragma: no cover - exercised by runtime fallback
    _dependency_error = exc

_ocr_available: bool = False
try:
    from rapidocr_onnxruntime import RapidOCR
    _ocr_available = True
except Exception:
    pass


class PDFMultimodalPreparationWorker:
    def __init__(
        self,
        *,
        preview_scale: float = 0.15,
        review_scale: float = 0.30,
        preview_max_width: int = 1600,
        review_max_width: int = 2800,
        ocr_enabled: bool = True,
    ) -> None:
        self.preview_scale = preview_scale
        self.review_scale = review_scale
        self.preview_max_width = preview_max_width
        self.review_max_width = review_max_width
        self.ocr_enabled = ocr_enabled and _ocr_available
        self._ocr_engine = None

    def prepare(self, bundle: WorkingBundle) -> None:
        if bundle.source_document.extension.lower() != ".pdf":
            return

        source_path = bundle.source_document.source_path
        if source_path is None:
            self._skip_preparation(
                bundle,
                "PDF multimodal preparation skipped because the source path is missing.",
            )
            return

        if _dependency_error is not None:
            self._skip_preparation(
                bundle,
                (
                    "PDF multimodal preparation skipped because dependencies are unavailable: "
                    f"{_dependency_error}"
                ),
                metadata={
                    "status": "skipped",
                    "reason": "missing-dependencies",
                },
            )
            return

        self._prepare_pdf_bundle(bundle, Path(source_path))
        self._write_agent_brief(bundle)

    def _skip_preparation(
        self,
        bundle: WorkingBundle,
        diagnostic: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        bundle.add_diagnostic(diagnostic)
        if metadata is not None:
            bundle.metadata["multimodal_preparation"] = metadata
        self._write_agent_brief(bundle)

    def _prepare_pdf_bundle(self, bundle: WorkingBundle, pdf_path: Path) -> None:
        pages_dir = bundle.layout_paths()["pages"]
        page_records: list[PageRecord] = []
        review_pages: list[int] = []

        try:
            with pdfplumber.open(str(pdf_path)) as plumber_pdf:
                pdf = pdfium.PdfDocument(str(pdf_path))
                try:
                    page_count = len(pdf)
                    for index in range(page_count):
                        record = self._prepare_pdf_page(
                            bundle,
                            plumber_pdf,
                            pdf,
                            pages_dir,
                            pdf_path,
                            index,
                        )
                        page_records.append(record)
                        if record.needs_visual_review:
                            review_pages.append(record.page_number)
                finally:
                    pdf.close()
        except Exception as exc:
            bundle.add_diagnostic(f"PDF multimodal preparation failed: {exc}")
            bundle.metadata["multimodal_preparation"] = {
                "status": "failed",
                "error": str(exc),
            }
            return

        bundle.page_records = page_records
        bundle.metadata["multimodal_preparation"] = {
            "status": "prepared",
            "page_count": page_count,
            "review_pages": review_pages,
            "review_page_count": len(review_pages),
            "diagram_candidate_pages": [
                record.page_number for record in page_records if record.diagram_candidate
            ],
        }

    def _prepare_pdf_page(
        self,
        bundle: WorkingBundle,
        plumber_pdf: Any,
        pdf: Any,
        pages_dir: Path,
        pdf_path: Path,
        page_index: int,
    ) -> PageRecord:
        page_number = page_index + 1
        plumber_page = plumber_pdf.pages[page_index] if page_index < len(plumber_pdf.pages) else None
        text, page_tables = self._extract_page_text_and_tables(plumber_page, pdf_path, page_index)
        text_length = len(text)
        image_count = len(plumber_page.images) if plumber_page else 0
        char_count = len(plumber_page.chars) if plumber_page else 0
        needs_visual_review = self._needs_visual_review(
            route=bundle.route_decision.route,
            text_length=text_length,
            image_count=image_count,
            char_count=char_count,
        )
        diagram_candidate = self._is_diagram_candidate(
            page_number=page_number,
            text=text,
            image_count=image_count,
            text_length=text_length,
        )
        demo_spec_candidate = self._looks_like_demo_spec_page(text)
        demo_region_texts = self._extract_demo_region_texts(plumber_page) if demo_spec_candidate else {}

        page = pdf[page_index]
        screenshot_artifact = self._render_page_screenshot(bundle, page, pages_dir, page_number)

        # Check if this page needs adaptive tile splitting (pure-image route or oversized).
        tile_grid = self._compute_tile_grid_if_needed(
            page,
            route=bundle.route_decision.route,
            text_length=text_length,
            image_count=image_count,
        )

        tile_paths, region_paths = self._prepare_page_review_assets(
            bundle,
            page,
            pages_dir,
            page_number,
            needs_visual_review=needs_visual_review,
            diagram_candidate=diagram_candidate,
            demo_spec_candidate=demo_spec_candidate,
            screenshot_path=screenshot_artifact.path,
            tile_grid=tile_grid,
        )

        metadata: dict[str, Any] = {
            "raw_text": text,
            "raw_text_excerpt": text[:280],
            "demo_spec_candidate": demo_spec_candidate,
            "page_tables": page_tables,
            **demo_region_texts,
        }
        if tile_grid is not None:
            metadata["tile_grid"] = list(tile_grid)  # (rows, cols) as list for JSON

        return PageRecord(
            page_number=page_number,
            route_hint=bundle.route_decision.route,
            screenshot_path=screenshot_artifact.path,
            needs_visual_review=needs_visual_review,
            diagram_candidate=diagram_candidate,
            tile_paths=tile_paths,
            region_paths=region_paths,
            text_length=text_length,
            image_count=image_count,
            char_count=char_count,
            metadata=metadata,
        )

    def _extract_page_text_and_tables(
        self,
        plumber_page: Any,
        pdf_path: Path,
        page_index: int,
    ) -> tuple[str, list[dict[str, Any]]]:
        if plumber_page is None:
            return "", []

        text = plumber_page.extract_text() or ""
        used_ocr_fallback = False
        if not text.strip() and self.ocr_enabled:
            text = self._ocr_fallback_page(pdf_path, page_index)
            used_ocr_fallback = True

        page_tables = self._extract_page_tables(
            plumber_page,
            pdf_path,
            page_index,
            use_ocr=used_ocr_fallback,
        )
        return text, page_tables

    def _render_page_screenshot(
        self,
        bundle: WorkingBundle,
        page: Any,
        pages_dir: Path,
        page_number: int,
    ) -> Any:
        screenshot_path = pages_dir / f"page-{page_number:04d}-full.png"
        screenshot_scale = self._scale_for_max_width(
            page.get_width(),
            preferred_scale=self.preview_scale,
            max_width=self.preview_max_width,
        )
        self._render_page_image(page, screenshot_path, screenshot_scale)
        return bundle.add_artifact(
            kind="image",
            role="page-screenshot",
            path=screenshot_path,
            metadata={"page": page_number},
        )

    def _prepare_page_review_assets(
        self,
        bundle: WorkingBundle,
        page: Any,
        pages_dir: Path,
        page_number: int,
        *,
        needs_visual_review: bool,
        diagram_candidate: bool,
        demo_spec_candidate: bool,
        screenshot_path: str,
        tile_grid: tuple[int, int] | None = None,
    ) -> tuple[list[str], list[str]]:
        if not needs_visual_review and tile_grid is None:
            return [], []

        tile_paths = self._render_tiles(bundle, page, pages_dir, page_number, grid=tile_grid)
        region_paths = self._render_regions(
            bundle,
            page,
            page_number,
            diagram_candidate=diagram_candidate,
            demo_spec_candidate=demo_spec_candidate,
        )
        self._add_page_visual_review_task(
            bundle,
            page_number,
            screenshot_path,
            tile_paths,
            region_paths,
            diagram_candidate=diagram_candidate,
            demo_spec_candidate=demo_spec_candidate,
        )
        return tile_paths, region_paths

    def _add_page_visual_review_task(
        self,
        bundle: WorkingBundle,
        page_number: int,
        screenshot_path: str,
        tile_paths: list[str],
        region_paths: list[str],
        *,
        diagram_candidate: bool,
        demo_spec_candidate: bool,
    ) -> None:
        bundle.add_agent_task(
            kind="pdf-page-visual-review",
            description=(
                f"Page {page_number}: inspect annotations, module links, arrows, "
                "flow directions, and visual structure against the baseline markdown."
            ),
            metadata={
                "page": page_number,
                "screenshot_path": screenshot_path,
                "tile_paths": tile_paths,
                "region_paths": region_paths,
                "diagram_candidate": diagram_candidate,
                "demo_spec_candidate": demo_spec_candidate,
            },
        )

    def _render_tiles(
        self,
        bundle: WorkingBundle,
        page: Any,
        pages_dir: Path,
        page_number: int,
        *,
        grid: tuple[int, int] | None = None,
    ) -> list[str]:
        if grid is not None and grid != (1, 1):
            return self._render_adaptive_tiles(bundle, page, pages_dir, page_number, grid)

        # Default: fixed 2x2 tiles (original behavior).
        review_scale = self._scale_for_max_width(
            page.get_width(),
            preferred_scale=self.review_scale,
            max_width=self.review_max_width,
        )
        image = page.render(scale=review_scale).to_pil()
        width, height = image.size
        mid_x = width // 2
        mid_y = height // 2
        boxes = [
            ((0, 0, mid_x, mid_y), "r1c1"),
            ((mid_x, 0, width, mid_y), "r1c2"),
            ((0, mid_y, mid_x, height), "r2c1"),
            ((mid_x, mid_y, width, height), "r2c2"),
        ]

        tile_paths: list[str] = []
        for box, label in boxes:
            tile_path = pages_dir / f"page-{page_number:04d}-tile-{label}.png"
            image.crop(box).save(tile_path, format="PNG")
            artifact = bundle.add_artifact(
                kind="image",
                role="page-tile",
                path=tile_path,
                metadata={"page": page_number, "tile": label},
            )
            tile_paths.append(artifact.path)

        return tile_paths

    def _compute_tile_grid_if_needed(
        self,
        page: Any,
        *,
        route: str,
        text_length: int,
        image_count: int,
    ) -> tuple[int, int] | None:
        """Determine if this page needs adaptive tile splitting.

        Returns (rows, cols) if tiling is needed, None otherwise.
        """
        width = page.get_width()
        height = page.get_height()
        if width <= 0 or height <= 0:
            return None

        # Pure-image route: always check dimensions for tiling.
        if route == "pure_image_pdf_path":
            # Render at full resolution (scale=1.0) to get actual pixel dimensions.
            render_width_px = int(width * 96 / 72)
            render_height_px = int(height * 96 / 72)

            if (render_width_px > TILE_MAX_WIDTH
                    or render_height_px > TILE_MAX_HEIGHT
                    or render_width_px * render_height_px > TILE_MAX_PIXELS):
                return calculate_tile_grid(render_width_px, render_height_px)

            return None

        # Other routes: use existing heuristic.
        if text_length >= 320 or image_count == 0:
            return None

        # For visual review pages that are oversized, also tile.
        render_width_px = int(width * 96 / 72)
        render_height_px = int(height * 96 / 72)
        if (render_width_px > TILE_MAX_WIDTH
                or render_height_px > TILE_MAX_HEIGHT
                or render_width_px * render_height_px > TILE_MAX_PIXELS):
            return calculate_tile_grid(render_width_px, render_height_px)

        return None

    def _render_adaptive_tiles(
        self,
        bundle: WorkingBundle,
        page: Any,
        pages_dir: Path,
        page_number: int,
        grid: tuple[int, int],
    ) -> list[str]:
        """Render page as adaptive tiles based on grid (rows, cols).

        Each tile is rendered at full scale to stay within size limits
        for multimodal API consumption.
        """
        rows, cols = grid

        # Render at scale=1.0 for actual pixel dimensions, then crop.
        image = page.render(scale=1.0).to_pil()
        width, height = image.size

        tile_width = width // cols
        tile_height = height // rows

        tile_paths: list[str] = []
        for r in range(rows):
            for c in range(cols):
                x0 = c * tile_width
                y0 = r * tile_height
                x1 = width if c == cols - 1 else (c + 1) * tile_width
                y1 = height if r == rows - 1 else (r + 1) * tile_height

                tile_path = pages_dir / f"page-{page_number:04d}-tile-r{r}c{c}.png"
                image.crop((x0, y0, x1, y1)).save(tile_path, format="PNG")

                artifact = bundle.add_artifact(
                    kind="image",
                    role="page-tile",
                    path=tile_path,
                    metadata={
                        "page": page_number,
                        "tile": f"r{r}c{c}",
                        "tile_grid": list(grid),
                        "tile_position": {"row": r, "col": c},
                    },
                )
                tile_paths.append(artifact.path)

        return tile_paths

    def _render_page_image(self, page: Any, output_path: Path, scale: float) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image = page.render(scale=scale).to_pil()
        image.save(output_path, format="PNG")

    def _render_regions(
        self,
        bundle: WorkingBundle,
        page: Any,
        page_number: int,
        *,
        diagram_candidate: bool,
        demo_spec_candidate: bool,
    ) -> list[str]:
        regions_dir = bundle.layout_paths()["regions"]
        review_scale = self._scale_for_max_width(
            page.get_width(),
            preferred_scale=self.review_scale,
            max_width=self.review_max_width,
        )
        image = page.render(scale=review_scale).to_pil()
        width, height = image.size

        region_specs = [
            ((int(width * 0.08), int(height * 0.10), int(width * 0.92), int(height * 0.90)), "main"),
        ]
        if diagram_candidate:
            region_specs.append(
                ((int(width * 0.12), int(height * 0.18), int(width * 0.88), int(height * 0.82)), "diagram-focus")
            )

        region_specs.extend(
            self._special_region_specs(
                bundle,
                page_number,
                width,
                height,
                demo_spec_candidate=demo_spec_candidate,
            )
        )

        region_paths: list[str] = []
        for box, label in region_specs:
            region_path = regions_dir / f"page-{page_number:04d}-region-{label}.png"
            image.crop(box).save(region_path, format="PNG")
            artifact = bundle.add_artifact(
                kind="image",
                role="page-region",
                path=region_path,
                metadata={"page": page_number, "label": label},
            )
            region_paths.append(artifact.path)

        return region_paths

    def _special_region_specs(
        self,
        bundle: WorkingBundle,
        page_number: int,
        width: int,
        height: int,
        *,
        demo_spec_candidate: bool,
    ) -> list[tuple[tuple[int, int, int, int], str]]:
        if is_j90k_media_center_document(bundle.source_document.filename, bundle.draft_markdown):
            specs: list[tuple[tuple[int, int, int, int], str]] = []
            if demo_spec_candidate:
                specs.extend(
                    [
                        (
                            (
                                int(width * 0.04),
                                int(height * 0.12),
                                int(width * 0.49),
                                int(height * 0.96),
                            ),
                            "demo-left-pane",
                        ),
                        (
                            (
                                int(width * 0.51),
                                int(height * 0.12),
                                int(width * 0.96),
                                int(height * 0.96),
                            ),
                            "demo-right-pane",
                        ),
                    ]
                )

            if page_number == 10:
                specs.extend(
                    [
                        (
                            (
                                int(width * 0.06),
                                int(height * 0.08),
                                int(width * 0.96),
                                int(height * 0.48),
                            ),
                            "flow-low-config",
                        ),
                        (
                            (
                                int(width * 0.06),
                                int(height * 0.52),
                                int(width * 0.96),
                                int(height * 0.96),
                            ),
                            "flow-high-config",
                        ),
                        (
                            (
                                int(width * 0.44),
                                int(height * 0.10),
                                int(width * 0.96),
                                int(height * 0.48),
                            ),
                            "flow-low-main-branch",
                        ),
                        (
                            (
                                int(width * 0.44),
                                int(height * 0.54),
                                int(width * 0.96),
                                int(height * 0.96),
                            ),
                            "flow-high-main-branch",
                        ),
                    ]
                )

            if specs:
                return specs

        if page_number != 9:
            return []

        if not is_j90k_hvac_document(bundle.source_document.filename, bundle.draft_markdown):
            return []

        return [
            (
                (
                    int(width * 0.50),
                    int(height * 0.26),
                    int(width * 0.97),
                    int(height * 0.66),
                ),
                "massage-panel",
            ),
            (
                (
                    int(width * 0.03),
                    int(height * 0.56),
                    int(width * 0.49),
                    int(height * 0.96),
                ),
                "flow-left",
            ),
            (
                (
                    int(width * 0.50),
                    int(height * 0.58),
                    int(width * 0.98),
                    int(height * 0.98),
                ),
                "flow-right",
            ),
        ]

    def _scale_for_max_width(
        self, page_width: float, *, preferred_scale: float, max_width: int
    ) -> float:
        if not page_width or page_width <= 0:
            return preferred_scale

        return min(preferred_scale, max_width / page_width)

    def _needs_visual_review(
        self,
        *,
        route: str,
        text_length: int,
        image_count: int,
        char_count: int,
    ) -> bool:
        if route == "complex_visual_pdf_path":
            return True

        if image_count > 0:
            return True

        if text_length < 320 and char_count < 260:
            return True

        return False

    def _is_diagram_candidate(
        self,
        *,
        page_number: int,
        text: str,
        image_count: int,
        text_length: int,
    ) -> bool:
        diagram_keywords = ("标注说明", "信息架构", "页面布局", "座椅按摩", "跳转线")
        if any(keyword in text for keyword in diagram_keywords):
            return True

        if self._looks_like_multi_screen_flow_overview(text):
            return True

        if image_count >= 2 and text_length <= 800:
            return True

        return page_number <= 5 and image_count > 0

    def _looks_like_multi_screen_flow_overview(self, text: str) -> bool:
        if not any(keyword in text for keyword in ("QQ Music home", "QQ音乐首页", "QQ⾳乐⾸⻚")):
            return False

        marker_groups = [
            any(marker in text for marker in ("APP list", "06-1", "06-6")),
            any(marker in text for marker in ("向下滑动", "拉到底部")),
            any(marker in text for marker in ("加载失败", "无网络")),
            any(marker in text for marker in ("杜比", "更多杜比单曲", "杜比官方歌单")),
        ]
        return sum(marker_groups) >= 3

    def _looks_like_demo_spec_page(self, text: str) -> bool:
        page_refs = set(re.findall(r"\b\d{2}-\d+\b", text))
        if len(page_refs) < 2:
            return False

        if "【" not in text or "】" not in text:
            return False

        return any(marker in text for marker in ("点击", "上滑", "下滑", "左滑", "右滑", "点击后", "toast"))

    def _extract_demo_region_texts(self, plumber_page: Any) -> dict[str, str]:
        if plumber_page is None:
            return {}

        width = float(getattr(plumber_page, "width", 0) or 0)
        height = float(getattr(plumber_page, "height", 0) or 0)
        if width <= 0 or height <= 0:
            return {}

        specs = {
            "demo_left_text": (width * 0.04, height * 0.12, width * 0.49, height * 0.96),
            "demo_right_text": (width * 0.51, height * 0.12, width * 0.96, height * 0.96),
        }

        extracted: dict[str, str] = {}
        for key, bbox in specs.items():
            try:
                region_page = plumber_page.within_bbox(bbox)
                region_text = region_page.extract_text() or ""
            except Exception:
                region_text = ""
            if region_text.strip():
                extracted[key] = region_text
        return extracted

    def _write_agent_brief(self, bundle: WorkingBundle) -> None:
        brief_path = bundle.bundle_dir / "agent_brief.md"
        lines = self._agent_brief_intro_lines(bundle)
        lines.extend(self._agent_brief_page_checklist(bundle.page_records))
        lines.extend(self._agent_brief_workflow_lines())

        brief_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        bundle.add_artifact(kind="markdown", role="agent-brief", path=brief_path)

    def _agent_brief_intro_lines(self, bundle: WorkingBundle) -> list[str]:
        review_pages = [
            str(record.page_number) for record in bundle.page_records if record.needs_visual_review
        ]
        diagram_pages = [
            str(record.page_number) for record in bundle.page_records if record.diagram_candidate
        ]
        return [
            "# Agent Brief",
            "",
            "## Goal",
            "Use a text-first multimodal workflow: treat extracted text as the canonical body source, and use screenshots only to recover layout, flow, callouts, and visual semantics that text extraction cannot encode reliably.",
            "When a page contains a stable macro diagram such as information architecture, page layout, or an explicit flow, produce Mermaid only as a companion structure rather than a replacement for the text body.",
            "",
            "## Inputs",
            "- source.md: canonical baseline text extraction and wording source",
            "- final.md: current reconstructed markdown draft",
            "- artifacts/pages/: page screenshots and review tiles for multimodal checking",
            "- manifest.json: route, page records, tasks, and diagnostics",
            "",
            "## Required Repair Focus",
            "- Preserve extracted wording and original textual meaning as the primary body content.",
            "- Use page screenshots to restore annotation callouts, page labels, module links, directional arrows, and section boundaries.",
            "- Reconstruct flow or state transitions only when the visual evidence is explicit enough to support them.",
            "- For demo or walkthrough pages, the page-state relationship may be summarized, but callout and rule text should stay as close as possible to the extracted original wording.",
            "- When demo-page OCR is dominated by UI placeholder copy, prefer pane or local region extraction before asking the agent to rewrite the page from screenshots.",
            "- Do not replace readable extracted text with screenshot-only paraphrases.",
            "- Use Mermaid only when the relation graph is unambiguous; otherwise keep image evidence and describe the uncertainty.",
            "- Prefer a mixed output shape of text body + Mermaid companion + visual anchors for stable macro diagram pages.",
            "",
            "## Review Summary",
            f"- Route: {bundle.route_decision.route}",
            f"- Baseline adapter: {bundle.metadata.get('baseline_adapter', 'unknown')}",
            f"- Total pages prepared: {len(bundle.page_records)}",
            f"- Pages flagged for visual review: {', '.join(review_pages) or 'none'}",
            f"- Diagram candidate pages: {', '.join(diagram_pages) or 'none'}",
            "",
            "## Page Checklist",
        ]

    def _agent_brief_page_checklist(self, page_records: list[PageRecord]) -> list[str]:
        if not page_records:
            return ["- No page-level multimodal assets were prepared."]

        lines = [
            "| Page | Text Length | Images | Chars | Visual Review | Diagram Candidate | Screenshot | Tiles | Regions |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        lines.extend(self._agent_brief_page_row(record) for record in page_records)
        return lines

    def _agent_brief_page_row(self, record: PageRecord) -> str:
        screenshot = record.screenshot_path or ""
        tiles = ", ".join(record.tile_paths) if record.tile_paths else ""
        regions = ", ".join(record.region_paths) if record.region_paths else ""
        return (
            "| "
            + " | ".join(
                [
                    str(record.page_number),
                    str(record.text_length or 0),
                    str(record.image_count or 0),
                    str(record.char_count or 0),
                    "yes" if record.needs_visual_review else "no",
                    "yes" if record.diagram_candidate else "no",
                    screenshot,
                    tiles,
                    regions,
                ]
            )
            + " |"
        )

    def _agent_brief_workflow_lines(self) -> list[str]:
        return [
            "",
            "## Repair Workflow",
            "1. Read source.md first and treat it as the canonical wording source.",
            "2. Compare the extracted text with the full-page screenshot for the same page.",
            "3. Open the 2x2 tiles and region crops only to resolve layout, callout, and flow meaning.",
            "4. Rebuild markdown so the text remains primary while the visual evidence repairs structure and semantics.",
            "5. If the screenshot reveals a structure that the text did not encode clearly, add the structure without overwriting the extracted wording.",
            "6. When the recovered structure is a stable macro graph, add a Mermaid companion; when it is not stable, keep screenshots and textual rules instead.",
        ]

    def _ocr_fallback_page(self, pdf_path: Path, page_index: int) -> str:
        """Run RapidOCR on a single page when pdfplumber text extraction returns nothing."""
        ocr_result = self._run_ocr_on_page(pdf_path, page_index)
        if ocr_result is None:
            return ""

        result, _, _ = ocr_result
        return self._join_ocr_text(result)

    def _ensure_ocr_engine(self) -> bool:
        if not self.ocr_enabled:
            return False

        if self._ocr_engine is None:
            try:
                self._ocr_engine = RapidOCR()
            except Exception:
                return False

        return True

    def _run_ocr_on_page(
        self,
        pdf_path: Path,
        page_index: int,
    ) -> tuple[list[Any], int, int] | None:
        if not self._ensure_ocr_engine() or _dependency_error is not None:
            return None

        try:
            doc = pdfium.PdfDocument(str(pdf_path))
            try:
                page = doc[page_index]
                render_scale = scale_for_render_bounds(
                    page.get_width(),
                    page.get_height(),
                    preferred_scale=1.5,
                )
                pil_image = page.render(scale=render_scale).to_pil()
            finally:
                doc.close()
        except Exception:
            return None

        pil_image = scale_image_for_ocr(pil_image)
        img_width, img_height = pil_image.size

        try:
            result, _ = self._ocr_engine(np.array(pil_image))
        except Exception:
            return None

        if not result:
            return None

        return result, img_width, img_height

    def _join_ocr_text(self, result: list[Any]) -> str:
        texts: list[str] = []
        for item in result:
            text = item[1] if len(item) > 1 else ""
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())
        return "\n".join(texts)

    def _ocr_word_items(
        self,
        result: list[Any],
    ) -> list[dict[str, Any]]:
        word_items: list[dict[str, Any]] = []
        for item in result:
            text = item[1] if len(item) > 1 else ""
            if not isinstance(text, str) or not text.strip():
                continue

            try:
                box = item[0]
                x0 = min(point[0] for point in box)
                y0 = min(point[1] for point in box)
                y1 = max(point[1] for point in box)
            except Exception:
                continue

            word_items.append(
                {
                    "text": text.strip(),
                    "x0": x0,
                    "y_center": (y0 + y1) / 2,
                }
            )

        return word_items

    def _ocr_page_word_items(
        self,
        pdf_path: Path,
        page_index: int,
    ) -> tuple[list[dict[str, Any]], int, int] | None:
        ocr_result = self._run_ocr_on_page(pdf_path, page_index)
        if ocr_result is None:
            return None

        result, img_width, img_height = ocr_result
        word_items = self._ocr_word_items(result)
        if len(word_items) < 6:
            return None

        return word_items, img_width, img_height

    # =========================================================================
    # Table Extraction — detect and extract implicit/explicit table structure
    # =========================================================================

    def _extract_page_tables(
        self, plumber_page: Any, pdf_path: Path, page_index: int,
        *, use_ocr: bool = False,
    ) -> list[dict[str, Any]]:
        """Extract tables from a PDF page: explicit (via pdfplumber), implicit (via word clustering), or OCR-based."""
        tables = self._extract_explicit_tables(plumber_page)
        if tables:
            return tables

        tables = self._extract_implicit_tables(plumber_page)
        if tables or not use_ocr:
            return tables

        return self._extract_tables_from_ocr(pdf_path, page_index)

    def _extract_explicit_tables(self, plumber_page: Any) -> list[dict[str, Any]]:
        tables: list[dict[str, Any]] = []
        for idx, table_data in enumerate(plumber_page.extract_tables() or []):
            if not table_data or len(table_data) < 2:
                continue

            rows = self._clean_table_rows(table_data)
            if len(rows) < 2 or max(len(row) for row in rows) < 2:
                continue

            tables.append(
                {
                    "source": "explicit",
                    "table_index": idx,
                    "rows": rows,
                }
            )

        return tables

    def _extract_implicit_tables(self, plumber_page: Any) -> list[dict[str, Any]]:
        words = plumber_page.extract_words(x_tolerance=3, y_tolerance=3) or []
        implicit = self._detect_implicit_table_from_words(words, plumber_page)
        if not implicit:
            return []

        return [
            {
                "source": "implicit",
                "table_index": 0,
                "rows": implicit,
            }
        ]

    def _clean_table_rows(self, table_data: list[list[str | None]]) -> list[list[str]]:
        """Clean table rows: convert None to empty string, strip whitespace, merge multi-line cells."""
        rows: list[list[str]] = []
        for row in table_data:
            cleaned = [(cell or "").strip() for cell in row]
            if any(cell for cell in cleaned):
                rows.append(cleaned)
        return rows

    def _detect_implicit_table_from_words(
        self, words: list[dict], plumber_page: Any
    ) -> list[list[str]] | None:
        """Detect an implicit table by clustering words into rows (y-proximity) and columns (x-ordering)."""
        page_height = float(getattr(plumber_page, "height", 1) or 1)
        page_width = float(plumber_page.width or 1)
        return self._detect_table_rows(
            self._plumber_word_items(words),
            row_threshold=page_height * 0.025,
            x_round=10,
            x_merge=30,
            max_column_distance=(page_width * 0.05) * page_width,
        )

    def _plumber_word_items(self, words: list[dict]) -> list[dict[str, Any]]:
        word_items: list[dict[str, Any]] = []
        for word in words:
            text = str(word.get("text", "") or "").strip()
            if not text:
                continue

            top = float(word.get("top", 0) or 0)
            bottom = float(word.get("bottom", top) or top)
            word_items.append(
                {
                    "text": text,
                    "x0": float(word.get("x0", 0) or 0),
                    "y_center": top + (bottom - top) / 2,
                }
            )

        return word_items

    def _detect_table_rows(
        self,
        word_items: list[dict[str, Any]],
        *,
        row_threshold: float,
        x_round: int,
        x_merge: float,
        max_column_distance: float,
    ) -> list[list[str]] | None:
        if len(word_items) < 6:
            return None

        row_groups = self._group_word_rows(word_items, row_threshold=row_threshold)
        if len(row_groups) < 3:
            return None

        column_boundaries = self._column_boundaries(word_items, x_round=x_round, x_merge=x_merge)
        if len(column_boundaries) < 2:
            return None

        table_rows = self._build_table_rows(
            row_groups,
            column_boundaries,
            max_column_distance=max_column_distance,
        )
        return self._normalize_table_rows(table_rows)

    def _group_word_rows(
        self,
        word_items: list[dict[str, Any]],
        *,
        row_threshold: float,
    ) -> list[list[dict[str, Any]]]:
        if not word_items:
            return []

        words_sorted = sorted(word_items, key=lambda word: (word["y_center"], word["x0"]))
        row_groups: list[list[dict[str, Any]]] = [[words_sorted[0]]]
        current_y_center = words_sorted[0]["y_center"]

        for word in words_sorted[1:]:
            if abs(word["y_center"] - current_y_center) <= row_threshold:
                row_groups[-1].append(word)
                continue

            row_groups.append([word])
            current_y_center = word["y_center"]

        return row_groups

    def _column_boundaries(
        self,
        word_items: list[dict[str, Any]],
        *,
        x_round: int,
        x_merge: float,
    ) -> list[float]:
        if not word_items:
            return []

        round_step = max(x_round, 1)
        all_x = sorted(set(round(word["x0"] / round_step) * round_step for word in word_items))
        if not all_x:
            return []

        boundaries = [all_x[0]]
        for x in all_x[1:]:
            if x - boundaries[-1] > x_merge:
                boundaries.append(x)

        return boundaries

    def _build_table_rows(
        self,
        row_groups: list[list[dict[str, Any]]],
        column_boundaries: list[float],
        *,
        max_column_distance: float,
    ) -> list[list[str]]:
        table_rows: list[list[str]] = []

        for row in row_groups:
            cells = ["" for _ in range(len(column_boundaries))]
            for word in row:
                best_col, best_dist = self._nearest_column(word["x0"], column_boundaries)
                if best_dist <= max_column_distance:
                    if cells[best_col]:
                        cells[best_col] += " " + word["text"]
                    else:
                        cells[best_col] = word["text"]

            while cells and cells[-1] == "":
                cells.pop()

            if any(cells):
                table_rows.append(cells)

        return table_rows

    def _nearest_column(self, x: float, column_boundaries: list[float]) -> tuple[int, float]:
        best_col = 0
        best_dist = float("inf")
        for col_idx, boundary in enumerate(column_boundaries):
            dist = abs(x - boundary)
            if dist < best_dist:
                best_col = col_idx
                best_dist = dist
        return best_col, best_dist

    def _normalize_table_rows(self, table_rows: list[list[str]]) -> list[list[str]] | None:
        if len(table_rows) < 3:
            return None

        max_cols = max(len(row) for row in table_rows)
        if max_cols < 2:
            return None

        return [row + [""] * (max_cols - len(row)) for row in table_rows]

    def _extract_tables_from_ocr(
        self, pdf_path: Path, page_index: int
    ) -> list[dict[str, Any]]:
        """Extract table structure from OCR results when pdfplumber has no word data."""
        ocr_page = self._ocr_page_word_items(pdf_path, page_index)
        if ocr_page is None:
            return []

        word_items, img_width, img_height = ocr_page
        rows = self._detect_table_rows(
            word_items,
            row_threshold=img_height * 0.02,
            x_round=max(int(img_width * 0.05), 100),
            x_merge=int(img_width * 0.03),
            max_column_distance=(img_width * 0.05) * 10,
        )
        if not rows:
            return []

        return [
            {
                "source": "ocr-implicit",
                "table_index": 0,
                "rows": rows,
            }
        ]
