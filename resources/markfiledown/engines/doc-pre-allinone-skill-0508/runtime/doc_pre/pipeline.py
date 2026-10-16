from __future__ import annotations

import json
from pathlib import Path

from .adapters.legacy_output import LegacyOutputAdapter
from .adapters.local_file import LocalFileInputAdapter
from .adapters.markitdown_adapter import MarkItDownBaselineAdapter
from .models import WorkingBundle
from .repair import PDFVisualRepairAdapter
from .workers import (
    AgentCorrectionWorker,
    AgentReviewExecutor,
    BundleEvidenceWriter,
    PDFMultimodalPreparationWorker,
    PDFQualityGateWorker,
)
from .workers.multimodal_reconstruction import MultimodalReconstructionWorker


class DocumentPipeline:
    # Routes that trigger full PDF multimodal processing.
    PDF_MULTIMODAL_ROUTES = frozenset({
        "simple_text_pdf_path",
        "mixed_pdf_path",
        "complex_visual_pdf_path",
        "pure_image_pdf_path",
    })

    def __init__(
        self,
        *,
        input_adapter: LocalFileInputAdapter | None = None,
        baseline_adapter: MarkItDownBaselineAdapter | None = None,
        output_adapter: LegacyOutputAdapter | None = None,
        pdf_preparation_worker: PDFMultimodalPreparationWorker | None = None,
        pdf_repair_adapter: PDFVisualRepairAdapter | None = None,
        evidence_writer: BundleEvidenceWriter | None = None,
        agent_review_executor: AgentReviewExecutor | None = None,
        pdf_agent_readback_executor: AgentReviewExecutor | None = None,
        multimodal_reconstruction_worker: MultimodalReconstructionWorker | None = None,
        quality_gate_worker: PDFQualityGateWorker | None = None,
        minimal: bool = False,
    ):
        self.input_adapter = input_adapter or LocalFileInputAdapter()
        self.baseline_adapter = baseline_adapter or MarkItDownBaselineAdapter()
        self.output_adapter = output_adapter or LegacyOutputAdapter()
        self.pdf_preparation_worker = (
            pdf_preparation_worker or PDFMultimodalPreparationWorker()
        )
        self.pdf_repair_adapter = pdf_repair_adapter or PDFVisualRepairAdapter()
        self.evidence_writer = evidence_writer or BundleEvidenceWriter()
        self.agent_review_executor = (
            agent_review_executor
            or pdf_agent_readback_executor
            or AgentReviewExecutor()
        )
        self.pdf_agent_readback_executor = self.agent_review_executor
        self.multimodal_reconstruction_worker = (
            multimodal_reconstruction_worker
            or MultimodalReconstructionWorker()
        )
        self.agent_correction_worker = AgentCorrectionWorker()
        self.quality_gate_worker = quality_gate_worker or PDFQualityGateWorker()
        self.minimal = minimal

    def run_local(
        self, file_path: str | Path, output_root: str | Path
    ) -> WorkingBundle:
        bundle = self.input_adapter.load(file_path, output_root)
        self._seed_agent_tasks(bundle)

        bundle.draft_markdown = self.baseline_adapter.extract(bundle).strip()
        self._run_multimodal_preparation(bundle)
        self._run_multimodal_reconstruction(bundle)
        bundle.final_markdown = self._build_final_markdown(bundle)
        self._run_agent_correction(bundle)
        self._run_quality_gate_with_repair(bundle)
        bundle.metadata["bundle_version"] = "0.2.0"

        self._write_bundle_outputs(bundle)
        if not self.minimal:
            self.output_adapter.write(bundle)
        self._rewrite_manifest(bundle)
        return bundle

    def _run_multimodal_reconstruction(self, bundle: WorkingBundle) -> None:
        """OCR-based tile extraction and structural Markdown reconstruction."""
        route = bundle.route_decision.route
        if route not in self.PDF_MULTIMODAL_ROUTES:
            return

        # Use schema-first multimodal reconstruction for all visual PDF routes.
        # pure_image_pdf_path relies on OCR/vision most heavily; the others still
        # benefit from page-schema extraction for callouts, hierarchy, and layout.
        self.multimodal_reconstruction_worker.reconstruct(bundle)
        recon = bundle.metadata.get("multimodal_reconstruction")
        if recon and recon.get("status") == "completed":
            bundle.metadata["reconstruction_source"] = "schema-first-multimodal"

    def _seed_agent_tasks(self, bundle: WorkingBundle) -> None:
        route = bundle.route_decision.route

        if route in self.PDF_MULTIMODAL_ROUTES:
            bundle.add_agent_task(
                kind="pdf-review",
                description="Review routed PDF pages and decide whether screenshots, crops, or table reconstruction are required.",
            )

        if route == "presentation_pipeline":
            bundle.add_agent_task(
                kind="diagram-review",
                description="Inspect slide diagrams and decide whether Mermaid reconstruction is worthwhile.",
            )

        if route == "office_document_pipeline":
            bundle.add_agent_task(
                kind="image-review",
                description="Inspect embedded images and decide whether image export or diagram recovery is required.",
            )

        if route == "spreadsheet_pipeline":
            bundle.add_agent_task(
                kind="table-preview-review",
                description="Review whether large sheets should stay as CSV-only or receive a small Markdown preview.",
            )

    def _run_multimodal_preparation(self, bundle: WorkingBundle) -> None:
        route = bundle.route_decision.route
        if route in self.PDF_MULTIMODAL_ROUTES:
            self.pdf_preparation_worker.prepare(bundle)

    def _build_final_markdown(self, bundle: WorkingBundle) -> str:
        route = bundle.route_decision.route
        if route not in self.PDF_MULTIMODAL_ROUTES:
            return bundle.draft_markdown

        # pure_image_pdf_path: skip text-first repair (OCR fragments + table heuristic
        # produce garbage). Just use the baseline draft as-is. The agent can review
        # and fix it using the screenshots.
        if route == "pure_image_pdf_path":
            return bundle.draft_markdown

        return self.pdf_repair_adapter.repair(bundle).strip()

    def _run_agent_correction(self, bundle: WorkingBundle) -> None:
        """Stage 4: Write a multi-modal correction request for the agent to verify final.md.

        This runs for all PDF multimodal routes. The agent reads page screenshots
        alongside final.md and source.md, identifies missing/incorrect content,
        and directly corrects final.md.
        """
        route = bundle.route_decision.route
        if route not in self.PDF_MULTIMODAL_ROUTES:
            return

        if self.minimal:
            return

        self.agent_correction_worker.correct(bundle)

    def _run_quality_gate_with_repair(self, bundle: WorkingBundle) -> None:
        """Stage 5: Quality Gate — multimodal final verification with repair loop.

        After Stage 4 correction, the agent reads page screenshots alongside
        final.md to verify hierarchy, callout mapping, flow direction, and
        spatial zones. If the verdict is 'fail', a targeted repair round is
        triggered (up to max_repair_rounds, default 2).
        """
        route = bundle.route_decision.route
        if route not in self.PDF_MULTIMODAL_ROUTES:
            return

        if self.minimal:
            return

        max_rounds = 2
        bundle.metadata.setdefault("quality_gate", {})["repair_rounds"] = 0

        for round_idx in range(max_rounds + 1):
            self.quality_gate_worker.verify(bundle)
            # Agent processes quality-gate-request.json → writes quality-gate-report.json

            report_path = bundle.bundle_dir / "quality-gate-report.json"
            if not report_path.exists():
                bundle.metadata["quality_gate"]["status"] = "skipped-no-report"
                return

            try:
                import json
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except Exception:
                bundle.metadata["quality_gate"]["status"] = "failed-to-read-report"
                return

            verdict = report.get("overall_verdict", "fail")
            bundle.metadata["quality_gate"]["verdict"] = verdict
            bundle.metadata["quality_gate"]["repair_rounds"] = round_idx + 1

            if verdict == "pass":
                bundle.metadata["quality_gate"]["status"] = "passed"
                return

            if verdict == "pass-with-notes":
                bundle.metadata["quality_gate"]["status"] = "passed-with-notes"
                return

            # verdict == "fail" — attempt targeted repair
            if round_idx >= max_rounds - 1:
                bundle.metadata["quality_gate"]["status"] = "failed-max-rounds"
                bundle.metadata["quality_gate"]["max_repair_rounds_reached"] = True
                return

            # Feed fix_suggestions back into correction for another round
            self._apply_quality_gate_fix_suggestions(bundle, report)
            # Re-run agent correction with the fix suggestions
            self.agent_correction_worker.correct(bundle)
            # The agent processes the new correction request, fixing final.md

    def _apply_quality_gate_fix_suggestions(
        self, bundle: WorkingBundle, report: dict
    ) -> None:
        """Extract fix suggestions from the quality gate report and write them
        as a targeted correction request for the agent.
        """
        suggestions: list[str] = []
        for page_report in report.get("pages", []):
            if page_report.get("verdict") == "fail":
                for check in page_report.get("checks", []):
                    if check.get("status") == "fail":
                        page_num = page_report.get("page_number", "?")
                        suggestions.append(
                            f"[Page {page_num}] {check.get('description', '')}: "
                            f"{page_report.get('fix_suggestion', '')}"
                        )

        if not suggestions:
            return

        # Write a targeted correction request with the fix suggestions
        fix_request = bundle.bundle_dir / "quality-gate-fix-request.json"
        import json
        fix_request.write_text(
            json.dumps(
                {
                    "kind": "quality-gate-fix-request",
                    "version": "1.0",
                    "fix_suggestions": suggestions,
                    "instruction": (
                        "根据 Stage 5 Quality Gate 的校验结果，对 final.md 进行定点修复。\n"
                        "每个建议说明了哪个页面的哪个检查项失败，以及需要做什么修改。\n"
                        "修复后用 <!-- quality-gate-fixed: 原因 --> 标记修改处。\n"
                        "完成后删除本文件。"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def _write_bundle_outputs(self, bundle: WorkingBundle) -> None:
        bundle.ensure_layout()

        source_path = bundle.bundle_dir / "source.md"
        final_path = bundle.bundle_dir / "final.md"
        manifest_path = bundle.bundle_dir / "manifest.json"
        diagnostics_path = bundle.layout_paths()["diagnostics"] / "route.txt"

        source_path.write_text(bundle.draft_markdown.rstrip() + "\n", encoding="utf-8")
        final_path.write_text(bundle.final_markdown.rstrip() + "\n", encoding="utf-8")
        diagnostics_path.write_text(
            "\n".join(
                [
                    f"route={bundle.route_decision.route}",
                    f"confidence={bundle.route_decision.confidence}",
                    f"rationale={bundle.route_decision.rationale}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        bundle.add_artifact(kind="markdown", role="draft-markdown", path=source_path)
        bundle.add_artifact(kind="markdown", role="final-markdown", path=final_path)
        bundle.add_artifact(kind="text", role="route-diagnostic", path=diagnostics_path)

        if not self.minimal:
            self.evidence_writer.write(bundle)
            self.agent_review_executor.execute(bundle)

        self._write_manifest(bundle, manifest_path)

    def _rewrite_manifest(self, bundle: WorkingBundle) -> None:
        self._write_manifest(bundle, bundle.bundle_dir / "manifest.json")

    def _write_manifest(self, bundle: WorkingBundle, manifest_path: Path) -> None:
        manifest_path.write_text(
            json.dumps(bundle.manifest(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
