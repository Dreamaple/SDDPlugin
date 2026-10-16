from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from ..models import WorkingBundle
from ..utils import is_j90k_hvac_document


AGENT_REVIEW_REQUEST_FILENAME = "agent-review-request.json"
AGENT_REVIEW_RESPONSE_FILENAME = "agent-review-response.json"
AGENT_REVIEW_REPORT_FILENAME = "agent-review-report.json"
AGENT_REVIEW_SUMMARY_FILENAME = "agent-review-summary.md"


PDF_ROUTES = {
    "simple_text_pdf_path",
    "mixed_pdf_path",
    "complex_visual_pdf_path",
}


class AgentReviewExecutor:
    def __init__(
        self,
        *,
        enabled: bool = True,
        mode: str = "builtin",
        external_command: str | None = None,
    ) -> None:
        self.enabled = enabled
        self.mode = mode
        self.external_command = (
            external_command
            or os.getenv("DOC_PRE_AGENT_COMMAND")
            or os.getenv("DOC_PRE_PDF_AGENT_COMMAND")
        )

    def execute(self, bundle: WorkingBundle) -> None:
        layout = bundle.layout_paths()
        markdown_dir = layout["markdown"]
        request_path = markdown_dir / AGENT_REVIEW_REQUEST_FILENAME
        if not request_path.exists():
            bundle.add_diagnostic("Agent review skipped because request file was not created.")
            return

        request = json.loads(request_path.read_text(encoding="utf-8"))
        response_path = markdown_dir / AGENT_REVIEW_RESPONSE_FILENAME
        route = bundle.route_decision.route

        if route not in PDF_ROUTES:
            response = {
                "backend": "not-applicable-non-pdf",
                "status": "skipped",
                "checked_pages": 0,
                "checked_blocks": 0,
                "body_anchored_pages": [],
                "appendix_only_pages": [],
                "reviewed_relation_candidates": [],
                "findings": [],
            }
            response_path.write_text(
                json.dumps(response, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        elif not self.enabled:
            response = {
                "backend": "disabled",
                "status": "skipped",
                "checked_pages": 0,
                "checked_blocks": 0,
                "body_anchored_pages": [],
                "appendix_only_pages": [],
                "reviewed_relation_candidates": [],
                "findings": [],
            }
            response_path.write_text(
                json.dumps(response, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        elif self.mode == "external-command" and self.external_command:
            response = self._run_external_command(request_path, response_path)
        else:
            response = self._run_builtin_backend(request)
            response_path.write_text(
                json.dumps(response, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        bundle.add_artifact(
            kind="json",
            role="markdown-agent-review-response",
            path=response_path,
        )

        review_report = self._normalize_review_report(response)
        back_edge_decision = self._build_back_edge_decision(review_report)
        integrity_metrics = self._build_integrity_metrics(request, review_report)

        file_specs = [
            (
                markdown_dir / AGENT_REVIEW_REPORT_FILENAME,
                json.dumps(review_report, ensure_ascii=False, indent=2) + "\n",
                "json",
                "markdown-agent-review-report",
            ),
            (
                markdown_dir / AGENT_REVIEW_SUMMARY_FILENAME,
                self._render_agent_review_summary(review_report),
                "markdown",
                "markdown-agent-review-summary",
            ),
            (
                markdown_dir / "markdown-qv-report.md",
                self._render_quality_valve_report(request["freeze"], request["trace_rows"], review_report),
                "markdown",
                "markdown-qv-report",
            ),
            (
                markdown_dir / "back-edge-decision.json",
                json.dumps(back_edge_decision, ensure_ascii=False, indent=2) + "\n",
                "json",
                "markdown-back-edge-decision",
            ),
            (
                bundle.bundle_dir / "markdown-integrity-report.md",
                self._render_integrity_report(integrity_metrics, review_report),
                "markdown",
                "markdown-integrity-report",
            ),
            (
                bundle.bundle_dir / "integrity-metrics.json",
                json.dumps(integrity_metrics, ensure_ascii=False, indent=2) + "\n",
                "json",
                "integrity-metrics",
            ),
        ]

        for path, content, kind, role in file_specs:
            path.write_text(content, encoding="utf-8")
            bundle.add_artifact(kind=kind, role=role, path=path)

        bundle.metadata["agent_exec"] = {
            "mode": self.mode,
            "backend": review_report.get("backend", self.mode),
            "status": review_report["status"],
            "findings": len(review_report["findings"]),
        }
        if "evidence_pack" in bundle.metadata:
            bundle.metadata["evidence_pack"]["review_status"] = review_report["status"]

    def _run_external_command(
        self,
        request_path: Path,
        response_path: Path,
    ) -> dict[str, Any]:
        command = self.external_command or ""
        request_arg = str(request_path)
        response_arg = str(response_path)

        if "{request}" in command or "{response}" in command:
            command_line = command.format(request=request_arg, response=response_arg)
        else:
            command_line = f'{command} "{request_arg}" "{response_arg}"'

        completed = subprocess.run(
            command_line,
            shell=True,
            text=True,
            capture_output=True,
            check=False,
        )

        if completed.returncode != 0:
            return {
                "backend": "external-command",
                "status": "needs-human-review",
                "checked_pages": 0,
                "checked_blocks": 0,
                "body_anchored_pages": [],
                "appendix_only_pages": [],
                "findings": [
                    {
                        "page": None,
                        "severity": "error",
                        "issue": "agent-command-failed",
                        "detail": completed.stderr.strip() or completed.stdout.strip() or "External agent command failed.",
                    }
                ],
            }

        if not response_path.exists():
            return {
                "backend": "external-command",
                "status": "needs-human-review",
                "checked_pages": 0,
                "checked_blocks": 0,
                "body_anchored_pages": [],
                "appendix_only_pages": [],
                "findings": [
                    {
                        "page": None,
                        "severity": "error",
                        "issue": "agent-command-missing-response",
                        "detail": "External agent command completed without producing a response file.",
                    }
                ],
            }

        return json.loads(response_path.read_text(encoding="utf-8"))

    def _run_builtin_backend(self, request: dict[str, Any]) -> dict[str, Any]:
        blocks = request["block_catalog"]["blocks"]
        trace_rows = request["trace_rows"]
        page_records = request["page_records"]
        relation_candidates = request["relation_candidates"]
        review_profile = request.get("special_review_profile")
        is_hvac_document = review_profile == "j90k-hvac"
        if review_profile is None:
            is_hvac_document = is_j90k_hvac_document(
                request.get("source_document", {}).get("filename", "")
            )

        row_by_key = {row["raw_block_key"]: row for row in trace_rows}
        page_blocks = [block for block in blocks if block["block_type"] == "pdf-page"]
        page_rows = [row_by_key[block["raw_block_key"]] for block in page_blocks if block["raw_block_key"] in row_by_key]

        findings: list[dict[str, Any]] = []
        for page in page_records:
            page_key = f"pdf:p{page['page']:04d}:page:001"
            page_row = row_by_key.get(page_key)
            if page.get("needs_visual_review") and page_row and page_row["markdown_status"] != "body-anchored":
                findings.append(
                    {
                        "page": page["page"],
                        "severity": "warning",
                        "issue": "visual-review-page-not-anchored-in-body",
                        "detail": "Page requires visual review but the page-level anchor is not present in the body narrative.",
                    }
                )

            if is_hvac_document and page["page"] == 9:
                for region_label in ("massage-panel", "flow-left", "flow-right"):
                    block_key = f"pdf:p0009:region:{region_label}"
                    region_row = row_by_key.get(block_key)
                    if region_row is None or region_row["markdown_status"] != "body-anchored":
                        findings.append(
                            {
                                "page": 9,
                                "severity": "warning",
                                "issue": "seat-flow-anchor-gap",
                                "detail": f"Page 9 is missing a body anchor for region `{region_label}`.",
                            }
                        )

        for candidate in relation_candidates:
            if not is_hvac_document:
                continue
            if not candidate["needs_multimodal_review"]:
                continue
            if candidate["relation_level"] != "region":
                continue
            if candidate["relation_type"] not in {
                "configuration-panel",
                "state-transition-left-branch",
                "state-transition-right-branch",
            }:
                continue
            anchor_rows = [row_by_key.get(block_key) for block_key in candidate["anchor_block_keys"]]
            if not any(row and row["markdown_status"] == "body-anchored" for row in anchor_rows):
                findings.append(
                    {
                        "page": candidate["page"],
                        "severity": "warning",
                        "issue": "relation-candidate-not-anchored",
                        "detail": f"Relation candidate `{candidate['relation_key']}` has no body-anchored evidence block.",
                    }
                )

        deduped_findings: list[dict[str, Any]] = []
        seen = set()
        for finding in findings:
            key = (finding["page"], finding["issue"], finding["detail"])
            if key in seen:
                continue
            seen.add(key)
            deduped_findings.append(finding)

        status = "pass" if not deduped_findings else "needs-repair"
        return {
            "backend": "builtin-rule-agent",
            "status": status,
            "checked_pages": len(page_records),
            "checked_blocks": len(blocks),
            "body_anchored_pages": [row["page"] for row in page_rows if row["markdown_status"] == "body-anchored"],
            "appendix_only_pages": [row["page"] for row in page_rows if row["markdown_status"] == "appendix-only"],
            "reviewed_relation_candidates": [candidate["relation_key"] for candidate in relation_candidates],
            "findings": deduped_findings,
        }

    def _normalize_review_report(self, response: dict[str, Any]) -> dict[str, Any]:
        return {
            "backend": response.get("backend", self.mode),
            "status": response.get("status", "needs-human-review"),
            "checked_pages": int(response.get("checked_pages", 0)),
            "checked_blocks": int(response.get("checked_blocks", 0)),
            "body_anchored_pages": list(response.get("body_anchored_pages", [])),
            "appendix_only_pages": list(response.get("appendix_only_pages", [])),
            "findings": list(response.get("findings", [])),
            "reviewed_relation_candidates": list(response.get("reviewed_relation_candidates", [])),
        }

    def _build_back_edge_decision(self, review_report: dict[str, Any]) -> dict[str, Any]:
        if review_report["status"] in {"pass", "skipped"}:
            return {
                "decision": "complete",
                "target_step": None,
                "reasons": ["No blocking review findings remain."],
            }

        return {
            "decision": "return-to-agent-exec",
            "target_step": "3.5",
            "reasons": [finding["issue"] for finding in review_report["findings"]],
        }

    def _build_integrity_metrics(
        self,
        request: dict[str, Any],
        review_report: dict[str, Any],
    ) -> dict[str, Any]:
        trace_rows = request["trace_rows"]
        page_rows = [
            row
            for row in trace_rows
            if row["block_type"] == "pdf-page"
        ]
        return {
            "document_id": request["document_id"],
            "route": request["route"],
            "raw_block_total": request["freeze"]["raw_block_total"],
            "body_anchored_page_total": sum(
                1 for row in page_rows if row["markdown_status"] == "body-anchored"
            ),
            "appendix_only_page_total": sum(
                1 for row in page_rows if row["markdown_status"] == "appendix-only"
            ),
            "unreferenced_page_total": sum(
                1 for row in page_rows if row["markdown_status"] == "unreferenced"
            ),
            "relation_candidate_total": len(request["relation_candidates"]),
            "review_status": review_report["status"],
            "finding_total": len(review_report["findings"]),
        }

    def _render_agent_review_summary(self, review_report: dict[str, Any]) -> str:
        lines = [
            "# Agent Review Summary",
            "",
            f"- Backend: {review_report['backend']}",
            f"- Status: {review_report['status']}",
            f"- Checked pages: {review_report['checked_pages']}",
            f"- Checked blocks: {review_report['checked_blocks']}",
            f"- Body anchored pages: {', '.join(str(page) for page in review_report['body_anchored_pages']) or 'none'}",
            f"- Appendix only pages: {', '.join(str(page) for page in review_report['appendix_only_pages']) or 'none'}",
            "",
            "## Findings",
        ]
        for finding in review_report["findings"]:
            page_label = finding["page"] if finding["page"] is not None else "global"
            lines.append(f"- Page {page_label}: {finding['issue']} - {finding['detail']}")
        if not review_report["findings"]:
            lines.append("- none")
        return "\n".join(lines).rstrip() + "\n"
    def _render_quality_valve_report(
        self,
        freeze: dict[str, Any],
        trace_rows: list[dict[str, Any]],
        review_report: dict[str, Any],
    ) -> str:
        lines = [
            "# Markdown Quality Valve Report",
            "",
            f"- Raw blocks: {freeze['raw_block_total']}",
            f"- In markdown: {freeze['in_markdown_block_total']}",
            f"- Evidence only: {freeze['evidence_only_block_total']}",
            f"- Needs clarification: {freeze['needs_clarification_total']}",
            f"- Review status: {review_report['status']}",
            f"- Trace rows: {len(trace_rows)}",
            f"- Orphan blocks: {', '.join(freeze['orphan_blocks']) or 'none'}",
            f"- Unresolved relation candidates: {', '.join(freeze['unresolved_relation_candidates']) or 'none'}",
            "",
            "## Findings",
        ]
        for finding in review_report["findings"]:
            page_label = finding["page"] if finding["page"] is not None else "global"
            lines.append(f"- Page {page_label}: {finding['issue']}")
        if not review_report["findings"]:
            lines.append("- none")
        return "\n".join(lines).rstrip() + "\n"

    def _render_integrity_report(
        self,
        integrity_metrics: dict[str, Any],
        review_report: dict[str, Any],
    ) -> str:
        lines = [
            "# Markdown Integrity Report",
            "",
            f"- Document: {integrity_metrics['document_id']}",
            f"- Route: {integrity_metrics['route']}",
            f"- Review status: {integrity_metrics['review_status']}",
            f"- Findings: {integrity_metrics['finding_total']}",
            f"- Body anchored pages: {integrity_metrics['body_anchored_page_total']}",
            f"- Appendix only pages: {integrity_metrics['appendix_only_page_total']}",
            f"- Unreferenced pages: {integrity_metrics['unreferenced_page_total']}",
            f"- Relation candidates: {integrity_metrics['relation_candidate_total']}",
            "",
            "## Blocking Findings",
        ]
        for finding in review_report["findings"]:
            page_label = finding["page"] if finding["page"] is not None else "global"
            lines.append(f"- Page {page_label}: {finding['issue']} - {finding['detail']}")
        if not review_report["findings"]:
            lines.append("- none")
        return "\n".join(lines).rstrip() + "\n"


PDFAgentReadbackExecutor = AgentReviewExecutor
