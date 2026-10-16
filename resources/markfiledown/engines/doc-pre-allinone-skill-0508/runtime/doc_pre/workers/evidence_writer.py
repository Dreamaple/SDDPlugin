from __future__ import annotations

import json
from typing import Any

from ..models import PageRecord, WorkingBundle
from ..utils import is_j90k_hvac_document


AGENT_REVIEW_REQUEST_FILENAME = "agent-review-request.json"


class BundleEvidenceWriter:
    def write(self, bundle: WorkingBundle) -> None:
        layout = bundle.layout_paths()
        evidence_dir = layout["evidence"]
        markdown_dir = layout["markdown"]
        is_hvac_document = is_j90k_hvac_document(bundle.source_document.filename, bundle.draft_markdown)

        final_markdown = bundle.final_markdown.rstrip() + "\n"
        body_markdown = final_markdown.split("\n## 附录：页级视觉资产", 1)[0]

        block_catalog = self._build_block_catalog(bundle, body_markdown, final_markdown, is_hvac_document)
        relation_candidates = self._build_relation_candidates(bundle, block_catalog, is_hvac_document)
        review_queue = self._build_visual_review_queue(bundle)
        reading_order_map = self._build_reading_order_map(bundle, is_hvac_document)
        trace_rows = self._build_trace_rows(block_catalog, body_markdown, final_markdown)
        freeze = self._build_freeze(bundle, block_catalog, relation_candidates)
        agent_request = self._build_agent_request(
            bundle,
            block_catalog,
            relation_candidates,
            review_queue,
            reading_order_map,
            trace_rows,
            freeze,
            is_hvac_document,
        )

        file_specs = [
            (
                evidence_dir / "block-catalog.json",
                json.dumps(block_catalog, ensure_ascii=False, indent=2) + "\n",
                "json",
                "evidence-block-catalog",
            ),
            (
                evidence_dir / "relation-candidates.md",
                self._render_relation_candidates_markdown(relation_candidates),
                "markdown",
                "evidence-relation-candidates",
            ),
            (
                evidence_dir / "reading-order-map.json",
                json.dumps(reading_order_map, ensure_ascii=False, indent=2) + "\n",
                "json",
                "evidence-reading-order-map",
            ),
            (
                evidence_dir / "visual-review-queue.json",
                json.dumps(review_queue, ensure_ascii=False, indent=2) + "\n",
                "json",
                "evidence-visual-review-queue",
            ),
            (
                evidence_dir / "visual-review-summary.md",
                self._render_visual_review_summary(bundle, relation_candidates, review_queue),
                "markdown",
                "evidence-visual-review-summary",
            ),
            (
                evidence_dir / "md-input-freeze.json",
                json.dumps(freeze, ensure_ascii=False, indent=2) + "\n",
                "json",
                "evidence-input-freeze",
            ),
            (
                evidence_dir / "freeze-sources.md",
                self._render_freeze_sources(bundle),
                "markdown",
                "evidence-freeze-sources",
            ),
            (
                markdown_dir / "output.md",
                final_markdown,
                "markdown",
                "markdown-output",
            ),
            (
                markdown_dir / "block-md-trace.md",
                self._render_trace_markdown(trace_rows),
                "markdown",
                "markdown-block-trace",
            ),
            (
                markdown_dir / "asset-links.md",
                self._render_asset_links(bundle),
                "markdown",
                "markdown-asset-links",
            ),
            (
                markdown_dir / AGENT_REVIEW_REQUEST_FILENAME,
                json.dumps(agent_request, ensure_ascii=False, indent=2) + "\n",
                "json",
                "markdown-agent-review-request",
            ),
        ]

        written_files: list[str] = []
        for path, content, kind, role in file_specs:
            path.write_text(content, encoding="utf-8")
            bundle.add_artifact(kind=kind, role=role, path=path)
            written_files.append(path.name)

        bundle.metadata["evidence_pack"] = {
            "status": "written",
            "files": written_files,
            "raw_block_total": block_catalog["raw_block_total"],
            "relation_candidate_total": len(relation_candidates),
            "review_queue_total": len(review_queue["reviewed_pages"]),
            "review_status": "pending-agent-exec",
        }

    def _build_block_catalog(
        self,
        bundle: WorkingBundle,
        body_markdown: str,
        full_markdown: str,
        is_hvac_document: bool,
    ) -> dict[str, Any]:
        source_format = bundle.source_document.extension.lower().lstrip(".") or "unknown"
        blocks: list[dict[str, Any]] = [
            {
                "raw_block_key": f"{source_format}:document:body:001",
                "parent_block_key": None,
                "page": None,
                "block_type": "document-body",
                "semantic_role": "document-body",
                "target_section": "document-root",
                "section_heading": "#",
                "source_locator": {"path": bundle.source_document.filename},
                "evidence_sources": ["source.md", "final.md"],
                "status": "in-markdown",
            }
        ]

        for record in bundle.page_records:
            blocks.extend(self._page_blocks(record, body_markdown, full_markdown, is_hvac_document))

        return {
            "document_id": bundle.source_document.document_id,
            "source_format": source_format,
            "raw_block_total": len(blocks),
            "blocks": blocks,
        }

    def _page_blocks(
        self,
        record: PageRecord,
        body_markdown: str,
        full_markdown: str,
        is_hvac_document: bool,
    ) -> list[dict[str, Any]]:
        page_key = f"pdf:p{record.page_number:04d}:page:001"
        target_section = self._target_section(record.page_number, is_hvac_document)
        section_heading = self._section_heading(record.page_number, is_hvac_document)
        page_assets = self._page_assets(record)
        page_status = self._anchor_status(
            page_assets,
            body_markdown,
            full_markdown,
            review_required=record.needs_visual_review,
            section_heading=section_heading,
        )

        blocks: list[dict[str, Any]] = [
            {
                "raw_block_key": page_key,
                "parent_block_key": None,
                "page": record.page_number,
                "block_type": "pdf-page",
                "semantic_role": self._semantic_role(record),
                "target_section": target_section,
                "section_heading": section_heading,
                "source_locator": {"page": record.page_number},
                "evidence_sources": page_assets,
                "status": page_status,
            }
        ]

        excerpt = (record.metadata or {}).get("raw_text_excerpt", "").strip()
        if excerpt:
            blocks.append(
                {
                    "raw_block_key": f"pdf:p{record.page_number:04d}:text:001",
                    "parent_block_key": page_key,
                    "page": record.page_number,
                    "block_type": "paragraph",
                    "semantic_role": "page-text-excerpt",
                    "target_section": target_section,
                    "section_heading": section_heading,
                    "source_locator": {"page": record.page_number, "kind": "raw-text-excerpt"},
                    "evidence_sources": ["source.md"],
                    "status": "in-markdown" if section_heading in body_markdown else page_status,
                }
            )

        if record.screenshot_path:
            blocks.append(
                self._asset_block(
                    page_key=page_key,
                    page_number=record.page_number,
                    raw_block_key=f"pdf:p{record.page_number:04d}:image:screenshot",
                    block_type="image",
                    semantic_role="page-screenshot",
                    target_section=target_section,
                    section_heading=section_heading,
                    evidence_path=record.screenshot_path,
                    body_markdown=body_markdown,
                    full_markdown=full_markdown,
                    review_required=record.needs_visual_review,
                    locator_kind="page-screenshot",
                )
            )

        for tile_path in record.tile_paths:
            label = tile_path.rsplit("tile-", 1)[-1].removesuffix(".png")
            blocks.append(
                self._asset_block(
                    page_key=page_key,
                    page_number=record.page_number,
                    raw_block_key=f"pdf:p{record.page_number:04d}:tile:{label}",
                    block_type="image-tile",
                    semantic_role="page-tile",
                    target_section=target_section,
                    section_heading=section_heading,
                    evidence_path=tile_path,
                    body_markdown=body_markdown,
                    full_markdown=full_markdown,
                    review_required=record.needs_visual_review,
                    locator_kind="page-tile",
                    locator_label=label,
                )
            )

        for region_path in record.region_paths:
            label = region_path.rsplit("region-", 1)[-1].removesuffix(".png")
            blocks.append(
                self._asset_block(
                    page_key=page_key,
                    page_number=record.page_number,
                    raw_block_key=f"pdf:p{record.page_number:04d}:region:{label}",
                    block_type="image-region",
                    semantic_role=self._region_semantic_role(label),
                    target_section=target_section,
                    section_heading=section_heading,
                    evidence_path=region_path,
                    body_markdown=body_markdown,
                    full_markdown=full_markdown,
                    review_required=record.needs_visual_review,
                    locator_kind="page-region",
                    locator_label=label,
                )
            )

        return blocks

    def _asset_block(
        self,
        *,
        page_key: str,
        page_number: int,
        raw_block_key: str,
        block_type: str,
        semantic_role: str,
        target_section: str,
        section_heading: str,
        evidence_path: str,
        body_markdown: str,
        full_markdown: str,
        review_required: bool,
        locator_kind: str,
        locator_label: str | None = None,
    ) -> dict[str, Any]:
        locator: dict[str, Any] = {"page": page_number, "kind": locator_kind, "path": evidence_path}
        if locator_label is not None:
            locator["label"] = locator_label

        return {
            "raw_block_key": raw_block_key,
            "parent_block_key": page_key,
            "page": page_number,
            "block_type": block_type,
            "semantic_role": semantic_role,
            "target_section": target_section,
            "section_heading": section_heading,
            "source_locator": locator,
            "evidence_sources": [evidence_path],
            "status": self._anchor_status(
                [evidence_path],
                body_markdown,
                full_markdown,
                review_required=review_required,
                section_heading=None,
            ),
        }

    def _build_relation_candidates(
        self,
        bundle: WorkingBundle,
        block_catalog: dict[str, Any],
        is_hvac_document: bool,
    ) -> list[dict[str, Any]]:
        blocks = block_catalog["blocks"]
        page_blocks = [block for block in blocks if block["block_type"] == "pdf-page"]
        region_blocks = [block for block in blocks if block["block_type"] == "image-region"]

        candidates: list[dict[str, Any]] = []
        for page_block in page_blocks:
            page_number = int(page_block["page"])
            record = self._page_record(bundle, page_number)
            if record is None or not (record.diagram_candidate or record.needs_visual_review):
                continue
            candidates.append(
                {
                    "relation_key": f"page-{page_number:04d}-overview",
                    "page": page_number,
                    "relation_level": "page",
                    "relation_type": self._page_relation_type(record, is_hvac_document),
                    "anchor_block_keys": [page_block["raw_block_key"]],
                    "objects": [page_block["raw_block_key"]],
                    "evidence_sources": page_block["evidence_sources"],
                    "confidence": self._relation_confidence(record, bonus=0.0),
                    "needs_multimodal_review": record.needs_visual_review,
                }
            )

        for region_block in region_blocks:
            label = str(region_block["source_locator"].get("label", "region"))
            record = self._page_record(bundle, int(region_block["page"]))
            if record is None:
                continue
            candidates.append(
                {
                    "relation_key": f"page-{record.page_number:04d}-region-{label}",
                    "page": record.page_number,
                    "relation_level": "region",
                    "relation_type": self._region_relation_type(label, record.page_number, is_hvac_document),
                    "anchor_block_keys": [region_block["raw_block_key"], region_block["parent_block_key"]],
                    "objects": [region_block["raw_block_key"]],
                    "evidence_sources": region_block["evidence_sources"],
                    "confidence": self._relation_confidence(record, bonus=0.05 if "flow" in label else 0.0),
                    "needs_multimodal_review": record.needs_visual_review,
                }
            )

        return candidates

    def _build_visual_review_queue(self, bundle: WorkingBundle) -> dict[str, Any]:
        pages = []
        for task in bundle.agent_tasks:
            if task.kind != "pdf-page-visual-review":
                continue
            pages.append(
                {
                    "page": task.metadata.get("page"),
                    "description": task.description,
                    "screenshot_path": task.metadata.get("screenshot_path"),
                    "tile_paths": task.metadata.get("tile_paths", []),
                    "region_paths": task.metadata.get("region_paths", []),
                    "diagram_candidate": task.metadata.get("diagram_candidate", False),
                    "status": task.status,
                }
            )

        return {"route": bundle.route_decision.route, "reviewed_pages": pages}

    def _build_reading_order_map(self, bundle: WorkingBundle, is_hvac_document: bool) -> dict[str, Any]:
        return {
            "document_id": bundle.source_document.document_id,
            "pages": [
                {
                    "page": record.page_number,
                    "reading_order": record.page_number,
                    "target_section": self._target_section(record.page_number, is_hvac_document),
                    "screenshot_path": record.screenshot_path,
                    "tile_paths": list(record.tile_paths),
                    "region_paths": list(record.region_paths),
                    "diagram_candidate": record.diagram_candidate,
                }
                for record in bundle.page_records
            ],
        }

    def _build_trace_rows(
        self,
        block_catalog: dict[str, Any],
        body_markdown: str,
        full_markdown: str,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for block in block_catalog["blocks"]:
            body_anchors = self._block_body_anchors(block, body_markdown)
            any_anchors = self._block_any_anchors(block, full_markdown)
            if body_anchors:
                markdown_status = "body-anchored"
            elif any_anchors:
                markdown_status = "appendix-only"
            else:
                markdown_status = "unreferenced"

            rows.append(
                {
                    "raw_block_key": block["raw_block_key"],
                    "parent_block_key": block.get("parent_block_key"),
                    "page": block.get("page"),
                    "block_type": block["block_type"],
                    "semantic_role": block["semantic_role"],
                    "markdown_status": markdown_status,
                    "target_section": block["target_section"],
                    "body_assets": body_anchors,
                }
            )
        return rows

    def _build_freeze(
        self,
        bundle: WorkingBundle,
        block_catalog: dict[str, Any],
        relation_candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        blocks = block_catalog["blocks"]
        heading_tree = [line.strip() for line in bundle.final_markdown.splitlines() if line.startswith("## ")]
        return {
            "raw_block_total": block_catalog["raw_block_total"],
            "in_markdown_block_total": sum(1 for block in blocks if block["status"] == "in-markdown"),
            "evidence_only_block_total": sum(1 for block in blocks if block["status"] == "evidence-only"),
            "needs_clarification_total": sum(
                1 for block in blocks if block["status"] == "needs-clarification"
            ),
            "heading_tree": heading_tree,
            "figure_total": sum(1 for artifact in bundle.artifacts if artifact.kind == "image"),
            "table_total": len(bundle.table_records),
            "chart_total": 0,
            "visual_review_required_pages": [
                record.page_number for record in bundle.page_records if record.needs_visual_review
            ],
            "orphan_blocks": [
                block["raw_block_key"] for block in blocks if block["status"] == "needs-clarification"
            ],
            "unresolved_relation_candidates": [
                candidate["relation_key"]
                for candidate in relation_candidates
                if candidate["needs_multimodal_review"]
            ],
        }

    def _build_agent_request(
        self,
        bundle: WorkingBundle,
        block_catalog: dict[str, Any],
        relation_candidates: list[dict[str, Any]],
        review_queue: dict[str, Any],
        reading_order_map: dict[str, Any],
        trace_rows: list[dict[str, Any]],
        freeze: dict[str, Any],
        is_hvac_document: bool,
    ) -> dict[str, Any]:
        return {
            "document_id": bundle.source_document.document_id,
            "route": bundle.route_decision.route,
            "special_review_profile": "j90k-hvac" if is_hvac_document else "generic",
            "reconstruction_contract": {
                "strategy": "text-first-multimodal",
                "text_primary_sources": [
                    "source.md",
                    "page-level extracted text",
                ],
                "visual_secondary_sources": [
                    "artifacts/pages/*.png",
                    "artifacts/pages/*tile*.png",
                    "artifacts/regions/*.png",
                ],
                "rules": [
                    "Preserve extracted wording as the main body text whenever it is readable.",
                    "Use screenshots only to recover structure, page semantics, callouts, arrows, and layout relationships.",
                    "For explicit macro diagrams such as information architecture, page layout, or stable flow charts, add Mermaid only as a companion to the text-first body.",
                    "For demo or walkthrough pages, page-state relationships may be summarized, but explanatory callouts and rule text should quote extracted original wording whenever available.",
                    "If demo-page OCR is polluted by UI placeholder copy, prefer local pane or region extraction before escalating to heavier screenshot-only rewriting.",
                    "Do not replace readable extracted text with screenshot-only paraphrases.",
                    "If visual evidence and extracted text conflict, preserve the text and record the conflict for review.",
                    "If the relation graph is ambiguous or depends on screenshot-only state branches, keep visual anchors instead of forcing Mermaid.",
                ],
            },
            "source_document": {
                "filename": bundle.source_document.filename,
                "extension": bundle.source_document.extension,
            },
            "paths": {
                "source_markdown": "source.md",
                "final_markdown": "final.md",
                "block_catalog": "evidence/block-catalog.json",
                "relation_candidates": "evidence/relation-candidates.md",
                "reading_order_map": "evidence/reading-order-map.json",
                "visual_review_queue": "evidence/visual-review-queue.json",
                "freeze": "evidence/md-input-freeze.json",
                "trace": "markdown/block-md-trace.md",
            },
            "page_records": [
                {
                    "page": record.page_number,
                    "needs_visual_review": record.needs_visual_review,
                    "diagram_candidate": record.diagram_candidate,
                    "target_section": self._target_section(record.page_number, is_hvac_document),
                    "assets": self._page_assets(record),
                }
                for record in bundle.page_records
            ],
            "block_catalog": block_catalog,
            "relation_candidates": relation_candidates,
            "visual_review_queue": review_queue,
            "reading_order_map": reading_order_map,
            "trace_rows": trace_rows,
            "freeze": freeze,
        }

    def _render_relation_candidates_markdown(
        self, relation_candidates: list[dict[str, Any]]
    ) -> str:
        lines = [
            "# Relation Candidates",
            "",
            "| Key | Page | Level | Type | Confidence | Needs Multimodal Review | Anchor Blocks | Evidence |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for candidate in relation_candidates:
            lines.append(
                "| {key} | {page} | {level} | {type} | {confidence:.2f} | {review} | {anchors} | {evidence} |".format(
                    key=candidate["relation_key"],
                    page=candidate["page"],
                    level=candidate["relation_level"],
                    type=candidate["relation_type"],
                    confidence=candidate["confidence"],
                    review="yes" if candidate["needs_multimodal_review"] else "no",
                    anchors=", ".join(candidate["anchor_block_keys"]),
                    evidence=", ".join(candidate["evidence_sources"]),
                )
            )
        if len(lines) == 4:
            lines.append("| none | - | - | none | 0.00 | no | none | none |")
        return "\n".join(lines).rstrip() + "\n"

    def _render_visual_review_summary(
        self,
        bundle: WorkingBundle,
        relation_candidates: list[dict[str, Any]],
        review_queue: dict[str, Any],
    ) -> str:
        lines = [
            "# Visual Review Summary",
            "",
            f"- Route: {bundle.route_decision.route}",
            f"- Review queue pages: {len(review_queue['reviewed_pages'])}",
            f"- Relation candidates: {len(relation_candidates)}",
            "",
            "## Review Queue",
        ]
        for page in review_queue["reviewed_pages"]:
            lines.append(
                f"- Page {page['page']}: diagram_candidate={'yes' if page['diagram_candidate'] else 'no'}; regions={', '.join(page['region_paths']) or 'none'}"
            )
        if not review_queue["reviewed_pages"]:
            lines.append("- none")
        return "\n".join(lines).rstrip() + "\n"

    def _render_freeze_sources(self, bundle: WorkingBundle) -> str:
        lines = [
            "# Freeze Sources",
            "",
            f"- source document: {bundle.source_document.filename}",
            "- source markdown: source.md",
            "- final markdown: final.md",
            "- manifest: manifest.json",
        ]
        for record in bundle.page_records:
            if record.screenshot_path:
                lines.append(f"- page {record.page_number} screenshot: {record.screenshot_path}")
        return "\n".join(lines).rstrip() + "\n"

    def _render_trace_markdown(self, trace_rows: list[dict[str, Any]]) -> str:
        lines = [
            "# Block Markdown Trace",
            "",
            "| Block | Parent | Page | Type | Role | Markdown Status | Target Section | Body Assets |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for row in trace_rows:
            lines.append(
                "| {block} | {parent} | {page} | {block_type} | {role} | {status} | {section} | {assets} |".format(
                    block=row["raw_block_key"],
                    parent=row["parent_block_key"] or "-",
                    page=row["page"] if row["page"] is not None else "-",
                    block_type=row["block_type"],
                    role=row["semantic_role"],
                    status=row["markdown_status"],
                    section=row["target_section"],
                    assets=", ".join(row["body_assets"]) or "none",
                )
            )
        return "\n".join(lines).rstrip() + "\n"

    def _render_asset_links(self, bundle: WorkingBundle) -> str:
        lines = ["# Asset Links", ""]
        for record in bundle.page_records:
            lines.append(f"## Page {record.page_number:02d}")
            if record.screenshot_path:
                lines.append(f"- Screenshot: {record.screenshot_path}")
            if record.tile_paths:
                lines.append(f"- Tiles: {', '.join(record.tile_paths)}")
            if record.region_paths:
                lines.append(f"- Regions: {', '.join(record.region_paths)}")
            lines.append("")
        if len(lines) == 2:
            lines.append("- none")
        return "\n".join(lines).rstrip() + "\n"

    def _anchor_status(
        self,
        evidence_sources: list[str],
        body_markdown: str,
        full_markdown: str,
        *,
        review_required: bool,
        section_heading: str | None,
    ) -> str:
        if any(source in body_markdown for source in evidence_sources):
            return "in-markdown"
        if section_heading and section_heading in body_markdown:
            return "in-markdown"
        if any(source in full_markdown for source in evidence_sources):
            return "evidence-only"
        if section_heading and section_heading in full_markdown:
            return "evidence-only"
        return "needs-clarification" if review_required else "evidence-only"

    def _block_body_anchors(self, block: dict[str, Any], body_markdown: str) -> list[str]:
        anchors = [source for source in block["evidence_sources"] if source in body_markdown]
        if self._block_uses_section_heading(block) and block.get("section_heading") and block["section_heading"] in body_markdown:
            anchors.append(block["section_heading"])
        return anchors

    def _block_any_anchors(self, block: dict[str, Any], full_markdown: str) -> list[str]:
        anchors = [source for source in block["evidence_sources"] if source in full_markdown]
        if self._block_uses_section_heading(block) and block.get("section_heading") and block["section_heading"] in full_markdown:
            anchors.append(block["section_heading"])
        return anchors

    def _block_uses_section_heading(self, block: dict[str, Any]) -> bool:
        return block["block_type"] in {"document-body", "pdf-page", "paragraph"}

    def _page_assets(self, record: PageRecord) -> list[str]:
        assets: list[str] = []
        if record.screenshot_path:
            assets.append(record.screenshot_path)
        assets.extend(record.tile_paths)
        assets.extend(record.region_paths)
        return assets

    def _page_record(self, bundle: WorkingBundle, page_number: int) -> PageRecord | None:
        for record in bundle.page_records:
            if record.page_number == page_number:
                return record
        return None

    def _semantic_role(self, record: PageRecord) -> str:
        if record.diagram_candidate:
            return "diagram-candidate-page"
        if record.needs_visual_review:
            return "visual-review-page"
        return "supporting-page"

    def _page_relation_type(self, record: PageRecord, is_hvac_document: bool) -> str:
        if is_hvac_document and record.page_number == 9:
            return "seat-flow-overview"
        if is_hvac_document and record.page_number == 5:
            return "module-link-graph"
        if is_hvac_document and record.page_number == 6:
            return "layout-zones"
        if is_hvac_document and record.page_number == 4:
            return "annotation-flow"
        if record.diagram_candidate:
            return "diagram-page"
        return "visual-structure"

    def _region_semantic_role(self, label: str) -> str:
        if label == "massage-panel":
            return "seat-massage-control-panel"
        if label == "flow-left":
            return "seat-flow-left-branch"
        if label == "flow-right":
            return "seat-flow-right-branch"
        if label == "diagram-focus":
            return "diagram-focus-region"
        return f"region-{label}"

    def _region_relation_type(self, label: str, page_number: int, is_hvac_document: bool) -> str:
        if is_hvac_document and label == "massage-panel":
            return "configuration-panel"
        if is_hvac_document and label == "flow-left":
            return "state-transition-left-branch"
        if is_hvac_document and label == "flow-right":
            return "state-transition-right-branch"
        if is_hvac_document and label == "diagram-focus" and page_number == 9:
            return "seat-flow-focus"
        if label == "diagram-focus":
            return "diagram-focus"
        if label == "main":
            return "page-main-region"
        return "region-structure"

    def _relation_confidence(self, record: PageRecord, *, bonus: float) -> float:
        confidence = 0.55
        if record.diagram_candidate:
            confidence += 0.20
        if len(record.region_paths) >= 2:
            confidence += 0.10
        if record.page_number == 9:
            confidence += 0.05
        confidence += bonus
        return min(confidence, 0.98)

    def _target_section(self, page_number: int, is_hvac_document: bool) -> str:
        if not is_hvac_document:
            return f"page-{page_number:04d}"

        section_map = {
            1: "document-overview",
            2: "table-of-contents",
            3: "1. 变更记录",
            4: "2. 标注说明与跳转线语义",
            5: "3. 信息架构与模块指向",
            6: "4. 页面布局分区",
            7: "5. 信息详情与主界面控件",
            8: "6. 空调设置与自动化策略",
            9: "7. 座椅控制与按摩流程",
            10: "closing-page",
        }
        return section_map.get(page_number, "appendix")

    def _section_heading(self, page_number: int, is_hvac_document: bool) -> str:
        if not is_hvac_document:
            return f"## Page {page_number}"

        heading_map = {
            1: "## 文档概览",
            2: "## 目录页快照",
            3: "## 1. 变更记录",
            4: "## 2. 标注说明与跳转线语义",
            5: "## 3. 信息架构与模块指向",
            6: "## 4. 页面布局分区",
            7: "## 5. 信息详情与主界面控件",
            8: "## 6. 空调设置与自动化策略",
            9: "## 7. 座椅控制与按摩流程",
            10: "## 结束页与发布尾注",
        }
        return heading_map.get(page_number, "")
